package web

import (
	"encoding/json"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/signalfx/obstudio/observer/internal/store"
)

const (
	throttleInterval = 100 * time.Millisecond
	writeWait        = 10 * time.Second
	pingInterval     = 30 * time.Second
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

// ── Protocol messages ────────────────────────────────────

// ClientMessage is sent from the browser to the server.
type ClientMessage struct {
	Type string `json:"type"`
}

// ServerMessage is sent from the server to the browser.
type ServerMessage struct {
	Type   string `json:"type"`
	Signal string `json:"signal,omitempty"`
	Data   any    `json:"data,omitempty"`
}

// ── Connection state ─────────────────────────────────────

type conn struct {
	ws    *websocket.Conn
	store *store.Store

	mu     sync.Mutex
	closed sync.Once
	paused bool

	// Whether a paused-update notification has already been sent (reset on resume).
	pausedNotified bool

	// Subscribed after first "subscribe" message.
	subscribed bool

	// Throttle state.
	pending map[string]bool
	timers  map[string]*time.Timer

	done chan struct{}
}

// ── Global connection registry ───────────────────────────

var (
	connsMu sync.Mutex
	conns   = make(map[*conn]struct{})
)

func broadcastSignal(s *store.Store, sig store.Signal) {
	connsMu.Lock()
	snapshot := make([]*conn, 0, len(conns))
	for c := range conns {
		snapshot = append(snapshot, c)
	}
	connsMu.Unlock()

	for _, c := range snapshot {
		c.onStoreSignal(sig)
	}
}

// ── HTTP handler ─────────────────────────────────────────

func wsHandler(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ws, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			log.Printf("websocket upgrade: %v", err)
			return
		}

		c := &conn{
			ws:      ws,
			store:   s,
			pending: make(map[string]bool),
			timers:  make(map[string]*time.Timer),
			done:    make(chan struct{}),
		}

		connsMu.Lock()
		conns[c] = struct{}{}
		connsMu.Unlock()

		c.sendMsg(ServerMessage{Type: "connected"})

		go c.readLoop()
		go c.pingLoop()
	}
}

// ── Read loop ────────────────────────────────────────────

func (c *conn) readLoop() {
	defer c.cleanup()

	for {
		_, raw, err := c.ws.ReadMessage()
		if err != nil {
			return
		}
		var msg ClientMessage
		if err := json.Unmarshal(raw, &msg); err != nil {
			continue
		}
		switch msg.Type {
		case "subscribe":
			c.mu.Lock()
			c.subscribed = true
			c.mu.Unlock()
			c.pushAll()
		case "pause":
			c.mu.Lock()
			c.paused = true
			c.pausedNotified = false
			c.mu.Unlock()
		case "resume":
			c.mu.Lock()
			c.paused = false
			c.pausedNotified = false
			c.mu.Unlock()
			c.pushAll()
		}
	}
}

func (c *conn) pingLoop() {
	ticker := time.NewTicker(pingInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			c.mu.Lock()
			_ = c.ws.SetWriteDeadline(time.Now().Add(writeWait))
			err := c.ws.WriteMessage(websocket.PingMessage, nil)
			c.mu.Unlock()
			if err != nil {
				c.cleanup()
				return
			}
		case <-c.done:
			return
		}
	}
}

func (c *conn) cleanup() {
	c.closed.Do(func() {
		connsMu.Lock()
		delete(conns, c)
		connsMu.Unlock()

		c.mu.Lock()
		c.subscribed = false
		for key, t := range c.timers {
			t.Stop()
			delete(c.timers, key)
		}
		c.mu.Unlock()

		close(c.done)
		_ = c.ws.Close()
	})
}

// ── Query + push ─────────────────────────────────────────

func (c *conn) pushAll() {
	c.mu.Lock()
	if !c.subscribed {
		c.mu.Unlock()
		return
	}
	c.mu.Unlock()

	c.queryAndSend("traces")
	c.queryAndSend("metrics")
	c.queryAndSend("logs")
	c.queryAndSend("stats")
}

func (c *conn) queryAndSend(signal string) {
	var data any

	switch signal {
	case "traces":
		data = c.store.QueryTraces(100)
	case "metrics":
		data = c.store.QueryMetrics(100)
	case "logs":
		data = c.store.QueryLogs(100)
	case "stats":
		data = c.store.Stats()
	}

	c.sendMsg(ServerMessage{Type: "update", Signal: signal, Data: data})
}

// ── Store signal → throttled push ────────────────────────

func (c *conn) onStoreSignal(sig store.Signal) {
	c.mu.Lock()

	if !c.subscribed {
		c.mu.Unlock()
		return
	}

	signals := []string{string(sig)}
	// Always include stats on any signal change.
	signals = append(signals, "stats")

	if c.paused {
		if !c.pausedNotified {
			c.pausedNotified = true
			c.mu.Unlock()
			c.sendMsg(ServerMessage{Type: "paused-update"})
		} else {
			c.mu.Unlock()
		}
		return
	}
	c.mu.Unlock()

	for _, s := range signals {
		c.throttledPush(s)
	}
}

func (c *conn) throttledPush(signal string) {
	c.mu.Lock()

	if !c.subscribed || c.paused {
		c.mu.Unlock()
		return
	}

	// Throttle: if timer active, mark pending and return.
	if _, active := c.timers[signal]; active {
		c.pending[signal] = true
		c.mu.Unlock()
		return
	}

	// Start cooldown timer.
	c.timers[signal] = time.AfterFunc(throttleInterval, func() {
		c.mu.Lock()
		delete(c.timers, signal)
		hasPending := c.pending[signal]
		c.pending[signal] = false
		c.mu.Unlock()

		if hasPending {
			c.throttledPush(signal)
		}
	})
	c.mu.Unlock()

	c.queryAndSend(signal)
}

// ── Send JSON over WebSocket ─────────────────────────────

func (c *conn) sendMsg(msg ServerMessage) {
	c.mu.Lock()
	_ = c.ws.SetWriteDeadline(time.Now().Add(writeWait))
	err := c.ws.WriteJSON(msg)
	c.mu.Unlock()
	if err != nil {
		log.Printf("[ws] write error: %v", err)
		c.cleanup()
	}
}
