package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/buildutil"
)

func TestClaudeCodeTargetUsesClaudeJSON(t *testing.T) {
	t.Parallel()

	target, ok := targets["claude-code"]
	if !ok {
		t.Fatal("expected claude-code target to exist")
	}

	path := target.mcpConfig.path()
	if !strings.HasSuffix(path, ".claude.json") {
		t.Fatalf("expected Claude Code MCP config path to end with .claude.json, got %q", path)
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

func TestKiroTargetUsesSettingsMCPJSON(t *testing.T) {
	t.Parallel()

	target, ok := targets["kiro"]
	if !ok {
		t.Fatal("expected kiro target to exist")
	}

	if path := target.mcpConfig.path(); !strings.HasSuffix(path, filepath.Join(".kiro", "settings", "mcp.json")) {
		t.Fatalf("expected Kiro MCP config path to end with .kiro/settings/mcp.json, got %q", path)
	}
	if skillsDir := target.skillsDir("/home/test"); !strings.HasSuffix(skillsDir, filepath.Join(".kiro", "skills", "obstudio")) {
		t.Fatalf("expected Kiro skills path to end with .kiro/skills/obstudio, got %q", skillsDir)
	}
}

func TestInstallTargetFlagAcceptsCommaSeparatedValues(t *testing.T) {
	t.Parallel()

	cmd := newInstallCmd()
	if err := cmd.ParseFlags([]string{"--target", "codex,claude-code,cursor,kiro"}); err != nil {
		t.Fatalf("parse comma-separated targets: %v", err)
	}
	got, err := cmd.Flags().GetStringSlice("target")
	if err != nil {
		t.Fatalf("read parsed targets: %v", err)
	}
	if joined := strings.Join(got, ","); joined != "codex,claude-code,cursor,kiro" {
		t.Fatalf("parsed targets = %q, want %q", joined, "codex,claude-code,cursor,kiro")
	}
}

func TestNormalizeInstallTargets(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name          string
		requested     []string
		want          string
		errorContains string
	}{
		{name: "single", requested: []string{"codex"}, want: "codex"},
		{name: "all", requested: []string{"codex", "claude-code", "cursor", "kiro"}, want: "codex,claude-code,cursor,kiro"},
		{name: "trim and deduplicate", requested: []string{" codex ", "cursor", "codex"}, want: "codex,cursor"},
		{name: "missing", errorContains: "at least one target is required"},
		{name: "empty", requested: []string{"codex", " "}, errorContains: "target cannot be empty"},
		{name: "unknown", requested: []string{"codex", "other"}, errorContains: "unknown target: other"},
	}

	for _, tc := range tests {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			got, err := normalizeInstallTargets(tc.requested)
			if tc.errorContains != "" {
				if err == nil || !strings.Contains(err.Error(), tc.errorContains) {
					t.Fatalf("normalizeInstallTargets() error = %v, want containing %q", err, tc.errorContains)
				}
				return
			}
			if err != nil {
				t.Fatalf("normalizeInstallTargets() error = %v", err)
			}
			if joined := strings.Join(got, ","); joined != tc.want {
				t.Fatalf("normalizeInstallTargets() = %q, want %q", joined, tc.want)
			}
		})
	}
}

func TestRootCommandOnlyExposesObserverHTTPPortOverride(t *testing.T) {
	t.Parallel()

	var config runConfig
	root := newRootCmd(&config)

	if root.Flags().Lookup("observer-http-port") == nil {
		t.Fatal("expected --observer-http-port flag to be registered")
	}
	if root.Flags().Lookup("otlp-http-port") != nil {
		t.Fatal("did not expect --otlp-http-port to be exposed")
	}
	if root.Flags().Lookup("otlp-grpc-port") != nil {
		t.Fatal("did not expect --otlp-grpc-port to be exposed")
	}
}

func TestCopySiblingWeaverRuntimeCopiesBundledRuntime(t *testing.T) {
	t.Parallel()

	sourceDir := t.TempDir()
	destDir := t.TempDir()
	exePath := filepath.Join(sourceDir, "obstudio")
	weaverPath := filepath.Join(sourceDir, "weaver")

	if err := os.WriteFile(exePath, []byte("obstudio"), 0o755); err != nil {
		t.Fatalf("write obstudio: %v", err)
	}
	if err := os.WriteFile(weaverPath, []byte("weaver-runtime"), 0o755); err != nil {
		t.Fatalf("write weaver: %v", err)
	}

	copied, err := copySiblingWeaverRuntime(exePath, destDir)
	if err != nil {
		t.Fatalf("copySiblingWeaverRuntime returned error: %v", err)
	}
	if !copied {
		t.Fatal("expected Weaver runtime to be copied")
	}

	data, err := os.ReadFile(filepath.Join(destDir, "weaver"))
	if err != nil {
		t.Fatalf("read copied weaver: %v", err)
	}
	if string(data) != "weaver-runtime" {
		t.Fatalf("unexpected copied weaver contents: %q", string(data))
	}
}

func TestCopySiblingWeaverRuntimeIsOptional(t *testing.T) {
	t.Parallel()

	sourceDir := t.TempDir()
	destDir := t.TempDir()
	exePath := filepath.Join(sourceDir, "obstudio")
	if err := os.WriteFile(exePath, []byte("obstudio"), 0o755); err != nil {
		t.Fatalf("write obstudio: %v", err)
	}

	copied, err := copySiblingWeaverRuntime(exePath, destDir)
	if err != nil {
		t.Fatalf("copySiblingWeaverRuntime returned error: %v", err)
	}
	if copied {
		t.Fatal("expected no Weaver runtime copy when none is bundled")
	}
}

func TestEnsureInstallWeaverRuntimeUsesPATHFallback(t *testing.T) {
	sourceDir := t.TempDir()
	destDir := t.TempDir()
	pathDir := t.TempDir()
	exePath := filepath.Join(sourceDir, "obstudio")
	weaverPath := filepath.Join(pathDir, "weaver")

	if err := os.WriteFile(exePath, []byte("obstudio"), 0o755); err != nil {
		t.Fatalf("write obstudio: %v", err)
	}
	if err := os.WriteFile(weaverPath, []byte("external-weaver"), 0o755); err != nil {
		t.Fatalf("write weaver on PATH: %v", err)
	}
	t.Setenv("PATH", pathDir)
	t.Setenv("WEAVER_PATH", "")

	installed, external, err := ensureInstallWeaverRuntime(exePath, destDir, true)
	if err != nil {
		t.Fatalf("ensureInstallWeaverRuntime returned error: %v", err)
	}
	if installed {
		t.Fatal("expected PATH fallback instead of local copy")
	}
	if external != weaverPath {
		t.Fatalf("expected PATH weaver %q, got %q", weaverPath, external)
	}
}

func TestEnsureInstallWeaverRuntimeFailsWhenLocalValidationWouldBeBroken(t *testing.T) {
	sourceDir := t.TempDir()
	destDir := t.TempDir()
	exePath := filepath.Join(sourceDir, "obstudio")

	if err := os.WriteFile(exePath, []byte("obstudio"), 0o755); err != nil {
		t.Fatalf("write obstudio: %v", err)
	}
	t.Setenv("PATH", t.TempDir())
	t.Setenv("WEAVER_PATH", "")

	installed, external, err := ensureInstallWeaverRuntime(exePath, destDir, true)
	if err == nil {
		t.Fatal("expected ensureInstallWeaverRuntime to fail without a local or external runtime")
	}
	if installed {
		t.Fatal("expected no local weaver installation")
	}
	if external != "" {
		t.Fatalf("expected no external weaver runtime, got %q", external)
	}
	if !strings.Contains(err.Error(), "Weaver runtime not found beside obstudio or on PATH") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestEnsureInstallWeaverRuntimeAllowsSharedModeWithoutLocalRuntime(t *testing.T) {
	sourceDir := t.TempDir()
	destDir := t.TempDir()
	exePath := filepath.Join(sourceDir, "obstudio")

	if err := os.WriteFile(exePath, []byte("obstudio"), 0o755); err != nil {
		t.Fatalf("write obstudio: %v", err)
	}
	t.Setenv("PATH", t.TempDir())
	t.Setenv("WEAVER_PATH", "")

	installed, external, err := ensureInstallWeaverRuntime(exePath, destDir, false)
	if err != nil {
		t.Fatalf("ensureInstallWeaverRuntime returned error: %v", err)
	}
	if installed {
		t.Fatal("expected no local weaver installation")
	}
	if external != "" {
		t.Fatalf("expected no external weaver runtime, got %q", external)
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
	}, nil, nil); err != nil {
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

func TestConfigureMCPUsesKiroRemoteURLSchema(t *testing.T) {
	t.Parallel()

	configPath := filepath.Join(t.TempDir(), "mcp.json")
	initial := map[string]any{
		"mcpServers": map[string]any{
			"obstudio": map[string]any{
				"command":       "/tmp/old-obstudio",
				"args":          []string{"--old"},
				"url":           "https://old.example/mcp",
				"headers":       map[string]string{"Authorization": "stale"},
				"env":           map[string]string{"OBSERVER_MODE": "stale"},
				"oauth":         map[string]string{"clientId": "stale"},
				"oauthScopes":   []string{"stale.scope"},
				"autoApprove":   []string{"observer_status"},
				"disabled":      true,
				"disabledTools": []string{"observer_clear"},
				"timeout":       45_000,
			},
		},
	}
	data, err := json.Marshal(initial)
	if err != nil {
		t.Fatalf("marshal initial Kiro MCP config: %v", err)
	}
	if err := os.WriteFile(configPath, data, 0o644); err != nil {
		t.Fatalf("write initial Kiro MCP config: %v", err)
	}

	target := targets["kiro"].mcpConfig
	target.path = func() string { return configPath }
	if err := configureMCP(target, "/tmp/obstudio", "http://127.0.0.1:3000/mcp"); err != nil {
		t.Fatalf("configureMCP returned error: %v", err)
	}

	data, err = os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("read Kiro MCP config: %v", err)
	}
	var config struct {
		MCPServers map[string]map[string]any `json:"mcpServers"`
	}
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("unmarshal Kiro MCP config: %v", err)
	}
	server := config.MCPServers["obstudio"]
	if got := server["url"]; got != "http://127.0.0.1:3000/mcp" {
		t.Fatalf("Kiro obstudio URL = %#v, want documented remote URL", got)
	}
	if got, ok := server["type"]; ok {
		t.Fatalf("Kiro remote config should omit undocumented type field, got %#v", got)
	}
	for _, field := range []string{"command", "args", "headers", "env", "oauth", "oauthScopes"} {
		if got, ok := server[field]; ok {
			t.Fatalf("Kiro remote config should remove stale %s field, got %#v", field, got)
		}
	}
	if got := server["disabled"]; got != true {
		t.Fatalf("Kiro disabled policy = %#v, want true", got)
	}
	if got := server["autoApprove"].([]any); len(got) != 1 || got[0] != "observer_status" {
		t.Fatalf("Kiro autoApprove policy = %#v, want observer_status", got)
	}
	if got := server["disabledTools"].([]any); len(got) != 1 || got[0] != "observer_clear" {
		t.Fatalf("Kiro disabledTools policy = %#v, want observer_clear", got)
	}
	if got := server["timeout"]; got != float64(45_000) {
		t.Fatalf("Kiro timeout policy = %#v, want 45000", got)
	}
}

func TestConfigureMCPPreservesKiroRemoteOptionsForMatchingURL(t *testing.T) {
	t.Parallel()

	const mcpURL = "http://127.0.0.1:3000/mcp"
	configPath := filepath.Join(t.TempDir(), "mcp.json")
	initial := map[string]any{
		"mcpServers": map[string]any{
			"obstudio": map[string]any{
				"command":     "/tmp/old-obstudio",
				"args":        []string{"--old"},
				"url":         mcpURL,
				"headers":     map[string]string{"X-Observer-Test": "preserved"},
				"env":         map[string]string{"OBSERVER_MODE": "preserved"},
				"oauth":       map[string]string{"clientId": "preserved"},
				"oauthScopes": []string{"observer.read"},
				"timeout":     45_000,
			},
		},
	}
	data, err := json.Marshal(initial)
	if err != nil {
		t.Fatalf("marshal initial Kiro MCP config: %v", err)
	}
	if err := os.WriteFile(configPath, data, 0o644); err != nil {
		t.Fatalf("write initial Kiro MCP config: %v", err)
	}

	target := targets["kiro"].mcpConfig
	target.path = func() string { return configPath }
	if err := configureMCP(target, "/tmp/obstudio", mcpURL); err != nil {
		t.Fatalf("configureMCP returned error: %v", err)
	}

	data, err = os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("read Kiro MCP config: %v", err)
	}
	var config struct {
		MCPServers map[string]map[string]any `json:"mcpServers"`
	}
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("unmarshal Kiro MCP config: %v", err)
	}
	server := config.MCPServers["obstudio"]
	if got := server["url"]; got != mcpURL {
		t.Fatalf("Kiro obstudio URL = %#v, want %q", got, mcpURL)
	}
	for _, field := range []string{"command", "args", "type"} {
		if got, ok := server[field]; ok {
			t.Fatalf("Kiro remote config should remove stale %s field, got %#v", field, got)
		}
	}
	if got := server["headers"].(map[string]any)["X-Observer-Test"]; got != "preserved" {
		t.Fatalf("Kiro headers = %#v, want preserved", server["headers"])
	}
	if got := server["env"].(map[string]any)["OBSERVER_MODE"]; got != "preserved" {
		t.Fatalf("Kiro env = %#v, want preserved", server["env"])
	}
	if got := server["oauth"].(map[string]any)["clientId"]; got != "preserved" {
		t.Fatalf("Kiro oauth = %#v, want preserved", server["oauth"])
	}
	if got := server["oauthScopes"].([]any); len(got) != 1 || got[0] != "observer.read" {
		t.Fatalf("Kiro oauthScopes = %#v, want observer.read", got)
	}
	if got := server["timeout"]; got != float64(45_000) {
		t.Fatalf("Kiro timeout policy = %#v, want 45000", got)
	}
}

func TestConfigureMCPPreservesTypedRemoteSchemaForExistingTargets(t *testing.T) {
	t.Parallel()

	for _, targetName := range []string{"claude-code", "cursor"} {
		targetName := targetName
		t.Run(targetName, func(t *testing.T) {
			t.Parallel()

			configPath := filepath.Join(t.TempDir(), "mcp.json")
			target := targets[targetName].mcpConfig
			target.path = func() string { return configPath }
			if err := configureMCP(target, "/tmp/obstudio", "http://127.0.0.1:3000/mcp"); err != nil {
				t.Fatalf("configureMCP returned error: %v", err)
			}

			data, err := os.ReadFile(configPath)
			if err != nil {
				t.Fatalf("read MCP config: %v", err)
			}
			var config struct {
				MCPServers map[string]map[string]any `json:"mcpServers"`
			}
			if err := json.Unmarshal(data, &config); err != nil {
				t.Fatalf("unmarshal MCP config: %v", err)
			}
			if got := config.MCPServers["obstudio"]["type"]; got != "http" {
				t.Fatalf("%s obstudio type = %#v, want http", targetName, got)
			}
		})
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

func TestCreateSkillSymlinks(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink tests are not reliable on Windows without elevated privileges")
	}
	t.Parallel()

	skillsRoot := t.TempDir()
	obstudioDir := filepath.Join(skillsRoot, "obstudio")

	// Skill dir with SKILL.md -- should get a symlink.
	if err := os.MkdirAll(filepath.Join(obstudioDir, "otel-audit"), 0o755); err != nil {
		t.Fatalf("mkdir otel-audit: %v", err)
	}
	if err := os.WriteFile(filepath.Join(obstudioDir, "otel-audit", "SKILL.md"), []byte("audit"), 0o644); err != nil {
		t.Fatalf("write SKILL.md: %v", err)
	}

	// References dir (no SKILL.md) -- should NOT get a symlink.
	if err := os.MkdirAll(filepath.Join(obstudioDir, "references", "languages"), 0o755); err != nil {
		t.Fatalf("mkdir references: %v", err)
	}
	if err := os.WriteFile(filepath.Join(obstudioDir, "references", "languages", "go.md"), []byte("go ref"), 0o644); err != nil {
		t.Fatalf("write go.md: %v", err)
	}

	// Regular dir without SKILL.md -- should NOT get a symlink.
	if err := os.MkdirAll(filepath.Join(obstudioDir, "internal"), 0o755); err != nil {
		t.Fatalf("mkdir internal: %v", err)
	}

	// Regular file -- should NOT get a symlink.
	if err := os.WriteFile(filepath.Join(obstudioDir, "obstudio"), []byte("bin"), 0o755); err != nil {
		t.Fatalf("write binary: %v", err)
	}

	if err := createSkillSymlinks(skillsRoot, obstudioDir); err != nil {
		t.Fatalf("createSkillSymlinks: %v", err)
	}

	// otel-audit symlink should exist and point to obstudio/otel-audit.
	link := filepath.Join(skillsRoot, "otel-audit")
	dest, err := os.Readlink(link)
	if err != nil {
		t.Fatalf("readlink otel-audit: %v", err)
	}
	if dest != filepath.Join("obstudio", "otel-audit") {
		t.Fatalf("otel-audit symlink target = %q, want %q", dest, filepath.Join("obstudio", "otel-audit"))
	}

	// references dir should NOT have a top-level symlink (inlined per-skill at build time).
	if info, err := os.Lstat(filepath.Join(skillsRoot, "references")); err == nil && info.Mode()&os.ModeSymlink != 0 {
		t.Fatalf("unexpected top-level references symlink")
	}

	// internal dir should NOT have a symlink.
	if _, err := os.Lstat(filepath.Join(skillsRoot, "internal")); !os.IsNotExist(err) {
		t.Fatalf("expected no symlink for internal dir, got err=%v", err)
	}

	// Binary file should NOT have a symlink.
	info, err := os.Lstat(filepath.Join(skillsRoot, "obstudio"))
	if err != nil {
		if !os.IsNotExist(err) && info != nil && info.Mode()&os.ModeSymlink != 0 {
			t.Fatalf("unexpected symlink for obstudio binary")
		}
	}
}

func TestRemoveSkillSymlinks(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink tests are not reliable on Windows without elevated privileges")
	}
	t.Parallel()

	skillsRoot := t.TempDir()
	obstudioDir := filepath.Join(skillsRoot, "obstudio")
	if err := os.MkdirAll(obstudioDir, 0o755); err != nil {
		t.Fatalf("mkdir obstudio: %v", err)
	}

	// Obstudio-managed symlink -- should be removed.
	obstudioLink := filepath.Join(skillsRoot, "otel-audit")
	if err := os.Symlink(filepath.Join("obstudio", "otel-audit"), obstudioLink); err != nil {
		t.Fatalf("create obstudio symlink: %v", err)
	}

	// User-owned symlink pointing elsewhere -- should be preserved.
	userTarget := t.TempDir()
	userLink := filepath.Join(skillsRoot, "my-skill")
	if err := os.Symlink(userTarget, userLink); err != nil {
		t.Fatalf("create user symlink: %v", err)
	}

	// Regular directory -- should be preserved.
	regularDir := filepath.Join(skillsRoot, "regular-dir")
	if err := os.Mkdir(regularDir, 0o755); err != nil {
		t.Fatalf("mkdir regular-dir: %v", err)
	}

	removeSkillSymlinks(skillsRoot, obstudioDir)

	if _, err := os.Lstat(obstudioLink); !os.IsNotExist(err) {
		t.Fatalf("expected obstudio symlink to be removed, got err=%v", err)
	}
	if _, err := os.Lstat(userLink); err != nil {
		t.Fatalf("expected user symlink to be preserved, got err=%v", err)
	}
	if _, err := os.Stat(regularDir); err != nil {
		t.Fatalf("expected regular dir to be preserved, got err=%v", err)
	}
}

func TestReinstallCleansStaleSymlinks(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink tests are not reliable on Windows without elevated privileges")
	}
	t.Parallel()

	skillsRoot := t.TempDir()
	obstudioDir := filepath.Join(skillsRoot, "obstudio")

	// Simulate first install: create obstudio dir with a skill.
	if err := os.MkdirAll(filepath.Join(obstudioDir, "old-skill"), 0o755); err != nil {
		t.Fatalf("mkdir old-skill: %v", err)
	}
	if err := os.WriteFile(filepath.Join(obstudioDir, "old-skill", "SKILL.md"), []byte("old"), 0o644); err != nil {
		t.Fatalf("write old SKILL.md: %v", err)
	}
	if err := createSkillSymlinks(skillsRoot, obstudioDir); err != nil {
		t.Fatalf("first createSkillSymlinks: %v", err)
	}
	if _, err := os.Lstat(filepath.Join(skillsRoot, "old-skill")); err != nil {
		t.Fatalf("expected old-skill symlink after first install: %v", err)
	}

	// Simulate reinstall: remove symlinks, remove dir, create new dir with different skill.
	removeSkillSymlinks(skillsRoot, obstudioDir)
	if err := os.RemoveAll(obstudioDir); err != nil {
		t.Fatalf("remove obstudio dir: %v", err)
	}

	if err := os.MkdirAll(filepath.Join(obstudioDir, "new-skill"), 0o755); err != nil {
		t.Fatalf("mkdir new-skill: %v", err)
	}
	if err := os.WriteFile(filepath.Join(obstudioDir, "new-skill", "SKILL.md"), []byte("new"), 0o644); err != nil {
		t.Fatalf("write new SKILL.md: %v", err)
	}
	if err := createSkillSymlinks(skillsRoot, obstudioDir); err != nil {
		t.Fatalf("second createSkillSymlinks: %v", err)
	}

	// old-skill symlink should be gone.
	if _, err := os.Lstat(filepath.Join(skillsRoot, "old-skill")); !os.IsNotExist(err) {
		t.Fatalf("expected old-skill symlink to be removed after reinstall, got err=%v", err)
	}
	// new-skill symlink should exist.
	if _, err := os.Lstat(filepath.Join(skillsRoot, "new-skill")); err != nil {
		t.Fatalf("expected new-skill symlink after reinstall: %v", err)
	}
}

func TestDetectSharedObserverURLFromStateFile(t *testing.T) {
	t.Parallel()

	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"kind":       "obstudio",
			"apiVersion": "v1",
			"endpoints": map[string]string{
				"mcp": server.URL + "/mcp",
			},
		})
	}))
	defer server.Close()

	statePath := filepath.Join(t.TempDir(), "shared-observer.json")
	err := writeSharedObserverState(statePath, sharedObserverState{
		HealthURL: server.URL,
		MCPURL:    server.URL + "/mcp",
		PID:       42,
	})
	if err != nil {
		t.Fatalf("writeSharedObserverState returned error: %v", err)
	}

	detected, ok := detectSharedObserverURLFromStateFile(statePath, server.Client())
	if !ok {
		t.Fatal("expected state-file discovery to succeed")
	}
	if want := server.URL + "/mcp"; detected != want {
		t.Fatalf("detectSharedObserverURLFromStateFile = %q, want %q", detected, want)
	}
}

func TestClearSharedObserverStateIfOwned(t *testing.T) {
	t.Parallel()

	statePath := filepath.Join(t.TempDir(), "shared-observer.json")
	state := sharedObserverState{
		BaseURL:   "http://127.0.0.1:41234",
		HealthURL: "http://127.0.0.1:41234/api/health",
		MCPURL:    "http://127.0.0.1:41234/mcp",
		PID:       4242,
	}
	if err := writeSharedObserverState(statePath, state); err != nil {
		t.Fatalf("writeSharedObserverState returned error: %v", err)
	}

	if err := clearSharedObserverStateIfOwned(statePath, state); err != nil {
		t.Fatalf("clearSharedObserverStateIfOwned returned error: %v", err)
	}
	if _, err := os.Stat(statePath); !os.IsNotExist(err) {
		t.Fatalf("expected owned state file to be removed, got err=%v", err)
	}
}

func TestClearSharedObserverStateIfOwnedLeavesNewerStateAlone(t *testing.T) {
	t.Parallel()

	statePath := filepath.Join(t.TempDir(), "shared-observer.json")
	owned := sharedObserverState{
		BaseURL:   "http://127.0.0.1:41234",
		HealthURL: "http://127.0.0.1:41234/api/health",
		MCPURL:    "http://127.0.0.1:41234/mcp",
		PID:       4242,
	}
	newer := sharedObserverState{
		BaseURL:   "http://127.0.0.1:42345",
		HealthURL: "http://127.0.0.1:42345/api/health",
		MCPURL:    "http://127.0.0.1:42345/mcp",
		PID:       5252,
	}
	if err := writeSharedObserverState(statePath, newer); err != nil {
		t.Fatalf("writeSharedObserverState returned error: %v", err)
	}

	if err := clearSharedObserverStateIfOwned(statePath, owned); err != nil {
		t.Fatalf("clearSharedObserverStateIfOwned returned error: %v", err)
	}

	got, err := readSharedObserverState(statePath)
	if err != nil {
		t.Fatalf("readSharedObserverState returned error: %v", err)
	}
	if got.PID != newer.PID || got.MCPURL != newer.MCPURL {
		t.Fatalf("shared observer state was unexpectedly removed or replaced: %#v", got)
	}
}

func TestValidateRunConfigRejectsObserverPortOverlappingFixedListeners(t *testing.T) {
	t.Parallel()

	err := validateRunConfig(runConfig{
		host:             "127.0.0.1",
		observerHTTPPort: "4318",
		otlpHTTPPort:     "4318",
		otlpGRPCPort:     "4317",
	})
	if err == nil {
		t.Fatal("expected validateRunConfig to reject overlapping listener ports")
	}
	if !strings.Contains(err.Error(), "--otlp-http-port cannot use port 4318") {
		t.Fatalf("unexpected overlap error: %v", err)
	}
}

func TestBuildSharedObserverStateNormalizesWildcardHost(t *testing.T) {
	t.Parallel()

	state := buildSharedObserverState("0.0.0.0", "41234")
	if state.BaseURL != "http://127.0.0.1:41234" {
		t.Fatalf("BaseURL = %q, want %q", state.BaseURL, "http://127.0.0.1:41234")
	}
	if state.HealthURL != "http://127.0.0.1:41234/api/health" {
		t.Fatalf("HealthURL = %q, want %q", state.HealthURL, "http://127.0.0.1:41234/api/health")
	}
	if state.MCPURL != "http://127.0.0.1:41234/mcp" {
		t.Fatalf("MCPURL = %q, want %q", state.MCPURL, "http://127.0.0.1:41234/mcp")
	}
}

func TestInstallSmokeInstallsBinaryAndAcceptsOTLP(t *testing.T) {
	observerRoot := observerModuleRoot(t)
	tempRoot := t.TempDir()
	bundleDir := filepath.Join(tempRoot, "bundle")
	homeDir := filepath.Join(tempRoot, "home")
	binaryName := smokeBinaryName()
	weaverName := installedWeaverName(filepath.Join(bundleDir, binaryName))
	bundledBinary := filepath.Join(bundleDir, binaryName)
	bundledWeaver := filepath.Join(bundleDir, weaverName)

	if err := os.MkdirAll(bundleDir, 0o755); err != nil {
		t.Fatalf("mkdir bundle dir: %v", err)
	}
	if err := os.MkdirAll(homeDir, 0o755); err != nil {
		t.Fatalf("mkdir home dir: %v", err)
	}

	repoRoot := filepath.Dir(observerRoot)
	isolatedObserverRoot := copySmokeRepoForBuild(t, repoRoot, observerRoot, filepath.Join(tempRoot, "source"))
	isolatedRepoRoot := filepath.Dir(isolatedObserverRoot)
	if err := buildutil.StageEmbeddedSkills(isolatedRepoRoot, isolatedObserverRoot); err != nil {
		t.Fatalf("stage embedded skills: %v", err)
	}
	expectedSkills := smokeSkillContents(t, filepath.Join(isolatedRepoRoot, "skills"))

	build := exec.Command("go", "build", "-o", bundledBinary, "./cmd/obstudio")
	build.Dir = isolatedObserverRoot
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build smoke obstudio binary: %v\n%s", err, strings.TrimSpace(string(output)))
	}
	if err := copyFile(bundledBinary, bundledWeaver); err != nil {
		t.Fatalf("bundle sibling weaver runtime: %v", err)
	}
	if err := os.Chmod(bundledWeaver, 0o755); err != nil {
		t.Fatalf("chmod sibling weaver runtime: %v", err)
	}

	install := exec.Command(bundledBinary, "install", "--target", "codex,claude-code,cursor,kiro")
	install.Env = append(os.Environ(), smokeHomeEnv(homeDir)...)
	if output, err := install.CombinedOutput(); err != nil {
		t.Fatalf("run obstudio install smoke test: %v\n%s", err, strings.TrimSpace(string(output)))
	}

	installedDirs := map[string]string{}
	for _, targetName := range []string{"codex", "claude-code", "cursor", "kiro"} {
		installedDir := targets[targetName].skillsDir(homeDir)
		installedDirs[targetName] = installedDir
		assertSmokeTargetInstalled(t, targetName, installedDir, binaryName, weaverName, expectedSkills)
	}

	installedDir := installedDirs["codex"]
	installedBinary := filepath.Join(installedDir, binaryName)

	configPath := filepath.Join(homeDir, ".codex", "config.toml")
	config, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("read generated codex config: %v", err)
	}
	configText := string(config)
	for _, want := range []string{
		codexManagedBlockStart,
		"[mcp_servers.obstudio]",
		"enabled = true",
		codexManagedBlockEnd,
	} {
		if !strings.Contains(configText, want) {
			t.Fatalf("expected generated codex config to contain %q, got:\n%s", want, configText)
		}
	}
	hasURLConfig := strings.Contains(configText, `url = "http://127.0.0.1:3000/mcp"`)
	hasCommandConfig := strings.Contains(configText, fmt.Sprintf("command = %q", installedBinary)) &&
		strings.Contains(configText, "args = []")
	if !hasURLConfig && !hasCommandConfig {
		t.Fatalf("expected generated codex config to contain either local URL or installed command, got:\n%s", configText)
	}
	assertSmokeJSONMCPConfig(t, filepath.Join(homeDir, ".claude.json"), filepath.Join(installedDirs["claude-code"], binaryName))
	assertSmokeJSONMCPConfig(t, filepath.Join(homeDir, ".cursor", "mcp.json"), filepath.Join(installedDirs["cursor"], binaryName))
	assertSmokeJSONMCPConfig(t, filepath.Join(homeDir, ".kiro", "settings", "mcp.json"), filepath.Join(installedDirs["kiro"], binaryName))

	observerPort := pickSmokePort(t)
	otlpHTTPPort := pickSmokePort(t)
	otlpGRPCPort := pickSmokePort(t)
	baseURL := fmt.Sprintf("http://127.0.0.1:%d", observerPort)
	otlpHTTPURL := fmt.Sprintf("http://127.0.0.1:%d", otlpHTTPPort)

	run := exec.Command(installedBinary)
	runEnv := append(os.Environ(), smokeHomeEnv(homeDir)...)
	runEnv = append(runEnv,
		fmt.Sprintf("PORT=%d", observerPort),
		fmt.Sprintf("OTLP_HTTP_PORT=%d", otlpHTTPPort),
		fmt.Sprintf("OTLP_GRPC_PORT=%d", otlpGRPCPort),
	)
	run.Env = runEnv
	var logs bytes.Buffer
	run.Stdout = &logs
	run.Stderr = &logs
	if err := run.Start(); err != nil {
		t.Fatalf("start installed obstudio binary: %v", err)
	}

	done := make(chan error, 1)
	go func() {
		done <- run.Wait()
	}()
	defer stopSmokeProcess(run, done)

	client := &http.Client{Timeout: time.Second}
	waitForSmokeHealth(t, client, baseURL+"/api/health", done, &logs, 10*time.Second)

	var health struct {
		Kind      string            `json:"kind"`
		Endpoints map[string]string `json:"endpoints"`
	}
	if status := doSmokeJSONRequest(t, client, http.MethodGet, baseURL+"/api/health", "", nil, &health); status != http.StatusOK {
		t.Fatalf("health endpoint returned %d", status)
	}
	if health.Kind != "obstudio" {
		t.Fatalf("health kind = %q, want %q", health.Kind, "obstudio")
	}
	if got := health.Endpoints["otlpHttp"]; got != otlpHTTPURL {
		t.Fatalf("health otlpHttp = %q, want %q", got, otlpHTTPURL)
	}
	if got := health.Endpoints["otlpGrpc"]; got != fmt.Sprintf("127.0.0.1:%d", otlpGRPCPort) {
		t.Fatalf("health otlpGrpc = %q, want %q", got, fmt.Sprintf("127.0.0.1:%d", otlpGRPCPort))
	}

	if status := doSmokeJSONRequest(t, client, http.MethodDelete, baseURL+"/api/data", "", nil, nil); status != http.StatusOK {
		t.Fatalf("clear data endpoint returned %d", status)
	}

	tracePayload := `{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"install-smoke-test"}}]},"scopeSpans":[{"scope":{"name":"install-smoke"},"spans":[{"traceId":"0af7651916cd43dd8448eb211c80319c","spanId":"b7ad6b7169203331","name":"installed-binary-span","kind":1,"startTimeUnixNano":1000000000000000000,"endTimeUnixNano":1000000001000000000,"status":{"code":0},"attributes":[]}]}]}]}`
	if status := doSmokeJSONRequest(t, client, http.MethodPost, otlpHTTPURL+"/v1/traces", tracePayload, map[string]string{
		"Content-Type": "application/json",
	}, nil); status != http.StatusOK {
		t.Fatalf("otlp ingest endpoint returned %d", status)
	}

	var stats struct {
		SpanCount  int `json:"spanCount"`
		TraceCount int `json:"traceCount"`
	}
	waitForSmokeStats(t, client, baseURL+"/api/query/stats", done, &logs, 10*time.Second, &stats)
	if stats.SpanCount != 1 {
		t.Fatalf("stats spanCount = %d, want 1", stats.SpanCount)
	}
	if stats.TraceCount != 1 {
		t.Fatalf("stats traceCount = %d, want 1", stats.TraceCount)
	}

	var traces []struct {
		ServiceName string `json:"serviceName"`
		TraceID     string `json:"traceId"`
	}
	if status := doSmokeJSONRequest(t, client, http.MethodGet, baseURL+"/api/query/traces?limit=5", "", nil, &traces); status != http.StatusOK {
		t.Fatalf("trace query endpoint returned %d", status)
	}
	found := false
	for _, trace := range traces {
		if trace.TraceID == "0af7651916cd43dd8448eb211c80319c" || trace.ServiceName == "install-smoke-test" {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("expected ingested trace to be queryable, got %#v", traces)
	}
}

func observerModuleRoot(t *testing.T) string {
	t.Helper()

	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve install_test.go path")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "..", ".."))
}

func copySmokeRepoForBuild(t *testing.T, repoRoot, observerRoot, dstRoot string) string {
	t.Helper()

	isolatedObserverRoot := filepath.Join(dstRoot, "observer")
	copySmokeDir(t, observerRoot, isolatedObserverRoot, func(rel string, d fs.DirEntry) bool {
		return d.IsDir() && (rel == filepath.Join("cmd", "obstudio", "_skills") || rel == filepath.Join("client", "node_modules"))
	})
	copySmokeDir(t, filepath.Join(repoRoot, "skills"), filepath.Join(dstRoot, "skills"), nil)

	examplesSrc := filepath.Join(repoRoot, "docs", "examples.md")
	if _, err := os.Stat(examplesSrc); err == nil {
		if err := copyFile(examplesSrc, filepath.Join(dstRoot, "docs", "examples.md")); err != nil {
			t.Fatalf("copy examples.md: %v", err)
		}
	} else if !os.IsNotExist(err) {
		t.Fatalf("stat examples.md: %v", err)
	}

	return isolatedObserverRoot
}

func copySmokeDir(t *testing.T, src, dst string, skip func(string, fs.DirEntry) bool) {
	t.Helper()

	if err := filepath.WalkDir(src, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return os.MkdirAll(dst, 0o755)
		}
		if skip != nil && skip(rel, d) {
			if d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}

		target := filepath.Join(dst, rel)
		if d.IsDir() {
			info, err := d.Info()
			if err != nil {
				return err
			}
			return os.MkdirAll(target, info.Mode().Perm())
		}
		return copyFile(path, target)
	}); err != nil {
		t.Fatalf("copy %s to %s: %v", src, dst, err)
	}
}

func smokeBinaryName() string {
	if runtime.GOOS == "windows" {
		return "obstudio.exe"
	}
	return "obstudio"
}

func smokeHomeEnv(homeDir string) []string {
	env := []string{
		"HOME=" + homeDir,
		"USERPROFILE=" + homeDir,
		disableSharedObserverDetectionEnv + "=1",
	}
	if runtime.GOOS == "windows" {
		volume := filepath.VolumeName(homeDir)
		if volume != "" {
			env = append(env,
				"HOMEDRIVE="+volume,
				"HOMEPATH="+strings.TrimPrefix(homeDir, volume),
			)
		}
	}
	return env
}

func smokeSkillContents(t *testing.T, skillsDir string) map[string][]byte {
	t.Helper()

	entries, err := os.ReadDir(skillsDir)
	if err != nil {
		t.Fatalf("read source skills: %v", err)
	}
	expected := map[string][]byte{}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		skillPath := filepath.Join(skillsDir, entry.Name(), "SKILL.md")
		content, err := os.ReadFile(skillPath)
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			t.Fatalf("read source skill %s: %v", skillPath, err)
		}
		expected[entry.Name()] = content
	}
	if len(expected) == 0 {
		t.Fatal("expected source skills to contain at least one SKILL.md")
	}
	return expected
}

func assertSmokeTargetInstalled(t *testing.T, targetName, installedDir, binaryName, weaverName string, expectedSkills map[string][]byte) {
	t.Helper()

	for _, name := range []string{binaryName, weaverName} {
		path := filepath.Join(installedDir, name)
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("%s: expected installed file at %s: %v", targetName, path, err)
		}
	}

	skillsRoot := filepath.Dir(installedDir)
	for skillName, expectedContent := range expectedSkills {
		skillPath := filepath.Join(installedDir, skillName, "SKILL.md")
		installedContent, err := os.ReadFile(skillPath)
		if err != nil {
			t.Fatalf("%s: read installed skill at %s: %v", targetName, skillPath, err)
		}
		if !bytes.Equal(installedContent, expectedContent) {
			t.Fatalf("%s: installed skill %s does not match embedded source", targetName, skillName)
		}
		linkPath := filepath.Join(skillsRoot, skillName)
		linkTarget, err := os.Readlink(linkPath)
		if err != nil {
			t.Fatalf("%s: read discovery link %s: %v", targetName, linkPath, err)
		}
		if want := filepath.Join("obstudio", skillName); linkTarget != want {
			t.Fatalf("%s: discovery link %s = %q, want %q", targetName, linkPath, linkTarget, want)
		}
	}
	t.Logf("%s: verified %d copied skills, discovery links, binary, and Weaver runtime", targetName, len(expectedSkills))
}

func assertSmokeJSONMCPConfig(t *testing.T, configPath, installedBinary string) {
	t.Helper()

	data, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("read generated MCP config %s: %v", configPath, err)
	}
	var config struct {
		MCPServers map[string]map[string]any `json:"mcpServers"`
	}
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("parse generated MCP config %s: %v", configPath, err)
	}
	server, ok := config.MCPServers["obstudio"]
	if !ok {
		t.Fatalf("generated MCP config %s has no obstudio server", configPath)
	}
	hasURLConfig := server["url"] == "http://127.0.0.1:3000/mcp"
	hasCommandConfig := server["command"] == installedBinary
	if !hasURLConfig && !hasCommandConfig {
		t.Fatalf("generated MCP config %s has neither shared URL nor installed command: %#v", configPath, server)
	}
}

func pickSmokePort(t *testing.T) int {
	t.Helper()

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("pick free port: %v", err)
	}
	defer listener.Close()

	addr, ok := listener.Addr().(*net.TCPAddr)
	if !ok {
		t.Fatalf("expected TCP listener address, got %T", listener.Addr())
	}
	return addr.Port
}

func stopSmokeProcess(cmd *exec.Cmd, done <-chan error) {
	if cmd.Process != nil {
		_ = cmd.Process.Kill()
	}
	select {
	case <-done:
	case <-time.After(2 * time.Second):
	}
}

func waitForSmokeHealth(t *testing.T, client *http.Client, url string, done <-chan error, logs *bytes.Buffer, timeout time.Duration) {
	t.Helper()

	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		select {
		case err := <-done:
			t.Fatalf("installed obstudio exited before health check succeeded: %v\n%s", err, strings.TrimSpace(logs.String()))
		default:
		}

		resp, err := client.Get(url)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				return
			}
		}
		time.Sleep(200 * time.Millisecond)
	}

	t.Fatalf("installed obstudio did not become healthy within %s\n%s", timeout, strings.TrimSpace(logs.String()))
}

func waitForSmokeStats(t *testing.T, client *http.Client, url string, done <-chan error, logs *bytes.Buffer, timeout time.Duration, stats *struct {
	SpanCount  int `json:"spanCount"`
	TraceCount int `json:"traceCount"`
}) {
	t.Helper()

	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		select {
		case err := <-done:
			t.Fatalf("installed obstudio exited before stats query succeeded: %v\n%s", err, strings.TrimSpace(logs.String()))
		default:
		}

		if status := doSmokeJSONRequest(t, client, http.MethodGet, url, "", nil, stats); status == http.StatusOK && stats.SpanCount == 1 && stats.TraceCount == 1 {
			return
		}
		time.Sleep(200 * time.Millisecond)
	}

	t.Fatalf("installed obstudio did not report ingested stats within %s\n%s", timeout, strings.TrimSpace(logs.String()))
}

func doSmokeJSONRequest(t *testing.T, client *http.Client, method, url, body string, headers map[string]string, target any) int {
	t.Helper()

	var requestBody io.Reader
	if body != "" {
		requestBody = strings.NewReader(body)
	}
	req, err := http.NewRequest(method, url, requestBody)
	if err != nil {
		t.Fatalf("build %s request %s: %v", method, url, err)
	}
	for key, value := range headers {
		req.Header.Set(key, value)
	}

	resp, err := client.Do(req)
	if err != nil {
		t.Fatalf("%s %s: %v", method, url, err)
	}
	defer resp.Body.Close()

	if target == nil {
		io.Copy(io.Discard, resp.Body)
		return resp.StatusCode
	}
	if err := json.NewDecoder(resp.Body).Decode(target); err != nil {
		t.Fatalf("decode %s %s response: %v", method, url, err)
	}
	return resp.StatusCode
}

func TestMapTargetsToConnectorIDEs(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name    string
		targets []string
		want    []string
	}{
		{name: "cursor maps to cursor", targets: []string{"cursor"}, want: []string{"cursor"}},
		{name: "claude-code maps to claude-code", targets: []string{"claude-code"}, want: []string{"claude-code"}},
		{name: "codex maps to codex", targets: []string{"codex"}, want: []string{"codex"}},
		{name: "kiro has no connector equivalent", targets: []string{"kiro"}, want: []string{}},
		{
			name:    "preserves order and drops kiro from a mixed list",
			targets: []string{"kiro", "cursor", "codex"},
			want:    []string{"cursor", "codex"},
		},
		{name: "empty input yields empty output", targets: []string{}, want: []string{}},
	}

	for _, tc := range tests {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			got := mapTargetsToConnectorIDEs(tc.targets)
			if joined, wantJoined := strings.Join(got, ","), strings.Join(tc.want, ","); joined != wantJoined {
				t.Fatalf("mapTargetsToConnectorIDEs(%v) = %q, want %q", tc.targets, joined, wantJoined)
			}
		})
	}
}

func TestShouldConnectRemoteO11y(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name          string
		flagSet       bool
		isInteractive bool
		answer        string
		want          bool
	}{
		{name: "flag set wins even on a non-interactive session", flagSet: true, isInteractive: false, want: true},
		{name: "flag set wins even with no answer", flagSet: true, isInteractive: true, answer: "n", want: true},
		{name: "non-interactive with no flag skips silently", flagSet: false, isInteractive: false, want: false},
		{name: "interactive yes answer", flagSet: false, isInteractive: true, answer: "y\n", want: true},
		{name: "interactive full yes answer", flagSet: false, isInteractive: true, answer: "yes", want: true},
		{name: "interactive case-insensitive yes", flagSet: false, isInteractive: true, answer: "Y", want: true},
		{name: "interactive no answer", flagSet: false, isInteractive: true, answer: "n", want: false},
		{name: "interactive empty answer defaults to no", flagSet: false, isInteractive: true, answer: "", want: false},
	}

	for _, tc := range tests {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			got := shouldConnectRemoteO11y(tc.flagSet, tc.isInteractive, tc.answer)
			if got != tc.want {
				t.Fatalf("shouldConnectRemoteO11y(%v, %v, %q) = %v, want %v", tc.flagSet, tc.isInteractive, tc.answer, got, tc.want)
			}
		})
	}
}

func TestRemoteO11yConnectArgs(t *testing.T) {
	t.Parallel()

	got := remoteO11yConnectArgs([]string{"cursor", "codex"})
	want := []string{"-y", "@splunk/o11y-mcp-connect", "connect", "--ide", "cursor,codex"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("remoteO11yConnectArgs() = %v, want %v", got, want)
	}
}

func TestMaybeConnectRemoteO11ySkipsKiroOnlyInstallsWithNote(t *testing.T) {
	t.Parallel()

	var stdout strings.Builder
	if err := maybeConnectRemoteO11y([]string{"kiro"}, false, strings.NewReader(""), &stdout); err != nil {
		t.Fatalf("maybeConnectRemoteO11y returned error: %v", err)
	}
	if !strings.Contains(stdout.String(), "doesn't support kiro") {
		t.Fatalf("expected a kiro fallback note, got: %q", stdout.String())
	}
}

func TestMaybeConnectRemoteO11ySkipsNonInteractiveWithoutFlag(t *testing.T) {
	t.Parallel()

	var stdout strings.Builder
	if err := maybeConnectRemoteO11y([]string{"cursor"}, false, strings.NewReader(""), &stdout); err != nil {
		t.Fatalf("maybeConnectRemoteO11y returned error: %v", err)
	}
	if stdout.String() != "" {
		t.Fatalf("expected no output when skipping non-interactively, got: %q", stdout.String())
	}
}

func TestReadLineLeavesLaterInputUntouched(t *testing.T) {
	t.Parallel()

	// Regression test: a bufio.Reader wrapping stdin can buffer past the
	// first newline, silently consuming input meant for a later reader of
	// the same stdin (here, the npx child process). readLine must consume
	// exactly one line and leave the rest of r untouched.
	r := strings.NewReader("y\nus0\nsekrit-token\n")

	line, err := readLine(r)
	if err != nil {
		t.Fatalf("readLine returned error: %v", err)
	}
	if line != "y" {
		t.Fatalf("readLine() = %q, want %q", line, "y")
	}

	rest, err := io.ReadAll(r)
	if err != nil {
		t.Fatalf("reading remainder failed: %v", err)
	}
	if string(rest) != "us0\nsekrit-token\n" {
		t.Fatalf("remaining input = %q, want %q", string(rest), "us0\nsekrit-token\n")
	}
}

func TestReadLineHandlesMissingTrailingNewline(t *testing.T) {
	t.Parallel()

	line, err := readLine(strings.NewReader("y"))
	if line != "y" {
		t.Fatalf("readLine() = %q, want %q", line, "y")
	}
	if err == nil {
		t.Fatalf("expected an error (EOF) when the input has no trailing newline")
	}
}
