package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
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
