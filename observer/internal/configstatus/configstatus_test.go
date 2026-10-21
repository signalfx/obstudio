package configstatus

import (
	"crypto/sha256"
	"encoding/hex"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

func eventually(t *testing.T, cond func() bool, msg string) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting: %s", msg)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func quietManager(t *testing.T, path string) *userconfig.Manager {
	t.Helper()
	m, err := userconfig.NewManager(path, userconfig.WithLogf(func(string, ...any) {}))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { m.Close() })
	return m
}

func newPath(t *testing.T, content *string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.yaml")
	if content != nil {
		if err := os.WriteFile(path, []byte(*content), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return path
}

// write replaces the file atomically and, when the content is well-formed,
// waits for the Manager to pick it up.
func write(t *testing.T, m *userconfig.Manager, path, content string) {
	t.Helper()
	tmp := path + ".tmp-test"
	if err := os.WriteFile(tmp, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(tmp, path); err != nil {
		t.Fatal(err)
	}
	if _, _, err := userconfig.Load(path); err != nil {
		return
	}
	want := sha256.Sum256([]byte(content))
	eventually(t, func() bool { return m.Get().Hash == want }, "manager reload")
}

func scaffoldWith(old, new string) string {
	return strings.Replace(userconfig.Scaffold(), old, new, 1)
}

func noSection() string {
	sc := userconfig.Scaffold()
	return sc[:strings.Index(sc, "telemetry:")]
}

type kk struct{ key, kind string }

func TestStateTable(t *testing.T) {
	type row struct {
		name     string
		start    string
		change   func(t *testing.T, m *userconfig.Manager, path string)
		state    State
		warn     bool
		enabled  bool
		diags    []kk
		unixOnly bool
	}
	writeRow := func(content string) func(*testing.T, *userconfig.Manager, string) {
		return func(t *testing.T, m *userconfig.Manager, path string) { write(t, m, path, content) }
	}
	sc := userconfig.Scaffold()
	rows := []row{
		{name: "none", change: func(*testing.T, *userconfig.Manager, string) {}, state: StateOK, enabled: true},
		{name: "maybe", change: writeRow(scaffoldWith("enabled: true", "enabled: maybe")), state: StateInvalid, warn: true, diags: []kk{{"telemetry.enabled", "invalid"}}},
		{name: "line removed", change: writeRow(scaffoldWith("  enabled: true\n", "")), state: StateInvalid, warn: true, diags: []kk{{"telemetry.enabled", "absent"}}},
		{name: "section removed", change: writeRow(noSection()), state: StateInvalid, warn: true, diags: []kk{{"telemetry.enabled", "absent"}}},
		{name: "section not mapping", change: writeRow(noSection() + "telemetry: true\n"), state: StateInvalid, warn: true, diags: []kk{{"telemetry", "invalid"}}},
		{name: "empty", change: writeRow(""), state: StateInvalid, warn: true, diags: []kk{{"telemetry.enabled", "absent"}}},
		{name: "version", change: writeRow("version: 1\n" + sc), state: StateOK, enabled: true, diags: []kk{{"version", "unknown_key"}}},
		{name: "server", change: writeRow(sc + "server: {port: 9000}\n"), state: StateOK, enabled: true, diags: []kk{{"server", "unknown_key"}}},
		{name: "broken", change: writeRow("telemetry: [unclosed"), state: StateUnparseable, warn: true, enabled: true},
		{name: "broken from off", start: scaffoldWith("enabled: true", "enabled: false"), change: writeRow("telemetry: [unclosed"), state: StateUnparseable, warn: true},
		{name: "deleted", change: func(t *testing.T, _ *userconfig.Manager, path string) { os.Remove(path) }, state: StateMissing, enabled: true},
		{name: "unreadable", change: func(t *testing.T, _ *userconfig.Manager, path string) {
			if err := os.Chmod(path, 0); err != nil {
				t.Fatal(err)
			}
		}, state: StateUnparseable, warn: true, enabled: true, unixOnly: true},
	}
	for _, r := range rows {
		t.Run(r.name, func(t *testing.T) {
			if r.name == "line removed" {
				t.Skip("pending spec clarification: null section value")
			}
			if r.unixOnly && (runtime.GOOS == "windows" || os.Geteuid() == 0) {
				t.Skip("needs Unix permissions and a non-root user")
			}
			start := sc
			if r.start != "" {
				start = r.start
			}
			path := newPath(t, &start)
			m := quietManager(t, path)
			r.change(t, m, path)
			st := New(m, path).Build()
			if st.State != r.state || st.Warn != r.warn || st.Degraded || st.Effective.Telemetry.Enabled != r.enabled {
				t.Errorf("status %+v", st)
			}
			var got []kk
			for _, d := range st.Diagnostics {
				got = append(got, kk{d.Key, d.Kind})
			}
			if st.Diagnostics == nil || !reflect.DeepEqual(got, r.diags) {
				t.Errorf("diagnostics %v (nil=%v), want %v", got, st.Diagnostics == nil, r.diags)
			}
			if st.Path != path {
				t.Errorf("path %q", st.Path)
			}
			assertMessage(t, st, path)
		})
	}
}

func assertMessage(t *testing.T, st Status, path string) {
	t.Helper()
	if !st.Warn {
		if st.Message != "" {
			t.Errorf("message on a non-warn status: %q", st.Message)
		}
		return
	}
	prefix := "Using your last valid settings"
	if !st.Effective.Telemetry.Enabled {
		prefix = "Telemetry is off"
	}
	if !strings.HasPrefix(st.Message, prefix) || !strings.Contains(st.Message, st.Path) || strings.Contains(st.Message, "\n") {
		t.Errorf("message %q", st.Message)
	}
	_, diags, err := userconfig.Load(path)
	if st.State == StateUnparseable && !strings.Contains(st.Message, err.Error()) {
		t.Errorf("message lacks the error text: %q", st.Message)
	}
	if st.State == StateInvalid {
		for _, d := range diags {
			if warnWorthy(d, warnKeys()) && !strings.Contains(st.Message, d.Message) {
				t.Errorf("message lacks %q: %q", d.Message, st.Message)
			}
		}
	}
	if !strings.Contains(st.Message, "delete") {
		t.Errorf("message has no fix-or-delete hint: %q", st.Message)
	}
}

func TestDegradedStart(t *testing.T) {
	broken := "telemetry: [unclosed"
	path := newPath(t, &broken)
	st := New(quietManager(t, path), path).Build()
	if st.State != StateUnparseable || !st.Warn || !st.Degraded || st.Effective.Telemetry.Enabled || !strings.HasPrefix(st.Message, "Telemetry is off") {
		t.Errorf("a: %+v", st)
	}

	if runtime.GOOS == "windows" || os.Geteuid() == 0 {
		return
	}
	parent := t.TempDir()
	if err := os.Chmod(parent, 0o500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chmod(parent, 0o700) })
	bpath := filepath.Join(parent, ".obstudio", "config.yaml")
	st = New(quietManager(t, bpath), bpath).Build()
	if st.State != StateMissing || st.Warn || !st.Degraded || st.Effective.Telemetry.Enabled {
		t.Errorf("b: %+v", st)
	}
}

var hex64 = regexp.MustCompile(`^[0-9a-f]{64}$`)

func TestFingerprintStability(t *testing.T) {
	sc := userconfig.Scaffold()
	path := newPath(t, &sc)
	m := quietManager(t, path)
	b := New(m, path)
	fp := func(content string) string {
		t.Helper()
		write(t, m, path, content)
		f := b.Build().Fingerprint
		if !hex64.MatchString(f) {
			t.Fatalf("fingerprint %q", f)
		}
		return f
	}
	maybe := scaffoldWith("enabled: true", "enabled: maybe")
	f1 := fp(maybe)
	f2 := b.Build().Fingerprint
	f3 := fp(maybe)
	if f1 != f2 || f2 != f3 {
		t.Error("same content gave different fingerprints")
	}
	if fp(scaffoldWith("enabled: true", "enabled: nope")) != f1 {
		t.Error("a different value at the same site changed the fingerprint")
	}
	different := map[string]string{
		"maybe":       f1,
		"not mapping": fp(noSection() + "telemetry: true\n"),
		"broken":      fp("telemetry: [unclosed"),
	}
	seen := map[string]string{}
	for name, f := range different {
		if other, ok := seen[f]; ok {
			t.Errorf("%s and %s share a fingerprint", name, other)
		}
		seen[f] = name
	}
	moved := strings.Replace(maybe, "  enabled: maybe", "  # moved\n  enabled: maybe", 1)
	if fp(moved) == f1 {
		t.Error("moving the line kept the fingerprint")
	}
	if fp(maybe+"zz: 1\n") != f1 {
		t.Error("an unknown key changed the fingerprint")
	}

	t.Run("consequence-flip", func(t *testing.T) {
		sc := userconfig.Scaffold()
		path := newPath(t, &sc)
		m := quietManager(t, path)
		write(t, m, path, "telemetry: [unclosed")
		_, _, err1 := userconfig.Load(path)
		s1 := New(m, path).Build()
		m.Close()
		_, _, err2 := userconfig.Load(path)
		s2 := New(quietManager(t, path), path).Build()
		if err1.Error() != err2.Error() {
			t.Fatal("error text changed between loads")
		}
		if !s1.Effective.Telemetry.Enabled || s2.Effective.Telemetry.Enabled || !s2.Degraded {
			t.Errorf("effective %+v / %+v", s1, s2)
		}
		if s1.State != StateUnparseable || s2.State != StateUnparseable || s1.Fingerprint == s2.Fingerprint {
			t.Error("a flipped consequence kept the fingerprint")
		}
	})
	t.Run("rows-9-10", func(t *testing.T) {
		fps := map[bool]string{}
		for _, start := range []string{userconfig.Scaffold(), scaffoldWith("enabled: true", "enabled: false")} {
			path := newPath(t, &start)
			m := quietManager(t, path)
			write(t, m, path, "telemetry: [unclosed")
			st := New(m, path).Build()
			fps[st.Effective.Telemetry.Enabled] = st.Fingerprint
		}
		if fps[true] == "" || fps[false] == "" || fps[true] == fps[false] {
			t.Errorf("fingerprints %v", fps)
		}
	})
	t.Run("no-flip-no-change", func(t *testing.T) {
		off := scaffoldWith("enabled: true", "enabled: false")
		path := newPath(t, &off)
		m := quietManager(t, path)
		write(t, m, path, "telemetry: [unclosed")
		f1 := New(m, path).Build().Fingerprint
		m.Close()
		f2 := New(quietManager(t, path), path).Build().Fingerprint
		if f1 != f2 {
			t.Error("a restart with the same consequence changed the fingerprint")
		}
	})
	t.Run("recompute", func(t *testing.T) {
		for _, content := range []string{maybe, "telemetry: [unclosed"} {
			path := newPath(t, &content)
			st := New(quietManager(t, path), path).Build()
			_, diags, err := userconfig.Load(path)
			bit := "0"
			if st.Effective.Telemetry.Enabled {
				bit = "1"
			}
			var entries []string
			for _, d := range diags {
				if warnWorthy(d, warnKeys()) {
					entries = append(entries, d.Key+":"+string(d.Kind)+":"+strconv.Itoa(d.Line))
				}
			}
			x := ""
			if err != nil {
				x = err.Error()
			}
			sum := sha256.Sum256([]byte(string(st.State) + "\n" + bit + "\n" + strings.Join(entries, "\n") + "\n" + x))
			if hex.EncodeToString(sum[:]) != st.Fingerprint {
				t.Errorf("%q: fingerprint does not match the formula", content)
			}
		}
	})
}

func TestBuildReadsGetUnwatched(t *testing.T) {
	if runtime.GOOS == "windows" || os.Geteuid() == 0 {
		t.Skip("needs Unix permissions and a non-root user")
	}
	parent := t.TempDir()
	if err := os.Chmod(parent, 0o500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chmod(parent, 0o700) })
	dir := filepath.Join(parent, ".obstudio")
	path := filepath.Join(dir, "config.yaml")
	m := quietManager(t, path)
	if err := os.Chmod(parent, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	aged := func(content string) time.Time {
		t.Helper()
		if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
		old := time.Now().Add(-time.Second).Truncate(time.Millisecond)
		if err := os.Chtimes(path, old, old); err != nil {
			t.Fatal(err)
		}
		return old
	}
	b := New(m, path)
	aged(userconfig.Scaffold())
	if st := b.Build(); st.State != StateOK || st.Degraded || !st.Effective.Telemetry.Enabled {
		t.Errorf("first build %+v", st)
	}
	content := scaffoldWith("enabled: true", "enabled: maybe")
	mtime := aged(content)
	if st := b.Build(); st.State != StateInvalid || !st.Warn || st.Effective.Telemetry.Enabled {
		t.Errorf("second build %+v", st)
	}
	got, _ := os.ReadFile(path)
	fi, _ := os.Stat(path)
	if string(got) != content || !fi.ModTime().Equal(mtime) {
		t.Error("Build touched the file")
	}
}

type countingGetter struct{ calls int }

func (g *countingGetter) Get() userconfig.Snapshot {
	g.calls++
	return userconfig.FailSafeSnapshot()
}

var _ Getter = (*userconfig.Manager)(nil)

func nonTestSources(t *testing.T) map[string][]byte {
	t.Helper()
	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	out := map[string][]byte{}
	for _, f := range files {
		if strings.HasSuffix(f, "_test.go") {
			continue
		}
		src, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		out[f] = src
	}
	return out
}

func TestBuilderUsesGetter(t *testing.T) {
	sc := userconfig.Scaffold()
	path := newPath(t, &sc)
	g := &countingGetter{}
	st := New(g, path).Build()
	if g.calls != 1 {
		t.Errorf("Get called %d times", g.calls)
	}
	if st.Effective.Telemetry.Enabled || !st.Degraded || st.State != StateOK {
		t.Errorf("status %+v", st)
	}
	for f, src := range nonTestSources(t) {
		if strings.Contains(string(src), "userconfig.Manager") {
			t.Errorf("%s names the Manager type", f)
		}
	}
}

func TestWarnKeysDerived(t *testing.T) {
	if got := warnKeys(); !reflect.DeepEqual(got, []string{userconfig.TelemetryEnabled.Path()}) {
		t.Errorf("warn keys %v", got)
	}
	keys := warnKeys()
	sec := userconfig.SectionTelemetry.Path()
	if !warnWorthy(userconfig.Diagnostic{Key: sec, Kind: userconfig.DiagInvalid}, keys) {
		t.Error("an invalid section holding a warn key is not warn-worthy")
	}
	if warnWorthy(userconfig.Diagnostic{Key: "zz", Kind: userconfig.DiagInvalid}, keys) ||
		warnWorthy(userconfig.Diagnostic{Key: "server", Kind: userconfig.DiagUnknownKey}, keys) {
		t.Error("an unrelated diagnostic is warn-worthy")
	}
	// Struct tags are the JSON field names, not references to settings.
	for f, src := range nonTestSources(t) {
		file, err := parser.ParseFile(token.NewFileSet(), f, src, 0)
		if err != nil {
			t.Fatal(err)
		}
		tags := map[*ast.BasicLit]bool{}
		ast.Inspect(file, func(n ast.Node) bool {
			if field, ok := n.(*ast.Field); ok && field.Tag != nil {
				tags[field.Tag] = true
			}
			return true
		})
		ast.Inspect(file, func(n ast.Node) bool {
			lit, ok := n.(*ast.BasicLit)
			if !ok || lit.Kind != token.STRING || tags[lit] {
				return true
			}
			if v, err := strconv.Unquote(lit.Value); err == nil && (v == "telemetry.enabled" || v == "telemetry") {
				t.Errorf("%s: string literal %s names a setting", f, lit.Value)
			}
			return true
		})
	}
}

func TestPrivacyImports(t *testing.T) {
	goBin, err := exec.LookPath("go")
	if err != nil {
		t.Skip("go tool not on PATH")
	}
	const mod = "github.com/signalfx/obstudio/observer"
	cmd := exec.Command(goBin, "list", "-deps", "-f", "{{.ImportPath}} {{join .Imports \" \"}}", "./...")
	cmd.Dir = filepath.Join("..", "..")
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("go list: %v", err)
	}
	allowed := map[string]bool{mod + "/internal/api": true, mod + "/internal/mcp": true, mod + "/cmd/obstudio": true}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 0 {
			continue
		}
		pkg, imports := fields[0], fields[1:]
		for _, imp := range imports {
			if imp == mod+"/internal/configstatus" && !allowed[pkg] {
				t.Errorf("%s imports configstatus", pkg)
			}
		}
		if pkg == mod+"/internal/configstatus" {
			for _, imp := range imports {
				if strings.HasPrefix(imp, mod+"/") && imp != mod+"/internal/userconfig" {
					t.Errorf("configstatus imports %s", imp)
				}
			}
		}
		if pkg == mod+"/internal/userconfig" {
			for _, imp := range imports {
				if imp == mod+"/internal/configstatus" {
					t.Error("userconfig imports configstatus")
				}
			}
		}
	}
}
