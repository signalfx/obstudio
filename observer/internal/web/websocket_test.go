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

func TestPausedConnectionStillReceivesValidationUpdates(t *testing.T) {
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
	if msg.Type != "connected" {
		t.Fatalf("expected connected message, got %#v", msg)
	}

	if err := conn.WriteJSON(ClientMessage{Type: "subscribe"}); err != nil {
		t.Fatalf("subscribe: %v", err)
	}

	for i := 0; i < 5; i++ {
		if err := conn.ReadJSON(&msg); err != nil {
			t.Fatalf("read initial snapshot message: %v", err)
		}
		if msg.Type != "update" {
			t.Fatalf("expected initial update message, got %#v", msg)
		}
	}

	if err := conn.WriteJSON(ClientMessage{Type: "pause"}); err != nil {
		t.Fatalf("pause: %v", err)
	}

	v.SetRuntimeStatus(validator.StatusIdle, "Validation has not been run yet")

	if err := conn.ReadJSON(&msg); err != nil {
		t.Fatalf("read validation update while paused: %v", err)
	}
	if msg.Type != "update" || msg.Signal != "validation" {
		t.Fatalf("expected validation update while paused, got %#v", msg)
	}
}
