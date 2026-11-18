package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"syscall"
	"testing"

	"github.com/signalfx/obstudio/observer/internal/api"
)

// TestResolveRunConfigDefaultsToFixedPort verifies the UI port defaults to the
// fixed 17900 (not the old 3000) when neither --port nor OBSTUDIO_PORT is set,
// and that an unset port is treated as NOT explicitly pinned (so a singleton
// collision defers rather than failing loud).
func TestResolveRunConfigDefaultsToFixedPort(t *testing.T) {
	t.Setenv(observerPortEnv, "")
	t.Setenv("PORT", "")
	resolved := resolveRunConfig(runConfig{})
	if resolved.observerHTTPPort != defaultObserverHTTPPort {
		t.Fatalf("observerHTTPPort = %q, want fixed default %q", resolved.observerHTTPPort, defaultObserverHTTPPort)
	}
	if resolved.observerHTTPPort != "17900" {
		t.Fatalf("fixed default drifted from 17900: got %q", resolved.observerHTTPPort)
	}
	if resolved.portExplicit {
		t.Fatal("portExplicit = true for the default port; want false (unpinned must defer on collision)")
	}
}

// TestResolveRunConfigIgnoresBarePORT verifies the ambient PORT env is NOT read
// for the UI port. Bare PORT is the var developers most often already export
// (Heroku/foreman/PaaS lineage); reading it would silently bind the wrong port.
func TestResolveRunConfigIgnoresBarePORT(t *testing.T) {
	t.Setenv("PORT", "4000")
	t.Setenv(observerPortEnv, "")
	resolved := resolveRunConfig(runConfig{})
	if resolved.observerHTTPPort != defaultObserverHTTPPort {
		t.Fatalf("observerHTTPPort = %q, want %q (bare PORT must be ignored)", resolved.observerHTTPPort, defaultObserverHTTPPort)
	}
	if resolved.portExplicit {
		t.Fatal("portExplicit = true from bare PORT; want false (bare PORT must not count as explicit)")
	}
}

// TestResolveRunConfigHonorsOBSTUDIOPORT verifies OBSTUDIO_PORT overrides the
// default and marks the port as explicitly pinned (collision -> fail loud).
func TestResolveRunConfigHonorsOBSTUDIOPORT(t *testing.T) {
	t.Setenv("PORT", "")
	t.Setenv(observerPortEnv, "18080")
	resolved := resolveRunConfig(runConfig{})
	if resolved.observerHTTPPort != "18080" {
		t.Fatalf("observerHTTPPort = %q, want 18080 from OBSTUDIO_PORT", resolved.observerHTTPPort)
	}
	if !resolved.portExplicit {
		t.Fatal("portExplicit = false with OBSTUDIO_PORT set; want true")
	}
}

// TestResolveRunConfigFlagBeatsEnv verifies precedence: --port (the config
// field) wins over OBSTUDIO_PORT, which wins over the default.
func TestResolveRunConfigFlagBeatsEnv(t *testing.T) {
	t.Setenv("PORT", "4000")
	t.Setenv(observerPortEnv, "18080")
	resolved := resolveRunConfig(runConfig{observerHTTPPort: "19000"})
	if resolved.observerHTTPPort != "19000" {
		t.Fatalf("observerHTTPPort = %q, want 19000 (--port must win)", resolved.observerHTTPPort)
	}
	if !resolved.portExplicit {
		t.Fatal("portExplicit = false with --port set; want true")
	}
}

// TestIsAddrInUseError verifies the cross-OS address-in-use detector that gates
// the singleton defer/fail-loud decision: a syscall EADDRINUSE (bare or wrapped
// with %w, as the ConnTracker's net.Listen error reaches it) is detected, while
// unrelated errors and nil are not.
func TestIsAddrInUseError(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want bool
	}{
		{"nil", nil, false},
		{"syscall EADDRINUSE", syscall.EADDRINUSE, true},
		{"wrapped EADDRINUSE", fmt.Errorf("listen tcp: %w", syscall.EADDRINUSE), true},
		{"deeply wrapped EADDRINUSE", fmt.Errorf("start connection tracker: %w", fmt.Errorf("listen 127.0.0.1:4317: %w", syscall.EADDRINUSE)), true},
		{"unrelated", errors.New("connection refused"), false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := isAddrInUseError(tc.err); got != tc.want {
				t.Fatalf("isAddrInUseError(%v) = %v, want %v", tc.err, got, tc.want)
			}
		})
	}
}

// TestRegisterWorkspaceWithRunningObserver covers the deferred-launch handoff:
// a CLI launch from a second repo points the running singleton at that repo,
// while a launcher-owned process without an explicit root registers nothing.
func TestRegisterWorkspaceWithRunningObserver(t *testing.T) {
	var got []string
	status := http.StatusOK
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != api.WorkspacePath || r.Header.Get("Origin") != "" {
			t.Errorf("unexpected request %s %s origin=%q", r.Method, r.URL.Path, r.Header.Get("Origin"))
		}
		var body struct {
			Root string
			At   int64
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body.At <= 0 {
			t.Errorf("registration carried at=%d, want a client timestamp so older ones can be ignored", body.At)
		}
		got = append(got, body.Root)
		w.WriteHeader(status)
	}))
	defer srv.Close()

	cwd := t.TempDir()
	t.Chdir(cwd)
	wantCwd, _ := os.Getwd()
	explicit := t.TempDir()

	t.Run("plain CLI registers its working directory", func(t *testing.T) {
		got = nil
		t.Setenv("OBSTUDIO_WORKSPACE_ROOT", "")
		t.Setenv("OBSTUDIO_OWNER", "")
		if err := registerWorkspaceWithRunningObserver(srv.URL); err != nil {
			t.Fatal(err)
		}
		if len(got) != 1 || got[0] != wantCwd {
			t.Fatalf("registered %v, want [%s]", got, wantCwd)
		}
	})
	t.Run("launcher-owned process without a root registers nothing", func(t *testing.T) {
		got = nil
		t.Setenv("OBSTUDIO_WORKSPACE_ROOT", "")
		t.Setenv("OBSTUDIO_OWNER", "vscode-extension")
		if err := registerWorkspaceWithRunningObserver(srv.URL); err != nil {
			t.Fatal(err)
		}
		if len(got) != 0 {
			t.Fatalf("registered %v, want nothing", got)
		}
	})
	t.Run("explicit root wins for any owner", func(t *testing.T) {
		got = nil
		t.Setenv("OBSTUDIO_WORKSPACE_ROOT", explicit)
		t.Setenv("OBSTUDIO_OWNER", "vscode-extension")
		if err := registerWorkspaceWithRunningObserver(srv.URL); err != nil {
			t.Fatal(err)
		}
		if len(got) != 1 || got[0] != explicit {
			t.Fatalf("registered %v, want [%s]", got, explicit)
		}
	})
	t.Run("rejected registration is an error, not a panic", func(t *testing.T) {
		status = http.StatusForbidden
		t.Setenv("OBSTUDIO_WORKSPACE_ROOT", explicit)
		if err := registerWorkspaceWithRunningObserver(srv.URL); err == nil {
			t.Fatal("want error for a 403 response")
		}
	})
	t.Run("unreachable observer is an error", func(t *testing.T) {
		t.Setenv("OBSTUDIO_WORKSPACE_ROOT", explicit)
		if err := registerWorkspaceWithRunningObserver("http://127.0.0.1:1"); err == nil {
			t.Fatal("want error when nothing is listening")
		}
	})
}
