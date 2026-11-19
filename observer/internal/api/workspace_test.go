package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/audit"
	"github.com/signalfx/obstudio/observer/internal/dashboards"
	"github.com/signalfx/obstudio/observer/internal/store"
)

const workspaceTestSpec = `{"schemaVersion":1,"generatedAt":"2026-11-17T00:00:00Z","groups":[{"name":"g","description":"","dashboards":[{"name":"d","description":"","charts":[]}]}]}`

func writeWorkspaceArtifact(t *testing.T, root, rel, content string) {
	t.Helper()
	path := filepath.Join(root, rel)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func newWorkspaceTestMux(t *testing.T, dashboardsCfg dashboards.Config, auditCfg audit.Config) *http.ServeMux {
	t.Helper()
	mux := http.NewServeMux()
	Register(mux, store.New(), dashboardsCfg, auditCfg)
	return mux
}

func postWorkspace(mux *http.ServeMux, root string, mutate func(*http.Request)) *httptest.ResponseRecorder {
	body, _ := json.Marshal(map[string]string{"root": root})
	req := httptest.NewRequest(http.MethodPost, WorkspacePath, strings.NewReader(string(body)))
	req.RemoteAddr = "127.0.0.1:54321"
	req.Host = "127.0.0.1:17900"
	req.Header.Set("Content-Type", "application/json")
	if mutate != nil {
		mutate(req)
	}
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	return rec
}

func getJSON[T any](t *testing.T, mux *http.ServeMux, path string) T {
	t.Helper()
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	var v T
	if err := json.Unmarshal(rec.Body.Bytes(), &v); err != nil {
		t.Fatalf("GET %s: %v (%s)", path, err, rec.Body.String())
	}
	return v
}

func previewAvailable(t *testing.T, mux *http.ServeMux) bool {
	return getJSON[dashboards.PreviewResponse](t, mux, "/api/dashboards/preview").Available
}

func auditReportStatus(mux *http.ServeMux) int {
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/audit/report", nil))
	return rec.Code
}

func TestWorkspaceRegistrationSwitchesArtifactRoot(t *testing.T) {
	repoA := filepath.Join(t.TempDir(), "repoA")
	repoB := filepath.Join(t.TempDir(), "repoB")
	if err := os.MkdirAll(repoA, 0o755); err != nil {
		t.Fatal(err)
	}
	writeWorkspaceArtifact(t, repoB, dashboards.DefaultSpecRelPath, workspaceTestSpec)
	writeWorkspaceArtifact(t, repoB, audit.DefaultHTMLRelPath, "<html>repo B report</html>")

	mux := newWorkspaceTestMux(t, dashboards.Config{WorkspaceRoot: repoA}, audit.Config{WorkspaceRoot: repoA})
	if previewAvailable(t, mux) {
		t.Fatal("repo A has no preview, want unavailable before registration")
	}
	if got := auditReportStatus(mux); got != http.StatusNotFound {
		t.Fatalf("audit report before registration = %d, want 404", got)
	}
	if got := getJSON[workspaceResponse](t, mux, WorkspacePath).Name; got != "repoA" {
		t.Fatalf("workspace name = %q, want repoA", got)
	}

	rec := postWorkspace(mux, repoB, nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("register repo B = %d %s", rec.Code, rec.Body.String())
	}
	if !previewAvailable(t, mux) {
		t.Fatal("want repo B preview after registration")
	}
	if got := auditReportStatus(mux); got != http.StatusOK {
		t.Fatalf("audit report after registration = %d, want 200", got)
	}
	if got := getJSON[workspaceResponse](t, mux, WorkspacePath).Name; got != "repoB" {
		t.Fatalf("workspace name = %q, want repoB", got)
	}
	if strings.Contains(rec.Body.String(), repoB) {
		t.Fatalf("response leaks the absolute root: %s", rec.Body.String())
	}
}

func TestWorkspaceRegistrationRejectsBrowserAndRemoteRequests(t *testing.T) {
	repoA := t.TempDir()
	repoB := t.TempDir()
	writeWorkspaceArtifact(t, repoB, dashboards.DefaultSpecRelPath, workspaceTestSpec)
	mux := newWorkspaceTestMux(t, dashboards.Config{WorkspaceRoot: repoA}, audit.Config{WorkspaceRoot: repoA})

	cases := map[string]func(*http.Request){
		"cross-origin page": func(r *http.Request) { r.Header.Set("Origin", "https://evil.example") },
		"same-origin UI": func(r *http.Request) {
			r.Header.Set("Origin", "http://127.0.0.1:17900")
			r.Header.Set("Sec-Fetch-Site", "same-origin")
			r.Header.Set(splunkBrowserRequestHeader, "1")
		},
		"non-loopback peer":   func(r *http.Request) { r.RemoteAddr = "192.0.2.10:5000" },
		"DNS rebinding host":  func(r *http.Request) { r.Host = "attacker.example:17900" },
		"no-cors simple post": func(r *http.Request) { r.Header.Set("Sec-Fetch-Mode", "no-cors") },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			if rec := postWorkspace(mux, repoB, mutate); rec.Code != http.StatusForbidden {
				t.Fatalf("status = %d, want 403", rec.Code)
			}
			if previewAvailable(t, mux) {
				t.Fatal("rejected request still switched the workspace")
			}
		})
	}
}

func TestWorkspaceRegistrationRejectsInvalidRoots(t *testing.T) {
	repoA := t.TempDir()
	file := filepath.Join(t.TempDir(), "file.txt")
	writeWorkspaceArtifact(t, filepath.Dir(file), "file.txt", "x")
	mux := newWorkspaceTestMux(t, dashboards.Config{WorkspaceRoot: repoA}, audit.Config{WorkspaceRoot: repoA})
	wantName := filepath.Base(repoA)

	for name, root := range map[string]string{
		"empty":    "",
		"relative": "repoB",
		"missing":  filepath.Join(repoA, "does-not-exist"),
		"file":     file,
		"nul byte": repoA + "\x00/x",
	} {
		t.Run(name, func(t *testing.T) {
			if rec := postWorkspace(mux, root, nil); rec.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400", rec.Code)
			}
			if got := getJSON[workspaceResponse](t, mux, WorkspacePath).Name; got != wantName {
				t.Fatalf("workspace name = %q, want unchanged %q", got, wantName)
			}
		})
	}
}

func TestWorkspaceRegistrationKeepsAbsoluteOverridesPinned(t *testing.T) {
	pinnedRoot := t.TempDir()
	writeWorkspaceArtifact(t, pinnedRoot, "pinned.preview.json", workspaceTestSpec)
	repoB := t.TempDir()
	mux := newWorkspaceTestMux(t,
		dashboards.Config{SpecPath: filepath.Join(pinnedRoot, "pinned.preview.json")},
		audit.Config{WorkspaceRoot: pinnedRoot},
	)
	if !previewAvailable(t, mux) {
		t.Fatal("want pinned preview before registration")
	}
	if rec := postWorkspace(mux, repoB, nil); rec.Code != http.StatusOK {
		t.Fatalf("register = %d", rec.Code)
	}
	if !previewAvailable(t, mux) {
		t.Fatal("absolute OBSTUDIO_DASHBOARDS_PREVIEW override should stay pinned after registration")
	}
}

func postWorkspaceAt(mux *http.ServeMux, root string, at int64) (*httptest.ResponseRecorder, workspaceRegistrationResponse) {
	body, _ := json.Marshal(map[string]any{"root": root, "at": at})
	req := httptest.NewRequest(http.MethodPost, WorkspacePath, strings.NewReader(string(body)))
	req.RemoteAddr = "127.0.0.1:54321"
	req.Host = "127.0.0.1:17900"
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	var resp workspaceRegistrationResponse
	_ = json.Unmarshal(rec.Body.Bytes(), &resp)
	return rec, resp
}

func TestWorkspaceRegistrationIgnoresOlderTimestamps(t *testing.T) {
	startup := t.TempDir()
	repoA := filepath.Join(t.TempDir(), "repoA")
	repoB := filepath.Join(t.TempDir(), "repoB")
	for _, dir := range []string{repoA, repoB} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	mux := newWorkspaceTestMux(t, dashboards.Config{WorkspaceRoot: startup}, audit.Config{WorkspaceRoot: startup})

	// B was focused later than A, but A's request arrives last.
	if _, resp := postWorkspaceAt(mux, repoB, 2000); !resp.Applied || resp.Name != "repoB" {
		t.Fatalf("newer registration = %+v, want applied repoB", resp)
	}
	rec, resp := postWorkspaceAt(mux, repoA, 1000)
	if rec.Code != http.StatusOK || resp.Applied || resp.Name != "repoB" {
		t.Fatalf("older registration = %d %+v, want 200 ignored and still repoB", rec.Code, resp)
	}
	if got := getJSON[workspaceResponse](t, mux, WorkspacePath).Name; got != "repoB" {
		t.Fatalf("workspace name = %q, want repoB after a stale registration", got)
	}
	if list := getJSON[workspaceListResponse](t, mux, WorkspacesPath).Workspaces; !slices.ContainsFunc(list, func(item workspaceListItem) bool { return item.Name == "repoA" }) {
		t.Fatalf("workspace list = %+v, want the stale repo A still registered", list)
	}

	// A registration without a timestamp keeps the arrival-order behavior.
	if _, resp := postWorkspaceAt(mux, repoA, 0); !resp.Applied || resp.Name != "repoA" {
		t.Fatalf("untimestamped registration = %+v, want applied repoA", resp)
	}
	// The timestamp of the last applied registration still gates later ones.
	if _, resp := postWorkspaceAt(mux, repoB, 1500); resp.Applied {
		t.Fatalf("registration older than the recorded timestamp was applied: %+v", resp)
	}
}

func TestWorkspaceRegistrationForUnchangedRootKeepsResolvers(t *testing.T) {
	root := t.TempDir()
	w := newWorkspaceResolvers(store.New(), dashboards.Config{WorkspaceRoot: root}, audit.Config{WorkspaceRoot: root})

	if _, applied, err := w.setRoot(root, 100); err != nil || !applied {
		t.Fatalf("setRoot(startup root) = applied %v, err %v", applied, err)
	}
	dash, aud := w.dashboards(), w.audit()
	if _, applied, err := w.setRoot(root+string(filepath.Separator), 200); err != nil || !applied {
		t.Fatalf("setRoot(same root again) = applied %v, err %v", applied, err)
	}
	if w.dashboards() != dash || w.audit() != aud {
		t.Fatal("unchanged root rebuilt the resolvers, want a no-op")
	}
	// The refreshed timestamp still gates an older registration for another root.
	other := t.TempDir()
	if _, applied, _ := w.setRoot(other, 150); applied {
		t.Fatal("registration older than the refreshed timestamp was applied")
	}
	if _, applied, _ := w.setRoot(other, 300); !applied || w.dashboards() == dash {
		t.Fatal("newer registration for a different root should rebuild the resolvers")
	}
}

func workspaceAudit(service string) string {
	return `{"schema_version":2,"kind":"otel-audit","meta":{"service_name":"` + service + `","language":"go","status":"Pass"},` +
		`"current_instrumentation":{"spans":[],"metrics":[],"logs":[]},"findings":[],"anti_patterns":[],"recommendation":[]}`
}

func mkdirRepo(t *testing.T, parts ...string) string {
	t.Helper()
	dir := filepath.Join(append([]string{t.TempDir()}, parts...)...)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	return dir
}

func getStatus(mux *http.ServeMux, path string) (int, string) {
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	return rec.Code, rec.Body.String()
}

func TestWorkspaceListKeepsEveryRegisteredRepo(t *testing.T) {
	repoA := mkdirRepo(t, "repoA")
	repoB := mkdirRepo(t, "repoB")
	repoC := mkdirRepo(t, "repoC")
	writeWorkspaceArtifact(t, repoA, audit.DefaultReportRelPath, workspaceAudit("checkout"))
	writeWorkspaceArtifact(t, repoB, audit.DefaultReportRelPath, workspaceAudit("payments"))
	mux := newWorkspaceTestMux(t, dashboards.Config{WorkspaceRoot: repoA}, audit.Config{WorkspaceRoot: repoA})

	for _, root := range []string{repoC, repoB} {
		if rec := postWorkspace(mux, root, nil); rec.Code != http.StatusOK {
			t.Fatalf("register %s = %d %s", filepath.Base(root), rec.Code, rec.Body.String())
		}
	}

	code, body := getStatus(mux, WorkspacesPath)
	if code != http.StatusOK {
		t.Fatalf("GET %s = %d %s", WorkspacesPath, code, body)
	}
	for _, root := range []string{repoA, repoB, repoC} {
		if strings.Contains(body, filepath.Dir(root)) {
			t.Fatalf("workspace list leaks a local path: %s", body)
		}
	}
	got := getJSON[workspaceListResponse](t, mux, WorkspacesPath)
	want := workspaceListResponse{Active: "repoB", Workspaces: []workspaceListItem{
		{Name: "repoA", Folder: "repoA", Service: "checkout"},
		{Name: "repoB", Folder: "repoB", Service: "payments"},
		{Name: "repoC", Folder: "repoC"},
	}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("workspace list = %+v, want %+v", got, want)
	}
}

func TestWorkspaceQueryReadsTheNamedRepo(t *testing.T) {
	repoA := mkdirRepo(t, "repoA")
	repoB := mkdirRepo(t, "repoB")
	writeWorkspaceArtifact(t, repoA, dashboards.DefaultSpecRelPath, workspaceTestSpec)
	writeWorkspaceArtifact(t, repoA, audit.DefaultReportRelPath, workspaceAudit("checkout"))
	mux := newWorkspaceTestMux(t, dashboards.Config{WorkspaceRoot: repoA}, audit.Config{WorkspaceRoot: repoA})
	if rec := postWorkspace(mux, repoB, nil); rec.Code != http.StatusOK {
		t.Fatalf("register repo B = %d", rec.Code)
	}

	// The active workspace stays the default for requests that name none.
	if previewAvailable(t, mux) {
		t.Fatal("repo B is active and has no preview, want unavailable")
	}
	if got := getJSON[audit.Report](t, mux, "/api/audit/score").Available; got {
		t.Fatal("repo B is active and has no audit, want unavailable score")
	}

	if !getJSON[dashboards.PreviewResponse](t, mux, "/api/dashboards/preview?workspace=repoA").Available {
		t.Fatal("want repo A's preview when the request names repo A")
	}
	if got := getJSON[audit.Report](t, mux, "/api/audit/score?workspace=repoA"); !got.Available || got.ServiceName != "checkout" {
		t.Fatalf("score for repo A = %+v, want repo A's checkout audit", got)
	}
	if got := getJSON[workspaceResponse](t, mux, WorkspacePath+"?workspace=repoA").Name; got != "repoA" {
		t.Fatalf("workspace name for ?workspace=repoA = %q", got)
	}
	// Choosing a repo for one request does not change the active one.
	if got := getJSON[workspaceResponse](t, mux, WorkspacePath).Name; got != "repoB" {
		t.Fatalf("active workspace = %q after a scoped read, want repoB", got)
	}

	for _, name := range []string{"nope", "..", repoA, url.QueryEscape("../repoA")} {
		for _, path := range []string{"/api/dashboards/preview", "/api/audit/score", "/api/audit/report", WorkspacePath} {
			if code, body := getStatus(mux, path+"?workspace="+url.QueryEscape(name)); code != http.StatusNotFound {
				t.Fatalf("GET %s?workspace=%q = %d %s, want 404", path, name, code, body)
			}
		}
	}
}

func TestWorkspaceScopedReportKeepsSiblingLinksInTheRepo(t *testing.T) {
	repoA := mkdirRepo(t, "repoA")
	repoB := mkdirRepo(t, "repoB")
	writeWorkspaceArtifact(t, repoA, audit.DefaultHTMLRelPath, "<html>repo A report</html>")
	writeWorkspaceArtifact(t, repoA, audit.DefaultReportRelPath, workspaceAudit("checkout"))
	writeWorkspaceArtifact(t, repoB, audit.DefaultHTMLRelPath, "<html>repo B report</html>")
	mux := newWorkspaceTestMux(t, dashboards.Config{WorkspaceRoot: repoA}, audit.Config{WorkspaceRoot: repoA})
	if rec := postWorkspace(mux, repoB, nil); rec.Code != http.StatusOK {
		t.Fatalf("register repo B = %d", rec.Code)
	}

	if code, body := getStatus(mux, "/api/audit/report"); code != http.StatusOK || !strings.Contains(body, "repo B") {
		t.Fatalf("unscoped report = %d %q, want the active repo B", code, body)
	}
	code, body := getStatus(mux, "/api/workspaces/repoA/audit/report")
	if code != http.StatusOK || !strings.Contains(body, "repo A") {
		t.Fatalf("scoped report = %d %q, want repo A", code, body)
	}
	// The report links to otel-audit.json relatively, which resolves under the
	// same scoped prefix.
	if code, body := getStatus(mux, "/api/workspaces/repoA/audit/otel-audit.json"); code != http.StatusOK || !strings.Contains(body, "checkout") {
		t.Fatalf("scoped sibling = %d %q, want repo A's audit", code, body)
	}
	if code, _ := getStatus(mux, "/api/workspaces/nope/audit/report"); code != http.StatusNotFound {
		t.Fatalf("report for an unknown workspace = %d, want 404", code)
	}
}

func TestWorkspaceReposSharingAFolderNameGetDistinctNames(t *testing.T) {
	startup := mkdirRepo(t, "startup")
	apiOne := mkdirRepo(t, "one", "api")
	apiTwo := mkdirRepo(t, "two", "api")
	writeWorkspaceArtifact(t, apiTwo, dashboards.DefaultSpecRelPath, workspaceTestSpec)
	mux := newWorkspaceTestMux(t, dashboards.Config{WorkspaceRoot: startup}, audit.Config{WorkspaceRoot: startup})

	_, first := postWorkspaceAt(mux, apiOne, 0)
	_, second := postWorkspaceAt(mux, apiTwo, 0)
	_, again := postWorkspaceAt(mux, apiOne, 0)
	if first.Name != "api" || second.Name != "api (2)" || again.Name != "api" {
		t.Fatalf("names = %q, %q, then %q; want api, api (2), api", first.Name, second.Name, again.Name)
	}
	if !getJSON[dashboards.PreviewResponse](t, mux, "/api/dashboards/preview?workspace="+url.QueryEscape("api (2)")).Available {
		t.Fatal("want the second api repo's preview by its distinct name")
	}
	if code, _ := getStatus(mux, "/api/workspaces/"+url.PathEscape("api (2)")+"/audit/report"); code != http.StatusNotFound {
		t.Fatalf("scoped report for a repo without one = %d, want 404 from the resolver", code)
	}
	list := getJSON[workspaceListResponse](t, mux, WorkspacesPath).Workspaces
	if len(list) != 3 || list[0].Folder != "api" || list[1].Folder != "api" || list[1].Name != "api (2)" {
		t.Fatalf("workspace list = %+v, want both api repos with folder api", list)
	}
}

func TestWorkspaceRegistryForgetsTheLeastRecentlyRegisteredRepo(t *testing.T) {
	startup := mkdirRepo(t, "startup")
	w := newWorkspaceResolvers(store.New(), dashboards.Config{WorkspaceRoot: startup}, audit.Config{WorkspaceRoot: startup})
	parent := t.TempDir()
	register := func(name string, at int64) {
		t.Helper()
		root := filepath.Join(parent, name)
		if err := os.MkdirAll(root, 0o755); err != nil {
			t.Fatal(err)
		}
		if _, _, err := w.setRoot(root, at); err != nil {
			t.Fatal(err)
		}
	}

	// A newer registration keeps "pinned" active while every later one is stale.
	register("pinned", 1_000_000)
	for i := range maxRegisteredWorkspaces + 4 {
		register(fmt.Sprintf("repo%02d", i), int64(i+1))
	}

	if got := w.name(); got != "pinned" {
		t.Fatalf("active = %q, want pinned to survive eviction", got)
	}
	names := map[string]bool{}
	for _, item := range w.list().Workspaces {
		names[item.Name] = true
	}
	if len(names) != maxRegisteredWorkspaces {
		t.Fatalf("registry holds %d workspaces, want the cap %d", len(names), maxRegisteredWorkspaces)
	}
	for _, gone := range []string{"startup", "repo00", "repo01", "repo02", "repo03", "repo04"} {
		if names[gone] {
			t.Fatalf("%s should have been forgotten first: %v", gone, names)
		}
	}
	if !names["pinned"] || !names["repo05"] || !names[fmt.Sprintf("repo%02d", maxRegisteredWorkspaces+3)] {
		t.Fatalf("registry dropped the active or a recent workspace: %v", names)
	}
}

func TestWorkspaceRegistryIsSafeUnderConcurrentUse(t *testing.T) {
	startup := mkdirRepo(t, "startup")
	w := newWorkspaceResolvers(store.New(), dashboards.Config{WorkspaceRoot: startup}, audit.Config{WorkspaceRoot: startup})
	parent := t.TempDir()
	roots := make([]string, maxRegisteredWorkspaces+8)
	for i := range roots {
		roots[i] = filepath.Join(parent, fmt.Sprintf("repo%02d", i))
		if err := os.MkdirAll(roots[i], 0o755); err != nil {
			t.Fatal(err)
		}
	}

	var wg sync.WaitGroup
	for i, root := range roots {
		wg.Add(2)
		go func() {
			defer wg.Done()
			if _, _, err := w.setRoot(root, int64(i)); err != nil {
				t.Error(err)
			}
		}()
		go func() {
			defer wg.Done()
			for _, item := range w.list().Workspaces {
				if _, ok := w.lookup(item.Name); !ok && item.Name == w.name() {
					t.Errorf("active workspace %q is not resolvable", item.Name)
				}
			}
		}()
	}
	wg.Wait()

	if got := len(w.list().Workspaces); got != maxRegisteredWorkspaces {
		t.Fatalf("registry holds %d workspaces after concurrent registration, want %d", got, maxRegisteredWorkspaces)
	}
	if _, ok := w.lookup(w.name()); !ok {
		t.Fatal("active workspace must stay registered")
	}
}
