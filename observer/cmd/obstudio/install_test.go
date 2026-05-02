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
