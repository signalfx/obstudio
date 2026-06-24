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
OBSTUDIO_TEST_EXPORT=true
export OBSTUDIO_TEST_REALM=us1
OBSTUDIO_TEST_TOKEN="token with spaces"
OBSTUDIO_TEST_TIMEOUT='7s'
`), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	for _, key := range []string{"OBSTUDIO_TEST_EXPORT", "OBSTUDIO_TEST_REALM", "OBSTUDIO_TEST_TOKEN", "OBSTUDIO_TEST_TIMEOUT"} {
		_ = os.Unsetenv(key)
		t.Cleanup(func() {
			_ = os.Unsetenv(key)
		})
	}

	if err := loadEnvFile(path); err != nil {
		t.Fatalf("load env file: %v", err)
	}

	if got := os.Getenv("OBSTUDIO_TEST_EXPORT"); got != "true" {
		t.Fatalf("OBSTUDIO_TEST_EXPORT = %q", got)
	}
	if got := os.Getenv("OBSTUDIO_TEST_REALM"); got != "us1" {
		t.Fatalf("OBSTUDIO_TEST_REALM = %q", got)
	}
	if got := os.Getenv("OBSTUDIO_TEST_TOKEN"); got != "token with spaces" {
		t.Fatalf("OBSTUDIO_TEST_TOKEN = %q", got)
	}
	if got := os.Getenv("OBSTUDIO_TEST_TIMEOUT"); got != "7s" {
		t.Fatalf("OBSTUDIO_TEST_TIMEOUT = %q", got)
	}
}

func TestLoadEnvFileDoesNotOverrideExistingEnv(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obstudio.env")
	if err := os.WriteFile(path, []byte("SPLUNK_REALM=from-file\n"), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	t.Setenv("SPLUNK_REALM", "from-shell")

	if err := loadEnvFile(path); err != nil {
		t.Fatalf("load env file: %v", err)
	}
	if got := os.Getenv("SPLUNK_REALM"); got != "from-shell" {
		t.Fatalf("SPLUNK_REALM = %q, want from-shell", got)
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
	if _, _, _, err := parseEnvLine("SPLUNK_REALM"); err == nil {
		t.Fatal("expected parse error")
	}
}
