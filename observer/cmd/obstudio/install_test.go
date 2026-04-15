package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestClaudeCodeTargetUsesSettingsJSON(t *testing.T) {
	t.Parallel()

	target, ok := targets["claude-code"]
	if !ok {
		t.Fatal("expected claude-code target to exist")
	}

	path := target.mcpConfig.path()
	if !strings.HasSuffix(path, filepath.Join(".claude", "settings.json")) {
		t.Fatalf("expected Claude Code MCP config path to end with .claude/settings.json, got %q", path)
	}
}

func TestCodexTargetUsesConfigTOML(t *testing.T) {
	t.Parallel()

	target, ok := targets["codex"]
	if !ok {
		t.Fatal("expected codex target to exist")
	}

	path := target.mcpConfig.path()
	if !strings.HasSuffix(path, filepath.Join(".codex", "config.toml")) {
		t.Fatalf("expected Codex MCP config path to end with .codex/config.toml, got %q", path)
	}
}

func TestUpsertJSONMCPServerPreservesExistingEntries(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "mcp.json")
	initial := map[string]any{
		"mcpServers": map[string]any{
			"existing": map[string]any{
				"command": "existing-server",
				"args":    []string{"--flag"},
			},
		},
		"theme": "dark",
	}
	data, err := json.Marshal(initial)
	if err != nil {
		t.Fatalf("marshal initial config: %v", err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatalf("write initial config: %v", err)
	}

	if err := upsertJSONMCPServer(path, map[string]any{
		"type": "http",
		"url":  "http://127.0.0.1:3000/mcp",
	}); err != nil {
		t.Fatalf("upsertJSONMCPServer returned error: %v", err)
	}

	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read config: %v", err)
	}

	var config map[string]any
	if err := json.Unmarshal(out, &config); err != nil {
		t.Fatalf("unmarshal config: %v", err)
	}

	if got := config["theme"]; got != "dark" {
		t.Fatalf("expected theme to be preserved, got %#v", got)
	}

	servers, ok := config["mcpServers"].(map[string]any)
	if !ok {
		t.Fatalf("mcpServers missing or wrong type: %#v", config["mcpServers"])
	}

	if _, ok := servers["existing"]; !ok {
		t.Fatalf("existing server was removed: %#v", servers)
	}

	obstudio, ok := servers["obstudio"].(map[string]any)
	if !ok {
		t.Fatalf("obstudio server missing or wrong type: %#v", servers["obstudio"])
	}
	if got := obstudio["type"]; got != "http" {
		t.Fatalf("expected obstudio type=http, got %#v", got)
	}
	if got := obstudio["url"]; got != "http://127.0.0.1:3000/mcp" {
		t.Fatalf("expected obstudio url to be preserved, got %#v", got)
	}
}

func TestUpsertCodexMCPServerAppendsManagedBlock(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := strings.Join([]string{
		`model = "gpt-5.4"`,
		``,
		`[projects."/tmp/demo"]`,
		`trust_level = "trusted"`,
		``,
	}, "\n")
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write initial config: %v", err)
	}

	if err := upsertCodexMCPServer(path, codexMCPServer{
		URL: "http://127.0.0.1:3000/mcp",
	}); err != nil {
		t.Fatalf("upsertCodexMCPServer returned error: %v", err)
	}

	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read config: %v", err)
	}
	text := string(out)

	for _, want := range []string{
		`model = "gpt-5.4"`,
		`[projects."/tmp/demo"]`,
		`trust_level = "trusted"`,
		codexManagedBlockStart,
		`[mcp_servers.obstudio]`,
		`enabled = true`,
		`url = "http://127.0.0.1:3000/mcp"`,
		codexManagedBlockEnd,
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("expected config to contain %q, got:\n%s", want, text)
		}
	}
}

func TestUpsertCodexMCPServerReplacesLegacySection(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := strings.Join([]string{
		`model = "gpt-5.4"`,
		``,
		`[mcp_servers.obstudio]`,
		`command = "/tmp/old-obstudio"`,
		`args = ["--stdio"]`,
		``,
		`[mcp_servers.other]`,
		`url = "http://example.com/mcp"`,
		``,
	}, "\n")
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write initial config: %v", err)
	}

	if err := upsertCodexMCPServer(path, codexMCPServer{
		Command: "/tmp/new-obstudio",
		Args:    []string{},
	}); err != nil {
		t.Fatalf("upsertCodexMCPServer returned error: %v", err)
	}

	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read config: %v", err)
	}
	text := string(out)

	if strings.Contains(text, `/tmp/old-obstudio`) {
		t.Fatalf("legacy obstudio section was not removed:\n%s", text)
	}
	if strings.Count(text, `[mcp_servers.obstudio]`) != 1 {
		t.Fatalf("expected exactly one obstudio section, got:\n%s", text)
	}
	if !strings.Contains(text, `command = "/tmp/new-obstudio"`) {
		t.Fatalf("new obstudio command missing:\n%s", text)
	}
	if !strings.Contains(text, `[mcp_servers.other]`) {
		t.Fatalf("other MCP section was removed:\n%s", text)
	}
}

func TestValidateSharedURL(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name    string
		raw     string
		wantErr bool
	}{
		{name: "http", raw: "http://127.0.0.1:3000/mcp"},
		{name: "https", raw: "https://example.com/mcp"},
		{name: "missing scheme", raw: "127.0.0.1:3000/mcp", wantErr: true},
		{name: "missing host", raw: "http:///mcp", wantErr: true},
		{name: "wrong scheme", raw: "stdio://obstudio", wantErr: true},
	}

	for _, tc := range tests {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			err := validateSharedURL(tc.raw, "--shared-url")
			if tc.wantErr && err == nil {
				t.Fatalf("expected error for %q", tc.raw)
			}
			if !tc.wantErr && err != nil {
				t.Fatalf("unexpected error for %q: %v", tc.raw, err)
			}
		})
	}
}

func TestNormalizeSharedURL(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name     string
		raw      string
		expected string
	}{
		{name: "base URL", raw: "http://127.0.0.1:3000", expected: "http://127.0.0.1:3000/mcp"},
		{name: "base URL with slash", raw: "http://127.0.0.1:3000/", expected: "http://127.0.0.1:3000/mcp"},
		{name: "existing mcp URL", raw: "http://127.0.0.1:3000/mcp", expected: "http://127.0.0.1:3000/mcp"},
		{name: "subpath", raw: "https://example.com/obstudio", expected: "https://example.com/obstudio/mcp"},
		{name: "subpath mcp", raw: "https://example.com/obstudio/mcp", expected: "https://example.com/obstudio/mcp"},
	}

	for _, tc := range tests {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			got, err := normalizeSharedURL(tc.raw, "--shared-url")
			if err != nil {
				t.Fatalf("normalizeSharedURL(%q) returned error: %v", tc.raw, err)
			}
			if got != tc.expected {
				t.Fatalf("normalizeSharedURL(%q) = %q, want %q", tc.raw, got, tc.expected)
			}
		})
	}
}

func TestValidateSharedURLIncludesSourceLabel(t *testing.T) {
	t.Parallel()

	err := validateSharedURL("stdio://obstudio", "detected shared observer URL")
	if err == nil {
		t.Fatal("expected validation error")
	}
	if !strings.Contains(err.Error(), "invalid detected shared observer URL") {
		t.Fatalf("expected source label in error, got %q", err.Error())
	}
}

func TestDetectSharedObserverURL(t *testing.T) {
	t.Parallel()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			Endpoints: map[string]string{
				"mcp": "http://127.0.0.1:3000/mcp",
			},
		})
	}))
	defer server.Close()

	detected, ok := detectSharedObserverURL(server.URL, server.Client())
	if !ok {
		t.Fatal("expected shared observer to be detected")
	}
	if detected != "http://127.0.0.1:3000/mcp" {
		t.Fatalf("unexpected detected URL: %s", detected)
	}
}

func TestDetectSharedObserverURLRejectsMismatchedService(t *testing.T) {
	t.Parallel()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"kind":       "other-service",
			"apiVersion": "v1",
			"endpoints": map[string]string{
				"mcp": "http://127.0.0.1:3000/mcp",
			},
		})
	}))
	defer server.Close()

	if detected, ok := detectSharedObserverURL(server.URL, server.Client()); ok {
		t.Fatalf("expected no detection, got %s", detected)
	}
}

func TestUpsertCodexMCPServerWrapsWriteErrors(t *testing.T) {
	t.Parallel()

	if runtime.GOOS == "windows" {
		t.Skip("permission-based write error assertion is not reliable on Windows")
	}

	parentDir := filepath.Join(t.TempDir(), "readonly")
	if err := os.Mkdir(parentDir, 0o755); err != nil {
		t.Fatalf("mkdir parent dir: %v", err)
	}
	if err := os.Chmod(parentDir, 0o555); err != nil {
		t.Fatalf("chmod parent dir: %v", err)
	}
	t.Cleanup(func() {
		_ = os.Chmod(parentDir, 0o755)
	})

	path := filepath.Join(parentDir, "config.toml")

	err := upsertCodexMCPServer(path, codexMCPServer{URL: "http://127.0.0.1:3000/mcp"})
	if err == nil {
		t.Fatal("expected upsertCodexMCPServer to fail when parent directory is not writable")
	}
	if !strings.Contains(err.Error(), "write codex MCP config") {
		t.Fatalf("expected wrapped write error, got %v", err)
	}
	if !strings.Contains(err.Error(), path) {
		t.Fatalf("expected error to include path %q, got %v", path, err)
	}
}

func TestCopyFileWrapsSourcePathErrors(t *testing.T) {
	t.Parallel()

	dst := filepath.Join(t.TempDir(), "copy", "target")
	err := copyFile(filepath.Join(t.TempDir(), "missing"), dst)
	if err == nil {
		t.Fatal("expected copyFile to fail for missing source")
	}
	if !strings.Contains(err.Error(), "missing") {
		t.Fatalf("expected missing source path in error, got %v", err)
	}
}
