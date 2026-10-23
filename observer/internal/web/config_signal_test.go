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

func readRaw(ws *websocket.Conn, wait time.Duration) (map[string]any, error) {
	ws.SetReadDeadline(time.Now().Add(wait))
	var msg map[string]any
	err := ws.ReadJSON(&msg)
	return msg, err
}

func waitPaused(t *testing.T, want int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for {
		connsMu.Lock()
		n := 0
		for c := range conns {
			c.mu.Lock()
			if c.paused {
				n++
			}
			c.mu.Unlock()
		}
		connsMu.Unlock()
		if n == want {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("%d paused connections, want %d", n, want)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestConfigSignalBypassesPause(t *testing.T) {
	s := store.New()
	v := validator.NewStore()
	mux := http.NewServeMux()
	cleanup := Register(mux, s, v)
	defer cleanup()
	server := httptest.NewServer(mux)
	defer server.Close()
	url := "ws" + strings.TrimPrefix(server.URL, "http") + "/api/ws"

	paused := dialConnected(t, url)
	if err := paused.WriteJSON(ClientMessage{Type: "subscribe"}); err != nil {
		t.Fatal(err)
	}
	for range 5 {
		if _, err := readRaw(paused, 2*time.Second); err != nil {
			t.Fatalf("initial snapshot: %v", err)
		}
	}
	if err := paused.WriteJSON(ClientMessage{Type: "pause"}); err != nil {
		t.Fatal(err)
	}
	waitPaused(t, 1)
	unsubscribed := dialConnected(t, url)

	NotifyConfigChanged()
	msg, err := readRaw(paused, 2*time.Second)
	if err != nil {
		t.Fatalf("config message: %v", err)
	}
	if len(msg) != 2 || msg["type"] != "update" || msg["signal"] != "config" {
		t.Errorf("message %v, want exactly {type:update, signal:config}", msg)
	}
	// A read that times out leaves a gorilla connection unusable, so the
	// "nothing else arrived" checks come from what arrives next.
	broadcastSignal(s, v, "traces")
	msg, err = readRaw(paused, 2*time.Second)
	if err != nil || msg["type"] != "paused-update" {
		t.Errorf("next message after config: %v, %v; want paused-update (no stats, pause state untouched)", msg, err)
	}
	if got, err := readRaw(unsubscribed, 300*time.Millisecond); err == nil {
		t.Errorf("unsubscribed connection got %v", got)
	}

	goBin, err := exec.LookPath("go")
	if err != nil {
		return
	}
	out, err := exec.Command(goBin, "list", "-f", "{{.Imports}}", ".").Output()
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(out), "internal/userconfig") || strings.Contains(string(out), "internal/api") {
		t.Errorf("web imports %s", out)
	}
}
