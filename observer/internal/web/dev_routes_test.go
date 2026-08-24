//go:build dev

package web

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
)

func TestLiveReloadTriggerRoutePushesReloadToOpenConnections(t *testing.T) {
	s := store.New()
	v := validator.NewStore()

	mux := http.NewServeMux()
	cleanup := Register(mux, s, v)
	defer cleanup()
	server := httptest.NewServer(mux)
	defer server.Close()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http") + "/api/ws"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("dial websocket: %v", err)
	}
	defer conn.Close()

	if err := conn.SetReadDeadline(time.Now().Add(2 * time.Second)); err != nil {
		t.Fatalf("set read deadline: %v", err)
	}

	var msg ServerMessage
	if err := conn.ReadJSON(&msg); err != nil {
		t.Fatalf("read connected message: %v", err)
	}

	resp, err := http.Post(server.URL+"/__live-reload/trigger", "", nil)
	if err != nil {
		t.Fatalf("post trigger: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("expected 204 from trigger, got %d", resp.StatusCode)
	}

	if err := conn.ReadJSON(&msg); err != nil {
		t.Fatalf("read reload message: %v", err)
	}
	if msg.Type != "reload" {
		t.Fatalf("expected reload message, got %#v", msg)
	}
}
