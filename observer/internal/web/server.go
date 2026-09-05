// Package web implements the WebSocket and static file server for the web UI.
package web

import (
	"bytes"
	"encoding/json"
	"io/fs"
	"net"
	"net/http"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
)

// Register adds WebSocket, static file, and SPA routes to the given mux.
// It returns a cleanup function that should be called on shutdown to
// unsubscribe from the store.
//
// controlToken, when non-empty, is injected into index.html as an inline script (see
// injectControlToken) so Observer's own page -- and only Observer's own page, since a
// cross-origin tab cannot read another origin's served HTML -- can attach it to
// mutating API requests. This is the standalone-binary equivalent of the VS Code
// extension injecting its own bridge token into the webview it controls.
//
// Injection is further restricted to requests with a loopback RemoteAddr AND Host (see
// isLoopbackHTTPRequest): a foreground Observer can be bound to 0.0.0.0 or a LAN address
// (see cmd/obstudio's --host flag), and without this check any remote visitor who loads
// the page -- or, via DNS rebinding, an attacker-controlled hostname later pointed at
// 127.0.0.1 -- would receive the same bearer credential that authorizes the mutating
// cloud APIs.
func Register(mux *http.ServeMux, s *store.Store, v *validator.Store, controlToken string) func() {
	mux.HandleFunc("GET /api/ws", wsHandler(s, v))
	registerDevRoutes(mux)

	subID, ch := s.Subscribe()
	go func() {
		for sig := range ch {
			broadcastSignal(s, v, string(sig))
		}
	}()

	validationSubID, validationCh := v.Subscribe()
	go func() {
		for range validationCh {
			broadcastSignal(s, v, string(validator.SignalValidation))
		}
	}()

	sub, _ := fs.Sub(staticFS(), "static")
	fileServer := http.FileServer(http.FS(sub))

	// SPA fallback: serve index.html for paths that don't match a static file.
	mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/assets/") {
			// Asset names are stable, so keep webviews from pinning stale JS/CSS
			// across extension upgrades.
			w.Header().Set("Cache-Control", "max-age=0, must-revalidate")
			fileServer.ServeHTTP(w, r)
			return
		}
		w.Header().Set("Content-Security-Policy", "frame-ancestors 'none'")
		w.Header().Set("X-Frame-Options", "DENY")
		index, err := fs.ReadFile(sub, "index.html")
		if err != nil {
			fileServer.ServeHTTP(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Cache-Control", "no-store")
		token := controlToken
		if !isLoopbackHTTPRequest(r) {
			token = ""
		}
		_, _ = w.Write(injectControlToken(index, token))
	})

	return func() {
		s.Unsubscribe(subID)
		v.Unsubscribe(validationSubID)
	}
}

// isLoopbackHTTPRequest reports whether both the TCP peer and the request's Host are
// loopback. Checking RemoteAddr alone is not enough: in a DNS-rebinding attack, a page
// first loaded from an attacker-controlled hostname can have that hostname's DNS record
// later flipped to 127.0.0.1, so a subsequent request's RemoteAddr becomes loopback while
// Host -- and therefore the browser's same-origin identity for that page -- remains
// attacker-controlled, letting its script read an injected credential. Fails closed
// (false) if either does not parse, since callers use this to decide whether to hand out
// a bearer credential.
func isLoopbackHTTPRequest(r *http.Request) bool {
	remoteHost, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil || !isLoopbackHostname(remoteHost) {
		return false
	}
	requestHost := r.Host
	if host, _, err := net.SplitHostPort(requestHost); err == nil {
		requestHost = host
	}
	return isLoopbackHostname(requestHost)
}

func isLoopbackHostname(host string) bool {
	host = strings.Trim(strings.TrimSpace(host), "[]")
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// injectControlToken splices a inline script defining window.__OBSTUDIO_CONTROL_TOKEN__
// into index.html, right after <head>, so the served page (and nothing else) can read
// it. Falls back to the unmodified document if controlToken is empty or <head> is
// missing, rather than failing the request.
func injectControlToken(index []byte, controlToken string) []byte {
	if controlToken == "" {
		return index
	}
	const headTag = "<head>"
	insertAt := bytes.Index(index, []byte(headTag))
	if insertAt < 0 {
		return index
	}
	insertAt += len(headTag)
	encodedToken, err := json.Marshal(controlToken)
	if err != nil {
		return index
	}
	script := []byte("\n  <script>window.__OBSTUDIO_CONTROL_TOKEN__ = " + string(encodedToken) + ";</script>")
	return append(append(append([]byte{}, index[:insertAt]...), script...), index[insertAt:]...)
}
