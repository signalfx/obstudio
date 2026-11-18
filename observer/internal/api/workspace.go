package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"

	"github.com/signalfx/obstudio/observer/internal/audit"
	"github.com/signalfx/obstudio/observer/internal/dashboards"
	"github.com/signalfx/obstudio/observer/internal/store"
)

// WorkspacePath is where a local launcher registers its workspace root with
// the running singleton. A launch from a second repo defers to the instance
// that already owns the OTLP ports, so without this the Dashboards and
// Overview tabs keep reading the first repo's .observe artifacts.
const WorkspacePath = "/api/workspace"

const maxWorkspaceRequestBytes = 4 << 10

// workspaceResolvers holds the artifact resolvers for the most recently
// registered workspace root. Explicit absolute artifact overrides stay pinned
// to their startup resolver because the user chose that exact file.
//
// This is deliberately one process-global active workspace: every client of the
// instance, including a webview in an unfocused editor window, reads whichever
// repo registered last. Requests do not carry their own root. A per-client
// choice is the repo switcher (BORN-450) and replaces this.
//
// Registrations may carry a client timestamp so that two launchers racing each
// other cannot leave the older one applied: the newest timestamp wins, not the
// last to arrive.
type workspaceResolvers struct {
	store         *store.Store
	dashboardsCfg dashboards.Config
	auditCfg      audit.Config
	mu            sync.Mutex // serializes setRoot so the stale check and the swap are atomic
	current       atomic.Pointer[workspaceState]
}

type workspaceState struct {
	root       string
	at         int64 // timestamp (ms) of the registration that set this root, 0 if none
	name       string
	dashboards *dashboards.Resolver
	audit      *audit.Resolver
}

func newWorkspaceResolvers(s *store.Store, dashboardsCfg dashboards.Config, auditCfg audit.Config) *workspaceResolvers {
	w := &workspaceResolvers{store: s, dashboardsCfg: dashboardsCfg, auditCfg: auditCfg}
	root := auditCfg.WorkspaceRoot
	if root == "" {
		root = dashboardsCfg.WorkspaceRoot
	}
	if root == "" {
		if cwd, err := os.Getwd(); err == nil {
			root = cwd
		}
	}
	w.current.Store(&workspaceState{
		root:       filepath.Clean(root),
		name:       filepath.Base(root),
		dashboards: dashboards.NewResolver(s, dashboardsCfg),
		audit:      audit.NewResolver(auditCfg),
	})
	return w
}

func (w *workspaceResolvers) dashboards() *dashboards.Resolver { return w.current.Load().dashboards }

func (w *workspaceResolvers) audit() *audit.Resolver { return w.current.Load().audit }

func (w *workspaceResolvers) name() string { return w.current.Load().name }

// setRoot switches artifact resolution to root, which must be an existing
// absolute directory. at is the registering client's timestamp in
// milliseconds, or 0 when it sent none. It returns the name now being read and
// whether this registration was applied: one older than the registration that
// set the current root is ignored, and one for the current root only refreshes
// the timestamp without rebuilding the resolvers.
func (w *workspaceResolvers) setRoot(root string, at int64) (string, bool, error) {
	root = strings.TrimSpace(root)
	if root == "" || strings.ContainsRune(root, 0) || !filepath.IsAbs(root) {
		return "", false, errWorkspaceRoot
	}
	root = filepath.Clean(root)
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return "", false, errWorkspaceRoot
	}

	w.mu.Lock()
	defer w.mu.Unlock()
	prev := w.current.Load()
	if at != 0 && at < prev.at {
		return prev.name, false, nil
	}
	newest := max(at, prev.at)
	if root == prev.root {
		if newest != prev.at {
			refreshed := *prev
			refreshed.at = newest
			w.current.Store(&refreshed)
		}
		return prev.name, true, nil
	}
	next := &workspaceState{root: root, at: newest, name: filepath.Base(root), dashboards: prev.dashboards, audit: prev.audit}
	if !filepath.IsAbs(w.dashboardsCfg.SpecPath) {
		cfg := w.dashboardsCfg
		cfg.WorkspaceRoot = root
		next.dashboards = dashboards.NewResolver(w.store, cfg)
	}
	if !filepath.IsAbs(w.auditCfg.ReportPath) {
		cfg := w.auditCfg
		cfg.WorkspaceRoot = root
		next.audit = audit.NewResolver(cfg)
	}
	w.current.Store(next)
	return next.name, true, nil
}

var errWorkspaceRoot = errors.New("root must be an existing absolute directory")

type workspaceResponse struct {
	Name string `json:"name"`
}

type workspaceRegistrationResponse struct {
	Name string `json:"name"`
	// Applied is false when a newer registration had already been accepted.
	Applied bool `json:"applied"`
}

func (w *workspaceResolvers) register(mux *http.ServeMux) {
	mux.HandleFunc("GET "+WorkspacePath, func(rw http.ResponseWriter, r *http.Request) {
		// Only the basename is exposed, and only same-origin, so the UI can say
		// which repo it is reading without disclosing the local path layout.
		writeSameOriginJSON(rw, workspaceResponse{Name: w.name()})
	})
	mux.HandleFunc("POST "+WorkspacePath, func(rw http.ResponseWriter, r *http.Request) {
		// Native local processes only: any browser request, same-origin
		// included, is rejected, so a web page cannot repoint the served files.
		if !isLocalAgentObservabilitySDKRequest(r) {
			writeWorkspaceError(rw, http.StatusForbidden, "workspace registration must come from a local process")
			return
		}
		var body struct {
			Root string `json:"root"`
			At   int64  `json:"at"`
		}
		if err := json.NewDecoder(http.MaxBytesReader(rw, r.Body, maxWorkspaceRequestBytes)).Decode(&body); err != nil {
			writeWorkspaceError(rw, http.StatusBadRequest, "invalid JSON body")
			return
		}
		name, applied, err := w.setRoot(body.Root, body.At)
		if err != nil {
			writeWorkspaceError(rw, http.StatusBadRequest, err.Error())
			return
		}
		writeSameOriginJSON(rw, workspaceRegistrationResponse{Name: name, Applied: applied})
	})
}

func writeWorkspaceError(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": message})
}
