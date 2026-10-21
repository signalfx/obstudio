package api

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/configstatus"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

type fakeUserConfig struct {
	mu        sync.Mutex
	snaps     []userconfig.Snapshot
	gets      int
	updates   []userconfig.Changes
	updateErr error
}

func snapshotWith(enabled bool) userconfig.Snapshot {
	s := userconfig.DefaultSnapshot()
	s.Telemetry.Enabled = enabled
	return s
}

func (f *fakeUserConfig) Get() userconfig.Snapshot {
	f.mu.Lock()
	defer f.mu.Unlock()
	i := min(f.gets, len(f.snaps)-1)
	f.gets++
	return f.snaps[i]
}

func (f *fakeUserConfig) Update(c userconfig.Changes) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.updates = append(f.updates, c)
	return f.updateErr
}

func (f *fakeUserConfig) calls() (gets, updates int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.gets, len(f.updates)
}

func configMux(params ...any) *http.ServeMux {
	mux := http.NewServeMux()
	Register(mux, store.New(), params...)
	return mux
}

type reqOpt func(*http.Request)

func header(k, v string) reqOpt { return func(r *http.Request) { r.Header.Set(k, v) } }

func serve(mux *http.ServeMux, method, path, body string, opts ...reqOpt) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.RemoteAddr = "127.0.0.1:5555"
	r.Host = "127.0.0.1:17900"
	for _, o := range opts {
		o(r)
	}
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, r)
	return w
}

func assertConfigHeaders(t *testing.T, w *httptest.ResponseRecorder) {
	t.Helper()
	if w.Header().Get("Content-Type") != "application/json" || w.Header().Get("Cache-Control") != "no-store" {
		t.Errorf("headers %v", w.Header())
	}
	for k := range w.Header() {
		if strings.HasPrefix(k, "Access-Control-Allow-") {
			t.Errorf("CORS header %s", k)
		}
	}
}

func errorText(t *testing.T, w *httptest.ResponseRecorder) string {
	t.Helper()
	var body struct{ Error string }
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("body %q: %v", w.Body.String(), err)
	}
	return body.Error
}

func tempManager(t *testing.T, content string) (*userconfig.Manager, string) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	m, err := userconfig.NewManager(path, userconfig.WithLogf(func(string, ...any) {}))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { m.Close() })
	return m, path
}

func TestUserConfigGetShape(t *testing.T) {
	f := &fakeUserConfig{snaps: []userconfig.Snapshot{snapshotWith(true), snapshotWith(false)}}
	mux := configMux(f)
	for _, want := range []string{`{"telemetry":{"enabled":true}}`, `{"telemetry":{"enabled":false}}`} {
		w := serve(mux, "GET", "/api/config", "")
		if w.Code != 200 || w.Body.String() != want {
			t.Errorf("GET = %d %q, want %q", w.Code, w.Body.String(), want)
		}
		assertConfigHeaders(t, w)
	}
	if _, updates := f.calls(); updates != 0 {
		t.Error("GET called Update")
	}
}

// assertNotRegistered checks that no handler serves the route. The API mux
// answers 405 rather than 404 for any unregistered /api/ path, because the
// OPTIONS /api/ preflight pattern matches the path.
func assertNotRegistered(t *testing.T, mux *http.ServeMux, method, path string) {
	t.Helper()
	w := serve(mux, method, path, "{}")
	if w.Code != 404 && w.Code != 405 {
		t.Errorf("%s %s = %d, want no handler", method, path, w.Code)
	}
	body := w.Body.Bytes()
	var doc map[string]json.RawMessage
	if json.Unmarshal(body, &doc) == nil {
		if _, ok := doc["telemetry"]; ok {
			t.Errorf("%s %s returned a config body", method, path)
		}
		if _, ok := doc["fingerprint"]; ok {
			t.Errorf("%s %s returned a status body", method, path)
		}
	}
	if bytes.Equal(body, userconfig.DefinitionsDocument()) {
		t.Errorf("%s %s returned the definitions document", method, path)
	}
}

func TestUserConfigRoutesAbsentWithoutManager(t *testing.T) {
	mux := configMux()
	for _, rt := range [][2]string{{"GET", "/api/config"}, {"POST", "/api/config"}, {"GET", "/api/config/definitions"}, {"POST", "/api/config/telemetry"}} {
		assertNotRegistered(t, mux, rt[0], rt[1])
	}
	f := &fakeUserConfig{snaps: []userconfig.Snapshot{snapshotWith(true)}}
	assertNotRegistered(t, configMux(f), "POST", "/api/config/telemetry")
	if _, updates := f.calls(); updates != 0 {
		t.Errorf("old route called Update %d times", updates)
	}
}

func TestUserConfigPostLocalNoOrigin(t *testing.T) {
	m, path := tempManager(t, userconfig.Scaffold())
	w := serve(configMux(NewUserConfig(m)), "POST", "/api/config", `{"telemetry":{"enabled":false}}`)
	if w.Code != 200 || w.Body.String() != `{"telemetry":{"enabled":false}}` {
		t.Errorf("POST = %d %q", w.Code, w.Body.String())
	}
	assertConfigHeaders(t, w)
	s, diags, err := userconfig.Load(path)
	if err != nil || s.Telemetry.Enabled || len(diags) != 0 {
		t.Errorf("file %+v %v %v", s, diags, err)
	}
}

func TestUserConfigGuardMatrix(t *testing.T) {
	type row struct {
		name, remote, host, origin, browser, fetchSite string
		want                                           int
	}
	rows := []row{
		{"same-origin", "127.0.0.1:1", "127.0.0.1:17900", "http://127.0.0.1:17900", "1", "same-origin", 200},
		{"localhost-same-origin", "127.0.0.1:1", "localhost:17900", "http://localhost:17900", "1", "same-origin", 200},
		{"cross-origin", "127.0.0.1:1", "127.0.0.1:17900", "http://evil.example", "1", "cross-site", 403},
		{"dns-rebind", "127.0.0.1:1", "evil.example:17900", "http://evil.example:17900", "1", "same-origin", 403},
		{"null-origin", "127.0.0.1:1", "127.0.0.1:17900", "null", "1", "", 403},
		{"no-browser-header", "127.0.0.1:1", "127.0.0.1:17900", "http://127.0.0.1:17900", "", "same-origin", 403},
		{"fetch-site-only", "127.0.0.1:1", "127.0.0.1:17900", "", "", "cross-site", 403},
		{"remote-peer", "10.0.0.5:1", "127.0.0.1:17900", "", "", "", 403},
	}
	assertNoCORS := func(t *testing.T, w *httptest.ResponseRecorder) {
		t.Helper()
		if w.Header().Get("Access-Control-Allow-Origin") != "" || w.Header().Get("Access-Control-Allow-Methods") != "" {
			t.Errorf("CORS headers %v", w.Header())
		}
	}
	for _, r := range rows {
		t.Run(r.name, func(t *testing.T) {
			f := &fakeUserConfig{snaps: []userconfig.Snapshot{snapshotWith(true)}}
			w := serve(configMux(f), "POST", "/api/config", `{"telemetry":{"enabled":true}}`, func(req *http.Request) {
				req.RemoteAddr, req.Host = r.remote, r.host
				for k, v := range map[string]string{"Origin": r.origin, "X-Obstudio-Browser-Request": r.browser, "Sec-Fetch-Site": r.fetchSite} {
					if v != "" {
						req.Header.Set(k, v)
					}
				}
			})
			if w.Code != r.want {
				t.Errorf("status %d, want %d (%s)", w.Code, r.want, w.Body.String())
			}
			wantUpdates := 0
			if r.want == 200 {
				wantUpdates = 1
			}
			if _, updates := f.calls(); updates != wantUpdates {
				t.Errorf("%d updates, want %d", updates, wantUpdates)
			}
			assertNoCORS(t, w)
		})
	}
	f := &fakeUserConfig{snaps: []userconfig.Snapshot{snapshotWith(true)}}
	w := serve(configMux(f), "OPTIONS", "/api/config", "", header("Origin", "http://evil.example"), header("Access-Control-Request-Method", "POST"))
	if w.Code != 403 {
		t.Errorf("preflight = %d", w.Code)
	}
	assertNoCORS(t, w)
}

func TestUserConfigPostBodyValidation(t *testing.T) {
	f := &fakeUserConfig{snaps: []userconfig.Snapshot{snapshotWith(true)}}
	mux := configMux(f)
	bodies := []string{
		`{"telemetry":{"enabled":"false"}}`,
		`{"telemetry":{"enabled":null}}`,
		`{"telemetry":{"zz":1}}`,
		`{"zz":{}}`,
		`{"telemetry":null}`,
		`{"telemetry":{"enabled":false},"zz":{}}`,
		`{"telemetry":{"enabled":false}}{"telemetry":{"enabled":true}}`,
		`[]`,
		``,
	}
	for _, body := range bodies {
		w := serve(mux, "POST", "/api/config", body)
		_, wantErr := userconfig.DecodeChanges([]byte(body))
		if w.Code != 400 || errorText(t, w) != wantErr.Error() {
			t.Errorf("%q: %d %q, want 400 %q", body, w.Code, w.Body.String(), wantErr)
		}
	}
	large := `{"telemetry":{"enabled":false}}` + strings.Repeat(" ", 5*1024)
	if w := serve(mux, "POST", "/api/config", large); w.Code != 400 || errorText(t, w) == "" {
		t.Errorf("large body: %d %q", w.Code, w.Body.String())
	}
	if _, updates := f.calls(); updates != 0 {
		t.Errorf("%d updates for invalid bodies", updates)
	}
	if w := serve(mux, "POST", "/api/config", `{"telemetry":{"enabled":false}}`); w.Code != 200 {
		t.Errorf("no Content-Type: %d", w.Code)
	}
}

func TestUserConfigPostEmptyBody(t *testing.T) {
	f := &fakeUserConfig{snaps: []userconfig.Snapshot{snapshotWith(false)}}
	w := serve(configMux(f), "POST", "/api/config", `{}`)
	if w.Code != 200 || w.Body.String() != `{"telemetry":{"enabled":false}}` {
		t.Errorf("fake: %d %q", w.Code, w.Body.String())
	}
	if len(f.updates) != 1 || f.updates[0].Len() != 0 {
		t.Errorf("updates %v", f.updates)
	}

	m, path := tempManager(t, userconfig.Scaffold())
	old := time.Now().Add(-time.Hour).Truncate(time.Second)
	if err := os.Chtimes(path, old, old); err != nil {
		t.Fatal(err)
	}
	w = serve(configMux(NewUserConfig(m)), "POST", "/api/config", `{}`)
	if w.Code != 200 || w.Body.String() != `{"telemetry":{"enabled":true}}` {
		t.Errorf("manager: %d %q", w.Code, w.Body.String())
	}
	content, _ := os.ReadFile(path)
	fi, _ := os.Stat(path)
	if string(content) != userconfig.Scaffold() || !fi.ModTime().Equal(old) {
		t.Error("empty body wrote the file")
	}
}

func TestUserConfigPostUpdateErrors(t *testing.T) {
	broken, path := tempManager(t, userconfig.Scaffold())
	if err := os.WriteFile(path, []byte("telemetry: [unclosed"), 0o600); err != nil {
		t.Fatal(err)
	}
	w := serve(configMux(NewUserConfig(broken)), "POST", "/api/config", `{"telemetry":{"enabled":true}}`)
	msg := errorText(t, w)
	if w.Code != 409 || !strings.HasPrefix(msg, "config.yaml could not be updated: ") || !strings.HasSuffix(msg, "Fix the file, or delete it and try again.") {
		t.Errorf("409 row: %d %q", w.Code, msg)
	}
	if content, _ := os.ReadFile(path); string(content) != "telemetry: [unclosed" {
		t.Error("broken file changed")
	}

	closed, _ := tempManager(t, userconfig.Scaffold())
	closed.Close()
	for _, body := range []string{`{"telemetry":{"enabled":true}}`, `{}`} {
		w := serve(configMux(NewUserConfig(closed)), "POST", "/api/config", body)
		if w.Code != 503 || errorText(t, w) != "Splunk Observability Studio is shutting down." {
			t.Errorf("503 row %q: %d %q", body, w.Code, w.Body.String())
		}
	}

	for _, tc := range []struct {
		err  error
		code int
		msg  string
	}{
		{errors.New("disk full"), 500, "config.yaml could not be updated: disk full"},
		{fmt.Errorf("%w: x", userconfig.ErrInvalidValue), 400, "userconfig: invalid value: x"},
	} {
		f := &fakeUserConfig{snaps: []userconfig.Snapshot{snapshotWith(true)}, updateErr: tc.err}
		w := serve(configMux(f), "POST", "/api/config", `{"telemetry":{"enabled":true}}`)
		if w.Code != tc.code || errorText(t, w) != tc.msg {
			t.Errorf("%v: %d %q", tc.err, w.Code, w.Body.String())
		}
	}
}

func TestUserConfigPostReturnsGet(t *testing.T) {
	f := &fakeUserConfig{snaps: []userconfig.Snapshot{snapshotWith(true)}}
	w := serve(configMux(f), "POST", "/api/config", `{"telemetry":{"enabled":false}}`)
	if w.Body.String() != `{"telemetry":{"enabled":true}}` {
		t.Errorf("body %q", w.Body.String())
	}
}

func TestUserConfigDefinitionsRoute(t *testing.T) {
	f := &fakeUserConfig{snaps: []userconfig.Snapshot{snapshotWith(true)}}
	mux := configMux(f)
	for _, opts := range [][]reqOpt{nil, {header("Origin", "http://evil.example")}} {
		w := serve(mux, "GET", "/api/config/definitions", "", opts...)
		if w.Code != 200 || !bytes.Equal(w.Body.Bytes(), userconfig.DefinitionsDocument()) {
			t.Errorf("GET = %d", w.Code)
		}
		assertConfigHeaders(t, w)
	}
	if gets, updates := f.calls(); gets != 0 || updates != 0 {
		t.Errorf("definitions called the manager: %d gets, %d updates", gets, updates)
	}
	if w := serve(mux, "POST", "/api/config/definitions", "{}"); w.Code != 405 {
		t.Errorf("POST = %d, want 405", w.Code)
	}
}

func TestUserConfigAdapter(t *testing.T) {
	m, path := tempManager(t, userconfig.Scaffold())
	u := NewUserConfig(m)
	var c userconfig.Changes
	userconfig.Put(&c, userconfig.TelemetryEnabled, false)
	if err := u.Update(c); err != nil {
		t.Fatal(err)
	}
	if s, _, _ := userconfig.Load(path); s.Telemetry.Enabled || u.Get() != m.Get() {
		t.Error("adapter did not delegate")
	}
	m.Close()
	if err := u.Update(c); !errors.Is(err, userconfig.ErrClosed) {
		t.Errorf("after Close: %v", err)
	}
	if n := reflect.TypeOf((*UserConfig)(nil)).Elem().NumMethod(); n != 2 {
		t.Errorf("UserConfig has %d methods", n)
	}
}

func TestConfigStatusEndpointShape(t *testing.T) {
	maybe := strings.Replace(userconfig.Scaffold(), "enabled: true", "enabled: maybe", 1)
	m, path := tempManager(t, maybe)
	b := configstatus.New(m, path)
	mux := configMux(b)
	w := serve(mux, "GET", "/api/config/status", "")
	if w.Code != 200 || !strings.HasPrefix(w.Header().Get("Content-Type"), "application/json") || w.Header().Get("Cache-Control") != "no-store" {
		t.Errorf("GET = %d %v", w.Code, w.Header())
	}
	if w.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Error("status response is readable cross-origin")
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(w.Body.Bytes(), &raw); err != nil {
		t.Fatal(err)
	}
	var keys []string
	for k := range raw {
		keys = append(keys, k)
	}
	want := []string{"degraded", "diagnostics", "effective", "fingerprint", "message", "path", "state", "warn"}
	if !sameSet(keys, want) {
		t.Errorf("keys %v", keys)
	}
	if string(raw["effective"]) != `{"telemetry":{"enabled":false}}` {
		t.Errorf("effective %s", raw["effective"])
	}
	var got configstatus.Status
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, b.Build()) {
		t.Errorf("body %+v differs from Build()", got)
	}
	if w := serve(mux, "POST", "/api/config/status", ""); w.Code != 405 {
		t.Errorf("POST = %d, want 405", w.Code)
	}
	assertNotRegistered(t, configMux(), "GET", "/api/config/status")

	okm, okPath := tempManager(t, userconfig.Scaffold())
	w = serve(configMux(configstatus.New(okm, okPath)), "GET", "/api/config/status", "")
	if !strings.Contains(w.Body.String(), `"diagnostics":[]`) {
		t.Errorf("ok body %s", w.Body.String())
	}
}

func sameSet(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	seen := map[string]bool{}
	for _, x := range a {
		seen[x] = true
	}
	for _, x := range b {
		if !seen[x] {
			return false
		}
	}
	return true
}
