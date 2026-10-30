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
		if !configManagerEnabled() {
			t.Errorf("on: %q gave off", v)
		}
	}
	for _, v := range []string{"", "0", "false", "no", "off", "enabled", "2"} {
		t.Setenv(configManagerGateEnv, v)
		if configManagerEnabled() {
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
		if got := configManagerEnabled(); got != tc.want {
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
		if got := configManagerEnabled(); got != tc.want {
			t.Errorf("(%s) %q = %v, want %v", tc.name, tc.content, got, tc.want)
		}
	}

	home := gateHome(t)
	writeGateEnvFile(t, filepath.Join(home, ".obstudio", "env"), "OBSTUDIO_CONFIG_MANAGER=true\n")
	if !configManagerEnabled() {
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
		if configManagerEnabled() {
			t.Errorf("off: %s gave on", name)
		}
	}
}

func TestConfigManagerGateNoHome(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Unix only")
	}
	gateHome(t)
	t.Setenv("HOME", "")
	if configManagerEnabled() {
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

	if !configManagerEnabled() {
		t.Fatal("file true gave off")
	}
	if got := sortedEnviron(); !slices.Equal(got, environ) {
		t.Error("env-unchanged: the process environment changed")
	}
	t.Setenv(configManagerGateEnv, "true")
	if !configManagerEnabled() {
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
	if configManagerEnabled() {
		t.Error("not-cached: rewriting the file to false still gives on")
	}
}

func TestConfigManagerGateSourceScan(t *testing.T) {
	const call = "configManagerEnabled()"
	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, f := range files {
		if strings.HasSuffix(f, "_test.go") {
			continue
		}
		src, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		count += bytes.Count(src, []byte(call))
	}
	if count != 3 {
		t.Errorf("two-call-sites: %q occurs %d times in non-test files, want 3 (declaration, newRootCmd, run)", call, count)
	}

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
