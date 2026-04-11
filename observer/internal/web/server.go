// Package web implements the WebSocket and static file server for the web UI.
package web

import (
	"io/fs"
	"net/http"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/store"
)

// Register adds WebSocket, static file, and SPA routes to the given mux.
// It returns a cleanup function that should be called on shutdown to
// unsubscribe from the store.
func Register(mux *http.ServeMux, s *store.Store) func() {
	mux.HandleFunc("GET /api/ws", wsHandler(s))

	subID, ch := s.Subscribe()
	go func() {
		for sig := range ch {
			broadcastSignal(s, sig)
		}
	}()

	sub, _ := fs.Sub(staticFS(), "static")
	fileServer := http.FileServer(http.FS(sub))

	// SPA fallback: serve index.html for paths that don't match a static file.
	mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/assets/") {
			fileServer.ServeHTTP(w, r)
			return
		}
		index, err := fs.ReadFile(sub, "index.html")
		if err != nil {
			fileServer.ServeHTTP(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(index)
	})

	return func() { s.Unsubscribe(subID) }
}
