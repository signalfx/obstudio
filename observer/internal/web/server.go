// Package web implements the WebSocket and static file server for the web UI.
package web

import (
	"io/fs"
	"net/http"
	"strings"

	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
)

// Register adds WebSocket, static file, and SPA routes to the given mux.
// It returns a cleanup function that should be called on shutdown to
// unsubscribe from the store.
func Register(mux *http.ServeMux, s *store.Store, v *validator.Store) func() {
	mux.HandleFunc("GET /api/ws", wsHandler(s, v))

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
		index, err := fs.ReadFile(sub, "index.html")
		if err != nil {
			fileServer.ServeHTTP(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(index)
	})

	return func() {
		s.Unsubscribe(subID)
		v.Unsubscribe(validationSubID)
	}
}
