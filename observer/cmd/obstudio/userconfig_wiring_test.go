package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

func TestUserConfigFileStateWiring(t *testing.T) {
	_, path := telemetryHome(t)
	var notified atomic.Int32
	prev := notifyConfigChanged
	notifyConfigChanged = func() { notified.Add(1) }
	t.Cleanup(func() { notifyConfigChanged = prev })

	w := openUserConfig()
	if w.manager == nil || w.api == nil || w.status == nil {
		t.Fatalf("wiring %+v", w)
	}
	m := w.manager
	waitFor := func(n int32, msg string) {
		t.Helper()
		deadline := time.Now().Add(2 * time.Second)
		for notified.Load() != n {
			if time.Now().After(deadline) {
				t.Fatalf("timed out: %s: %d notifications, want %d", msg, notified.Load(), n)
			}
			time.Sleep(10 * time.Millisecond)
		}
	}
	handWrite := func(content []byte) {
		t.Helper()
		tmp := path + ".tmp-test"
		if err := os.WriteFile(tmp, content, 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Rename(tmp, path); err != nil {
			t.Fatal(err)
		}
	}

	if err := userconfig.Set(m, userconfig.TelemetryEnabled, false); err != nil {
		t.Fatal(err)
	}
	waitFor(1, "value")

	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	afterB := append(content, "foo: 1\n"...)
	handWrite(afterB)
	waitFor(2, "unknown-key")

	handWrite([]byte("telemetry: [unclosed"))
	waitFor(3, "broken")
	if m.Get().Telemetry.Enabled {
		t.Error("broken: last-good not kept")
	}

	handWrite(afterB)
	waitFor(4, "fixed-same-values")

	src, err := os.ReadFile("userconfig_wiring.go")
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(src, []byte(".Subscribe(")) {
		t.Error("one-callback: the wiring calls Subscribe")
	}

	if err := m.Close(); err != nil {
		t.Fatal(err)
	}
	if err := userconfig.Set(m, userconfig.TelemetryEnabled, true); !errors.Is(err, userconfig.ErrClosed) {
		t.Errorf("close-cancels: Set after Close: %v", err)
	}
	if n := notified.Load(); n > 5 {
		t.Errorf("close-cancels: %d notifications after Close", n)
	}
}

func TestUserConfigWiringWithoutHome(t *testing.T) {
	t.Setenv("HOME", "")
	t.Setenv("USERPROFILE", "")
	if w := openUserConfig(); w.manager != nil || w.api != nil || w.status != nil {
		t.Errorf("wiring without a home: %+v", w)
	}
}

// gateWiringMux builds the wiring for the given gate value and registers it on
// an API mux the way run() does.
func gateWiringMux(t *testing.T, enabled bool) (userConfigWiring, *http.ServeMux, *atomic.Int32) {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	var notified atomic.Int32
	prev := notifyConfigChanged
	notifyConfigChanged = func() { notified.Add(1) }
	t.Cleanup(func() { notifyConfigChanged = prev })

	w := buildUserConfig(enabled)
	if w.manager != nil {
		t.Cleanup(func() { _ = w.manager.Close() })
	}
	mux := http.NewServeMux()
	api.Register(mux, store.New(), api.ServerInfo{Kind: "obstudio", APIVersion: "v1", ConfigManager: enabled}, w.api, w.status)
	return w, mux, &notified
}

func gateGet(mux *http.ServeMux, method, path string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader("{}"))
	r.RemoteAddr = "127.0.0.1:5555"
	r.Host = "127.0.0.1:17900"
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, r)
	return rec
}

func assertHealthConfigManager(t *testing.T, mux *http.ServeMux, want bool) {
	t.Helper()
	rec := gateGet(mux, http.MethodGet, "/api/health")
	if rec.Code != http.StatusOK {
		t.Fatalf("health: status %d", rec.Code)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if got, ok := body["configManager"].(bool); !ok || got != want {
		t.Errorf("health: configManager = %#v, want %v", body["configManager"], want)
	}
}

func TestUserConfigWiringGateOff(t *testing.T) {
	w, mux, notified := gateWiringMux(t, false)
	if w.manager != nil || w.api != nil || w.status != nil {
		t.Errorf("no-manager: %+v", w)
	}
	home := os.Getenv("HOME")
	if _, err := os.Stat(filepath.Join(home, ".obstudio", "config.yaml")); err == nil {
		t.Error("no-file: config.yaml exists")
	}
	for _, rt := range []struct{ method, path string }{
		{http.MethodGet, "/api/config"},
		{http.MethodPost, "/api/config"},
		{http.MethodGet, "/api/config/definitions"},
		{http.MethodGet, "/api/config/status"},
	} {
		rec := gateGet(mux, rt.method, rt.path)
		if rec.Code != http.StatusNotFound && rec.Code != http.StatusMethodNotAllowed {
			t.Errorf("no-routes: %s %s = %d", rt.method, rt.path, rec.Code)
		}
		if b := rec.Body.String(); strings.Contains(b, "telemetry") || strings.Contains(b, "\"state\"") {
			t.Errorf("no-routes: %s %s body %q", rt.method, rt.path, b)
		}
	}
	assertHealthConfigManager(t, mux, false)
	if n := notified.Load(); n != 0 {
		t.Errorf("no-notice: %d notifications", n)
	}
}

func TestUserConfigWiringGateOn(t *testing.T) {
	w, mux, _ := gateWiringMux(t, true)
	if w.manager == nil || w.api == nil || w.status == nil {
		t.Fatalf("manager: %+v", w)
	}
	got, err := os.ReadFile(filepath.Join(os.Getenv("HOME"), ".obstudio", "config.yaml"))
	if err != nil || string(got) != userconfig.Scaffold() {
		t.Errorf("scaffolded: %q, %v", got, err)
	}
	for _, path := range []string{"/api/config", "/api/config/definitions", "/api/config/status"} {
		if rec := gateGet(mux, http.MethodGet, path); rec.Code != http.StatusOK {
			t.Errorf("routes: GET %s = %d", path, rec.Code)
		}
	}
	assertHealthConfigManager(t, mux, true)
}
