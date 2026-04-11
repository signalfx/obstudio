//go:build dev

package web

import (
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"runtime"
)

// staticFS returns the web package directory (containing the static/
// subdirectory) so that fs.Sub(staticFS(), "static") in server.go works
// consistently with both the embedded and dev builds.
// File changes from the esbuild watcher are served immediately.
func staticFS() fs.FS {
	_, thisFile, _, _ := runtime.Caller(0)
	dir := filepath.Dir(thisFile) // web/ directory (parent of static/)
	staticDir := filepath.Join(dir, "static")
	if _, err := os.Stat(staticDir); err != nil {
		log.Fatalf("[dev] static directory not found: %s", staticDir)
	}
	log.Printf("[dev] serving static files from disk: %s", staticDir)
	return os.DirFS(dir)
}
