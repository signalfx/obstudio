package mcp

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/signalfx/obstudio/observer-go/internal/store"
)

type httpHandler struct {
	dispatcher *Dispatcher
	sessions   sync.Map
}

// Register adds the MCP HTTP endpoints to the given ServeMux.
func Register(mux *http.ServeMux, s *store.Store) {
	h := &httpHandler{dispatcher: NewDispatcher(s)}
	mux.HandleFunc("POST /mcp", h.handle)
	mux.HandleFunc("OPTIONS /mcp", h.handleOptions)
}

func (h *httpHandler) handleOptions(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Allow", "OPTIONS, POST")
	setCORSHeaders(w)
	w.WriteHeader(http.StatusNoContent)
}

func (h *httpHandler) handle(w http.ResponseWriter, r *http.Request) {
	setCORSHeaders(w)
	w.Header().Set("Content-Type", "application/json")

	var req jsonRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(rpcError(nil, -32700, "Parse error"))
		return
	}

	resp, handled := h.dispatcher.Dispatch(req)
	if !handled {
		w.WriteHeader(http.StatusAccepted)
		return
	}

	if req.Method == "initialize" {
		sessionID := generateSessionID()
		h.sessions.Store(sessionID, true)
		w.Header().Set("Mcp-Session-Id", sessionID)
	}

	json.NewEncoder(w).Encode(resp)
}

func setCORSHeaders(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Mcp-Session-Id")
	w.Header().Set("Access-Control-Expose-Headers", "Mcp-Session-Id")
}

func generateSessionID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		log.Printf("[mcp] failed to generate session ID via crypto/rand: %v", err)
		return fmt.Sprintf("fallback-%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}
