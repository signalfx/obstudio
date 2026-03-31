package web

import (
	"embed"
	"fmt"
	"io/fs"
	"net/http"

	"github.com/signalfx/obstudio/observer-go/internal/store"
)

//go:embed static
var staticFS embed.FS

func Register(mux *http.ServeMux, s *store.Store) {
	mux.HandleFunc("GET /api/events", sseHandler(s))

	sub, _ := fs.Sub(staticFS, "static")
	mux.Handle("GET /", http.FileServer(http.FS(sub)))
}

func sseHandler(s *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, "streaming not supported", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Connection", "keep-alive")
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("X-Accel-Buffering", "no")
		flusher.Flush()

		subID, ch := s.Subscribe()
		defer s.Unsubscribe(subID)

		ctx := r.Context()
		for {
			select {
			case <-ctx.Done():
				return
			case sig := <-ch:
				fmt.Fprintf(w, "event: telemetry-changed\ndata: {\"signal\":\"%s\"}\n\n", sig)
				flusher.Flush()
			}
		}
	}
}
