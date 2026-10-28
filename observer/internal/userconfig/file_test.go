package userconfig

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
	"unicode/utf8"

	"go.yaml.in/yaml/v3"
)

const v1Scaffold = `# ~/.obstudio/config.yaml — Splunk Observability Studio local configuration.
# Per-user, per-machine; applies to every IDE/agent using this obstudio binary.
# Changes are picked up live unless noted.

# Privacy
telemetry:
  # Allow Cisco to collect anonymous usage data about Splunk Observability
  # Studio itself. Turning this off does not change what Splunk Observability
  # Studio collects from your agents or shows you locally.
  # Values: true or false.
  # To turn this off, run: obstudio telemetry disable
  enabled: true
`

func writeFile(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func readFile(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func dirEntries(t *testing.T, dir string) []string {
	t.Helper()
	es, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, e := range es {
		names = append(names, e.Name())
	}
	return names
}

func scaffoldCommentLines() []string {
	var out []string
	for _, l := range strings.Split(Scaffold(), "\n") {
		if l = strings.TrimSpace(l); strings.HasPrefix(l, "#") {
			out = append(out, l)
		}
	}
	return out
}

func assertCommentsKept(t *testing.T, out string) {
	t.Helper()
	for _, c := range scaffoldCommentLines() {
		if !strings.Contains(out, c) {
			t.Errorf("comment %q lost:\n%s", c, out)
		}
	}
}

func mustLoad(t *testing.T, path string) (Snapshot, []Diagnostic) {
	t.Helper()
	s, d, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	return s, d
}

func TestScaffoldParsesToDefaults(t *testing.T) {
	path := writeFile(t, Scaffold())
	s, diags, err := Load(path)
	if err != nil || len(diags) != 0 {
		t.Fatalf("Load = %v, %v", diags, err)
	}
	want := DefaultSnapshot()
	want.Hash = s.Hash
	if s != want || !s.Telemetry.Enabled || s.Degraded {
		t.Errorf("snapshot = %+v", s)
	}
	if s.Hash != sha256.Sum256([]byte(Scaffold())) {
		t.Error("hash is not the SHA-256 of the scaffold")
	}
}

func TestScaffoldGolden(t *testing.T) {
	got := Scaffold()
	assertGolden(t, "testdata/scaffold.golden.yaml", []byte(got))
	if got != v1Scaffold {
		t.Errorf("Scaffold() differs from the v1 reference:\n%s", got)
	}
	if Scaffold() != got {
		t.Error("Scaffold() is not stable")
	}
	lines := strings.Split(got, "\n")
	if !reflect.DeepEqual(lines[:3], strings.Split(scaffoldHeader, "\n")) || len(strings.Split(scaffoldHeader, "\n")) != 3 || lines[3] != "" {
		t.Errorf("scaffold does not start with the 3-line header and a blank line:\n%s", strings.Join(lines[:4], "\n"))
	}
	if lines[11] != "  enabled: true" {
		t.Errorf("line 12 = %q, want %q", lines[11], "  enabled: true")
	}
	for i, l := range lines[3:] {
		if utf8.RuneCountInString(l) > 80 {
			t.Errorf("line %d is %d code points", i+4, utf8.RuneCountInString(l))
		}
	}
	if strings.Contains(strings.ToLower(got), "port") {
		t.Error("scaffold names a port")
	}
	for _, d := range Definitions() {
		want := "  " + strings.TrimPrefix(d.Path, d.Section+".") + ": " + valueText(d.Default)
		sec := slices.Index(lines, d.Section+":")
		if sec < 0 || !slices.Contains(lines[sec+1:], want) {
			t.Errorf("scaffold has no %q under %q", want, d.Section+":")
		}
	}
}

func TestScaffoldRenderRules(t *testing.T) {
	secDesc := strings.TrimSpace(strings.Repeat("one two three four five ", 5))
	desc := strings.TrimSpace(strings.Repeat("alpha beta gamma delta epsilon zeta ", 5))
	tsec := newSection("t", sectionSpec{Title: "Tee", Description: secDesc})
	usec := newSection("u", sectionSpec{Title: "You"})
	a := newDefinition(tsec, "a", defSpec[string]{
		Title: "A", Description: desc, Hint: "Run tee --reset.", Default: "x y",
		Enum: []string{"x y", "z"}, Apply: ApplyRestart,
	})
	b := newDefinition(tsec, "b", defSpec[int]{Title: "B", Description: "B value.", Default: 7, Apply: ApplyLive})
	c := newDefinition(usec, "c", defSpec[bool]{Title: "C", Description: "C value.", Default: false, Apply: ApplyLive})
	got := renderScaffold([]Section{tsec, usec}, []def{a, b, c})
	lines := strings.Split(strings.TrimSuffix(got, "\n"), "\n")

	secLines := wrapComment("# ", secDesc)
	aLines := wrapComment("  # ", desc)
	want := strings.Split(scaffoldHeader, "\n")
	want = append(want, "", "# Tee")
	want = append(want, secLines...)
	want = append(want, "t:")
	want = append(want, aLines...)
	want = append(want, `  # Values: "x y", "z".`, "  # Requires restart.", "  # Run tee --reset.", `  a: "x y"`,
		"", "  # B value.", "  b: 7",
		"", "# You", "u:", "  # C value.", "  # Values: true or false.", "  c: false")
	if !reflect.DeepEqual(lines, want) {
		t.Fatalf("scaffold lines:\n%s\nwant:\n%s", strings.Join(lines, "\n"), strings.Join(want, "\n"))
	}
	for _, g := range []struct {
		prefix, text string
		lines        []string
	}{{"# ", secDesc, secLines}, {"  # ", desc, aLines}} {
		var words []string
		for i, l := range g.lines {
			if utf8.RuneCountInString(l) > 80 {
				t.Errorf("comment line %q is too wide", l)
			}
			if i+1 < len(g.lines) {
				next := strings.Fields(strings.TrimPrefix(g.lines[i+1], g.prefix))[0]
				if utf8.RuneCountInString(l)+1+utf8.RuneCountInString(next) <= 80 {
					t.Errorf("line %q could have held %q", l, next)
				}
			}
			words = append(words, strings.TrimPrefix(l, g.prefix))
		}
		if strings.Join(words, " ") != g.text {
			t.Errorf("wrapped comment does not reproduce %q", g.text)
		}
	}
	if len(aLines) < 2 {
		t.Error("30-word description did not wrap")
	}
	bAt := slices.Index(lines, "  b: 7")
	if slices.ContainsFunc(lines[slices.Index(lines, `  a: "x y"`)+1:bAt], func(l string) bool { return strings.Contains(l, "Values:") }) {
		t.Error("an int without Enum has a Values line")
	}
	if you := slices.Index(lines, "# You"); lines[you+1] != "u:" {
		t.Errorf("line after # You = %q, want u:", lines[you+1])
	}
	if strings.Count(got, "Requires restart") != 1 {
		t.Error("a live definition has a restart note")
	}
}

type diagKK struct {
	key  string
	kind DiagnosticKind
}

func TestParseMatrix(t *testing.T) {
	sc := Scaffold()
	replace := func(old, new string) string {
		if !strings.Contains(sc, old) {
			t.Fatalf("scaffold has no %q", old)
		}
		return strings.Replace(sc, old, new, 1)
	}
	noSection := sc[:strings.Index(sc, "telemetry:")]
	rows := []struct {
		name    string
		content string
		enabled bool
		diags   []diagKK
	}{
		{"false", replace("enabled: true", "enabled: false"), false, nil},
		{"true", sc, true, nil},
		{"on", replace("enabled: true", "enabled: on"), false, []diagKK{{"telemetry.enabled", DiagInvalid}}},
		{"yes", replace("enabled: true", "enabled: yes"), false, []diagKK{{"telemetry.enabled", DiagInvalid}}},
		{"True", replace("enabled: true", "enabled: True"), false, []diagKK{{"telemetry.enabled", DiagInvalid}}},
		{"quoted false", replace("enabled: true", `enabled: "false"`), false, []diagKK{{"telemetry.enabled", DiagInvalid}}},
		{"quoted true", replace("enabled: true", `enabled: "true"`), false, []diagKK{{"telemetry.enabled", DiagInvalid}}},
		{"null", replace("enabled: true", "enabled:"), false, []diagKK{{"telemetry.enabled", DiagInvalid}}},
		{"fasle", replace("enabled: true", "enabled: fasle"), false, []diagKK{{"telemetry.enabled", DiagInvalid}}},
		{"list", replace("enabled: true", "enabled: [a]"), false, []diagKK{{"telemetry.enabled", DiagInvalid}}},
		{"key removed", replace("  enabled: true\n", "  other: 1\n"), false, []diagKK{{"telemetry.enabled", DiagAbsent}, {"telemetry.other", DiagUnknownKey}}},
		{"key line removed", replace("  enabled: true\n", ""), false, []diagKK{{"telemetry.enabled", DiagAbsent}}},
		{"section removed", noSection, false, []diagKK{{"telemetry.enabled", DiagAbsent}}},
		{"section not mapping", noSection + "telemetry: true\n", false, []diagKK{{"telemetry", DiagInvalid}}},
		{"section null", noSection + "telemetry: ~\n", false, []diagKK{{"telemetry.enabled", DiagAbsent}}},
		{"section empty string", noSection + "telemetry: \"\"\n", false, []diagKK{{"telemetry", DiagInvalid}}},
		{"section list", noSection + "telemetry: [a]\n", false, []diagKK{{"telemetry", DiagInvalid}}},
		{"version", "version: 1\n" + sc, true, []diagKK{{"version", DiagUnknownKey}}},
		{"server", sc + "server: {port: 9000}\n", true, []diagKK{{"server", DiagUnknownKey}}},
		{"level", sc + "  level: high\n", true, []diagKK{{"telemetry.level", DiagUnknownKey}}},
		{"zz and on", "zz: 1\n" + replace("enabled: true", "enabled: on"), false, []diagKK{{"telemetry.enabled", DiagInvalid}, {"zz", DiagUnknownKey}}},
		{"empty", "", false, []diagKK{{"telemetry.enabled", DiagAbsent}}},
	}
	for _, r := range rows {
		t.Run(r.name, func(t *testing.T) {
			path := writeFile(t, r.content)
			s, diags, err := Load(path)
			if err != nil {
				t.Fatalf("Load error %v", err)
			}
			if s.Telemetry.Enabled != r.enabled || s.Degraded {
				t.Errorf("snapshot = %+v", s)
			}
			var got []diagKK
			for _, d := range diags {
				got = append(got, diagKK{d.Key, d.Kind})
			}
			if !reflect.DeepEqual(got, r.diags) {
				t.Errorf("diagnostics = %v, want %v", got, r.diags)
			}
			lines := strings.Split(r.content, "\n")
			for _, d := range diags {
				if d.Kind == DiagAbsent {
					if d.Line != 0 {
						t.Errorf("%s absent at line %d", d.Key, d.Line)
					}
					continue
				}
				last := d.Key[strings.LastIndex(d.Key, ".")+1:]
				if d.Line < 1 || !strings.Contains(lines[d.Line-1], last+":") {
					t.Errorf("%s at line %d (%q)", d.Key, d.Line, lines[max(d.Line-1, 0)])
				}
			}
			switch r.name {
			case "on":
				if diags[0].Message != `telemetry.enabled: "on" is not true or false` {
					t.Errorf("message = %q", diags[0].Message)
				}
			case "list":
				if diags[0].Message != "telemetry.enabled: is not a single value" {
					t.Errorf("message = %q", diags[0].Message)
				}
			}
		})
	}
}

func valueNode(t *testing.T, text string) *yaml.Node {
	t.Helper()
	var doc yaml.Node
	if err := yaml.Unmarshal([]byte("x: "+text+"\n"), &doc); err != nil {
		t.Fatalf("parse %q: %v", text, err)
	}
	return doc.Content[0].Content[1]
}

func TestDecodeValue(t *testing.T) {
	tt := newTT()
	type row struct {
		d    def
		text string
		want any
		msg  string // exact message, or a suffix when it starts with "…"
	}
	rows := []row{
		{tt.b, "true", true, ""},
		{tt.b, "false", false, ""},
		{tt.b, "True", nil, `t.b: "True" is not true or false`},
		{tt.b, `"true"`, nil, `t.b: "true" is not true or false`},
		{tt.b, "1", nil, `t.b: "1" is not true or false`},
		{tt.b, "~", nil, `t.b: "~" is not true or false`},
		{tt.n, "42", 42, ""},
		{tt.n, "0", nil, "t.n: 0 is less than 1"},
		{tt.n, `"42"`, nil, "…is not a base-10 integer"},
		{tt.n, "0x10", nil, "…is not a base-10 integer"},
		{tt.n, "1.5", nil, "…is not a base-10 integer"},
		{tt.n, "99999999999999999999", nil, "…is not a base-10 integer"},
		{tt.s, "low", "low", ""},
		{tt.s, `"high"`, "high", ""},
		{tt.s, "'low'", "low", ""},
		{tt.s, "mid", nil, `t.s: "mid" is not one of "low", "high"`},
		{tt.s, "true", nil, "…is not a string"},
		{tt.s, "123", nil, "…is not a string"},
		{tt.s, "null", nil, "…is not a string"},
	}
	for _, d := range tt.defs {
		rows = append(rows, row{d, "{a: 1}", nil, d.path() + ": is not a single value"})
	}
	for _, r := range rows {
		n := valueNode(t, r.text)
		v, diag := decodeValue(n, r.d)
		if r.msg == "" {
			if diag != nil || v != r.want {
				t.Errorf("%s %s: got %v, %+v", r.d.path(), r.text, v, diag)
			}
			continue
		}
		if diag == nil {
			t.Errorf("%s %s: no diagnostic", r.d.path(), r.text)
			continue
		}
		if suffix, ok := strings.CutPrefix(r.msg, "…"); ok {
			if !strings.HasSuffix(diag.Message, suffix) {
				t.Errorf("%s %s: message %q", r.d.path(), r.text, diag.Message)
			}
		} else if diag.Message != r.msg {
			t.Errorf("%s %s: message %q, want %q", r.d.path(), r.text, diag.Message, r.msg)
		}
		if diag.Kind != DiagInvalid || diag.Line != n.Line || diag.Key != r.d.path() {
			t.Errorf("%s %s: diagnostic %+v", r.d.path(), r.text, diag)
		}
	}
}

func TestScalarCodec(t *testing.T) {
	sec := newSection("t", sectionSpec{Title: "T"})
	defs := map[Type]def{
		TypeBool:   newDefinition(sec, "b", defSpec[bool]{Title: "b", Description: "b.", Apply: ApplyLive}),
		TypeInt:    newDefinition(sec, "n", defSpec[int]{Title: "n", Description: "n.", Apply: ApplyLive}),
		TypeString: newDefinition(sec, "s", defSpec[string]{Title: "s", Description: "s.", Apply: ApplyLive}),
	}
	values := []any{true, false, 0, -7, 123456, "", "true", "123", "null", "a: b", "# x", "line1\nline2", "ünï"}
	for _, v := range values {
		n := encodeScalar(v)
		var d def
		switch v.(type) {
		case bool:
			d = defs[TypeBool]
		case int:
			d = defs[TypeInt]
		default:
			d = defs[TypeString]
			if n.Style != yaml.DoubleQuotedStyle {
				t.Errorf("%q: style %v, want double-quoted", v, n.Style)
			}
		}
		if d.typ() != TypeString && n.Style != 0 {
			t.Errorf("%v: style %v, want plain", v, n.Style)
		}
		out, err := yaml.Marshal(&yaml.Node{Kind: yaml.MappingNode, Content: []*yaml.Node{{Kind: yaml.ScalarNode, Value: "x"}, n}})
		if err != nil {
			t.Fatal(err)
		}
		var doc yaml.Node
		if err := yaml.Unmarshal(out, &doc); err != nil {
			t.Fatalf("%v: reparse %q: %v", v, out, err)
		}
		got, diag := decodeValue(doc.Content[0].Content[1], d)
		if diag != nil || got != v {
			t.Errorf("%#v: round trip gave %#v, %+v (yaml %q)", v, got, diag, out)
		}
	}
}

func TestLoadMissingFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	s, _, err := Load(path)
	if s != FailSafeSnapshot() || s.Telemetry.Enabled || !s.Degraded {
		t.Errorf("snapshot = %+v", s)
	}
	if !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("err = %v", err)
	}
	if _, err := os.Stat(path); !errors.Is(err, fs.ErrNotExist) {
		t.Error("Load created the file")
	}
}

func TestLoadSyntaxError(t *testing.T) {
	for _, content := range []string{"telemetry: [unclosed", "- a\n- b", "42"} {
		s, _, err := Load(writeFile(t, content))
		if s != FailSafeSnapshot() || !errors.Is(err, ErrSyntax) {
			t.Errorf("%q: %+v, %v", content, s, err)
		}
	}
}

func TestEnsureScaffoldCreates(t *testing.T) {
	dir := filepath.Join(t.TempDir(), ".obstudio")
	path := filepath.Join(dir, "config.yaml")
	created, err := EnsureScaffold(path)
	if !created || err != nil {
		t.Fatalf("EnsureScaffold = %v, %v", created, err)
	}
	if readFile(t, path) != Scaffold() {
		t.Error("content is not the scaffold")
	}
	if runtime.GOOS != "windows" {
		di, _ := os.Stat(dir)
		fi, _ := os.Stat(path)
		if di.Mode().Perm() != 0o700 || fi.Mode().Perm() != 0o600 {
			t.Errorf("modes dir=%v file=%v", di.Mode().Perm(), fi.Mode().Perm())
		}
	}
	if got := dirEntries(t, dir); !reflect.DeepEqual(got, []string{"config.yaml"}) {
		t.Errorf("directory holds %v", got)
	}
}

func TestEnsureScaffoldNeverOverwrites(t *testing.T) {
	for _, content := range []string{"telemetry:\n  enabled: false\n", "", "telemetry: [unclosed"} {
		path := writeFile(t, content)
		old := time.Now().Add(-time.Hour).Truncate(time.Second)
		if err := os.Chtimes(path, old, old); err != nil {
			t.Fatal(err)
		}
		created, err := EnsureScaffold(path)
		if created || err != nil {
			t.Errorf("%q: EnsureScaffold = %v, %v", content, created, err)
		}
		fi, _ := os.Stat(path)
		if readFile(t, path) != content || !fi.ModTime().Equal(old) {
			t.Errorf("%q: file was touched", content)
		}
	}
}

func TestWritePreservesComments(t *testing.T) {
	path := writeFile(t, Scaffold())
	if err := Write(path, TelemetryEnabled, false); err != nil {
		t.Fatal(err)
	}
	s, diags := mustLoad(t, path)
	if s.Telemetry.Enabled || len(diags) != 0 {
		t.Errorf("after write: %+v %v", s, diags)
	}
	assertCommentsKept(t, readFile(t, path))
}

func TestWritePreservesUnknownKeys(t *testing.T) {
	path := writeFile(t, Scaffold()+"  level: high\nserver:\n  port: 9000  # mine\n")
	if err := Write(path, TelemetryEnabled, false); err != nil {
		t.Fatal(err)
	}
	out := readFile(t, path)
	var parsed struct {
		Server    struct{ Port int }
		Telemetry struct {
			Enabled bool
			Level   string
		}
	}
	if err := yaml.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatal(err)
	}
	if parsed.Server.Port != 9000 || parsed.Telemetry.Level != "high" || parsed.Telemetry.Enabled {
		t.Errorf("after write: %+v\n%s", parsed, out)
	}
	_, diags := mustLoad(t, path)
	var got []diagKK
	for _, d := range diags {
		got = append(got, diagKK{d.Key, d.Kind})
	}
	if want := []diagKK{{"telemetry.level", DiagUnknownKey}, {"server", DiagUnknownKey}}; !reflect.DeepEqual(got, want) {
		t.Errorf("diagnostics = %v", got)
	}
	if !strings.Contains(out, "# mine") {
		t.Errorf("comment lost:\n%s", out)
	}
}

func TestWriteRejectsBeforeDisk(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "absent")
	path := filepath.Join(dir, "config.yaml")
	n := newDefinition(newSection("t", sectionSpec{Title: "T"}), "n", defSpec[int]{Title: "n", Description: "n.", Apply: ApplyLive, Min: ptr(1), Default: 1})

	if err := Write(path, Key[bool]{}, true); err != ErrUnknownKey {
		t.Errorf("zero Key: %v", err)
	}
	var c2 Changes
	c2.put(n, 0)
	var c3 Changes
	c3.put(table()[0], "false")
	var c4 Changes
	Put(&c4, TelemetryEnabled, false)
	c4.put(n, 0)
	for i, c := range []Changes{c2, c3, c4} {
		err := WriteChanges(path, c)
		if !errors.Is(err, ErrInvalidValue) {
			t.Errorf("call %d: %v", i+2, err)
		}
		if i != 1 && (err == nil || err.Error() != "userconfig: invalid value: t.n: 0 is less than 1") {
			t.Errorf("call %d: text %v", i+2, err)
		}
	}
	if _, err := os.Stat(dir); !errors.Is(err, fs.ErrNotExist) {
		t.Error("a rejected write touched the filesystem")
	}
}

func TestWriteChangesEmptyNoOp(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "absent")
	if err := WriteChanges(filepath.Join(dir, "config.yaml"), Changes{}); err != nil {
		t.Error(err)
	}
	if _, err := os.Stat(dir); !errors.Is(err, fs.ErrNotExist) {
		t.Error("empty write created the directory")
	}
	path := writeFile(t, Scaffold())
	old := time.Now().Add(-time.Hour).Truncate(time.Second)
	if err := os.Chtimes(path, old, old); err != nil {
		t.Fatal(err)
	}
	if err := WriteChanges(path, Changes{}); err != nil {
		t.Error(err)
	}
	fi, _ := os.Stat(path)
	if readFile(t, path) != Scaffold() || !fi.ModTime().Equal(old) {
		t.Error("empty write touched the file")
	}
}

func countingRename(n *int) func(string, string) error {
	return func(o, p string) error { *n++; return os.Rename(o, p) }
}

func TestWriteChangesOneRename(t *testing.T) {
	path := writeFile(t, Scaffold()+"server:\n  port: 9000\n")
	sec := newSection("t", sectionSpec{Title: "T"})
	a := newDefinition(sec, "a", defSpec[string]{Title: "a", Description: "a.", Apply: ApplyLive})
	b := newDefinition(sec, "b", defSpec[int]{Title: "b", Description: "b.", Apply: ApplyLive})
	var c Changes
	Put(&c, TelemetryEnabled, false)
	c.put(a, "x")
	c.put(b, 3)
	renames := 0
	if err := writeChanges(path, c, countingRename(&renames)); err != nil {
		t.Fatal(err)
	}
	if renames != 1 {
		t.Errorf("%d renames, want 1", renames)
	}
	out := readFile(t, path)
	var doc yaml.Node
	if err := yaml.Unmarshal([]byte(out), &doc); err != nil {
		t.Fatal(err)
	}
	root := doc.Content[0]
	var keys []string
	for i := 0; i < len(root.Content); i += 2 {
		keys = append(keys, root.Content[i].Value)
	}
	if !reflect.DeepEqual(keys, []string{"telemetry", "server", "t"}) {
		t.Errorf("root keys %v", keys)
	}
	_, tNode := lookup(root, "t")
	if len(tNode.Content) != 4 || tNode.Content[0].Value != "a" || tNode.Content[1].Value != "x" ||
		tNode.Content[2].Value != "b" || tNode.Content[3].Value != "3" {
		t.Errorf("section t:\n%s", out)
	}
	_, tel := lookup(root, "telemetry")
	_, en := lookup(tel, "enabled")
	_, srv := lookup(root, "server")
	_, port := lookup(srv, "port")
	if en.Value != "false" || port.Value != "9000" {
		t.Errorf("values:\n%s", out)
	}
	assertCommentsKept(t, out)
	if got := dirEntries(t, filepath.Dir(path)); !reflect.DeepEqual(got, []string{"config.yaml"}) {
		t.Errorf("directory holds %v", got)
	}
}

func TestWriteChangesAllOrNothing(t *testing.T) {
	n := newDefinition(newSection("t", sectionSpec{Title: "T"}), "n", defSpec[int]{Title: "n", Description: "n.", Apply: ApplyLive, Min: ptr(1), Default: 1})
	uc := newDefinition(newSection("u", sectionSpec{Title: "U"}), "c", defSpec[bool]{Title: "c", Description: "c.", Apply: ApplyLive})
	f1, f2, f3 := Scaffold(), Scaffold()+"u: 5\n", "telemetry: [unclosed"
	var c1, c2, c3 Changes
	Put(&c1, TelemetryEnabled, false)
	c1.put(n, 0)
	Put(&c2, TelemetryEnabled, false)
	c2.put(uc, true)
	Put(&c3, TelemetryEnabled, false)
	cases := []struct {
		content string
		c       Changes
		check   func(error) bool
	}{
		{f1, c1, func(err error) bool { return errors.Is(err, ErrInvalidValue) && strings.Contains(err.Error(), "t.n") }},
		{f2, c2, func(err error) bool {
			return errors.Is(err, ErrNotMapping) && err.Error() == "userconfig: path segment is not a mapping: u"
		}},
		{f3, c3, func(err error) bool { return errors.Is(err, ErrSyntax) }},
	}
	for i, tc := range cases {
		path := writeFile(t, tc.content)
		renames := 0
		err := writeChanges(path, tc.c, countingRename(&renames))
		if !tc.check(err) {
			t.Errorf("call %d: %v", i+1, err)
		}
		if readFile(t, path) != tc.content {
			t.Errorf("call %d: file changed", i+1)
		}
		if renames != 0 {
			t.Errorf("call %d: %d renames", i+1, renames)
		}
	}
}

func TestVersionIsUnknownKey(t *testing.T) {
	path := writeFile(t, "version: 1\n"+Scaffold())
	want := []Diagnostic{{Key: "version", Kind: DiagUnknownKey, Line: 1, Message: "version: is not a known key"}}
	s, diags := mustLoad(t, path)
	if !s.Telemetry.Enabled || !reflect.DeepEqual(diags, want) {
		t.Errorf("first load: %+v %+v", s, diags)
	}
	if err := Write(path, TelemetryEnabled, false); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(readFile(t, path), "version: 1\n") {
		t.Error("version line lost")
	}
	s, diags = mustLoad(t, path)
	if s.Telemetry.Enabled || len(diags) != 1 || diags[0].Key != "version" || diags[0].Kind != DiagUnknownKey {
		t.Errorf("second load: %+v %+v", s, diags)
	}
	if _, ok := reflect.TypeOf(Snapshot{}).FieldByName("Version"); ok {
		t.Error("Snapshot has a Version field")
	}
}

func TestWriteScaffoldsMissingFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".obstudio", "config.yaml")
	if err := Write(path, TelemetryEnabled, false); err != nil {
		t.Fatal(err)
	}
	s, _ := mustLoad(t, path)
	if s.Telemetry.Enabled {
		t.Error("value not written")
	}
	assertCommentsKept(t, readFile(t, path))
}

func TestWriteInsertsMissingSection(t *testing.T) {
	path := writeFile(t, "zz: 1\n# keep\n")
	if err := Write(path, TelemetryEnabled, true); err != nil {
		t.Fatal(err)
	}
	s, diags := mustLoad(t, path)
	if !s.Telemetry.Enabled {
		t.Error("value not written")
	}
	for _, d := range diags {
		if d.Kind == DiagAbsent {
			t.Errorf("absent diagnostic %+v", d)
		}
	}
	if !strings.Contains(readFile(t, path), "# keep") {
		t.Error("comment lost")
	}
}

func TestWriteFillsNullSection(t *testing.T) {
	content := strings.Replace(Scaffold(), "  enabled: true\n", "", 1)
	path := writeFile(t, content)
	if err := Write(path, TelemetryEnabled, true); err != nil {
		t.Fatalf("Write: %v", err)
	}
	s, diags := mustLoad(t, path)
	if !s.Telemetry.Enabled || len(diags) != 0 {
		t.Errorf("after write: %+v %v", s, diags)
	}
	out := readFile(t, path)
	for _, l := range strings.Split(content, "\n") {
		if l = strings.TrimSpace(l); strings.HasPrefix(l, "#") && !strings.Contains(out, l) {
			t.Errorf("comment %q lost:\n%s", l, out)
		}
	}
}

func TestWriteKeepsCommentOnlyFile(t *testing.T) {
	path := writeFile(t, "# mine\n")
	if err := Write(path, TelemetryEnabled, false); err != nil {
		t.Fatal(err)
	}
	out := readFile(t, path)
	if !strings.HasPrefix(out, "# mine\n") {
		t.Errorf("comment lost:\n%s", out)
	}
	if s, _ := mustLoad(t, path); s.Telemetry.Enabled {
		t.Error("value not written")
	}
}

func TestWriteRefusesMalformed(t *testing.T) {
	for _, tc := range []struct {
		content string
		want    error
	}{{"telemetry: [unclosed", ErrSyntax}, {"telemetry: true\n", ErrNotMapping}} {
		path := writeFile(t, tc.content)
		if err := Write(path, TelemetryEnabled, false); !errors.Is(err, tc.want) {
			t.Errorf("%q: %v", tc.content, err)
		}
		if readFile(t, path) != tc.content {
			t.Errorf("%q: file changed", tc.content)
		}
	}
}

func TestWriteFailureLeavesNoDebris(t *testing.T) {
	path := writeFile(t, Scaffold())
	var c Changes
	Put(&c, TelemetryEnabled, false)
	err := writeChanges(path, c, func(string, string) error { return errors.New("rename failed") })
	if err == nil {
		t.Fatal("nil error")
	}
	if readFile(t, path) != Scaffold() {
		t.Error("target changed")
	}
	if got := dirEntries(t, filepath.Dir(path)); !reflect.DeepEqual(got, []string{"config.yaml"}) {
		t.Errorf("directory holds %v", got)
	}
}

func TestEnsureScaffoldRace(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	var created atomic.Int32
	var wg sync.WaitGroup
	start := make(chan struct{})
	errs := make(chan error, 16)
	for range 16 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			c, err := EnsureScaffold(path)
			if c {
				created.Add(1)
			}
			if err != nil {
				errs <- err
			}
		}()
	}
	close(start)
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Error(err)
	}
	if created.Load() != 1 {
		t.Errorf("%d creators, want 1", created.Load())
	}
	if readFile(t, path) != Scaffold() {
		t.Error("content is not the scaffold")
	}
	if got := dirEntries(t, dir); !reflect.DeepEqual(got, []string{"config.yaml"}) {
		t.Errorf("directory holds %v", got)
	}
}

func TestOpenScaffoldFailureFailsSafe(t *testing.T) {
	if runtime.GOOS == "windows" || os.Geteuid() == 0 {
		t.Skip("needs Unix permissions and a non-root user")
	}
	parent := t.TempDir()
	if err := os.Chmod(parent, 0o500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chmod(parent, 0o700) })
	r, err := Open(filepath.Join(parent, ".obstudio", "config.yaml"))
	if err == nil {
		t.Error("nil error")
	}
	if r.Snapshot != FailSafeSnapshot() || r.Snapshot.Telemetry.Enabled || r.Created {
		t.Errorf("result = %+v", r)
	}
}

func TestOpenFirstRunFlag(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".obstudio", "config.yaml")
	first, err := Open(path)
	if err != nil || !first.Created || !first.Snapshot.Telemetry.Enabled {
		t.Fatalf("first Open = %+v, %v", first, err)
	}
	second, err := Open(path)
	if err != nil || second.Created || second.Snapshot != first.Snapshot {
		t.Errorf("second Open = %+v, %v", second, err)
	}
}

func TestConcurrentWriteNeverTorn(t *testing.T) {
	path := writeFile(t, Scaffold())
	dir := filepath.Dir(path)
	deadline := time.Now().Add(2 * time.Second)
	var stop atomic.Bool
	var wg sync.WaitGroup
	for w := range 2 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < 500 && !stop.Load() && time.Now().Before(deadline); i++ {
				if err := Write(path, TelemetryEnabled, (i+w)%2 == 0); err != nil {
					t.Errorf("write: %v", err)
					return
				}
			}
		}()
	}
	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	for loads := 0; ; loads++ {
		select {
		case <-done:
			return
		default:
		}
		_, diags, err := Load(path)
		if err != nil {
			stop.Store(true)
			t.Fatalf("load %d: %v", loads, err)
		}
		for _, d := range diags {
			if d.Kind != DiagUnknownKey {
				stop.Store(true)
				t.Fatalf("load %d: %+v", loads, d)
			}
		}
		for _, name := range dirEntries(t, dir) {
			if strings.Contains(strings.ToLower(name), "lock") {
				t.Errorf("lock file %s", name)
			}
		}
	}
}

func TestLoadIsPure(t *testing.T) {
	path := writeFile(t, strings.Replace(Scaffold(), "enabled: true", "enabled: on", 1))
	old := time.Now().Add(-time.Hour).Truncate(time.Second)
	if err := os.Chtimes(path, old, old); err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	prev := log.Writer()
	log.SetOutput(&logs)
	defer log.SetOutput(prev)
	before := runtime.NumGoroutine()
	for range 100 {
		Load(path)
	}
	if logs.Len() != 0 {
		t.Errorf("Load logged %q", logs.String())
	}
	if after := runtime.NumGoroutine(); after != before {
		t.Errorf("goroutines %d -> %d", before, after)
	}
	if fi, _ := os.Stat(path); !fi.ModTime().Equal(old) {
		t.Error("Load touched the file")
	}
}

func TestFileLayerBuildsAlone(t *testing.T) {
	assertBuildsAlone(t, []string{"definitions.go", "render.go", "file.go", "scaffold.go"}, []string{"github.com/fsnotify/fsnotify"})
	for _, f := range []string{"file.go", "scaffold.go"} {
		src := readFile(t, f)
		for _, banned := range []string{"define(", "section(", `"telemetry"`, `"telemetry.enabled"`} {
			if strings.Contains(src, banned) {
				t.Errorf("%s contains %s", f, banned)
			}
		}
	}
	for _, f := range []string{"file.go", "scaffold.go", "render.go", "codec.go"} {
		if strings.Contains(strings.ToLower(readFile(t, f)), "telemetry") {
			t.Errorf("%s names a setting: it contains %q", f, "telemetry")
		}
	}
}
