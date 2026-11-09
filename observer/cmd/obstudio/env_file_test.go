package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadEnvFileParsesEnvSyntax(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
# comments and blank lines are ignored
OBSTUDIO_TEST_FLAG=true
export OBSTUDIO_TEST_NAME=us1
OBSTUDIO_TEST_TEXT="token with spaces"
OBSTUDIO_TEST_TIMEOUT='7s'
`), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	for _, key := range []string{"OBSTUDIO_TEST_FLAG", "OBSTUDIO_TEST_NAME", "OBSTUDIO_TEST_TEXT", "OBSTUDIO_TEST_TIMEOUT"} {
		_ = os.Unsetenv(key)
		t.Cleanup(func() {
			_ = os.Unsetenv(key)
		})
	}

	if err := loadEnvFile(path); err != nil {
		t.Fatalf("load env file: %v", err)
	}

	if got := os.Getenv("OBSTUDIO_TEST_FLAG"); got != "true" {
		t.Fatalf("OBSTUDIO_TEST_FLAG = %q", got)
	}
	if got := os.Getenv("OBSTUDIO_TEST_NAME"); got != "us1" {
		t.Fatalf("OBSTUDIO_TEST_NAME = %q", got)
	}
	if got := os.Getenv("OBSTUDIO_TEST_TEXT"); got != "token with spaces" {
		t.Fatalf("OBSTUDIO_TEST_TEXT = %q", got)
	}
	if got := os.Getenv("OBSTUDIO_TEST_TIMEOUT"); got != "7s" {
		t.Fatalf("OBSTUDIO_TEST_TIMEOUT = %q", got)
	}
}

func TestLoadEnvFileDoesNotOverrideExistingEnv(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte("HOST=from-file\n"), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	t.Setenv("HOST", "from-shell")

	if err := loadEnvFile(path); err != nil {
		t.Fatalf("load env file: %v", err)
	}
	if got := os.Getenv("HOST"); got != "from-shell" {
		t.Fatalf("HOST = %q, want from-shell", got)
	}
}

func TestLoadEnvFileDoesNotOverrideEmptyExistingEnv(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte("WEAVER_PATH=/tmp/from-file\n"), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	t.Setenv("WEAVER_PATH", "")

	if err := loadEnvFile(path); err != nil {
		t.Fatalf("load env file: %v", err)
	}
	if got := os.Getenv("WEAVER_PATH"); got != "" {
		t.Fatalf("WEAVER_PATH = %q, want empty shell value", got)
	}
}

func TestLoadEnvFileKeepsFirstDuplicateValue(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte(`
HOST=us0
HOST=eu0
WEAVER_PATH=/tmp/first
WEAVER_PATH=/tmp/second
`), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	for _, key := range []string{"HOST", "WEAVER_PATH"} {
		key := key
		_ = os.Unsetenv(key)
		t.Cleanup(func() {
			_ = os.Unsetenv(key)
		})
	}

	if err := loadEnvFile(path); err != nil {
		t.Fatalf("load env file: %v", err)
	}

	if got := os.Getenv("HOST"); got != "us0" {
		t.Fatalf("HOST = %q, want us0", got)
	}
	if got := os.Getenv("WEAVER_PATH"); got != "/tmp/first" {
		t.Fatalf("WEAVER_PATH = %q, want /tmp/first", got)
	}
}

func TestLoadConfiguredEnvFileIgnoresMissingDefault(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("OBSTUDIO_ENV_FILE", "")

	if err := loadConfiguredEnvFile(""); err != nil {
		t.Fatalf("missing default env file should be ignored: %v", err)
	}
}

func TestLoadConfiguredEnvFileErrorsForMissingExplicitPath(t *testing.T) {
	path := filepath.Join(t.TempDir(), "missing.env")

	if err := loadConfiguredEnvFile(path); err == nil {
		t.Fatal("expected missing explicit env file to fail")
	}
}

func TestParseEnvLineRejectsInvalidLine(t *testing.T) {
	if _, _, _, err := parseEnvLine("HOST"); err == nil {
		t.Fatal("expected parse error")
	}
}
