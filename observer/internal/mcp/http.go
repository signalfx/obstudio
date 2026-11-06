package mcp

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
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
	h := &httpHandler{
		dispatcher: NewDispatcher(s, params...),
	}
	mux.HandleFunc("GET /mcp", h.handleStream)
	mux.HandleFunc("POST /mcp", h.handle)
	mux.HandleFunc("DELETE /mcp", h.handleDelete)
	mux.HandleFunc("OPTIONS /mcp", h.handleOptions)
}

func (h *httpHandler) handleOptions(w http.ResponseWriter, r *http.Request) {
	if !originAllowed(r) {
		http.Error(w, "origin not allowed", http.StatusForbidden)
		return
	}
	w.Header().Set("Allow", "GET, POST, DELETE, OPTIONS")
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

	var req jsonRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(rpcError(nil, -32700, "Parse error"))
		return
	}
	if !validJSONRPCRequestID(req.ID) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(rpcError(nil, -32600, "Invalid Request"))
		return
	}

	sessionID := strings.TrimSpace(r.Header.Get("Mcp-Session-Id"))
	// Keep direct POST compatibility for existing clients that never open an SSE
	// stream or send a session header after initialize.
	if req.Method != "initialize" && sessionID != "" && !h.sessionExists(sessionID) {
		http.NotFound(w, r)
		return
	}

	resp, handled := h.dispatcher.DispatchContext(r.Context(), req)
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

func originAllowed(r *http.Request) bool {
	remoteHost, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil || !loopbackHost(remoteHost) {
		return false
	}
	origin := strings.TrimSpace(r.Header.Get("Origin"))
	if origin == "" {
		// This is an intentional local-machine trust boundary, not same-user
		// authentication: native clients omit Origin, and any OS account or
		// process that can reach this loopback endpoint is trusted. Browser
		// callers must pass the exact same-origin check below.
		return true
	}

	parsed, err := url.Parse(origin)
	if err != nil {
		return false
	}
	expectedScheme := "http"
	if r.TLS != nil {
		expectedScheme = "https"
	}
	return parsed.User == nil && parsed.Path == "" && parsed.RawQuery == "" && parsed.Fragment == "" &&
		parsed.Scheme == expectedScheme && strings.EqualFold(parsed.Host, r.Host) && loopbackHost(parsed.Hostname())
}

func loopbackHost(host string) bool {
	host = strings.TrimSuffix(strings.Trim(strings.TrimSpace(host), "[]"), ".")
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func generateSessionID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		log.Printf("[mcp] failed to generate session ID via crypto/rand: %v", err)
		return fmt.Sprintf("fallback-%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}
