//go:build dev

package web

import "net/http"

// registerDevRoutes adds routes that only make sense against a disk-served,
// live-rebuilt client (see static_dev.go). The client's esbuild watcher POSTs
// here after every successful rebuild so open tabs can reload themselves.
func registerDevRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /__live-reload/trigger", func(w http.ResponseWriter, r *http.Request) {
		broadcastReload()
		w.WriteHeader(http.StatusNoContent)
	})
}
