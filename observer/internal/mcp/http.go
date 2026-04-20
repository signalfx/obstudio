package mcp

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/signalfx/obstudio/observer/internal/store"
)

type httpHandler struct {
	dispatcher *Dispatcher
	// TODO: expire abandoned sessions if we see real accumulation in long-lived use.
	sessions sync.Map
}

// Register adds the MCP HTTP endpoints to the given ServeMux.
func Register(mux *http.ServeMux, s *store.Store, params ...any) {
	h := &httpHandler{dispatcher: NewDispatcher(s, params...)}
	mux.HandleFunc("GET /mcp", h.handleStream)
	mux.HandleFunc("POST /mcp", h.handle)
	mux.HandleFunc("DELETE /mcp", h.handleDelete)
	mux.HandleFunc("OPTIONS /mcp", h.handleOptions)
}

func (h *httpHandler) handleOptions(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Allow", "GET, POST, DELETE, OPTIONS")
	setCORSHeaders(w)
	w.WriteHeader(http.StatusNoContent)
}

func (h *httpHandler) handleStream(w http.ResponseWriter, r *http.Request) {
	if !originAllowed(r) {
		http.Error(w, "origin not allowed", http.StatusForbidden)
		return
	}

	sessionID := strings.TrimSpace(r.Header.Get("Mcp-Session-Id"))
	// Streamable HTTP clients may establish the SSE stream before sending
	// initialize, so a missing session ID is allowed here.
	if sessionID != "" && !h.sessionExists(sessionID) {
		http.NotFound(w, r)
		return
	}

	setCORSHeaders(w)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusOK)
	_, _ = io.WriteString(w, ": connected\n\n")
	flusher.Flush()

	keepAlive := time.NewTicker(30 * time.Second)
	defer keepAlive.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case <-keepAlive.C:
			_, _ = io.WriteString(w, ": keepalive\n\n")
			flusher.Flush()
		}
	}
}

func (h *httpHandler) handle(w http.ResponseWriter, r *http.Request) {
	if !originAllowed(r) {
		http.Error(w, "origin not allowed", http.StatusForbidden)
		return
	}

	setCORSHeaders(w)

	var req jsonRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(rpcError(nil, -32700, "Parse error"))
		return
	}

	sessionID := strings.TrimSpace(r.Header.Get("Mcp-Session-Id"))
	// Keep direct POST compatibility for existing clients that never open an SSE
	// stream or send a session header after initialize.
	if req.Method != "initialize" && sessionID != "" && !h.sessionExists(sessionID) {
		http.NotFound(w, r)
		return
	}

	resp, handled := h.dispatcher.Dispatch(req)
	if !handled {
		w.WriteHeader(http.StatusAccepted)
		return
	}

	if req.Method == "initialize" {
		sessionID = generateSessionID()
		h.sessions.Store(sessionID, struct{}{})
		w.Header().Set("Mcp-Session-Id", sessionID)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func (h *httpHandler) handleDelete(w http.ResponseWriter, r *http.Request) {
	if !originAllowed(r) {
		http.Error(w, "origin not allowed", http.StatusForbidden)
		return
	}

	setCORSHeaders(w)
	sessionID := strings.TrimSpace(r.Header.Get("Mcp-Session-Id"))
	if sessionID == "" {
		http.Error(w, "missing Mcp-Session-Id header", http.StatusBadRequest)
		return
	}
	if !h.sessionExists(sessionID) {
		http.NotFound(w, r)
		return
	}

	h.sessions.Delete(sessionID)
	w.WriteHeader(http.StatusNoContent)
}

func (h *httpHandler) sessionExists(sessionID string) bool {
	if sessionID == "" {
		return false
	}
	_, ok := h.sessions.Load(sessionID)
	return ok
}

func setCORSHeaders(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Mcp-Session-Id")
	w.Header().Set("Access-Control-Expose-Headers", "Mcp-Session-Id")
}

func originAllowed(r *http.Request) bool {
	origin := strings.TrimSpace(r.Header.Get("Origin"))
	if origin == "" {
		// Non-browser local clients like Codex and Claude do not send Origin.
		return true
	}

	parsed, err := url.Parse(origin)
	if err != nil {
		return false
	}

	switch parsed.Hostname() {
	case "localhost", "127.0.0.1", "::1":
		return true
	default:
		return false
	}
}

func generateSessionID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		log.Printf("[mcp] failed to generate session ID via crypto/rand: %v", err)
		return fmt.Sprintf("fallback-%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}
