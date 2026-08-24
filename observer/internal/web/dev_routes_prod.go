//go:build !dev

package web

import "net/http"

// registerDevRoutes is a no-op in production/embedded builds: there is no
// disk watcher to trigger a reload against, so the endpoint must not exist.
func registerDevRoutes(_ *http.ServeMux) {}
