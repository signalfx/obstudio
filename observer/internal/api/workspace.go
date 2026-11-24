package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"slices"
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

// WorkspacesPath lists the registered workspaces by name for the repo
// switcher. WorkspaceScopedPrefix serves one workspace's audit report under a
// path of its own, so the report's relative links to its siblings stay in the
// same workspace.
const (
	WorkspacesPath        = "/api/workspaces"
	WorkspaceScopedPrefix = "/api/workspaces/{workspace}"
)

// workspaceParam is the query parameter a client uses to read one registered
// workspace's artifacts instead of the active one. It carries a name from
// GET /api/workspaces, never a path.
const workspaceParam = "workspace"

// maxRegisteredWorkspaces bounds the registry. The least recently registered
// workspace that is not active is forgotten first.
const maxRegisteredWorkspaces = 32

// workspaceResolvers tracks every workspace root a local launcher registered,
// each with its own artifact resolvers, plus the active one. Explicit absolute
// artifact overrides stay pinned to their startup resolver in every workspace
// because the user chose that exact file.
//
// The active workspace is the default for any request that names none, and is
// the most recently registered root. Registrations may carry a client
// timestamp so that two launchers racing each other cannot leave the older one
// active: the newest timestamp wins, not the last to arrive. A client picks a
// different workspace per request with ?workspace=<name> (the repo switcher),
// so one browser's choice never changes what another client reads.
type workspaceResolvers struct {
	store         *store.Store
	dashboardsCfg dashboards.Config
	auditCfg      audit.Config
	startup       *workspaceEntry
	mu            sync.Mutex        // guards known and serializes setRoot so the stale check and the swap are atomic
	known         []*workspaceEntry // least recently registered first
	current       atomic.Pointer[workspaceState]
}

// workspaceEntry is one registered root. Its name is unique among registered
// workspaces and is all a client ever sees of it.
type workspaceEntry struct {
	root       string
	name       string
	folder     string
	dashboards *dashboards.Resolver
	audit      *audit.Resolver
}

type workspaceState struct {
	entry *workspaceEntry
	at    int64 // timestamp (ms) of the registration that made entry active, 0 if none
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
	root = filepath.Clean(root)
	w.startup = &workspaceEntry{
		root:       root,
		name:       filepath.Base(root),
		folder:     filepath.Base(root),
		dashboards: dashboards.NewResolver(s, dashboardsCfg),
		audit:      audit.NewResolver(auditCfg),
	}
	w.known = []*workspaceEntry{w.startup}
	w.current.Store(&workspaceState{entry: w.startup})
	return w
}

func (w *workspaceResolvers) active() *workspaceEntry { return w.current.Load().entry }

func (w *workspaceResolvers) dashboards() *dashboards.Resolver { return w.active().dashboards }

func (w *workspaceResolvers) audit() *audit.Resolver { return w.active().audit }

func (w *workspaceResolvers) name() string { return w.active().name }

// lookup returns the registered workspace with this name, or the active one
// when name is empty.
func (w *workspaceResolvers) lookup(name string) (*workspaceEntry, bool) {
	if name == "" {
		return w.active(), true
	}
	w.mu.Lock()
	defer w.mu.Unlock()
	for _, entry := range w.known {
		if entry.name == name {
			return entry, true
		}
	}
	return nil, false
}

// setRoot registers root, which must be an existing absolute directory, and
// makes it the active workspace. at is the registering client's timestamp in
// milliseconds, or 0 when it sent none. It returns the active workspace's name
// and whether this registration became active: one older than the
// registration that set the active root is still added to the registry but
// does not become active, and one for the active root only refreshes the
// timestamp without rebuilding the resolvers.
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
	stale := at != 0 && at < prev.at
	// A stale registration still lists a new repo, but never refreshes an
	// existing one's eviction order, so a launcher that keeps losing the race
	// cannot keep its repo ahead of ones actually in use.
	entry := w.rememberLocked(root, prev.entry, !stale)
	if stale {
		return prev.entry.name, false, nil
	}
	newest := max(at, prev.at)
	if entry != prev.entry || newest != prev.at {
		w.current.Store(&workspaceState{entry: entry, at: newest})
	}
	return entry.name, true, nil
}

// rememberLocked returns the registry entry for root, creating it when new.
// A new entry, or an existing one when touch is set, becomes the most recently
// registered. When the registry is full the least recently registered entry
// other than keep is forgotten. w.mu must be held.
func (w *workspaceResolvers) rememberLocked(root string, keep *workspaceEntry, touch bool) *workspaceEntry {
	for i, entry := range w.known {
		if entry.root == root {
			if touch {
				w.known = append(append(w.known[:i:i], w.known[i+1:]...), entry)
			}
			return entry
		}
	}
	entry := w.newEntryLocked(root)
	w.known = append(w.known, entry)
	if len(w.known) > maxRegisteredWorkspaces {
		for i, candidate := range w.known {
			if candidate != keep && candidate != entry {
				w.known = append(w.known[:i:i], w.known[i+1:]...)
				break
			}
		}
	}
	return entry
}

// newEntryLocked builds resolvers for root under a name no registered
// workspace uses yet: the folder name, then "name (2)", "name (3)", and so on.
// w.mu must be held.
func (w *workspaceResolvers) newEntryLocked(root string) *workspaceEntry {
	folder := filepath.Base(root)
	name := folder
	for n := 2; w.nameTakenLocked(name); n++ {
		name = fmt.Sprintf("%s (%d)", folder, n)
	}
	entry := &workspaceEntry{root: root, name: name, folder: folder, dashboards: w.startup.dashboards, audit: w.startup.audit}
	if !filepath.IsAbs(w.dashboardsCfg.SpecPath) {
		cfg := w.dashboardsCfg
		cfg.WorkspaceRoot = root
		entry.dashboards = dashboards.NewResolver(w.store, cfg)
	}
	if !filepath.IsAbs(w.auditCfg.ReportPath) {
		cfg := w.auditCfg
		cfg.WorkspaceRoot = root
		entry.audit = audit.NewResolver(cfg)
	}
	return entry
}

func (w *workspaceResolvers) nameTakenLocked(name string) bool {
	for _, entry := range w.known {
		if entry.name == name {
			return true
		}
	}
	return false
}

type workspaceContextKey struct{}

// scoped resolves the workspace a request names, by path segment for the
// report routes or by ?workspace= otherwise, and hands it to next through the
// request context. An unknown name is a 404 rather than a silent fallback to
// the active workspace, so a client never mistakes one repo's artifacts for
// another's.
func (w *workspaceResolvers) scoped(next http.HandlerFunc) http.HandlerFunc {
	return func(rw http.ResponseWriter, r *http.Request) {
		name := r.PathValue(workspaceParam)
		if name == "" {
			name = r.URL.Query().Get(workspaceParam)
		}
		entry, ok := w.lookup(name)
		if !ok {
			writeWorkspaceError(rw, http.StatusNotFound, "unknown workspace")
			return
		}
		next(rw, r.WithContext(context.WithValue(r.Context(), workspaceContextKey{}, entry)))
	}
}

// entryFor returns the workspace scoped resolved for r, or the active one for
// a request that did not pass through scoped.
func (w *workspaceResolvers) entryFor(r *http.Request) *workspaceEntry {
	if entry, ok := r.Context().Value(workspaceContextKey{}).(*workspaceEntry); ok {
		return entry
	}
	return w.active()
}

func (w *workspaceResolvers) dashboardsFor(r *http.Request) *dashboards.Resolver {
	return w.entryFor(r).dashboards
}

func (w *workspaceResolvers) auditFor(r *http.Request) *audit.Resolver { return w.entryFor(r).audit }

type workspaceListItem struct {
	Name string `json:"name"`
	// Folder is the root's base name, which differs from Name only when two
	// registered roots share it. The UI matches it against service names when
	// the workspace has no audit.
	Folder string `json:"folder"`
	// Service is the audit's meta.service_name, empty without a usable audit.
	Service string `json:"service,omitempty"`
}

type workspaceListResponse struct {
	Active     string              `json:"active"`
	Workspaces []workspaceListItem `json:"workspaces"`
}

func (w *workspaceResolvers) list() workspaceListResponse {
	// One lock for both, so the active name is always one of the listed
	// workspaces even while a registration lands.
	w.mu.Lock()
	entries := slices.Clone(w.known)
	active := w.current.Load().entry.name
	w.mu.Unlock()
	resp := workspaceListResponse{Active: active, Workspaces: make([]workspaceListItem, 0, len(entries))}
	for _, entry := range entries {
		resp.Workspaces = append(resp.Workspaces, workspaceListItem{
			Name:    entry.name,
			Folder:  entry.folder,
			Service: entry.audit.ServiceName(),
		})
	}
	slices.SortFunc(resp.Workspaces, func(a, b workspaceListItem) int { return strings.Compare(a.Name, b.Name) })
	return resp
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
	mux.HandleFunc("GET "+WorkspacePath, w.scoped(func(rw http.ResponseWriter, r *http.Request) {
		// Only the name is exposed, and only same-origin, so the UI can say
		// which repo it is reading without disclosing the local path layout.
		writeSameOriginJSON(rw, workspaceResponse{Name: w.entryFor(r).name})
	}))
	mux.HandleFunc("GET "+WorkspacesPath, func(rw http.ResponseWriter, r *http.Request) {
		writeSameOriginJSON(rw, w.list())
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
