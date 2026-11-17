package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"strings"
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
type workspaceResolvers struct {
	store         *store.Store
	dashboardsCfg dashboards.Config
	auditCfg      audit.Config
	current       atomic.Pointer[workspaceState]
}

type workspaceState struct {
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
// absolute directory. It returns the name reported to the UI.
func (w *workspaceResolvers) setRoot(root string) (string, error) {
	root = strings.TrimSpace(root)
	if root == "" || strings.ContainsRune(root, 0) || !filepath.IsAbs(root) {
		return "", errWorkspaceRoot
	}
	root = filepath.Clean(root)
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return "", errWorkspaceRoot
	}

	prev := w.current.Load()
	next := &workspaceState{name: filepath.Base(root), dashboards: prev.dashboards, audit: prev.audit}
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
	return next.name, nil
}

var errWorkspaceRoot = errors.New("root must be an existing absolute directory")

type workspaceResponse struct {
	Name string `json:"name"`
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
		}
		if err := json.NewDecoder(http.MaxBytesReader(rw, r.Body, maxWorkspaceRequestBytes)).Decode(&body); err != nil {
			writeWorkspaceError(rw, http.StatusBadRequest, "invalid JSON body")
			return
		}
		name, err := w.setRoot(body.Root)
		if err != nil {
			writeWorkspaceError(rw, http.StatusBadRequest, err.Error())
			return
		}
		writeSameOriginJSON(rw, workspaceResponse{Name: name})
	})
}

func writeWorkspaceError(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": message})
}
