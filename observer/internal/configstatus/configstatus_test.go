package configstatus

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
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

// homePath points the home directory at a fresh temp dir H and returns
// H/.obstudio/config.yaml, written with content unless content is nil.
func homePath(t *testing.T, content *string) string {
	t.Helper()
	home := t.TempDir()
	setHome(t, home)
	path := filepath.Join(home, ".obstudio", "config.yaml")
	if content != nil {
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(*content), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return path
}

func setHome(t *testing.T, home string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Setenv("USERPROFILE", home)
	} else {
		t.Setenv("HOME", home)
	}
}

var sep = string(filepath.Separator)

// tildePath is <P> for a homePath config.
var tildePath = "~" + sep + ".obstudio" + sep + "config.yaml"

const fix = "Fix the file, or delete it to restore defaults on next start."

// wantMessage is the FR7 text for st, with <P> = p and <E> from loading path.
func wantMessage(t *testing.T, st Status, path, p string) string {
	t.Helper()
	_, diags, err := userconfig.Load(path)
	switch {
	case st.State == StateInvalid:
		return "Some settings could not be read from " + p + ", so safe defaults are in use. " + fix
	case st.State == StateUnparseable:
		e := strings.NewReplacer("\r", " ", "\n", " ").Replace(err.Error())
		if st.Degraded {
			return "Some settings could not be read from " + p + ", so safe defaults are in use. " + e + " " + fix
		}
		return "Some settings could not be read from " + p + ", so your last valid settings are in use. " + e + " " + fix
	case st.State == StateOK && len(diags) > 0:
		return "Some entries in " + p + " are not recognized and have no effect."
	}
	return ""
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

var maybe = scaffoldWith("enabled: true", "enabled: maybe")

type kk struct{ key, kind string }

func kinds(st Status) []kk {
	var got []kk
	for _, d := range st.Diagnostics {
		got = append(got, kk{d.Key, d.Kind})
	}
	return got
}

// enabled reads effective.telemetry.enabled from a Status.
func enabled(t *testing.T, st Status) bool {
	t.Helper()
	var e struct {
		Telemetry struct {
			Enabled *bool `json:"enabled"`
		} `json:"telemetry"`
	}
	if err := json.Unmarshal(st.Effective, &e); err != nil || e.Telemetry.Enabled == nil {
		t.Fatalf("effective %s: %v", st.Effective, err)
	}
	return *e.Telemetry.Enabled
}

func unixOnly(t *testing.T) {
	t.Helper()
	if runtime.GOOS == "windows" || os.Geteuid() == 0 {
		t.Skip("needs Unix permissions and a non-root user")
	}
}

// started builds a home-setup config holding start, starts a Manager on it,
// and returns both.
func started(t *testing.T, start string) (*userconfig.Manager, string) {
	t.Helper()
	path := homePath(t, &start)
	return quietManager(t, path), path
}

func TestStateTable(t *testing.T) {
	type row struct {
		name     string
		start    string
		change   func(t *testing.T, m *userconfig.Manager, path string)
		state    State
		problem  bool
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
		{name: "maybe", change: writeRow(maybe), state: StateInvalid, problem: true, diags: []kk{{"telemetry.enabled", "invalid"}}},
		{name: "line removed", change: writeRow(scaffoldWith("  enabled: true\n", "")), state: StateInvalid, problem: true, diags: []kk{{"telemetry.enabled", "absent"}}},
		{name: "section removed", change: writeRow(noSection()), state: StateInvalid, problem: true, diags: []kk{{"telemetry.enabled", "absent"}}},
		{name: "section not mapping", change: writeRow(noSection() + "telemetry: true\n"), state: StateInvalid, problem: true, diags: []kk{{"telemetry", "invalid"}}},
		{name: "empty", change: writeRow(""), state: StateInvalid, problem: true, diags: []kk{{"telemetry.enabled", "absent"}}},
		{name: "version", change: writeRow("version: 1\n" + sc), state: StateOK, enabled: true, diags: []kk{{"version", "unknown_key"}}},
		{name: "server", change: writeRow(sc + "server: {port: 9000}\n"), state: StateOK, enabled: true, diags: []kk{{"server", "unknown_key"}}},
		{name: "broken", change: writeRow("telemetry: [unclosed"), state: StateUnparseable, problem: true, enabled: true},
		{name: "broken from off", start: scaffoldWith("enabled: true", "enabled: false"), change: writeRow("telemetry: [unclosed"), state: StateUnparseable, problem: true},
		{name: "deleted", change: func(t *testing.T, _ *userconfig.Manager, path string) { os.Remove(path) }, state: StateMissing, enabled: true},
		{name: "unreadable", change: func(t *testing.T, _ *userconfig.Manager, path string) {
			if err := os.Chmod(path, 0); err != nil {
				t.Fatal(err)
			}
		}, state: StateUnparseable, problem: true, enabled: true, unixOnly: true},
	}
	for _, r := range rows {
		t.Run(r.name, func(t *testing.T) {
			if r.unixOnly {
				unixOnly(t)
			}
			start := sc
			if r.start != "" {
				start = r.start
			}
			m, path := started(t, start)
			r.change(t, m, path)
			st := New(m, path).Build()
			if want := userconfig.EncodeSettings(m.Get().Settings); !bytes.Equal(st.Effective, want) {
				t.Errorf("effective-bytes: %s, want %s", st.Effective, want)
			}
			if st.State != r.state || st.Problem != r.problem || st.Degraded || enabled(t, st) != r.enabled {
				t.Errorf("fields: %+v", st)
			}
			if got := kinds(st); st.Diagnostics == nil || !reflect.DeepEqual(got, r.diags) {
				t.Errorf("diags-exact: %v (nil=%v), want %v", got, st.Diagnostics == nil, r.diags)
			}
			if st.Path != path {
				t.Errorf("path: %q", st.Path)
			}
			if want := wantMessage(t, st, path, tildePath); st.Message != want {
				t.Errorf("message-row: %q, want %q", st.Message, want)
			}
		})
	}
}

func TestDegradedStart(t *testing.T) {
	t.Run("a", func(t *testing.T) {
		broken := "telemetry: [unclosed"
		path := homePath(t, &broken)
		st := New(quietManager(t, path), path).Build()
		if st.State != StateUnparseable || !st.Problem || !st.Degraded || enabled(t, st) ||
			!bytes.Equal(st.Effective, userconfig.EncodeSettings(userconfig.FailSafeSettings())) {
			t.Errorf("%+v", st)
		}
		if want := wantMessage(t, st, path, tildePath); st.Message != want || !strings.Contains(st.Message, "so safe defaults are in use.") {
			t.Errorf("message %q, want %q", st.Message, want)
		}
	})
	t.Run("b", func(t *testing.T) {
		unixOnly(t)
		path := homePath(t, nil)
		home := filepath.Dir(filepath.Dir(path))
		if err := os.Chmod(home, 0o500); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { os.Chmod(home, 0o700) })
		st := New(quietManager(t, path), path).Build()
		if st.State != StateMissing || st.Problem || !st.Degraded || enabled(t, st) || st.Message != "" {
			t.Errorf("%+v", st)
		}
	})
}

func TestProblemLevels(t *testing.T) {
	level2 := "Some entries in " + tildePath + " are not recognized and have no effect."
	t.Run("level-1", func(t *testing.T) {
		for _, content := range []string{maybe, "telemetry: [unclosed"} {
			m, path := started(t, userconfig.Scaffold())
			write(t, m, path, content)
			if st := New(m, path).Build(); !st.Problem {
				t.Errorf("%q: %+v", content, st)
			}
		}
	})
	t.Run("level-2", func(t *testing.T) {
		m, path := started(t, userconfig.Scaffold())
		write(t, m, path, userconfig.Scaffold()+"zz: 1\n")
		st := New(m, path).Build()
		if st.State != StateOK || st.Problem || st.Message != level2 {
			t.Errorf("%+v", st)
		}
		if len(st.Diagnostics) != 1 || st.Diagnostics[0].Key != "zz" || st.Diagnostics[0].Kind != "unknown_key" || st.Diagnostics[0].Line == 0 {
			t.Errorf("diagnostics %+v", st.Diagnostics)
		}
	})
	t.Run("mixed", func(t *testing.T) {
		m, path := started(t, userconfig.Scaffold())
		write(t, m, path, maybe+"zz: 1\n")
		st := New(m, path).Build()
		if !st.Problem || st.Message != wantMessage(t, st, path, tildePath) || st.State != StateInvalid || strings.Contains(st.Message, "not recognized") {
			t.Errorf("%+v", st)
		}
		if got := kinds(st); !reflect.DeepEqual(got, []kk{{"telemetry.enabled", "invalid"}, {"zz", "unknown_key"}}) {
			t.Errorf("diagnostics %v", got)
		}
	})
	t.Run("neither", func(t *testing.T) {
		m, path := started(t, userconfig.Scaffold())
		b := New(m, path)
		if st := b.Build(); st.Problem || st.Message != "" {
			t.Errorf("scaffold: %+v", st)
		}
		os.Remove(path)
		if st := b.Build(); st.Problem || st.Message != "" {
			t.Errorf("deleted: %+v", st)
		}
	})
}

func TestMessageShape(t *testing.T) {
	type c struct {
		name string
		st   Status
		path string
	}
	var cases []c
	{ // row 2
		m, path := started(t, userconfig.Scaffold())
		write(t, m, path, maybe)
		cases = append(cases, c{"row2", New(m, path).Build(), path})
	}
	{ // row 9
		m, path := started(t, userconfig.Scaffold())
		write(t, m, path, "telemetry: [unclosed")
		cases = append(cases, c{"row9", New(m, path).Build(), path})
	}
	{ // row 11
		path := homePath(t, ptr("telemetry: [unclosed"))
		cases = append(cases, c{"row11", New(quietManager(t, path), path).Build(), path})
	}
	for _, k := range cases {
		msg := k.st.Message
		if want := wantMessage(t, k.st, k.path, tildePath); msg != want {
			t.Errorf("exact %s: %q, want %q", k.name, msg, want)
		}
		if strings.ContainsAny(msg, "\r\n") {
			t.Errorf("one-line %s: %q", k.name, msg)
		}
		generic := strings.ReplaceAll(msg, tildePath, "")
		if _, _, err := userconfig.Load(k.path); err != nil {
			generic = strings.ReplaceAll(generic, strings.NewReplacer("\r", " ", "\n", " ").Replace(err.Error()), "")
		}
		for _, w := range []string{"telemetry", "enabled", "maybe", "false", "true", "fail-safe"} {
			if strings.Contains(generic, w) {
				t.Errorf("generic %s: %q contains %q", k.name, msg, w)
			}
		}
		if !strings.HasSuffix(msg, fix) {
			t.Errorf("ends-with-fix %s: %q", k.name, msg)
		}
	}
	if !strings.Contains(cases[1].st.Message, "so your last valid settings are in use.") || cases[1].st.Degraded {
		t.Errorf("last-valid-only-running row9: %+v", cases[1].st)
	}
	if !strings.Contains(cases[2].st.Message, "so safe defaults are in use.") || !cases[2].st.Degraded {
		t.Errorf("last-valid-only-running row11: %+v", cases[2].st)
	}
}

func ptr(s string) *string { return &s }

type fixedGetter userconfig.Snapshot

func (g fixedGetter) Get() userconfig.Snapshot { return userconfig.Snapshot(g) }

func TestHomeAbbrev(t *testing.T) {
	g := fixedGetter(userconfig.DefaultSnapshot())
	inHome := func(t *testing.T, home string) string {
		t.Helper()
		path := filepath.Join(home, ".obstudio", "config.yaml")
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(maybe), 0o600); err != nil {
			t.Fatal(err)
		}
		return path
	}
	t.Run("inside", func(t *testing.T) {
		h := t.TempDir()
		path := inHome(t, h)
		setHome(t, h)
		st := New(g, path).Build()
		if !strings.Contains(st.Message, tildePath) || strings.Contains(st.Message, h) || st.Path != path {
			t.Errorf("%+v", st)
		}
	})
	t.Run("trailing-sep-home", func(t *testing.T) {
		h := t.TempDir()
		path := inHome(t, h)
		setHome(t, h+sep)
		if st := New(g, path).Build(); !strings.Contains(st.Message, tildePath) || strings.Contains(st.Message, h) {
			t.Errorf("%+v", st)
		}
	})
	t.Run("outside", func(t *testing.T) {
		h, o := t.TempDir(), t.TempDir()
		path := inHome(t, o)
		setHome(t, h)
		if st := New(g, path).Build(); !strings.Contains(st.Message, path) || strings.Contains(st.Message, "~") {
			t.Errorf("%+v", st)
		}
	})
	t.Run("sibling-prefix", func(t *testing.T) {
		h := t.TempDir()
		sib := h + "2"
		t.Cleanup(func() { os.RemoveAll(sib) })
		path := inHome(t, sib)
		setHome(t, h)
		if st := New(g, path).Build(); !strings.Contains(st.Message, path) || strings.Contains(st.Message, "~") {
			t.Errorf("%+v", st)
		}
	})
	t.Run("no-home", func(t *testing.T) {
		if runtime.GOOS == "windows" {
			t.Skip("Unix only")
		}
		path := inHome(t, t.TempDir())
		t.Setenv("HOME", "")
		if st := New(g, path).Build(); !strings.Contains(st.Message, path) || strings.Contains(st.Message, "~") {
			t.Errorf("%+v", st)
		}
	})
}

func TestBuildReadsGetUnwatched(t *testing.T) {
	unixOnly(t)
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
	if st := b.Build(); st.State != StateOK || st.Degraded || !enabled(t, st) {
		t.Errorf("fresh-ok: %+v", st)
	}
	mtime := aged(maybe)
	if st := b.Build(); st.State != StateInvalid || !st.Problem || enabled(t, st) {
		t.Errorf("fresh-invalid: %+v", st)
	}
	got, _ := os.ReadFile(path)
	fi, _ := os.Stat(path)
	if string(got) != maybe || !fi.ModTime().Equal(mtime) {
		t.Error("no-write: Build touched the file")
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
	if len(out) == 0 {
		t.Fatal("no non-test sources found")
	}
	return out
}

func TestBuilderUsesGetter(t *testing.T) {
	sc := userconfig.Scaffold()
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(sc), 0o600); err != nil {
		t.Fatal(err)
	}
	g := &countingGetter{}
	st := New(g, path).Build()
	if g.calls != 1 {
		t.Errorf("one-get: Get called %d times", g.calls)
	}
	if !bytes.Equal(st.Effective, userconfig.EncodeSettings(userconfig.FailSafeSettings())) || !st.Degraded || st.State != StateOK {
		t.Errorf("effective-from-getter: %+v", st)
	}
	for f, src := range nonTestSources(t) {
		if strings.Contains(string(src), "userconfig.Manager") {
			t.Errorf("no-concrete: %s names the Manager type", f)
		}
	}
}

func TestNoSettingText(t *testing.T) {
	names := map[string]bool{}
	for _, d := range userconfig.Definitions() {
		names[d.Path] = true
		names[d.Section] = true
	}
	for f, src := range nonTestSources(t) {
		lower := bytes.ToLower(src)
		if bytes.Contains(lower, []byte("telemetry")) {
			t.Errorf("no-telemetry: %s contains %q", f, "telemetry")
		}
		for _, w := range []string{"Definitions", "userconfig.Definition"} {
			if bytes.Contains(src, []byte(w)) {
				t.Errorf("no-definitions: %s contains %q", f, w)
			}
		}
		for _, w := range []string{"Fingerprint", "warnKey", "warnWorthy", `json:"warn"`} {
			if bytes.Contains(src, []byte(w)) {
				t.Errorf("no-removed-fields: %s contains %q", f, w)
			}
		}
		if bytes.Contains(lower, []byte("fail-safe")) {
			t.Errorf("no-removed-fields: %s contains %q", f, "fail-safe")
		}

		// No string literal names a definition path. Struct tags are JSON
		// field names, not literals in this sense.
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
			if v, err := strconv.Unquote(lit.Value); err == nil && names[v] {
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
