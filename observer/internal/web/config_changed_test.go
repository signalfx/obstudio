package web

import (
	"net/http"
	"net/http/httptest"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
)

func dialConnected(t *testing.T, url string) *websocket.Conn {
	t.Helper()
	ws, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		t.Fatalf("dial websocket: %v", err)
	}
	t.Cleanup(func() { ws.Close() })
	var msg ServerMessage
	ws.SetReadDeadline(time.Now().Add(2 * time.Second))
	if err := ws.ReadJSON(&msg); err != nil || msg.Type != "connected" {
		t.Fatalf("connected message: %#v, %v", msg, err)
	}
	return ws
}

func dialSubscribed(t *testing.T, url string) *websocket.Conn {
	t.Helper()
	ws := dialConnected(t, url)
	if err := ws.WriteJSON(ClientMessage{Type: "subscribe"}); err != nil {
		t.Fatal(err)
	}
	for range 5 {
		if _, err := readRaw(ws, 2*time.Second); err != nil {
			t.Fatalf("initial snapshot: %v", err)
		}
	}
	return ws
}

func readRaw(ws *websocket.Conn, wait time.Duration) (map[string]any, error) {
	ws.SetReadDeadline(time.Now().Add(wait))
	var msg map[string]any
	err := ws.ReadJSON(&msg)
	return msg, err
}

func waitConns(t *testing.T, what string, count func(c *conn) bool, want int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for {
		connsMu.Lock()
		n := 0
		for c := range conns {
			c.mu.Lock()
			if count(c) {
				n++
			}
			c.mu.Unlock()
		}
		connsMu.Unlock()
		if n == want {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("%d %s connections, want %d", n, what, want)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// expectConfigChanged reads the next message and requires it to be exactly
// {"type":"config-changed"}. Because the read is the next one, any update
// sent before the notice fails it too.
func expectConfigChanged(t *testing.T, name string, ws *websocket.Conn) {
	t.Helper()
	msg, err := readRaw(ws, 2*time.Second)
	if err != nil {
		t.Fatalf("%s: read: %v", name, err)
	}
	if len(msg) != 1 || msg["type"] != "config-changed" {
		t.Errorf("%s: got %v, want exactly {type:config-changed}", name, msg)
	}
}

func TestConfigChangedBypassesPause(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	mux := http.NewServeMux()
	cleanup := Register(mux, s, v)
	defer cleanup()
	server := httptest.NewServer(mux)
	defer server.Close()
	url := "ws" + strings.TrimPrefix(server.URL, "http") + "/api/ws"

	p := dialSubscribed(t, url)
	if err := p.WriteJSON(ClientMessage{Type: "pause"}); err != nil {
		t.Fatal(err)
	}
	waitConns(t, "paused", func(c *conn) bool { return c.paused }, 1)
	u := dialSubscribed(t, url)
	n := dialConnected(t, url)
	window := 3 * throttleInterval
	time.Sleep(window)

	// (a) delivered: one notice each to P and U.
	NotifyConfigChanged()
	expectConfigChanged(t, "a: P", p)
	expectConfigChanged(t, "a: U", u)
	time.Sleep(window)

	// (b) not-throttled: two back-to-back calls give two notices, inside one
	// throttle interval. The first read on each also shows no update came
	// in (a)'s window (no-update).
	start := time.Now()
	NotifyConfigChanged()
	NotifyConfigChanged()
	for _, c := range []struct {
		name string
		ws   *websocket.Conn
	}{{"b: P", p}, {"b: U", u}} {
		expectConfigChanged(t, c.name+" #1", c.ws)
		expectConfigChanged(t, c.name+" #2", c.ws)
	}
	if elapsed := time.Since(start); elapsed >= throttleInterval {
		t.Errorf("not-throttled: both notices took %v, want < %v", elapsed, throttleInterval)
	}
	time.Sleep(window)

	// no-paused-update: pausedNotified is untouched, so the next telemetry
	// signal still gives P exactly one paused-update, and it is P's next
	// message (no update arrived in (b)'s window).
	broadcastSignal(s, v, "traces")
	if msg, err := readRaw(p, 2*time.Second); err != nil || len(msg) != 1 || msg["type"] != "paused-update" {
		t.Errorf("no-paused-update: P's next message %v, %v; want paused-update", msg, err)
	}

	// unsubscribed-dropped. A read that times out leaves a gorilla
	// connection unusable, so this check runs last on N.
	if got, err := readRaw(n, 300*time.Millisecond); err == nil {
		t.Errorf("unsubscribed-dropped: N got %v", got)
	}

	// no-connections.
	for _, ws := range []*websocket.Conn{p, u, n} {
		ws.Close()
	}
	waitConns(t, "open", func(*conn) bool { return true }, 0)
	NotifyConfigChanged()

	// no-import.
	goBin, err := exec.LookPath("go")
	if err != nil {
		return
	}
	out, err := exec.Command(goBin, "list", "-f", "{{.Imports}}", ".").Output()
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(out), "internal/userconfig") || strings.Contains(string(out), "internal/api") {
		t.Errorf("no-import: web imports %s", out)
	}
}
