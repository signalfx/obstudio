package main

import (
	"bytes"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/userconfig"
)

// unsetEnv removes key for the rest of the test; t.Setenv restores the
// original value afterwards.
func unsetEnv(t *testing.T, key string) {
	t.Helper()
	t.Setenv(key, "")
	if err := os.Unsetenv(key); err != nil {
		t.Fatal(err)
	}
}

// gateHome gives the test a fresh home, with the gate variable and
// OBSTUDIO_ENV_FILE absent, so no test reads the developer's real env file.
func gateHome(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	unsetEnv(t, configManagerGateEnv)
	unsetEnv(t, "OBSTUDIO_ENV_FILE")
	return home
}

func writeGateEnvFile(t *testing.T, path, content string) string {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestConfigManagerGateValuesMatrix(t *testing.T) {
	gateHome(t)
	t.Setenv("OBSTUDIO_ENV_FILE", writeGateEnvFile(t, filepath.Join(t.TempDir(), "env"), "OBSTUDIO_CONFIG_MANAGER=true\n"))
	for _, v := range []string{"1", "true", "TRUE", " yes ", "y", "On"} {
		t.Setenv(configManagerGateEnv, v)
		if !configManagerEnabled("") {
			t.Errorf("on: %q gave off", v)
		}
	}
	for _, v := range []string{"", "0", "false", "no", "off", "enabled", "2"} {
		t.Setenv(configManagerGateEnv, v)
		if configManagerEnabled("") {
			t.Errorf("off: %q gave on (the file must not be consulted)", v)
		}
	}
}

func TestConfigManagerGatePrecedence(t *testing.T) {
	gateHome(t)
	dir := t.TempDir()
	for _, tc := range []struct {
		process, file string
		want          bool
	}{
		{"false", "true", false},
		{"", "true", false},
		{"true", "false", true},
	} {
		t.Setenv("OBSTUDIO_ENV_FILE", writeGateEnvFile(t, filepath.Join(dir, "env"), "OBSTUDIO_CONFIG_MANAGER="+tc.file+"\n"))
		t.Setenv(configManagerGateEnv, tc.process)
		if got := configManagerEnabled(""); got != tc.want {
			t.Errorf("process-wins: process %q file %q = %v, want %v", tc.process, tc.file, got, tc.want)
		}
	}
}

func TestConfigManagerGateEnvFile(t *testing.T) {
	dir := t.TempDir()
	for _, tc := range []struct {
		name, content string
		want          bool
	}{
		{"a", "OBSTUDIO_CONFIG_MANAGER=true\n", true},
		{"b", "export OBSTUDIO_CONFIG_MANAGER=\"on\"\n", true},
		{"c", "OBSTUDIO_CONFIG_MANAGER=false\n", false},
		{"d", "SPLUNK_REALM=us0\n", false},
	} {
		gateHome(t)
		t.Setenv("OBSTUDIO_ENV_FILE", writeGateEnvFile(t, filepath.Join(dir, tc.name+".env"), tc.content))
		if got := configManagerEnabled(""); got != tc.want {
			t.Errorf("(%s) %q = %v, want %v", tc.name, tc.content, got, tc.want)
		}
	}

	home := gateHome(t)
	writeGateEnvFile(t, filepath.Join(home, ".obstudio", "env"), "OBSTUDIO_CONFIG_MANAGER=true\n")
	if !configManagerEnabled("") {
		t.Error("(e) default ~/.obstudio/env with =true gave off")
	}
}

func TestConfigManagerGateEnvFileFailures(t *testing.T) {
	gateHome(t)
	dir := t.TempDir()
	cases := map[string]string{
		"missing":   filepath.Join(dir, "does-not-exist"),
		"directory": dir,
		"bad-line":  writeGateEnvFile(t, filepath.Join(dir, "bad.env"), "OBSTUDIO_CONFIG_MANAGER=true\nnot a pair\n"),
	}
	if runtime.GOOS != "windows" && os.Geteuid() != 0 {
		unreadable := writeGateEnvFile(t, filepath.Join(dir, "unreadable.env"), "OBSTUDIO_CONFIG_MANAGER=true\n")
		if err := os.Chmod(unreadable, 0o000); err != nil {
			t.Fatal(err)
		}
		cases["mode-0000"] = unreadable
	}
	for name, path := range cases {
		t.Setenv("OBSTUDIO_ENV_FILE", path)
		if configManagerEnabled("") {
			t.Errorf("off: %s via OBSTUDIO_ENV_FILE gave on", name)
		}
		unsetEnv(t, "OBSTUDIO_ENV_FILE")
		if configManagerEnabled(path) {
			t.Errorf("off: %s via --env-file gave on", name)
		}
	}
}

func TestConfigManagerGateNoHome(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix only")
	}
	gateHome(t)
	t.Setenv("HOME", "")
	if configManagerEnabled("") {
		t.Error("off: no home gave on")
	}
	root := newRootCmd(&runConfig{})
	var out bytes.Buffer
	root.SetArgs([]string{"--version"})
	root.SetOut(&out)
	root.SetErr(&out)
	if err := root.Execute(); err != nil {
		t.Errorf("cli-builds: --version: %v", err)
	}
}

type fileStamp struct {
	data  []byte
	mode  fs.FileMode
	mtime time.Time
}

func stampFile(t *testing.T, path string) fileStamp {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	return fileStamp{data, info.Mode(), info.ModTime()}
}

func dirNames(t *testing.T, dir string) []string {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, e := range entries {
		names = append(names, e.Name())
	}
	return names
}

func sortedEnviron() []string {
	env := os.Environ()
	slices.Sort(env)
	return env
}

func TestConfigManagerGateNoSideEffects(t *testing.T) {
	home := gateHome(t)
	var logBuf bytes.Buffer
	prevOut, prevFlags := log.Writer(), log.Flags()
	log.SetOutput(&logBuf)
	t.Cleanup(func() { log.SetOutput(prevOut); log.SetFlags(prevFlags) })

	envPath := writeGateEnvFile(t, filepath.Join(t.TempDir(), "env"), "OBSTUDIO_CONFIG_MANAGER=true\n")
	t.Setenv("OBSTUDIO_ENV_FILE", envPath)
	before := stampFile(t, envPath)
	homeBefore := dirNames(t, home)
	environ := sortedEnviron()

	if !configManagerEnabled("") {
		t.Fatal("file true gave off")
	}
	if got := sortedEnviron(); !slices.Equal(got, environ) {
		t.Error("env-unchanged: the process environment changed")
	}
	t.Setenv(configManagerGateEnv, "true")
	if !configManagerEnabled("") {
		t.Fatal("process true gave off")
	}

	after := stampFile(t, envPath)
	if !bytes.Equal(after.data, before.data) || after.mode != before.mode || !after.mtime.Equal(before.mtime) {
		t.Error("files-unchanged: the env file changed")
	}
	if got := dirNames(t, home); !slices.Equal(got, homeBefore) {
		t.Errorf("files-unchanged: home holds %v, was %v", got, homeBefore)
	}
	if logBuf.Len() != 0 {
		t.Errorf("silent: logged %q", logBuf.String())
	}

	unsetEnv(t, configManagerGateEnv)
	writeGateEnvFile(t, envPath, "OBSTUDIO_CONFIG_MANAGER=false\n")
	if configManagerEnabled("") {
		t.Error("not-cached: rewriting the file to false still gives on")
	}
}

// afterLoadHome is gateHome plus every key an env file in these cases holds,
// so the framework restores whatever loadConfiguredEnvFile sets.
func afterLoadHome(t *testing.T) string {
	t.Helper()
	home := gateHome(t)
	unsetEnv(t, "SPLUNK_REALM")
	return home
}

func TestConfigManagerGateAfterEnvLoad(t *testing.T) {
	// (a) Absent from the process; both env files say true. On before the
	// load, as newRootCmd sees it, and on after it, as run sees it.
	home := afterLoadHome(t)
	writeGateEnvFile(t, filepath.Join(home, ".obstudio", "env"), "OBSTUDIO_CONFIG_MANAGER=true\n")
	t.Setenv("OBSTUDIO_ENV_FILE", writeGateEnvFile(t, filepath.Join(t.TempDir(), "env"), "OBSTUDIO_CONFIG_MANAGER=true\n"))
	if !configManagerEnabled("") {
		t.Error("after-env-load (a): before the load, both files true gave off")
	}
	if err := loadConfiguredEnvFile(""); err != nil {
		t.Fatalf("after-env-load (a): load: %v", err)
	}
	if !configManagerEnabled("") {
		t.Error("after-env-load (a): after the load, both files true gave off")
	}

	// (b) and (c): the process environment decides, even when empty and
	// the default file says true.
	home = afterLoadHome(t)
	writeGateEnvFile(t, filepath.Join(home, ".obstudio", "env"), "OBSTUDIO_CONFIG_MANAGER=true\n")
	t.Setenv(configManagerGateEnv, "true")
	if !configManagerEnabled("") {
		t.Error("after-env-load (b): true gave off")
	}
	t.Setenv(configManagerGateEnv, "")
	if configManagerEnabled("") {
		t.Error("after-env-load (c): empty gave on")
	}

	// (d) --env-file names a file without the gate; ~/.obstudio/env says
	// true but is not the loaded file. This is the reviewer's case.
	home = afterLoadHome(t)
	writeGateEnvFile(t, filepath.Join(home, ".obstudio", "env"), "OBSTUDIO_CONFIG_MANAGER=true\n")
	other := writeGateEnvFile(t, filepath.Join(t.TempDir(), "other.env"), "SPLUNK_REALM=us0\n")
	if configManagerEnabled(other) {
		t.Error("after-env-load (d): before the load, ~/.obstudio/env turned the gate on behind --env-file")
	}
	if err := loadConfiguredEnvFile(other); err != nil {
		t.Fatalf("after-env-load (d): load: %v", err)
	}
	if configManagerEnabled(other) {
		t.Error("after-env-load (d): ~/.obstudio/env turned the gate on behind --env-file")
	}

	// (e) No flag and no OBSTUDIO_ENV_FILE: the default file is loaded and
	// its value is in the process environment.
	home = afterLoadHome(t)
	writeGateEnvFile(t, filepath.Join(home, ".obstudio", "env"), "OBSTUDIO_CONFIG_MANAGER=true\n")
	if err := loadConfiguredEnvFile(""); err != nil {
		t.Fatalf("after-env-load (e): load: %v", err)
	}
	if !configManagerEnabled("") {
		t.Error("after-env-load (e): loaded default env file with =true gave off")
	}

	// (f) --env-file names a file with the gate; ~/.obstudio/env lacks it.
	home = afterLoadHome(t)
	writeGateEnvFile(t, filepath.Join(home, ".obstudio", "env"), "SPLUNK_REALM=us0\n")
	flagged := writeGateEnvFile(t, filepath.Join(t.TempDir(), "flagged.env"), "OBSTUDIO_CONFIG_MANAGER=true\n")
	if !configManagerEnabled(flagged) {
		t.Error("after-env-load (f): before the load, --env-file with =true gave off")
	}
	if err := loadConfiguredEnvFile(flagged); err != nil {
		t.Fatalf("after-env-load (f): load: %v", err)
	}
	if !configManagerEnabled(flagged) {
		t.Error("after-env-load (f): --env-file with =true gave off")
	}
}

// TestConfigManagerGateEnvFileFlagSplit pins the case where the gate gives
// different answers before and after --env-file is parsed: ~/.obstudio/env
// turns it on and --env-file names a file without it. `telemetry` is
// registered and writes config.yaml itself, but run builds no Manager.
func TestConfigManagerGateEnvFileFlagSplit(t *testing.T) {
	home := afterLoadHome(t)
	writeGateEnvFile(t, filepath.Join(home, ".obstudio", "env"), "OBSTUDIO_CONFIG_MANAGER=true\n")
	other := writeGateEnvFile(t, filepath.Join(t.TempDir(), "other.env"), "SPLUNK_REALM=us0\n")
	path := filepath.Join(home, ".obstudio", "config.yaml")

	config := &runConfig{}
	root := newRootCmd(config)
	registered := false
	for _, c := range root.Commands() {
		registered = registered || c.Name() == "telemetry"
	}
	if !registered {
		t.Error("registered: newRootCmd has no telemetry command")
	}

	if err := root.ParseFlags([]string{"--env-file", other}); err != nil {
		t.Fatal(err)
	}
	if err := loadConfiguredEnvFile(config.envFile); err != nil {
		t.Fatalf("load %q: %v", config.envFile, err)
	}
	if configManagerEnabled(config.envFile) {
		t.Error("no-manager: the gate is on after --env-file without the variable")
	}
	if w := buildUserConfig(configManagerEnabled(config.envFile)); w.manager != nil {
		w.manager.Close()
		t.Error("no-manager: run would build a Manager")
	}
	if _, err := os.Stat(path); err == nil {
		t.Fatal("no-manager: config.yaml exists before the CLI ran")
	}

	r := runTelemetry("telemetry", "enable")
	if r.err != nil {
		t.Fatalf("cli-writes: telemetry enable: %v (stderr %q)", r.err, r.stderr)
	}
	if content, err := os.ReadFile(path); err != nil || string(content) != userconfig.Scaffold() {
		t.Errorf("cli-writes: config.yaml is not the scaffold: %v", err)
	}
}

func TestConfigManagerGateSourceScan(t *testing.T) {
	const literal = "OBSTUDIO_CONFIG_MANAGER"
	repo := filepath.Join("..", "..", "..")
	gate, err := filepath.Abs("config_manager_gate.go")
	if err != nil {
		t.Fatal(err)
	}
	scan := func(root string, match func(path string) bool) {
		t.Helper()
		err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if d.IsDir() {
				if name := d.Name(); name == "node_modules" || name == "dist" || name == "out" {
					return filepath.SkipDir
				}
				return nil
			}
			if !match(path) || isTestSource(path) {
				return nil
			}
			src, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			if !bytes.Contains(src, []byte(literal)) {
				return nil
			}
			if abs, _ := filepath.Abs(path); abs == gate {
				return nil
			}
			t.Errorf("one-reader: %s contains %s", path, literal)
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
	scan(filepath.Join(repo, "observer"), func(p string) bool {
		return strings.HasSuffix(p, ".go") && !strings.Contains(filepath.ToSlash(p), "/client/")
	})
	scan(filepath.Join(repo, "observer", "client", "src"), func(string) bool { return true })
	scan(filepath.Join(repo, "extension", "src"), func(string) bool { return true })

	src, err := os.ReadFile("config_manager_gate.go")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(src, []byte(literal)) {
		t.Errorf("one-reader: config_manager_gate.go does not contain %s", literal)
	}
}

func isTestSource(path string) bool {
	base := filepath.Base(path)
	if strings.HasSuffix(base, "_test.go") {
		return true
	}
	for _, s := range []string{".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"} {
		if strings.HasSuffix(base, s) {
			return true
		}
	}
	slashed := filepath.ToSlash(path)
	return strings.Contains(slashed, "/test/") || strings.Contains(slashed, "/__tests__/")
}
