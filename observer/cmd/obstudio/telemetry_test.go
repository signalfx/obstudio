package main

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

type telemetryRun struct {
	stdout, stderr string
	err            error
}

func telemetryHome(t *testing.T) (home, path string) {
	t.Helper()
	home = t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	return home, filepath.Join(home, ".obstudio", "config.yaml")
}

func runTelemetry(args ...string) telemetryRun {
	var out, errOut bytes.Buffer
	root := newRootCmd(&runConfig{})
	root.SetArgs(args)
	root.SetOut(&out)
	root.SetErr(&errOut)
	err := root.Execute()
	return telemetryRun{out.String(), errOut.String(), err}
}

func writeConfig(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

func scaffoldWith(old, new string) string {
	return strings.Replace(userconfig.Scaffold(), old, new, 1)
}

func assertHoldsLiteral(t *testing.T, path string, want bool) {
	t.Helper()
	s, diags, err := userconfig.Load(path)
	if !holdsLiteral(s, diags, err, want) {
		t.Errorf("file does not hold %v: %+v %+v %v", want, s, diags, err)
	}
}

func firstLine(s string) string {
	line, _, _ := strings.Cut(s, "\n")
	return line
}

func TestTelemetryDisableFreshHome(t *testing.T) {
	_, path := telemetryHome(t)
	r := runTelemetry("telemetry", "disable")
	if r.err != nil || r.stderr != "" {
		t.Fatalf("err=%v stderr=%q", r.err, r.stderr)
	}
	if want := "Anonymous usage data is now disabled.\nConfig: " + path + "\n"; r.stdout != want {
		t.Errorf("stdout %q, want %q", r.stdout, want)
	}
	assertHoldsLiteral(t, path, false)
	content, _ := os.ReadFile(path)
	for _, l := range strings.Split(userconfig.Scaffold(), "\n") {
		if l = strings.TrimSpace(l); strings.HasPrefix(l, "#") && !bytes.Contains(content, []byte(l)) {
			t.Errorf("comment %q lost", l)
		}
	}
}

func TestTelemetryDisableScaffold(t *testing.T) {
	_, path := telemetryHome(t)
	writeConfig(t, path, userconfig.Scaffold())
	r := runTelemetry("telemetry", "disable")
	if r.err != nil || firstLine(r.stdout) != "Anonymous usage data is now disabled." {
		t.Errorf("%+v", r)
	}
	assertHoldsLiteral(t, path, false)
}

func TestTelemetryEnableFreshHome(t *testing.T) {
	_, path := telemetryHome(t)
	r := runTelemetry("telemetry", "enable")
	if r.err != nil || firstLine(r.stdout) != "Anonymous usage data is already enabled." {
		t.Errorf("%+v", r)
	}
	if content, _ := os.ReadFile(path); string(content) != userconfig.Scaffold() {
		t.Error("file is not the scaffold")
	}
}

func TestTelemetryIdempotent(t *testing.T) {
	for _, tc := range []struct {
		content, verb, want string
	}{
		{scaffoldWith("enabled: true", "enabled: false"), "disable", "Anonymous usage data is already disabled."},
		{userconfig.Scaffold(), "enable", "Anonymous usage data is already enabled."},
	} {
		_, path := telemetryHome(t)
		writeConfig(t, path, tc.content)
		old := time.Now().Add(-time.Hour).Truncate(time.Second)
		if err := os.Chtimes(path, old, old); err != nil {
			t.Fatal(err)
		}
		r := runTelemetry("telemetry", tc.verb)
		if r.err != nil || firstLine(r.stdout) != tc.want {
			t.Errorf("%s: %+v", tc.verb, r)
		}
		content, _ := os.ReadFile(path)
		fi, _ := os.Stat(path)
		if string(content) != tc.content || !fi.ModTime().Equal(old) {
			t.Errorf("%s: file rewritten", tc.verb)
		}
	}
}

func TestTelemetryFixesInvalidValue(t *testing.T) {
	_, path := telemetryHome(t)
	writeConfig(t, path, scaffoldWith("enabled: true", "enabled: maybe"))
	r := runTelemetry("telemetry", "disable")
	if r.err != nil || firstLine(r.stdout) != "Anonymous usage data is now disabled." {
		t.Errorf("maybe: %+v", r)
	}
	assertHoldsLiteral(t, path, false)

	t.Run("enabled line removed", func(t *testing.T) {
		_, path := telemetryHome(t)
		writeConfig(t, path, scaffoldWith("  enabled: true\n", ""))
		r := runTelemetry("telemetry", "enable")
		if r.err != nil || firstLine(r.stdout) != "Anonymous usage data is now enabled." {
			t.Errorf("%+v", r)
		}
		assertHoldsLiteral(t, path, true)
	})
}

func TestTelemetryBrokenFile(t *testing.T) {
	const fix = "Fix the file, or delete it and run this command again."
	const running = "Until it is fixed, a running Splunk Observability Studio may keep using its last valid settings."
	notMapping := userconfig.Scaffold()
	notMapping = notMapping[:strings.Index(notMapping, "telemetry:")] + "telemetry: false\n"
	for _, tc := range []struct {
		content, verb string
		running       bool
	}{
		{"telemetry: [unclosed", "disable", true},
		{notMapping, "enable", false},
	} {
		_, path := telemetryHome(t)
		writeConfig(t, path, tc.content)
		r := runTelemetry("telemetry", tc.verb)
		if r.err == nil {
			t.Errorf("%s: exit 0", tc.verb)
		}
		if !strings.Contains(r.stderr, "cannot "+tc.verb+" anonymous usage data: "+path+": ") || !strings.Contains(r.stderr, fix) {
			t.Errorf("%s: stderr %q", tc.verb, r.stderr)
		}
		if strings.Contains(r.stderr, running) != tc.running {
			t.Errorf("%s: running-observer line present=%v, want %v", tc.verb, !tc.running, tc.running)
		}
		if r.stdout != "" || strings.Contains(r.stderr, "is now") || strings.Contains(r.stderr, "is already") {
			t.Errorf("%s: success text printed: %+v", tc.verb, r)
		}
		if content, _ := os.ReadFile(path); string(content) != tc.content {
			t.Errorf("%s: file changed", tc.verb)
		}
	}
}

func TestTelemetryReadback(t *testing.T) {
	_, path := telemetryHome(t)
	writeConfig(t, path, userconfig.Scaffold())
	prev := telemetryWrite
	telemetryWrite = func(p string, k userconfig.Key[bool], _ bool) error { return userconfig.Write(p, k, true) }
	t.Cleanup(func() { telemetryWrite = prev })
	r := runTelemetry("telemetry", "disable")
	if r.err == nil || !strings.Contains(r.stderr, "cannot confirm anonymous usage data is disabled: "+path) {
		t.Errorf("%+v", r)
	}
	if strings.Contains(r.stdout, "is now") {
		t.Errorf("stdout %q", r.stdout)
	}
}

func TestTelemetryStatusMatrix(t *testing.T) {
	const note = "Note: A running Splunk Observability Studio may still be using its last valid settings."
	sc := userconfig.Scaffold()
	enabledLine := 0
	for i, l := range strings.Split(sc, "\n") {
		if strings.HasPrefix(strings.TrimSpace(l), "enabled:") {
			enabledLine = i + 1
		}
	}
	notMapping := sc[:strings.Index(sc, "telemetry:")] + "telemetry: false\n"
	rows := []struct {
		name    string
		content *string
		line1   string
		reason  string // exact, or a prefix when it ends with "…"
		note    bool
	}{
		{"none", nil, "Anonymous usage data: enabled", "the file does not exist yet; it is created with telemetry.enabled: true the next time Splunk Observability Studio starts.", true},
		{"scaffold", &sc, "Anonymous usage data: enabled", "", false},
		{"false", ptrTo(scaffoldWith("enabled: true", "enabled: false")), "Anonymous usage data: disabled", "", false},
		{"on", ptrTo(scaffoldWith("enabled: true", "enabled: on")), "Anonymous usage data: disabled", "telemetry.enabled has an invalid value at line " + strconv.Itoa(enabledLine) + ", so telemetry.enabled is treated as false.", false},
		{"line removed", ptrTo(scaffoldWith("  enabled: true\n", "")), "Anonymous usage data: disabled", "telemetry.enabled is not set, so telemetry.enabled is treated as false.", false},
		{"not mapping", &notMapping, "Anonymous usage data: disabled", "telemetry has an invalid value…", false},
		{"broken", ptrTo("telemetry: [unclosed"), "Anonymous usage data: disabled", "the file is not valid YAML: …", true},
		{"unknown keys", ptrTo("version: 1\n" + sc + "server: {port: 9000}\n"), "Anonymous usage data: enabled", "", false},
	}
	for _, row := range rows {
		t.Run(row.name, func(t *testing.T) {
			_, path := telemetryHome(t)
			if row.content != nil {
				writeConfig(t, path, *row.content)
			}
			r := runTelemetry("telemetry", "status")
			if r.err != nil || r.stderr != "" {
				t.Fatalf("err=%v stderr=%q", r.err, r.stderr)
			}
			want := 2
			if row.reason != "" {
				want++
			}
			if row.note {
				want++
			}
			lines := strings.Split(strings.TrimSuffix(r.stdout, "\n"), "\n")
			if len(lines) != want {
				t.Fatalf("%d lines, want %d: %q", len(lines), want, r.stdout)
			}
			if lines[0] != row.line1 || lines[1] != "Config: "+path {
				t.Errorf("lines 1-2: %q", lines[:2])
			}
			if row.reason != "" {
				got := strings.TrimPrefix(lines[2], "Reason: ")
				if prefix, ok := strings.CutSuffix(row.reason, "…"); ok {
					if !strings.HasPrefix(got, prefix) {
						t.Errorf("reason %q, want prefix %q", got, prefix)
					}
				} else if lines[2] != "Reason: "+row.reason {
					t.Errorf("reason %q, want %q", lines[2], row.reason)
				}
			}
			if row.note && lines[len(lines)-1] != note {
				t.Errorf("note %q", lines[len(lines)-1])
			}
		})
	}
}

func ptrTo(s string) *string { return &s }

func TestTelemetryStatusReadOnly(t *testing.T) {
	home, _ := telemetryHome(t)
	runTelemetry("telemetry", "status")
	if _, err := os.Stat(filepath.Join(home, ".obstudio")); err == nil {
		t.Error("status created ~/.obstudio")
	}
	if runtime.GOOS == "windows" {
		return
	}
	_, path := telemetryHome(t)
	writeConfig(t, path, userconfig.Scaffold())
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatal(err)
	}
	old := time.Now().Add(-time.Hour).Truncate(time.Second)
	if err := os.Chtimes(path, old, old); err != nil {
		t.Fatal(err)
	}
	runTelemetry("telemetry", "status")
	fi, _ := os.Stat(path)
	content, _ := os.ReadFile(path)
	if string(content) != userconfig.Scaffold() || !fi.ModTime().Equal(old) || fi.Mode().Perm() != 0o644 {
		t.Error("status touched the file")
	}
}

func TestTelemetryRejectsFlagsAndArgs(t *testing.T) {
	for _, args := range [][]string{
		{"telemetry", "disable", "--target", "codex"},
		{"telemetry", "enable", "extra"},
		{"telemetry", "status", "--json"},
	} {
		home, _ := telemetryHome(t)
		if r := runTelemetry(args...); r.err == nil {
			t.Errorf("%v: exit 0", args)
		}
		if _, err := os.Stat(filepath.Join(home, ".obstudio")); err == nil {
			t.Errorf("%v: created ~/.obstudio", args)
		}
	}
}

func TestTelemetryUnresolvableHome(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix only")
	}
	cwd := t.TempDir()
	t.Chdir(cwd)
	for _, home := range []string{"", "relative/dir"} {
		t.Setenv("HOME", home)
		for verb, want := range map[string]string{
			"enable":  "cannot enable anonymous usage data: ",
			"disable": "cannot disable anonymous usage data: ",
			"status":  "cannot read anonymous usage data setting: ",
		} {
			r := runTelemetry("telemetry", verb)
			if r.err == nil || !strings.Contains(r.stderr, want) {
				t.Errorf("HOME=%q %s: %+v", home, verb, r)
			}
		}
		if _, err := userConfigYAMLPath(); err == nil {
			t.Errorf("HOME=%q: resolver returned no error", home)
		}
	}
	if entries, _ := os.ReadDir(cwd); len(entries) != 0 {
		t.Errorf("cwd holds %v", entries)
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	if p, err := userConfigYAMLPath(); err != nil || p != filepath.Join(home, ".obstudio", "config.yaml") {
		t.Errorf("resolver = %q, %v", p, err)
	}
}

func TestTelemetryHelpText(t *testing.T) {
	const (
		l2 = "This setting can also be managed in ~/.obstudio/config.yaml (telemetry.enabled). A running Splunk Observability Studio picks up a change without a restart."
		l3 = `To manage whether or not Splunk Observability Studio receives token telemetry from your Codex or Claude Code instances, use "obstudio token-telemetry".`
	)
	var d string
	for _, def := range userconfig.Definitions() {
		if def.Path == userconfig.TelemetryEnabled.Path() {
			d = def.Description
		}
	}
	if d == "" {
		t.Fatal("no Description for the setting")
	}
	shorts := map[string]string{
		"enable":  "Allow Cisco to collect anonymous usage data",
		"disable": "Stop Cisco collecting anonymous usage data",
		"status":  "Show whether anonymous usage data will be collected",
	}

	group := newTelemetryCommand()
	if group.Long != d+"\n\n"+l2+"\n\n"+l3 {
		t.Errorf("long-exact: Long = %q", group.Long)
	}
	if first, _, _ := strings.Cut(group.Long, "\n\n"); first != d {
		t.Errorf("description-first: %q", first)
	}
	for _, old := range []string{"non-PII", "sends about itself to Splunk"} {
		if strings.Contains(group.Long, old) {
			t.Errorf("no-old-text: Long contains %q", old)
		}
	}
	src, err := os.ReadFile("telemetry.go")
	if err != nil {
		t.Fatal(err)
	}
	// S1 is D through its first "." (all of D if none). The enable Short is a
	// prefix of D with no ".", so it never contains S1.
	s1 := d
	if i := strings.IndexByte(d, '.'); i >= 0 {
		s1 = d[:i+1]
	}
	if bytes.Contains(src, []byte(s1)) {
		t.Errorf("no-copied-literal: telemetry.go holds %q", s1)
	}
	if group.Short != "Manage the anonymous usage data Splunk Observability Studio sends about itself" {
		t.Errorf("group Short %q", group.Short)
	}
	for _, c := range group.Commands() {
		if want, ok := shorts[c.Name()]; ok && c.Short != want {
			t.Errorf("%s Short %q, want %q", c.Name(), c.Short, want)
		}
	}

	telemetryHome(t)
	for _, args := range [][]string{{"telemetry"}, {"telemetry", "--help"}} {
		r := runTelemetry(args...)
		if r.err != nil {
			t.Errorf("exit: %v: %v", args, r.err)
		}
		for _, want := range []string{d, l2, l3} {
			if !strings.Contains(r.stdout, want) {
				t.Errorf("printed: %v: help lacks %q", args, want)
			}
		}
		for name, short := range shorts {
			if !regexp.MustCompile(`(?m)^\s+` + name + `\s+` + regexp.QuoteMeta(short) + `$`).MatchString(r.stdout) {
				t.Errorf("subcommands: %v: help lacks %s %q", args, name, short)
			}
		}
	}
	if strings.Contains(group.Short, "token") {
		t.Error("no-token-in-short: group Short mentions token")
	}
	for _, c := range group.Commands() {
		if strings.Contains(c.Short, "token") {
			t.Errorf("no-token-in-short: %s Short mentions token", c.Name())
		}
	}
	r := runTelemetry("--help")
	if !strings.Contains(r.stdout, "  telemetry ") || !strings.Contains(r.stdout, "  token-telemetry ") {
		t.Errorf("root-lists-both: root help does not list both groups:\n%s", r.stdout)
	}
}

func TestConfigPathSingleSource(t *testing.T) {
	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range files {
		if strings.HasSuffix(f, "_test.go") {
			continue
		}
		src, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		has := bytes.Contains(src, []byte(`"config.yaml"`))
		if has != (f == "userconfig_path.go") {
			t.Errorf("%s: contains the config.yaml literal = %v", f, has)
		}
	}
}

func TestTelemetryNoSideChannels(t *testing.T) {
	home, _ := telemetryHome(t)
	t.Setenv("OBSTUDIO_ENV_FILE", filepath.Join(home, "sentinel.env"))
	t.Setenv("OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH", filepath.Join(home, "sentinel.json"))
	t.Setenv("DO_NOT_TRACK", "1")
	if r := runTelemetry("telemetry", "status"); firstLine(r.stdout) != "Anonymous usage data: enabled" {
		t.Errorf("status: %+v", r)
	}
	if r := runTelemetry("telemetry", "disable"); firstLine(r.stdout) != "Anonymous usage data is now disabled." {
		t.Errorf("disable: %+v", r)
	}
	entries, _ := os.ReadDir(filepath.Join(home, ".obstudio"))
	if len(entries) != 1 || entries[0].Name() != "config.yaml" {
		t.Errorf("~/.obstudio holds %v", entries)
	}
	for _, name := range []string{"sentinel.env", "sentinel.json"} {
		if _, err := os.Stat(filepath.Join(home, name)); err == nil {
			t.Errorf("%s created", name)
		}
	}
	src, err := os.ReadFile("telemetry.go")
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(src, []byte("internal/configstatus")) || bytes.Contains(src, []byte("NewManager")) {
		t.Error("telemetry.go imports configstatus or builds a Manager")
	}
}
