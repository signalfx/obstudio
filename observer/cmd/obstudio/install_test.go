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
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/buildutil"
	"github.com/spf13/cobra"
)

const (
	testHealthProofSecret      = "QkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkI"
	alternateHealthProofSecret = "Q0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0M"
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

func TestWindsurfTargetUsesCodiumMCPConfig(t *testing.T) {
	t.Parallel()

	target, ok := targets["windsurf"]
	if !ok {
		t.Fatal("expected windsurf target to exist")
	}

	if path := target.mcpConfig.path(); !strings.HasSuffix(path, filepath.Join(".codeium", "windsurf", "mcp_config.json")) {
		t.Fatalf("expected Windsurf MCP config path to end with .codeium/windsurf/mcp_config.json, got %q", path)
	}
	if skillsDir := target.skillsDir("/home/test"); !strings.HasSuffix(skillsDir, filepath.Join(".codeium", "windsurf", "skills", "obstudio")) {
		t.Fatalf("expected Windsurf skills path to end with .codeium/windsurf/skills/obstudio, got %q", skillsDir)
	}
	if !target.mcpConfig.includeRemoteType {
		t.Fatal("expected Windsurf MCP config to have includeRemoteType=true")
	}
}

func TestCopilotTargetUsesVSCodeUserMCPJSON(t *testing.T) {
	t.Parallel()

	target, ok := targets["copilot"]
	if !ok {
		t.Fatal("expected copilot target to exist")
	}

	if path := target.mcpConfig.path(); !strings.HasSuffix(path, filepath.Join("Code", "User", "mcp.json")) {
		t.Fatalf("expected Copilot MCP config path to end with Code/User/mcp.json, got %q", path)
	}
	if target.mcpConfig.serversKey != "servers" {
		t.Fatalf("expected Copilot MCP config rootKey to be %q, got %q", "servers", target.mcpConfig.serversKey)
	}
	if target.skillsDir != nil {
		t.Fatal("expected Copilot to have no skillsDir")
	}
	if !target.mcpConfig.includeLocalType {
		t.Fatal("expected Copilot MCP config to have includeLocalType=true")
	}
	if !target.mcpConfig.includeRemoteType {
		t.Fatal("expected Copilot MCP config to have includeRemoteType=true")
	}
}

func TestConfigureMCPCopilotLocalEmitsStdioType(t *testing.T) {
	t.Parallel()

	configPath := filepath.Join(t.TempDir(), "mcp.json")
	target := targets["copilot"].mcpConfig
	target.path = func() string { return configPath }

	if err := configureMCP(target, "/usr/local/bin/obstudio", ""); err != nil {
		t.Fatalf("configureMCP returned error: %v", err)
	}

	data, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("read Copilot MCP config: %v", err)
	}
	var config struct {
		Servers map[string]map[string]any `json:"servers"`
	}
	if err := json.Unmarshal(data, &config); err != nil {
		t.Fatalf("unmarshal Copilot MCP config: %v", err)
	}
	server := config.Servers["obstudio"]
	if server == nil {
		t.Fatalf("obstudio entry missing from servers: %#v", config.Servers)
	}
	if got := server["type"]; got != "stdio" {
		t.Fatalf("Copilot local config type = %#v, want %q", got, "stdio")
	}
	if got := server["command"]; got != "/usr/local/bin/obstudio" {
		t.Fatalf("Copilot local config command = %#v, want /usr/local/bin/obstudio", got)
	}
	if _, ok := server["url"]; ok {
		t.Fatalf("Copilot local config should not include url field, got %#v", server["url"])
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

func TestInstallCommandHasNoConnectRemoteO11yFlag(t *testing.T) {
	t.Parallel()

	cmd := newInstallCmd()
	if flag := cmd.Flags().Lookup("connect-remote-o11y"); flag != nil {
		t.Fatalf("expected --connect-remote-o11y to be removed, but flag is still registered: %+v", flag)
	}
}

func TestTokenTelemetryIsExplicitCommandNotInstallSideEffect(t *testing.T) {
	t.Parallel()

	install := newInstallCmd()
	if flag := install.Flags().Lookup("token-telemetry-endpoint"); flag != nil {
		t.Fatal("install must not configure provider token telemetry")
	}
	command := newTokenTelemetryCommand()
	for _, name := range []string{"enable", "disable", "status"} {
		child, _, err := command.Find([]string{name})
		if err != nil || child == nil || child.Name() != name {
			t.Fatalf("expected token-telemetry %s command, got command=%v err=%v", name, child, err)
		}
	}
}

func TestRunTokenTelemetryTargetsContinuesAfterProviderFailure(t *testing.T) {
	t.Parallel()

	command := &cobra.Command{}
	var output bytes.Buffer
	command.SetOut(&output)
	visited := make([]string, 0, 2)
	err := runTokenTelemetryTargets(command, []string{"codex", "claude-code"}, "enable", func(target string) (tokenTelemetryResult, error) {
		visited = append(visited, target)
		if target == "codex" {
			return tokenTelemetryResult{}, errors.New("user-owned exporter conflict")
		}
		return tokenTelemetryResult{Target: target, State: "enabled-managed", ConfigPath: "/tmp/settings.json"}, nil
	})
	if err == nil || !strings.Contains(err.Error(), "enable codex token telemetry") {
		t.Fatalf("runTokenTelemetryTargets() error = %v", err)
	}
	if got := strings.Join(visited, ","); got != "codex,claude-code" {
		t.Fatalf("visited targets = %q, want both providers", got)
	}
	if !strings.Contains(output.String(), "claude-code: enabled-managed") {
		t.Fatalf("successful provider output missing: %q", output.String())
	}
}

func TestTokenTelemetryConfigPathsRespectProviderHomes(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	codexHome := filepath.Join(root, "custom-codex")
	claudeHome := filepath.Join(root, "custom-claude")
	values := map[string]string{
		"CODEX_HOME":        codexHome,
		"CLAUDE_CONFIG_DIR": claudeHome,
	}
	lookup := func(key string) (string, bool) {
		value, ok := values[key]
		return value, ok
	}
	defaultHome := filepath.Join(root, "home")
	if got := codexTokenTelemetryConfigPath(defaultHome, lookup); got != filepath.Join(codexHome, "config.toml") {
		t.Fatalf("Codex config path = %q", got)
	}
	if got := claudeTokenTelemetryConfigPath(defaultHome, lookup); got != filepath.Join(claudeHome, "settings.json") {
		t.Fatalf("Claude config path = %q", got)
	}
	if got := codexTokenTelemetryConfigPath(defaultHome, nil); got != filepath.Join(defaultHome, ".codex", "config.toml") {
		t.Fatalf("default Codex config path = %q", got)
	}
}

func TestTokenTelemetryStatePathResolvesOverridesFromUserHome(t *testing.T) {
	home := t.TempDir()
	for raw, want := range map[string]string{
		filepath.Join("state", "token-telemetry.json"): filepath.Join(home, "state", "token-telemetry.json"),
		"~/custom-token-telemetry.json":                filepath.Join(home, "custom-token-telemetry.json"),
	} {
		if got := resolveTokenTelemetryStatePath(raw, home); got != want {
			t.Fatalf("resolve token telemetry state %q = %q, want %q", raw, got, want)
		}
	}
}

func TestTokenTelemetryConfigPathIdentityUsesWindowsCaseFolding(t *testing.T) {
	upper := `C:\Users\Example\.codex\config.toml`
	lower := `c:\users\example\.CODEX\CONFIG.TOML`
	if !sameTokenTelemetryConfigPathForOS(upper, lower, "windows") {
		t.Fatal("Windows config paths differing only by case were not treated as identical")
	}
	if sameTokenTelemetryConfigPathForOS(upper, lower, "linux") {
		t.Fatal("case-sensitive config paths were incorrectly treated as identical")
	}
}

func TestTokenTelemetryCommandCodexEnableStatusDisable(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", "token-telemetry.json")
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("CODEX_HOME", "")
	t.Setenv("OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH", statePath)

	run := func(args ...string) string {
		t.Helper()
		command := newTokenTelemetryCommand()
		var output bytes.Buffer
		command.SetOut(&output)
		command.SetErr(&output)
		command.SetArgs(args)
		if err := command.Execute(); err != nil {
			t.Fatalf("token-telemetry %s: %v\n%s", strings.Join(args, " "), err, output.String())
		}
		return output.String()
	}

	if output := run("enable", "--target", "codex", "--repository-correlation", "path"); !strings.Contains(output, "codex: enabled-managed") || !strings.Contains(output, "repository correlation: path") {
		t.Fatalf("enable output = %q", output)
	}
	ownership, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		t.Fatalf("read token telemetry state: %v", err)
	}
	correlation := ownership.RepositoryCorrelation["codex"]
	if correlation.Mode != "path" || correlation.Endpoint != defaultTokenTelemetryEndpoint {
		t.Fatalf("repository correlation state = %+v", correlation)
	}
	stateInfo, err := os.Stat(statePath)
	if err != nil {
		t.Fatalf("stat Codex ownership state: %v", err)
	}
	if stateInfo.Mode().Perm() != 0o600 {
		t.Fatalf("Codex ownership mode = %o, want 600", stateInfo.Mode().Perm())
	}
	if output := run("status", "--target", "codex"); !strings.Contains(output, "codex: enabled-managed") || !strings.Contains(output, "repository correlation: path") {
		t.Fatalf("status output = %q", output)
	}
	if output := run("disable", "--target", "codex"); !strings.Contains(output, "codex: disabled") || !strings.Contains(output, "repository correlation: off") {
		t.Fatalf("disable output = %q", output)
	}
	configPath := filepath.Join(home, ".codex", "config.toml")
	data, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("read Codex config: %v", err)
	}
	if len(data) != 0 {
		t.Fatalf("Codex config was not cleaned: %q", data)
	}
	if _, err := os.Stat(statePath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("Codex ownership state was not cleaned: %v", err)
	}
}

func TestTokenTelemetryEnableCreatesPrivateProviderConfigs(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows does not expose Unix permission bits")
	}
	for _, target := range tokenTelemetryTargets {
		t.Run(target, func(t *testing.T) {
			home := t.TempDir()
			statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
			if _, err := enableAgentTokenTelemetry(target, home, statePath, defaultTokenTelemetryEndpoint, nil); err != nil {
				t.Fatalf("enable %s token telemetry: %v", target, err)
			}
			configPath := codexTokenTelemetryConfigPath(home, nil)
			if target == "claude-code" {
				configPath = claudeTokenTelemetryConfigPath(home, nil)
			}
			info, err := os.Stat(configPath)
			if err != nil {
				t.Fatalf("stat %s config: %v", target, err)
			}
			if mode := info.Mode().Perm(); mode != 0o600 {
				t.Fatalf("new %s config mode = %#o, want 0600", target, mode)
			}
		})
	}
}

func TestTokenTelemetryEnableDefaultsToPathAndPreservesRecordedMode(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", "token-telemetry.json")
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("CODEX_HOME", "")
	t.Setenv("OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH", statePath)

	run := func(args ...string) string {
		t.Helper()
		command := newTokenTelemetryCommand()
		var output bytes.Buffer
		command.SetOut(&output)
		command.SetErr(&output)
		command.SetArgs(args)
		if err := command.Execute(); err != nil {
			t.Fatalf("token-telemetry %s: %v\n%s", strings.Join(args, " "), err, output.String())
		}
		return output.String()
	}
	assertMode := func(target, want string) {
		t.Helper()
		state, err := readTokenTelemetryOwnership(statePath)
		if err != nil {
			t.Fatalf("read token telemetry state: %v", err)
		}
		correlation, ok := state.RepositoryCorrelation[target]
		if !ok || correlation.Mode != want {
			t.Fatalf("%s repository correlation = %+v, present %t, want %q", target, correlation, ok, want)
		}
	}

	if output := run("enable", "--target", "codex"); !strings.Contains(output, "repository correlation: path") {
		t.Fatalf("default enable output = %q", output)
	}
	assertMode("codex", "path")

	if output := run("enable", "--target", "codex", "--repository-correlation", "path"); !strings.Contains(output, "repository correlation: path") {
		t.Fatalf("path enable output = %q", output)
	}
	if output := run("enable", "--target", "codex,claude-code"); strings.Count(output, "repository correlation:") != 2 {
		t.Fatalf("mixed-target enable output = %q", output)
	}
	assertMode("codex", "path")
	assertMode("claude-code", "path")

	if output := run("enable", "--target", "codex", "--repository-correlation", "off"); !strings.Contains(output, "repository correlation: off") {
		t.Fatalf("off enable output = %q", output)
	}
	if output := run("enable", "--target", "codex"); !strings.Contains(output, "repository correlation: off") {
		t.Fatalf("preserved off output = %q", output)
	}
	assertMode("codex", "off")
}

func TestTokenTelemetryOwnershipWriteFailureRollsBackProviderConfigAndCorrelation(t *testing.T) {
	endpoint := defaultTokenTelemetryEndpoint
	writeFailure := errors.New("injected ownership write failure")
	failingWriter := func(string, tokenTelemetryOwnership) error { return writeFailure }

	for _, target := range tokenTelemetryTargets {
		t.Run(target, func(t *testing.T) {
			home := t.TempDir()
			statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
			configPath := codexTokenTelemetryConfigPath(home, nil)
			initial := []byte("model = \"gpt-5\"\n")
			if target == "claude-code" {
				configPath = claudeTokenTelemetryConfigPath(home, nil)
				initial = []byte("{\n  \"model\": \"sonnet\"\n}\n")
			}
			if err := os.MkdirAll(filepath.Dir(configPath), 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(configPath, initial, 0o600); err != nil {
				t.Fatal(err)
			}

			_, err := enableAgentTokenTelemetryWithOwnershipMutation(
				target,
				home,
				statePath,
				endpoint,
				nil,
				setRepositoryCorrelationMutation(target, endpoint, "path"),
				failingWriter,
			)
			if !errors.Is(err, writeFailure) {
				t.Fatalf("enable ownership write error = %v, want %v", err, writeFailure)
			}
			if got, readErr := os.ReadFile(configPath); readErr != nil || !bytes.Equal(got, initial) {
				t.Fatalf("failed enable did not restore provider config: got %q, err %v", got, readErr)
			}
			if _, statErr := os.Stat(statePath); !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("failed enable committed ownership or correlation state: %v", statErr)
			}

			if _, err := enableAgentTokenTelemetryWithOwnershipMutation(
				target,
				home,
				statePath,
				endpoint,
				nil,
				setRepositoryCorrelationMutation(target, endpoint, "path"),
				writeTokenTelemetryOwnership,
			); err != nil {
				t.Fatalf("prepare enabled provider: %v", err)
			}
			configuredBefore, err := os.ReadFile(configPath)
			if err != nil {
				t.Fatal(err)
			}
			stateBefore, err := os.ReadFile(statePath)
			if err != nil {
				t.Fatal(err)
			}

			_, err = disableAgentTokenTelemetryWithOwnershipMutation(
				target,
				home,
				statePath,
				nil,
				removeRepositoryCorrelationMutation(target),
				failingWriter,
			)
			if !errors.Is(err, writeFailure) {
				t.Fatalf("disable ownership write error = %v, want %v", err, writeFailure)
			}
			if got, readErr := os.ReadFile(configPath); readErr != nil || !bytes.Equal(got, configuredBefore) {
				t.Fatalf("failed disable did not restore provider config: got %q, err %v", got, readErr)
			}
			if got, readErr := os.ReadFile(statePath); readErr != nil || !bytes.Equal(got, stateBefore) {
				t.Fatalf("failed disable changed ownership or correlation state: got %q, err %v", got, readErr)
			}
		})
	}
}

func TestTokenTelemetryOwnershipWriteFailureRemovesNewProviderConfig(t *testing.T) {
	writeFailure := errors.New("injected ownership write failure")
	for _, target := range tokenTelemetryTargets {
		t.Run(target, func(t *testing.T) {
			home := t.TempDir()
			statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
			configPath := codexTokenTelemetryConfigPath(home, nil)
			if target == "claude-code" {
				configPath = claudeTokenTelemetryConfigPath(home, nil)
			}
			_, err := enableAgentTokenTelemetryWithOwnershipMutation(
				target,
				home,
				statePath,
				defaultTokenTelemetryEndpoint,
				nil,
				setRepositoryCorrelationMutation(target, defaultTokenTelemetryEndpoint, "path"),
				func(string, tokenTelemetryOwnership) error { return writeFailure },
			)
			if !errors.Is(err, writeFailure) {
				t.Fatalf("enable ownership write error = %v, want %v", err, writeFailure)
			}
			if _, statErr := os.Stat(configPath); !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("failed enable retained newly created %s config: %v", target, statErr)
			}
			if _, statErr := os.Stat(statePath); !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("failed enable committed %s ownership: %v", target, statErr)
			}
			if _, statErr := os.Stat(tokenTelemetryPendingTransactionPath(statePath, target)); !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("failed enable retained %s pending transaction: %v", target, statErr)
			}
		})
	}
}

func TestTokenTelemetryRollbackPreservesConcurrentProviderConfigEdit(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
	configPath := codexTokenTelemetryConfigPath(home, nil)
	beforeConfig := tokenTelemetryConfigSnapshot{Data: []byte("before\n"), Exists: true}
	afterConfig := tokenTelemetryConfigSnapshot{Data: []byte("after\n"), Exists: true}
	concurrentConfig := []byte("after\n# concurrent user edit\n")
	if err := os.MkdirAll(filepath.Dir(configPath), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(configPath, beforeConfig.Data, 0o600); err != nil {
		t.Fatal(err)
	}

	writeFailure := errors.New("simulated ownership write failure")
	err := publishTokenTelemetryConfigTransaction(
		statePath,
		"codex",
		configPath,
		beforeConfig,
		afterConfig,
		tokenTelemetryOwnership{},
		tokenTelemetryOwnership{},
		func(string, tokenTelemetryOwnership) error {
			current, readErr := os.ReadFile(configPath)
			if readErr != nil || !bytes.Equal(current, afterConfig.Data) {
				t.Fatalf("config before simulated concurrent edit = %q, %v", current, readErr)
			}
			if writeErr := os.WriteFile(configPath, concurrentConfig, 0o600); writeErr != nil {
				t.Fatal(writeErr)
			}
			return writeFailure
		},
	)
	if !errors.Is(err, writeFailure) {
		t.Fatalf("publish error = %v, want %v", err, writeFailure)
	}
	got, readErr := os.ReadFile(configPath)
	if readErr != nil || !bytes.Equal(got, concurrentConfig) {
		t.Fatalf("rollback overwrote concurrent provider config: got %q, err %v", got, readErr)
	}
	if _, statErr := os.Stat(tokenTelemetryPendingTransactionPath(statePath, "codex")); statErr != nil {
		t.Fatalf("rollback discarded unresolved transaction: %v", statErr)
	}
}

func TestTokenTelemetryPublishRejectsConcurrentProviderConfigEdit(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
	configPath := codexTokenTelemetryConfigPath(home, nil)
	beforeConfig := tokenTelemetryConfigSnapshot{Data: []byte("before\n"), Exists: true}
	afterConfig := tokenTelemetryConfigSnapshot{Data: []byte("after\n"), Exists: true}
	concurrentConfig := []byte("before\n# concurrent user edit\n")
	if err := os.MkdirAll(filepath.Dir(configPath), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(configPath, beforeConfig.Data, 0o600); err != nil {
		t.Fatal(err)
	}

	ownershipWriterCalled := false
	err := publishTokenTelemetryConfigTransactionWithSnapshotReader(
		statePath,
		"codex",
		configPath,
		beforeConfig,
		afterConfig,
		tokenTelemetryOwnership{},
		tokenTelemetryOwnership{},
		func(string, tokenTelemetryOwnership) error {
			ownershipWriterCalled = true
			return nil
		},
		func(path string) (tokenTelemetryConfigSnapshot, error) {
			if _, statErr := os.Stat(tokenTelemetryPendingTransactionPath(statePath, "codex")); statErr != nil {
				t.Fatalf("config preflight ran before transaction journal was published: %v", statErr)
			}
			if writeErr := os.WriteFile(path, concurrentConfig, 0o600); writeErr != nil {
				t.Fatal(writeErr)
			}
			return readTokenTelemetryConfigSnapshot(path)
		},
	)
	if err == nil || !strings.Contains(err.Error(), "changed before token telemetry publish") {
		t.Fatalf("publish error = %v, want concurrent-config refusal", err)
	}
	if ownershipWriterCalled {
		t.Fatal("ownership was published after concurrent provider config edit")
	}
	got, readErr := os.ReadFile(configPath)
	if readErr != nil || !bytes.Equal(got, concurrentConfig) {
		t.Fatalf("publish overwrote concurrent provider config: got %q, err %v", got, readErr)
	}
	if _, statErr := os.Stat(tokenTelemetryPendingTransactionPath(statePath, "codex")); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("pre-publish refusal retained unnecessary transaction journal: %v", statErr)
	}
}

func TestTokenTelemetryRecoversInterruptionBeforeConfigPublish(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
	configPath := codexTokenTelemetryConfigPath(home, nil)
	beforeOwnership, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		t.Fatal(err)
	}
	afterOwnership := cloneTokenTelemetryOwnership(beforeOwnership)
	afterOwnership.Targets["codex"] = tokenTelemetryTargetOwnership{
		ConfigPath: configPath,
		Endpoint:   defaultTokenTelemetryEndpoint,
	}
	pendingPath := tokenTelemetryPendingTransactionPath(statePath, "codex")
	if err := writeTokenTelemetryPendingTransaction(pendingPath, tokenTelemetryPendingTransaction{
		BeforeConfig: tokenTelemetryConfigSnapshot{},
		AfterConfig:  tokenTelemetryConfigSnapshot{Data: []byte("configured"), Exists: true},
		BeforeTarget: tokenTelemetryTargetOwnershipSnapshot(beforeOwnership, "codex"),
		AfterTarget:  tokenTelemetryTargetOwnershipSnapshot(afterOwnership, "codex"),
		ConfigPath:   configPath,
		Target:       "codex",
		Version:      tokenTelemetryPendingTransactionVersion,
	}); err != nil {
		t.Fatal(err)
	}

	if _, err := withTokenTelemetryStateTransaction(statePath, "codex", func() (tokenTelemetryResult, error) {
		return tokenTelemetryResult{}, nil
	}); err != nil {
		t.Fatalf("recover before config publish: %v", err)
	}
	if _, err := os.Stat(configPath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("recovery created provider config: %v", err)
	}
	if _, err := os.Stat(statePath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("recovery published after ownership: %v", err)
	}
	if _, err := os.Stat(pendingPath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("recovery retained completed pending transaction: %v", err)
	}
}

func TestTokenTelemetryRecoversInterruptedEnableTransaction(t *testing.T) {
	for _, target := range tokenTelemetryTargets {
		t.Run(target, func(t *testing.T) {
			home := t.TempDir()
			statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
			panicked := false
			func() {
				defer func() {
					panicked = recover() != nil
				}()
				_, _ = enableAgentTokenTelemetryWithOwnershipMutation(
					target,
					home,
					statePath,
					defaultTokenTelemetryEndpoint,
					nil,
					setRepositoryCorrelationMutation(target, defaultTokenTelemetryEndpoint, "path"),
					func(string, tokenTelemetryOwnership) error {
						panic("simulated process interruption")
					},
				)
			}()
			if !panicked {
				t.Fatal("enable did not reach the simulated interruption")
			}
			pendingPath := tokenTelemetryPendingTransactionPath(statePath, target)
			pendingInfo, err := os.Stat(pendingPath)
			if err != nil {
				t.Fatalf("stat pending transaction: %v", err)
			}
			if runtime.GOOS != "windows" && pendingInfo.Mode().Perm() != 0o600 {
				t.Fatalf("pending transaction mode = %#o, want 0600", pendingInfo.Mode().Perm())
			}
			if _, err := os.Stat(statePath); !errors.Is(err, os.ErrNotExist) {
				t.Fatalf("interrupted enable unexpectedly published ownership: %v", err)
			}

			result, err := withTokenTelemetryStateTransaction(statePath, target, func() (tokenTelemetryResult, error) {
				return inspectAgentTokenTelemetry(target, home, statePath, "", nil)
			})
			if err != nil || result.State != "enabled-managed" {
				t.Fatalf("recover interrupted %s enable = %+v, %v", target, result, err)
			}
			state, err := readTokenTelemetryOwnership(statePath)
			if err != nil {
				t.Fatal(err)
			}
			if _, ok := state.Targets[target]; !ok {
				t.Fatalf("recovery did not publish %s ownership: %+v", target, state)
			}
			if state.RepositoryCorrelation[target].Mode != "path" {
				t.Fatalf("recovery lost %s repository correlation: %+v", target, state)
			}
			if _, err := os.Stat(pendingPath); !errors.Is(err, os.ErrNotExist) {
				t.Fatalf("recovery did not clear pending transaction: %v", err)
			}
		})
	}
}

func TestTokenTelemetryRecoveryPreservesConfigChangedAfterInterruption(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
	configPath := codexTokenTelemetryConfigPath(home, nil)
	func() {
		defer func() { _ = recover() }()
		_, _ = enableAgentTokenTelemetryWithOwnershipMutation(
			"codex",
			home,
			statePath,
			defaultTokenTelemetryEndpoint,
			nil,
			setRepositoryCorrelationMutation("codex", defaultTokenTelemetryEndpoint, "path"),
			func(string, tokenTelemetryOwnership) error {
				panic("simulated process interruption")
			},
		)
	}()
	configured, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatal(err)
	}
	diverged := append(configured, []byte("# user change after interruption\n")...)
	if err := os.WriteFile(configPath, diverged, 0o600); err != nil {
		t.Fatal(err)
	}

	_, err = withTokenTelemetryStateTransaction(statePath, "codex", func() (tokenTelemetryResult, error) {
		return tokenTelemetryResult{}, nil
	})
	if err == nil || !strings.Contains(err.Error(), "changed while token telemetry transaction") {
		t.Fatalf("recovery error = %v, want changed-config refusal", err)
	}
	after, readErr := os.ReadFile(configPath)
	if readErr != nil || !bytes.Equal(after, diverged) {
		t.Fatalf("recovery overwrote divergent user config: got %q, err %v", after, readErr)
	}
	if _, statErr := os.Stat(statePath); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("recovery published ownership for divergent config: %v", statErr)
	}
	if _, statErr := os.Stat(tokenTelemetryPendingTransactionPath(statePath, "codex")); statErr != nil {
		t.Fatalf("recovery discarded unresolved transaction: %v", statErr)
	}
}

func TestTokenTelemetryRecoveryFailureIsIsolatedToAffectedTarget(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
	codexConfigPath := codexTokenTelemetryConfigPath(home, nil)
	func() {
		defer func() { _ = recover() }()
		_, _ = enableAgentTokenTelemetryWithOwnershipMutation(
			"codex",
			home,
			statePath,
			defaultTokenTelemetryEndpoint,
			nil,
			setRepositoryCorrelationMutation("codex", defaultTokenTelemetryEndpoint, "path"),
			func(string, tokenTelemetryOwnership) error {
				panic("simulated process interruption")
			},
		)
	}()
	configuredCodex, err := os.ReadFile(codexConfigPath)
	if err != nil {
		t.Fatal(err)
	}
	divergedCodex := append(append([]byte(nil), configuredCodex...), []byte("# user change after interruption\n")...)
	if err := os.WriteFile(codexConfigPath, divergedCodex, 0o600); err != nil {
		t.Fatal(err)
	}

	command := &cobra.Command{}
	var output bytes.Buffer
	command.SetOut(&output)
	err = runTokenTelemetryTargets(command, tokenTelemetryTargets, "enable", func(target string) (tokenTelemetryResult, error) {
		return withTokenTelemetryStateTransaction(statePath, target, func() (tokenTelemetryResult, error) {
			return enableAgentTokenTelemetryWithOwnershipMutation(
				target,
				home,
				statePath,
				defaultTokenTelemetryEndpoint,
				nil,
				setRepositoryCorrelationMutation(target, defaultTokenTelemetryEndpoint, "path"),
				writeTokenTelemetryOwnership,
			)
		})
	})
	if err == nil || !strings.Contains(err.Error(), "enable codex token telemetry") {
		t.Fatalf("mixed-target enable error = %v, want isolated Codex recovery error", err)
	}
	if !strings.Contains(output.String(), "claude-code: enabled-managed") {
		t.Fatalf("unrelated Claude target was blocked by Codex recovery: %q", output.String())
	}
	state, readErr := readTokenTelemetryOwnership(statePath)
	if readErr != nil {
		t.Fatal(readErr)
	}
	if _, ok := state.Targets["claude-code"]; !ok {
		t.Fatalf("Claude ownership was not published: %+v", state)
	}

	if err := os.WriteFile(codexConfigPath, configuredCodex, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := withTokenTelemetryStateTransaction(statePath, "codex", func() (tokenTelemetryResult, error) {
		return tokenTelemetryResult{}, nil
	}); err != nil {
		t.Fatalf("recover resolved Codex transaction: %v", err)
	}
	state, readErr = readTokenTelemetryOwnership(statePath)
	if readErr != nil {
		t.Fatal(readErr)
	}
	for _, target := range tokenTelemetryTargets {
		if _, ok := state.Targets[target]; !ok {
			t.Errorf("recovering Codex erased %s ownership: %+v", target, state)
		}
		if _, ok := state.RepositoryCorrelation[target]; !ok {
			t.Errorf("recovering Codex erased %s correlation: %+v", target, state)
		}
	}
}

func TestConcurrentTokenTelemetryEnablesPreserveMixedTargetOwnership(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
	endpoint := defaultTokenTelemetryEndpoint
	writersReady := make(chan struct{}, 2)
	releaseWriters := make(chan struct{})
	writer := func(path string, state tokenTelemetryOwnership) error {
		writersReady <- struct{}{}
		select {
		case <-releaseWriters:
		case <-time.After(100 * time.Millisecond):
		}
		return writeTokenTelemetryOwnership(path, state)
	}
	results := make(chan error, 2)
	for _, target := range tokenTelemetryTargets {
		target := target
		go func() {
			_, err := withTokenTelemetryStateTransaction(statePath, target, func() (tokenTelemetryResult, error) {
				return enableAgentTokenTelemetryWithOwnershipMutation(
					target,
					home,
					statePath,
					endpoint,
					nil,
					setRepositoryCorrelationMutation(target, endpoint, "path"),
					writer,
				)
			})
			results <- err
		}()
	}
	<-writersReady
	<-writersReady
	close(releaseWriters)
	for range tokenTelemetryTargets {
		if err := <-results; err != nil {
			t.Fatalf("concurrent enable: %v", err)
		}
	}

	state, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		t.Fatalf("read concurrent ownership: %v", err)
	}
	for _, target := range tokenTelemetryTargets {
		if _, ok := state.Targets[target]; !ok {
			t.Errorf("concurrent enable lost %s target ownership: %+v", target, state)
		}
		if _, ok := state.RepositoryCorrelation[target]; !ok {
			t.Errorf("concurrent enable lost %s repository correlation: %+v", target, state)
		}
	}
}

func TestTokenTelemetryRepositoryCorrelationStateIsBackwardCompatibleAndIndependent(t *testing.T) {
	t.Parallel()

	statePath := filepath.Join(t.TempDir(), "token-telemetry.json")
	legacy := `{"version":1,"targets":{"claude-code":{"configPath":"/tmp/settings.json","endpoint":"http://127.0.0.1:4318/v1/logs","updatedAt":"2026-08-26T00:00:00Z"}}}`
	if err := os.WriteFile(statePath, []byte(legacy), 0o600); err != nil {
		t.Fatal(err)
	}
	state, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		t.Fatalf("read legacy token telemetry state: %v", err)
	}
	if state.RepositoryCorrelation == nil || len(state.RepositoryCorrelation) != 0 {
		t.Fatalf("legacy state did not initialize optional repository correlation: %+v", state)
	}
	mode, err := repositoryCorrelationModeForEnable(statePath, "claude-code")
	if err != nil || mode != defaultRepositoryCorrelation {
		t.Fatalf("legacy target mode = %q, err %v, want %q", mode, err, defaultRepositoryCorrelation)
	}
	mode, err = repositoryCorrelationModeForEnable(statePath, "codex")
	if err != nil || mode != defaultRepositoryCorrelation {
		t.Fatalf("new target mode = %q, err %v, want %q", mode, err, defaultRepositoryCorrelation)
	}
	if err := setTokenTelemetryRepositoryCorrelation(statePath, "claude-code", defaultTokenTelemetryEndpoint, "name"); err != nil {
		t.Fatalf("set repository correlation: %v", err)
	}
	state, err = readTokenTelemetryOwnership(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if state.RepositoryCorrelation["claude-code"].Mode != "name" || state.Targets["claude-code"].ConfigPath != "/tmp/settings.json" {
		t.Fatalf("repository correlation overwrote provider ownership: %+v", state)
	}
	if err := removeTokenTelemetryRepositoryCorrelation(statePath, "claude-code"); err != nil {
		t.Fatalf("remove repository correlation: %v", err)
	}
	state, err = readTokenTelemetryOwnership(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if len(state.RepositoryCorrelation) != 0 || state.Targets["claude-code"].ConfigPath != "/tmp/settings.json" {
		t.Fatalf("repository cleanup removed provider ownership: %+v", state)
	}
}

func TestNormalizeRepositoryCorrelationMode(t *testing.T) {
	t.Parallel()

	for _, mode := range []string{"off", "name", "path", " PATH "} {
		got, err := normalizeRepositoryCorrelationMode(mode)
		if err != nil {
			t.Fatalf("normalize mode %q: %v", mode, err)
		}
		if got != strings.ToLower(strings.TrimSpace(mode)) {
			t.Fatalf("normalize mode %q = %q", mode, got)
		}
	}
	if _, err := normalizeRepositoryCorrelationMode("full"); err == nil {
		t.Fatal("unsupported repository correlation mode was accepted")
	}
}

func TestProviderRepositoryCorrelationModeMapsProvidersAndDefaultsSafely(t *testing.T) {
	t.Parallel()

	statePath := filepath.Join(t.TempDir(), "token-telemetry.json")
	if got := providerRepositoryCorrelationMode(statePath, "codex"); got != "off" {
		t.Fatalf("missing Codex repository correlation mode = %q, want off", got)
	}
	if err := setTokenTelemetryRepositoryCorrelation(statePath, "codex", defaultTokenTelemetryEndpoint, "path"); err != nil {
		t.Fatal(err)
	}
	if err := setTokenTelemetryRepositoryCorrelation(statePath, "claude-code", defaultTokenTelemetryEndpoint, "name"); err != nil {
		t.Fatal(err)
	}
	if got := providerRepositoryCorrelationMode(statePath, "codex"); got != "path" {
		t.Fatalf("Codex repository correlation mode = %q, want path", got)
	}
	if got := providerRepositoryCorrelationMode(statePath, "claude"); got != "name" {
		t.Fatalf("Claude repository correlation mode = %q, want name", got)
	}
	if got := providerRepositoryCorrelationMode(statePath, "other"); got != "" {
		t.Fatalf("unknown provider repository correlation mode = %q, want empty", got)
	}
	if err := setTokenTelemetryRepositoryCorrelation(statePath, "codex", defaultTokenTelemetryEndpoint, "invalid"); err != nil {
		t.Fatal(err)
	}
	if got := providerRepositoryCorrelationMode(statePath, "codex"); got != "off" {
		t.Fatalf("invalid repository correlation mode = %q, want off", got)
	}
}

func TestTokenTelemetryCommandRejectsRemoteRepositoryCorrelationBeforeWriting(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", "token-telemetry.json")
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("CODEX_HOME", "")
	t.Setenv("OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH", statePath)

	command := newTokenTelemetryCommand()
	command.SetArgs([]string{
		"enable",
		"--target", "codex",
		"--endpoint", "https://telemetry.example/v1/logs",
		"--repository-correlation", "path",
	})
	err := command.Execute()
	if err == nil || !strings.Contains(err.Error(), "requires a loopback Observer") {
		t.Fatalf("remote repository correlation error = %v", err)
	}
	for _, path := range []string{
		filepath.Join(home, ".codex", "config.toml"),
		statePath,
	} {
		if _, statErr := os.Stat(path); !errors.Is(statErr, os.ErrNotExist) {
			t.Fatalf("remote repository correlation changed %q: %v", path, statErr)
		}
	}
}

func TestTokenTelemetryCommandRejectsRemoteDefaultRepositoryCorrelationBeforeWriting(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", "token-telemetry.json")
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("CODEX_HOME", "")
	t.Setenv("OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH", statePath)

	command := newTokenTelemetryCommand()
	command.SetArgs([]string{
		"enable",
		"--target", "codex",
		"--endpoint", "https://telemetry.example/v1/logs",
	})
	err := command.Execute()
	if err == nil || !strings.Contains(err.Error(), "requires a loopback Observer") {
		t.Fatalf("remote default repository correlation error = %v", err)
	}
	for _, path := range []string{
		filepath.Join(home, ".codex", "config.toml"),
		statePath,
	} {
		if _, statErr := os.Stat(path); !errors.Is(statErr, os.ErrNotExist) {
			t.Fatalf("remote default repository correlation changed %q: %v", path, statErr)
		}
	}
}

func TestTokenTelemetryRemoteEnableIsolatesRepositoryCorrelationFailures(t *testing.T) {
	home := t.TempDir()
	statePath := filepath.Join(home, ".obstudio", "token-telemetry.json")
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("CODEX_HOME", "")
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	t.Setenv("OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH", statePath)
	if err := setTokenTelemetryRepositoryCorrelation(statePath, "codex", defaultTokenTelemetryEndpoint, "off"); err != nil {
		t.Fatal(err)
	}
	if err := setTokenTelemetryRepositoryCorrelation(statePath, "claude-code", defaultTokenTelemetryEndpoint, "name"); err != nil {
		t.Fatal(err)
	}

	command := newTokenTelemetryCommand()
	var output bytes.Buffer
	command.SetOut(&output)
	command.SetErr(&output)
	command.SetArgs([]string{
		"enable",
		"--target", "codex,claude-code",
		"--endpoint", "https://telemetry.example/v1/logs",
	})
	err := command.Execute()
	if err == nil || !strings.Contains(err.Error(), "enable claude-code token telemetry") || strings.Contains(err.Error(), "enable codex token telemetry") {
		t.Fatalf("mixed-target remote enable error = %v", err)
	}
	if !strings.Contains(output.String(), "codex: enabled-managed") {
		t.Fatalf("valid Codex target did not complete: %q", output.String())
	}
	if _, statErr := os.Stat(filepath.Join(home, ".codex", "config.toml")); statErr != nil {
		t.Fatalf("Codex configuration was not written: %v", statErr)
	}
	if _, statErr := os.Stat(filepath.Join(home, ".claude", "settings.json")); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("ineligible Claude target changed configuration: %v", statErr)
	}
	state, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := state.Targets["codex"]; !ok {
		t.Fatalf("successful Codex ownership was not recorded: %+v", state)
	}
	if _, ok := state.Targets["claude-code"]; ok {
		t.Fatalf("failed Claude ownership was recorded: %+v", state)
	}
	if state.RepositoryCorrelation["codex"].Mode != "off" || state.RepositoryCorrelation["claude-code"].Mode != "name" {
		t.Fatalf("repository correlation modes changed unexpectedly: %+v", state.RepositoryCorrelation)
	}
}

func TestWriteConfigFilePublishesAtomicallyAndPreservesSymlink(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink tests require elevated privileges on some Windows hosts")
	}
	root := t.TempDir()
	target := filepath.Join(root, "actual-config.toml")
	link := filepath.Join(root, "config.toml")
	if err := os.WriteFile(target, []byte("original\n"), 0o640); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Base(target), link); err != nil {
		t.Fatal(err)
	}

	publishErr := errors.New("publish failed")
	err := writeConfigFileWith(link, []byte("replacement\n"), 0o644, true, func(_, _ string) error {
		return publishErr
	})
	if !errors.Is(err, publishErr) {
		t.Fatalf("atomic publish error = %v, want %v", err, publishErr)
	}
	if data, readErr := os.ReadFile(target); readErr != nil || string(data) != "original\n" {
		t.Fatalf("failed publish changed original config: data=%q err=%v", data, readErr)
	}
	if matches, globErr := filepath.Glob(filepath.Join(root, ".actual-config.toml.tmp-*")); globErr != nil || len(matches) != 0 {
		t.Fatalf("failed publish left temporary config files: matches=%v err=%v", matches, globErr)
	}

	if err := writeConfigFile(link, []byte("replacement\n"), 0o644, true); err != nil {
		t.Fatalf("atomic config write: %v", err)
	}
	if info, statErr := os.Lstat(link); statErr != nil || info.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("config symlink was replaced: info=%v err=%v", info, statErr)
	}
	if data, readErr := os.ReadFile(target); readErr != nil || string(data) != "replacement\n" {
		t.Fatalf("atomic write did not update symlink target: data=%q err=%v", data, readErr)
	}
	if info, statErr := os.Stat(target); statErr != nil || info.Mode().Perm() != 0o640 {
		t.Fatalf("atomic write did not preserve target mode: info=%v err=%v", info, statErr)
	}
}

func TestTokenTelemetryStatusUsesRecordedCustomEndpoint(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, ".codex", "config.toml")
	statePath := filepath.Join(root, ".obstudio", "token-telemetry.json")
	endpoint := "http://127.0.0.1:5318/v1/logs"
	if _, err := enableCodexTokenTelemetry(path, statePath, endpoint); err != nil {
		t.Fatalf("enable custom Codex endpoint: %v", err)
	}
	result, err := inspectOwnedCodexTokenTelemetry(path, statePath, "")
	if err != nil {
		t.Fatalf("inspect recorded Codex endpoint: %v", err)
	}
	if result.State != "enabled-managed" {
		t.Fatalf("status without --endpoint = %+v, want enabled-managed", result)
	}
}

func TestTokenTelemetryStatusUsesCorrelationEndpointForUserOwnedConfiguration(t *testing.T) {
	endpoint := "http://127.0.0.1:5318/v1/logs"

	t.Run("codex", func(t *testing.T) {
		home := t.TempDir()
		path := codexTokenTelemetryConfigPath(home, nil)
		statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
		traceEndpoint, err := tokenTelemetryTraceEndpoint(endpoint)
		if err != nil {
			t.Fatal(err)
		}
		config := fmt.Sprintf("[otel]\nexporter = { otlp-http = { endpoint = %q, protocol = \"binary\" } }\ntrace_exporter = { otlp-http = { endpoint = %q, protocol = \"binary\" } }\n", endpoint, traceEndpoint)
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(config), 0o600); err != nil {
			t.Fatal(err)
		}
		result, err := enableCodexTokenTelemetryWithOwnershipMutation(
			path,
			statePath,
			endpoint,
			setRepositoryCorrelationMutation("codex", endpoint, "path"),
			writeTokenTelemetryOwnership,
		)
		if err != nil || result.State != "enabled-existing" {
			t.Fatalf("enable user-owned Codex telemetry = %+v, err %v", result, err)
		}
		state, err := readTokenTelemetryOwnership(statePath)
		if err != nil {
			t.Fatal(err)
		}
		if _, owned := state.Targets["codex"]; owned {
			t.Fatalf("user-owned Codex exporters were adopted: %+v", state)
		}
		status, err := inspectAgentTokenTelemetry("codex", home, statePath, "", nil)
		if err != nil || status.State != "enabled-existing" {
			t.Fatalf("status for user-owned Codex custom endpoint = %+v, err %v", status, err)
		}
	})

	t.Run("claude-code", func(t *testing.T) {
		home := t.TempDir()
		path := claudeTokenTelemetryConfigPath(home, nil)
		statePath := filepath.Join(home, ".obstudio", tokenTelemetryStateFileName)
		required, defaults, err := claudeTokenTelemetrySettings(endpoint)
		if err != nil {
			t.Fatal(err)
		}
		env := make(map[string]any, len(required)+len(defaults))
		for _, setting := range append(required, defaults...) {
			env[setting.key] = setting.value
		}
		data, err := json.Marshal(map[string]any{"env": env})
		if err != nil {
			t.Fatal(err)
		}
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, data, 0o600); err != nil {
			t.Fatal(err)
		}
		result, err := enableClaudeTokenTelemetryWithOwnershipMutation(
			path,
			statePath,
			endpoint,
			nil,
			setRepositoryCorrelationMutation("claude-code", endpoint, "path"),
			writeTokenTelemetryOwnership,
		)
		if err != nil || result.State != "enabled-existing" {
			t.Fatalf("enable user-owned Claude telemetry = %+v, err %v", result, err)
		}
		state, err := readTokenTelemetryOwnership(statePath)
		if err != nil {
			t.Fatal(err)
		}
		if _, owned := state.Targets["claude-code"]; owned {
			t.Fatalf("user-owned Claude settings were adopted: %+v", state)
		}
		status, err := inspectAgentTokenTelemetry("claude-code", home, statePath, "", nil)
		if err != nil || status.State != "enabled-existing" {
			t.Fatalf("status for user-owned Claude custom endpoint = %+v, err %v", status, err)
		}
	})
}

func TestNormalizeTokenTelemetryEndpoint(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name          string
		raw           string
		want          string
		errorContains string
	}{
		{name: "http", raw: " http://127.0.0.1:4318/v1/logs/ ", want: "http://127.0.0.1:4318/v1/logs"},
		{name: "https", raw: "https://observer.example/v1/logs", want: "https://observer.example/v1/logs"},
		{name: "wrong path", raw: "http://127.0.0.1:4318", errorContains: "must end with /v1/logs"},
		{name: "wrong scheme", raw: "grpc://127.0.0.1:4317/v1/logs", errorContains: "must use http or https"},
		{name: "query", raw: "http://127.0.0.1:4318/v1/logs?key=value", errorContains: "query parameters"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			got, err := normalizeTokenTelemetryEndpoint(tc.raw)
			if tc.errorContains != "" {
				if err == nil || !strings.Contains(err.Error(), tc.errorContains) {
					t.Fatalf("normalizeTokenTelemetryEndpoint() error = %v, want containing %q", err, tc.errorContains)
				}
				return
			}
			if err != nil {
				t.Fatalf("normalizeTokenTelemetryEndpoint() error = %v", err)
			}
			if got != tc.want {
				t.Fatalf("normalizeTokenTelemetryEndpoint() = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestTokenTelemetryTraceEndpoint(t *testing.T) {
	t.Parallel()

	got, err := tokenTelemetryTraceEndpoint("http://127.0.0.1:4318/v1/logs")
	if err != nil {
		t.Fatalf("tokenTelemetryTraceEndpoint() error = %v", err)
	}
	if got != "http://127.0.0.1:4318/v1/traces" {
		t.Fatalf("tokenTelemetryTraceEndpoint() = %q", got)
	}
}

func TestTokenTelemetryMetricEndpoint(t *testing.T) {
	t.Parallel()

	got, err := tokenTelemetryMetricEndpoint("http://127.0.0.1:4318/v1/logs")
	if err != nil {
		t.Fatalf("tokenTelemetryMetricEndpoint() error = %v", err)
	}
	if got != "http://127.0.0.1:4318/v1/metrics" {
		t.Fatalf("tokenTelemetryMetricEndpoint() = %q", got)
	}
}

func TestConfigureCodexTokenTelemetryIsIdempotentAndCleanupRestoresUserConfig(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), ".codex", "config.toml")
	initial := strings.Join([]string{
		`model = "gpt-5.4"`,
		``,
		`[otel]`,
		`log_user_prompt = false`,
		``,
		`[otel.metrics_exporter]`,
		`endpoint = "https://metrics.example/v1/metrics"`,
		``,
	}, "\n")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("mkdir Codex config parent: %v", err)
	}
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}

	endpoint := "http://127.0.0.1:4318/v1/logs"
	for i := 0; i < 2; i++ {
		if err := configureCodexTokenTelemetry(path, endpoint); err != nil {
			t.Fatalf("configureCodexTokenTelemetry run %d: %v", i+1, err)
		}
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read Codex config: %v", err)
	}
	text := string(out)
	for _, want := range []string{
		`model = "gpt-5.4"`,
		`log_user_prompt = false`,
		`endpoint = "https://metrics.example/v1/metrics"`,
		`exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/logs", protocol = "binary" } }`,
		`trace_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/traces", protocol = "binary" } }`,
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("Codex config lost %q:\n%s", want, text)
		}
	}
	if strings.Count(text, codexTokenTelemetryBlockStart) != 1 || strings.Count(text, "exporter =") != 2 {
		t.Fatalf("Codex token telemetry was duplicated:\n%s", text)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat Codex config: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("Codex config mode = %o, want 600", info.Mode().Perm())
	}
	removed, err := disableCodexTokenTelemetry(path)
	if err != nil || !removed {
		t.Fatalf("disableCodexTokenTelemetry() = removed %v, error %v", removed, err)
	}
	restored, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read restored Codex config: %v", err)
	}
	if string(restored) != initial {
		t.Fatalf("Codex cleanup did not restore the original user config:\n%s", restored)
	}
}

func TestConfigureCodexTokenTelemetryCleanupRestoresConfigWithoutOTelParent(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name    string
		initial string
	}{
		{name: "append parent", initial: "model = \"gpt-5.4\"\n"},
		{name: "insert before child", initial: "model = \"gpt-5.4\"\n\n[otel.metrics_exporter]\nendpoint = \"https://metrics.example/v1/metrics\"\n"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "config.toml")
			if err := os.WriteFile(path, []byte(tc.initial), 0o600); err != nil {
				t.Fatalf("write Codex config: %v", err)
			}
			if err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs"); err != nil {
				t.Fatalf("configureCodexTokenTelemetry: %v", err)
			}
			removed, err := disableCodexTokenTelemetry(path)
			if err != nil || !removed {
				t.Fatalf("disableCodexTokenTelemetry() = %v, %v", removed, err)
			}
			out, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("read Codex config: %v", err)
			}
			if string(out) != tc.initial {
				t.Fatalf("cleanup changed user config:\n%s", out)
			}
		})
	}
}

func TestConfigureCodexTokenTelemetryOwnsOnlyMissingExporter(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := "[otel]\nexporter = { otlp-http = { endpoint = \"http://127.0.0.1:4318/v1/logs\", protocol = \"binary\", headers = { existing = \"preserved\" } } }\n"
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}
	if err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs"); err != nil {
		t.Fatalf("configureCodexTokenTelemetry: %v", err)
	}
	configured, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read configured Codex config: %v", err)
	}
	if strings.Count(string(configured), "trace_exporter =") != 1 || strings.Count(string(configured), "exporter =") != 2 {
		t.Fatalf("missing trace exporter was not added once:\n%s", configured)
	}
	removed, err := disableCodexTokenTelemetry(path)
	if err != nil || !removed {
		t.Fatalf("disableCodexTokenTelemetry() = %v, %v", removed, err)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read cleaned Codex config: %v", err)
	}
	if string(out) != initial {
		t.Fatalf("cleanup removed or changed the user-owned exporter:\n%s", out)
	}
}

func TestConfigureCodexTokenTelemetryPreservesConflictingExporter(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := "[otel]\nexporter = { otlp-http = { endpoint = \"https://existing.example/v1/logs\", protocol = \"binary\" } }\n"
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}
	err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs")
	if err == nil || !strings.Contains(err.Error(), "user-owned value") {
		t.Fatalf("expected conflicting Codex exporter error, got %v", err)
	}
	out, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatalf("read Codex config: %v", readErr)
	}
	if string(out) != initial {
		t.Fatalf("conflicting Codex exporter was changed:\n%s", out)
	}
}

func TestConfigureCodexTokenTelemetryRejectsMatchingEndpointWithWrongProtocol(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := "[otel]\nexporter = { otlp-http = { endpoint = \"http://127.0.0.1:4318/v1/logs\", protocol = \"grpc\" } }\n"
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}
	err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs")
	if err == nil || !strings.Contains(err.Error(), "user-owned value") {
		t.Fatalf("expected conflicting Codex exporter protocol error, got %v", err)
	}
	out, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatalf("read Codex config: %v", readErr)
	}
	if string(out) != initial {
		t.Fatalf("Codex exporter with a conflicting protocol was changed:\n%s", out)
	}
}

func TestConfigureCodexTokenTelemetryRejectsEndpointPrefixMatch(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := "[otel]\nexporter = { otlp-http = { endpoint = \"http://127.0.0.1:4318/v1/logs-extra\", protocol = \"binary\" } }\n"
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}
	err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs")
	if err == nil || !strings.Contains(err.Error(), "user-owned value") {
		t.Fatalf("expected endpoint-prefix conflict, got %v", err)
	}
	out, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatalf("read Codex config: %v", readErr)
	}
	if string(out) != initial {
		t.Fatalf("endpoint-prefix conflict was changed:\n%s", out)
	}
}

func TestConfigureCodexTokenTelemetryPreservesConflictingTraceExporter(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := strings.Join([]string{
		"[otel]",
		`exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/logs", protocol = "binary" } }`,
		`trace_exporter = { otlp-http = { endpoint = "https://existing.example/v1/traces", protocol = "binary" } }`,
		"",
	}, "\n")
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}
	err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs")
	if err == nil || !strings.Contains(err.Error(), "trace exporter") {
		t.Fatalf("expected conflicting Codex trace exporter error, got %v", err)
	}
	out, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatalf("read Codex config: %v", readErr)
	}
	if string(out) != initial {
		t.Fatalf("conflicting Codex trace exporter was changed:\n%s", out)
	}
}

func TestConfigureCodexTokenTelemetryKeepsMatchingUnmanagedExporterByteForByte(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := "[otel]\nexporter = { otlp-http = { endpoint = \"http://127.0.0.1:4318/v1/logs\", protocol = \"binary\", headers = { x-observer = \"preserved\" } } }\ntrace_exporter = { otlp-http = { endpoint = \"http://127.0.0.1:4318/v1/traces\", protocol = \"binary\", headers = { x-observer = \"preserved\" } } }\n"
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}
	if err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs"); err != nil {
		t.Fatalf("configureCodexTokenTelemetry: %v", err)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read Codex config: %v", err)
	}
	if string(out) != initial {
		t.Fatalf("matching unmanaged exporter options were replaced:\n%s", out)
	}
}

func TestConfigureCodexTokenTelemetryKeepsMatchingTableExportersByteForByte(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := strings.Join([]string{
		"[otel.exporter]",
		"[otel.exporter.otlp-http]",
		`endpoint = 'http://127.0.0.1:4318/v1/logs'`,
		`protocol = 'binary'`,
		"[otel.exporter.otlp-http.headers]",
		`x-observer = "preserved"`,
		"",
		"[otel.trace_exporter]",
		"[otel.trace_exporter.otlp-http]",
		`endpoint = 'http://127.0.0.1:4318/v1/traces'`,
		`protocol = 'binary'`,
		"[otel.trace_exporter.otlp-http.headers]",
		`x-observer = "preserved"`,
		"",
	}, "\n")
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}
	if err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs"); err != nil {
		t.Fatalf("configureCodexTokenTelemetry: %v", err)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read Codex config: %v", err)
	}
	if string(out) != initial {
		t.Fatalf("matching table exporters were replaced:\n%s", out)
	}
}

func TestConfigureCodexTokenTelemetryPreservesConflictingTableExporter(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := strings.Join([]string{
		"[otel.exporter.otlp-http]",
		`endpoint = "http://127.0.0.1:4318/v1/logs"`,
		`protocol = "binary"`,
		"",
		"[otel.trace_exporter.otlp-http]",
		`endpoint = "https://existing.example/v1/traces"`,
		`protocol = "binary"`,
		"",
	}, "\n")
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}
	err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs")
	if err == nil || !strings.Contains(err.Error(), "trace exporter") {
		t.Fatalf("expected conflicting table trace exporter error, got %v", err)
	}
	out, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatalf("read Codex config: %v", readErr)
	}
	if string(out) != initial {
		t.Fatalf("conflicting table exporter was changed:\n%s", out)
	}
}

func TestConfigureCodexTokenTelemetryCreatesParentBeforeChildTables(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := "model = \"gpt-5.4\"\n\n[otel.metrics_exporter]\nendpoint = \"https://metrics.example\"\n"
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}
	if err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs"); err != nil {
		t.Fatalf("configureCodexTokenTelemetry: %v", err)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read Codex config: %v", err)
	}
	text := string(out)
	if strings.Index(text, "[otel]") < 0 || strings.Index(text, "[otel]") > strings.Index(text, "[otel.metrics_exporter]") {
		t.Fatalf("parent OTel table was not inserted before child table:\n%s", text)
	}
}

func TestConfigureCodexTokenTelemetryIgnoresTablesInsideMultilineStrings(t *testing.T) {
	t.Parallel()

	for _, test := range []struct {
		name      string
		delimiter string
	}{
		{name: "literal", delimiter: "'''"},
		{name: "basic", delimiter: "\"\"\""},
	} {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "config.toml")
			initial := fmt.Sprintf("developer_instructions = %s\nkeep this text\n%s\n[otel]\nnot a table\n%s\n%s\nmodel = \"gpt-5.4\"\n", test.delimiter, codexTokenTelemetryBlockStart, codexTokenTelemetryBlockEnd, test.delimiter)
			if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
				t.Fatalf("write Codex config: %v", err)
			}
			if err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs"); err != nil {
				t.Fatalf("configureCodexTokenTelemetry: %v", err)
			}
			out, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("read Codex config: %v", err)
			}
			text := string(out)
			closingDelimiter := strings.LastIndex(text, test.delimiter)
			managedBlock := strings.LastIndex(text, codexTokenTelemetryBlockStart)
			realSection := strings.LastIndex(text, "[otel]")
			if !strings.HasPrefix(text, initial) || managedBlock < closingDelimiter || realSection < closingDelimiter {
				t.Fatalf("managed OTel settings were inserted into a multiline string:\n%s", text)
			}
			configured, err := codexTokenTelemetryConfigured(path)
			if err != nil || !configured {
				t.Fatalf("codexTokenTelemetryConfigured() = %v, %v, want true", configured, err)
			}
			cleaned, found, err := removeCodexTokenTelemetryBlock(text)
			if err != nil || !found {
				t.Fatalf("removeCodexTokenTelemetryBlock() found = %v, err = %v", found, err)
			}
			if cleaned != initial {
				t.Fatalf("disable cleanup modified multiline string content:\n%s", cleaned)
			}
		})
	}
}

func TestConfigureCodexTokenTelemetryPreservesUnterminatedMultilineString(t *testing.T) {
	t.Parallel()

	for _, delimiter := range []string{"'''", "\"\"\""} {
		path := filepath.Join(t.TempDir(), "config.toml")
		initial := fmt.Sprintf("developer_instructions = %s\n[otel]\n", delimiter)
		if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
			t.Fatalf("write Codex config: %v", err)
		}
		err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs")
		if err == nil || !strings.Contains(err.Error(), "unterminated TOML multiline string") {
			t.Fatalf("configureCodexTokenTelemetry() error = %v, want unterminated multiline string", err)
		}
		out, readErr := os.ReadFile(path)
		if readErr != nil {
			t.Fatalf("read Codex config: %v", readErr)
		}
		if string(out) != initial {
			t.Fatalf("unterminated multiline string was modified:\n%s", out)
		}
	}
}

func TestConfigureCodexTokenTelemetryPreservesExplicitlyDisabledExporter(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	initial := "[otel] # existing settings\nexporter = 'none' # disabled by default\nlog_user_prompt = false\n"
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write Codex config: %v", err)
	}
	if err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs"); err == nil || !strings.Contains(err.Error(), "user-owned value") {
		t.Fatalf("configureCodexTokenTelemetry() error = %v, want user-owned conflict", err)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read Codex config: %v", err)
	}
	if string(out) != initial {
		t.Fatalf("explicitly disabled Codex exporter was changed:\n%s", out)
	}
}

func TestConfigureCodexTokenTelemetryRejectsUnsupportedExporterFormsWithoutWriting(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name    string
		content string
	}{
		{name: "root dotted key", content: `otel.exporter = "none"` + "\n"},
		{name: "incomplete exporter table", content: "[otel.exporter.otlp-http]\nendpoint = \"https://existing.example/v1/logs\"\n"},
		{name: "unsupported exporter table", content: "[otel.exporter.grpc]\nendpoint = \"https://existing.example\"\n"},
		{name: "section dotted key", content: "[otel]\nexporter.otlp-http.endpoint = \"https://existing.example/v1/logs\"\n"},
		{name: "incomplete trace exporter table", content: "[otel.trace_exporter.otlp-http]\nendpoint = \"https://existing.example/v1/traces\"\n"},
		{name: "unsupported trace exporter table", content: "[otel.trace_exporter.grpc]\nendpoint = \"https://existing.example\"\n"},
		{name: "trace section dotted key", content: "[otel]\ntrace_exporter.otlp-http.endpoint = \"https://existing.example/v1/traces\"\n"},
		{name: "quoted exporter key", content: "[otel]\n\"exporter\" = \"none\"\n"},
		{name: "quoted otel table", content: "[\"otel\"]\nexporter = \"none\"\n"},
		{name: "spaced otel table", content: "[ otel ]\nexporter = \"none\"\n"},
		{name: "spaced child table", content: "[otel . exporter . otlp-http]\nendpoint = \"https://existing.example/v1/logs\"\n"},
		{name: "quoted exporter table", content: "[otel.\"exporter\"]\notlp-http = {}\n"},
		{name: "duplicate exporter child table", content: "[otel.exporter.otlp-http]\nendpoint = \"http://127.0.0.1:4318/v1/logs\"\nprotocol = \"binary\"\n[otel.exporter.otlp-http]\nendpoint = \"http://127.0.0.1:4318/v1/logs\"\nprotocol = \"binary\"\n"},
		{name: "duplicate otel table", content: "[otel]\nlog_user_prompt = false\n[otel]\nexporter = \"none\"\n"},
		{name: "otel array table", content: "[[otel]]\nexporter = \"none\"\n"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "config.toml")
			if err := os.WriteFile(path, []byte(tc.content), 0o644); err != nil {
				t.Fatalf("write Codex config: %v", err)
			}
			err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs")
			if err == nil || !strings.Contains(err.Error(), "unsupported") {
				t.Fatalf("configureCodexTokenTelemetry() error = %v, want unsupported syntax", err)
			}
			out, readErr := os.ReadFile(path)
			if readErr != nil {
				t.Fatalf("read Codex config: %v", readErr)
			}
			if string(out) != tc.content {
				t.Fatalf("unsupported Codex exporter form was changed:\n%s", out)
			}
		})
	}
}

func TestOwnedCodexTokenTelemetryPreservesModifiedSetting(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, ".codex", "config.toml")
	statePath := filepath.Join(root, ".obstudio", "token-telemetry.json")
	endpoint := "http://127.0.0.1:4318/v1/logs"
	if _, err := enableCodexTokenTelemetry(path, statePath, endpoint); err != nil {
		t.Fatalf("enable Codex token telemetry: %v", err)
	}
	configured, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read configured Codex config: %v", err)
	}
	modified := strings.Replace(
		string(configured),
		`exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/logs", protocol = "binary" } }`,
		`exporter = { otlp-http = { endpoint = "https://user.example/v1/logs", protocol = "binary" } }`,
		1,
	)
	if modified == string(configured) {
		t.Fatal("fixture did not modify the managed Codex exporter")
	}
	if err := os.WriteFile(path, []byte(modified), 0o600); err != nil {
		t.Fatalf("write user-modified Codex config: %v", err)
	}

	if _, err := enableCodexTokenTelemetry(path, statePath, endpoint); err == nil || !strings.Contains(err.Error(), "was modified") {
		t.Fatalf("re-enable error = %v, want modified-owned-setting refusal", err)
	}
	afterEnable, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read Codex config after refused enable: %v", err)
	}
	if string(afterEnable) != modified {
		t.Fatalf("re-enable overwrote user-modified Codex config:\n%s", afterEnable)
	}

	result, err := disableOwnedCodexTokenTelemetry(path, statePath)
	if err != nil {
		t.Fatalf("disable modified Codex telemetry: %v", err)
	}
	if result.State != "disabled-with-user-changes" {
		t.Fatalf("disable state = %+v, want disabled-with-user-changes", result)
	}
	cleaned, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read cleaned Codex config: %v", err)
	}
	text := string(cleaned)
	if !strings.Contains(text, "https://user.example/v1/logs") {
		t.Fatalf("modified Codex exporter was removed:\n%s", text)
	}
	if strings.Contains(text, "trace_exporter") || strings.Contains(text, codexTokenTelemetryBlockStart) || strings.Contains(text, codexTokenTelemetryBlockEnd) {
		t.Fatalf("unchanged owned setting or ownership markers remain:\n%s", text)
	}
	if _, err := os.Stat(statePath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("Codex ownership state was not removed: %v", err)
	}
}

func TestOwnedCodexTokenTelemetryPreservesExternalOTelSectionContent(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, ".codex", "config.toml")
	statePath := filepath.Join(root, ".obstudio", "token-telemetry.json")
	firstEndpoint := "http://127.0.0.1:4318/v1/logs"
	secondEndpoint := "http://127.0.0.1:5318/v1/logs"
	if _, err := enableCodexTokenTelemetry(path, statePath, firstEndpoint); err != nil {
		t.Fatalf("enable Codex token telemetry: %v", err)
	}
	configured, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read configured Codex settings: %v", err)
	}
	configured = append(configured, []byte("log_user_prompt = true\n")...)
	if err := os.WriteFile(path, configured, 0o600); err != nil {
		t.Fatalf("add user-owned OTel setting: %v", err)
	}

	if _, err := enableCodexTokenTelemetry(path, statePath, secondEndpoint); err != nil {
		t.Fatalf("update Obstudio-owned endpoint: %v", err)
	}
	updated, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read updated Codex settings: %v", err)
	}
	updatedText := string(updated)
	if sectionIndex, settingIndex := strings.Index(updatedText, "[otel]"), strings.Index(updatedText, "log_user_prompt = true"); sectionIndex < 0 || settingIndex < sectionIndex {
		t.Fatalf("user-owned setting moved out of the [otel] table during update:\n%s", updatedText)
	}

	if _, err := disableOwnedCodexTokenTelemetry(path, statePath); err != nil {
		t.Fatalf("disable Codex token telemetry: %v", err)
	}
	cleaned, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read cleaned Codex settings: %v", err)
	}
	cleanedText := string(cleaned)
	if !strings.Contains(cleanedText, "[otel]\nlog_user_prompt = true") {
		t.Fatalf("cleanup changed the user-owned OTel setting's table semantics:\n%s", cleanedText)
	}
	if strings.Contains(cleanedText, "exporter") || strings.Contains(cleanedText, codexTokenTelemetryBlockStart) {
		t.Fatalf("cleanup retained Obstudio-owned Codex settings:\n%s", cleanedText)
	}
}

func TestDisableCodexTokenTelemetryReportsRetainedUserOwnedExporter(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, ".codex", "config.toml")
	statePath := filepath.Join(root, ".obstudio", "token-telemetry.json")
	endpoint := "http://127.0.0.1:4318/v1/logs"
	initial := strings.Join([]string{
		"[otel]",
		`exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/logs", protocol = "binary" } }`,
		"",
	}, "\n")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("create Codex config directory: %v", err)
	}
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write user-owned Codex exporter: %v", err)
	}
	if _, err := enableCodexTokenTelemetry(path, statePath, endpoint); err != nil {
		t.Fatalf("enable Codex token telemetry: %v", err)
	}

	result, err := disableOwnedCodexTokenTelemetry(path, statePath)
	if err != nil {
		t.Fatalf("disable Codex token telemetry: %v", err)
	}
	if result.State != "unmanaged" || !strings.Contains(result.Detail, "user-owned Codex OTel configuration remains configured") {
		t.Fatalf("disable result = %+v, want retained user-owned telemetry", result)
	}
	cleaned, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read cleaned Codex config: %v", err)
	}
	if string(cleaned) != initial {
		t.Fatalf("user-owned Codex exporter changed:\n%s", cleaned)
	}
}

func TestDisableCodexTokenTelemetryPreservesMarkerWithoutOwnershipState(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "config.toml")
	if err := configureCodexTokenTelemetry(path, "http://127.0.0.1:4318/v1/logs"); err != nil {
		t.Fatalf("create legacy marked Codex config: %v", err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read marked Codex config: %v", err)
	}
	result, err := disableOwnedCodexTokenTelemetry(path, filepath.Join(t.TempDir(), "missing-state.json"))
	if err != nil {
		t.Fatalf("disable unmanaged Codex telemetry: %v", err)
	}
	if result.State != "unmanaged" {
		t.Fatalf("disable state = %+v, want unmanaged", result)
	}
	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read preserved Codex config: %v", err)
	}
	if string(after) != string(before) {
		t.Fatalf("marker content without ownership state was changed:\n%s", after)
	}
}

func TestEnableCodexTokenTelemetryReusesMatchingMarkerWithoutOwnershipState(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, "config.toml")
	statePath := filepath.Join(root, "missing-state.json")
	endpoint := "http://127.0.0.1:4318/v1/logs"
	initial := strings.Join([]string{
		"[otel]",
		codexTokenTelemetryBlockStart,
		`exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/logs", protocol = "binary" } }`,
		codexTokenTelemetryBlockEnd,
		`environment = "user-owned"`,
		"",
		"[otel.trace_exporter.otlp-http]",
		`endpoint = "http://127.0.0.1:4318/v1/traces"`,
		`protocol = "binary"`,
		"",
	}, "\n")
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write marked Codex config: %v", err)
	}

	result, err := enableCodexTokenTelemetry(path, statePath, endpoint)
	if err != nil {
		t.Fatalf("enable matching marked Codex telemetry: %v", err)
	}
	if result.State != "enabled-existing" || !strings.Contains(result.Detail, "remains user-owned") {
		t.Fatalf("enable result = %+v, want enabled-existing user-owned telemetry", result)
	}
	status, err := inspectOwnedCodexTokenTelemetry(path, statePath, endpoint)
	if err != nil {
		t.Fatalf("inspect matching marked Codex telemetry: %v", err)
	}
	if status.State != "enabled-existing" {
		t.Fatalf("status = %+v, want enabled-existing", status)
	}
	if _, err := os.Stat(statePath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("matching orphaned marker was incorrectly adopted as owned: %v", err)
	}
	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read preserved Codex config: %v", err)
	}
	if string(after) != initial {
		t.Fatalf("matching user-owned Codex config changed:\n%s", after)
	}
}

func TestEnableClaudeTokenTelemetryPreservesSettingsAndCleanupRemovesOnlyOwnedValues(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), ".claude", "settings.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("mkdir Claude settings parent: %v", err)
	}
	initial := map[string]any{
		"model": "sonnet",
		"env": map[string]any{
			"EXISTING":                    "preserved",
			"OTEL_LOGS_EXPORT_INTERVAL":   "2500",
			"OTEL_METRIC_EXPORT_INTERVAL": "2500",
		},
	}
	data, err := json.Marshal(initial)
	if err != nil {
		t.Fatalf("marshal Claude settings: %v", err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}

	endpoint := "http://127.0.0.1:4318/v1/logs"
	statePath := filepath.Join(t.TempDir(), "token-telemetry.json")
	for i := 0; i < 2; i++ {
		result, err := enableClaudeTokenTelemetry(path, statePath, endpoint, nil)
		if err != nil {
			t.Fatalf("enableClaudeTokenTelemetry run %d: %v", i+1, err)
		}
		if result.State != "enabled-managed" {
			t.Fatalf("enable state = %q, want enabled-managed", result.State)
		}
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read Claude settings: %v", err)
	}
	var config map[string]any
	if err := json.Unmarshal(out, &config); err != nil {
		t.Fatalf("parse Claude settings: %v", err)
	}
	if config["model"] != "sonnet" {
		t.Fatalf("Claude model setting was lost: %+v", config)
	}
	env := config["env"].(map[string]any)
	for key, want := range map[string]string{
		"EXISTING":                            "preserved",
		"OTEL_METRICS_EXPORTER":               "otlp",
		"OTEL_EXPORTER_OTLP_METRICS_PROTOCOL": "http/protobuf",
		"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://127.0.0.1:4318/v1/metrics",
		"CLAUDE_CODE_ENABLE_TELEMETRY":        "1",
		"CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
		"OTEL_LOGS_EXPORTER":                  "otlp",
		"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL":    "http/protobuf",
		"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT":    endpoint,
		"OTEL_TRACES_EXPORTER":                "otlp",
		"OTEL_EXPORTER_OTLP_TRACES_PROTOCOL":  "http/protobuf",
		"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT":  "http://127.0.0.1:4318/v1/traces",
		"OTEL_LOGS_EXPORT_INTERVAL":           "2500",
		"OTEL_TRACES_EXPORT_INTERVAL":         "1000",
		"OTEL_METRIC_EXPORT_INTERVAL":         "2500",
	} {
		if env[key] != want {
			t.Fatalf("Claude env %s = %#v, want %q: %+v", key, env[key], want, env)
		}
	}
	stateInfo, err := os.Stat(statePath)
	if err != nil {
		t.Fatalf("stat token telemetry ownership: %v", err)
	}
	if stateInfo.Mode().Perm() != 0o600 {
		t.Fatalf("ownership mode = %o, want 600", stateInfo.Mode().Perm())
	}
	result, err := disableClaudeTokenTelemetry(path, statePath, nil)
	if err != nil {
		t.Fatalf("disableClaudeTokenTelemetry: %v", err)
	}
	if result.State != "disabled" {
		t.Fatalf("disable state = %q, want disabled", result.State)
	}
	_, cleanedEnv, _, _, err := readClaudeSettings(path)
	if err != nil {
		t.Fatalf("read cleaned Claude settings: %v", err)
	}
	for key, want := range initial["env"].(map[string]any) {
		if cleanedEnv[key] != want {
			t.Fatalf("cleaned Claude env %s = %#v, want %#v", key, cleanedEnv[key], want)
		}
	}
	if len(cleanedEnv) != len(initial["env"].(map[string]any)) {
		t.Fatalf("cleanup left Obstudio-owned settings: %+v", cleanedEnv)
	}
}

func TestDisableClaudeTokenTelemetryReportsRetainedUserOwnedSettings(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, ".claude", "settings.json")
	statePath := filepath.Join(root, ".obstudio", "token-telemetry.json")
	endpoint := "http://127.0.0.1:4318/v1/logs"
	required, _, err := claudeTokenTelemetrySettings(endpoint)
	if err != nil {
		t.Fatalf("build Claude telemetry settings: %v", err)
	}
	userEnv := make(map[string]any, len(required))
	for _, setting := range required {
		userEnv[setting.key] = setting.value
	}
	initialConfig := map[string]any{"env": userEnv}
	initial, err := json.MarshalIndent(initialConfig, "", "  ")
	if err != nil {
		t.Fatalf("marshal user-owned Claude settings: %v", err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("create Claude config directory: %v", err)
	}
	if err := os.WriteFile(path, append(initial, '\n'), 0o600); err != nil {
		t.Fatalf("write user-owned Claude settings: %v", err)
	}
	if _, err := enableClaudeTokenTelemetry(path, statePath, endpoint, nil); err != nil {
		t.Fatalf("enable Claude token telemetry: %v", err)
	}

	result, err := disableClaudeTokenTelemetry(path, statePath, nil)
	if err != nil {
		t.Fatalf("disable Claude token telemetry: %v", err)
	}
	if result.State != "unmanaged" || !strings.Contains(result.Detail, "user-owned Claude telemetry settings remain configured") {
		t.Fatalf("disable result = %+v, want retained user-owned telemetry", result)
	}
	_, cleanedEnv, _, _, err := readClaudeSettings(path)
	if err != nil {
		t.Fatalf("read cleaned Claude settings: %v", err)
	}
	if !reflect.DeepEqual(cleanedEnv, userEnv) {
		t.Fatalf("user-owned Claude settings changed: got=%+v want=%+v", cleanedEnv, userEnv)
	}
}

func TestEnableClaudeTokenTelemetryPreservesLargeJSONNumbers(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, "settings.json")
	statePath := filepath.Join(root, "state.json")
	initial := `{"maxTurns":9007199254740993,"env":{"EXISTING":"preserved"}}`
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}
	if _, err := enableClaudeTokenTelemetry(path, statePath, "http://127.0.0.1:4318/v1/logs", nil); err != nil {
		t.Fatalf("enable Claude token telemetry: %v", err)
	}
	if _, err := disableClaudeTokenTelemetry(path, statePath, nil); err != nil {
		t.Fatalf("disable Claude token telemetry: %v", err)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read cleaned Claude settings: %v", err)
	}
	if !strings.Contains(string(out), "9007199254740993") {
		t.Fatalf("large user-owned JSON number lost precision: %s", out)
	}
}

func TestEnableClaudeTokenTelemetryRejectsDuplicateJSONKeysWithoutWriting(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "settings.json")
	statePath := filepath.Join(t.TempDir(), "state.json")
	initial := `{"env":{"OTEL_LOGS_EXPORTER":"console","OTEL_LOGS_EXPORTER":"otlp"}}`
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}
	if _, err := enableClaudeTokenTelemetry(path, statePath, "http://127.0.0.1:4318/v1/logs", nil); err == nil || !strings.Contains(err.Error(), "duplicate object key") {
		t.Fatalf("enableClaudeTokenTelemetry() error = %v, want duplicate-key refusal", err)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read preserved Claude settings: %v", err)
	}
	if string(out) != initial {
		t.Fatalf("duplicate-key Claude settings were changed: %s", out)
	}
	if _, err := os.Stat(statePath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("ownership was written for duplicate-key settings: %v", err)
	}
}

func TestEnableClaudeTokenTelemetryReusesMatchingInheritedSettings(t *testing.T) {
	t.Parallel()

	endpoint := "http://127.0.0.1:4318/v1/logs"
	required, defaults, err := claudeTokenTelemetrySettings(endpoint)
	if err != nil {
		t.Fatalf("claudeTokenTelemetrySettings: %v", err)
	}
	inherited := make(map[string]string, len(required)+len(defaults))
	for _, setting := range required {
		inherited[setting.key] = setting.value
	}
	for _, setting := range defaults {
		inherited[setting.key] = "9000"
	}
	lookup := func(key string) (string, bool) {
		value, ok := inherited[key]
		return value, ok
	}
	root := t.TempDir()
	path := filepath.Join(root, ".claude", "settings.json")
	statePath := filepath.Join(root, ".obstudio", "token-telemetry.json")
	result, err := enableClaudeTokenTelemetry(path, statePath, endpoint, lookup)
	if err != nil {
		t.Fatalf("enableClaudeTokenTelemetry: %v", err)
	}
	if result.State != "enabled-existing" {
		t.Fatalf("enable state = %q, want enabled-existing", result.State)
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("matching inherited settings were copied into Claude config: %v", err)
	}
	if _, err := os.Stat(statePath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("matching inherited settings were recorded as Obstudio-owned: %v", err)
	}
}

func TestEnableClaudeTokenTelemetryPreservesSupersededGenericRouting(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, "settings.json")
	statePath := filepath.Join(root, "state.json")
	endpoint := "http://127.0.0.1:4318/v1/logs"
	required, _, err := claudeTokenTelemetrySettings(endpoint)
	if err != nil {
		t.Fatalf("build Claude telemetry settings: %v", err)
	}
	env := make(map[string]any, len(required)+2)
	for _, setting := range required {
		if setting.key == "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA" {
			continue
		}
		env[setting.key] = setting.value
	}
	env["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://corporate.example:4318"
	env["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/json"
	initialConfig := map[string]any{"env": env}
	initial, err := json.MarshalIndent(initialConfig, "", "  ")
	if err != nil {
		t.Fatalf("marshal Claude settings: %v", err)
	}
	if err := os.WriteFile(path, append(initial, '\n'), 0o600); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}

	result, err := enableClaudeTokenTelemetry(path, statePath, endpoint, nil)
	if err != nil {
		t.Fatalf("enable Claude telemetry with explicit signal overrides: %v", err)
	}
	if result.State != "enabled-managed" {
		t.Fatalf("enable state = %+v, want enabled-managed for newly added values", result)
	}
	_, configuredEnv, _, _, err := readClaudeSettings(path)
	if err != nil {
		t.Fatalf("read configured Claude settings: %v", err)
	}
	if configuredEnv["OTEL_EXPORTER_OTLP_ENDPOINT"] != "https://corporate.example:4318" {
		t.Fatalf("generic OTLP endpoint changed: %+v", configuredEnv)
	}
	if configuredEnv["OTEL_EXPORTER_OTLP_PROTOCOL"] != "http/json" {
		t.Fatalf("generic OTLP protocol changed: %+v", configuredEnv)
	}

	if _, err := disableClaudeTokenTelemetry(path, statePath, nil); err != nil {
		t.Fatalf("disable Claude token telemetry: %v", err)
	}
	_, cleanedEnv, _, _, err := readClaudeSettings(path)
	if err != nil {
		t.Fatalf("read cleaned Claude settings: %v", err)
	}
	if _, exists := cleanedEnv["CLAUDE_CODE_ENHANCED_TELEMETRY_BETA"]; exists {
		t.Fatalf("Obstudio-owned setting was retained: %+v", cleanedEnv)
	}
	if cleanedEnv["OTEL_EXPORTER_OTLP_ENDPOINT"] != "https://corporate.example:4318" ||
		cleanedEnv["OTEL_EXPORTER_OTLP_PROTOCOL"] != "http/json" {
		t.Fatalf("user-owned generic routing changed during cleanup: %+v", cleanedEnv)
	}
}

func TestEnableClaudeTokenTelemetryAddsCumulativeTemporalityOnlyWhenAbsent(t *testing.T) {
	t.Parallel()

	const key = "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE"
	endpoint := "http://127.0.0.1:4318/v1/logs"

	t.Run("absent", func(t *testing.T) {
		root := t.TempDir()
		path := filepath.Join(root, "settings.json")
		statePath := filepath.Join(root, "state.json")
		if _, err := enableClaudeTokenTelemetry(path, statePath, endpoint, nil); err != nil {
			t.Fatalf("enable Claude token telemetry: %v", err)
		}
		_, env, _, _, err := readClaudeSettings(path)
		if err != nil {
			t.Fatalf("read Claude settings: %v", err)
		}
		if env[key] != "cumulative" {
			t.Fatalf("%s = %#v, want cumulative", key, env[key])
		}
		ownership, err := readTokenTelemetryOwnership(statePath)
		if err != nil {
			t.Fatalf("read ownership: %v", err)
		}
		if ownership.Targets["claude-code"].Env[key] != "cumulative" {
			t.Fatalf("cumulative temporality was not ownership tracked: %+v", ownership)
		}
		if _, err := disableClaudeTokenTelemetry(path, statePath, nil); err != nil {
			t.Fatalf("disable Claude token telemetry: %v", err)
		}
		_, env, _, _, err = readClaudeSettings(path)
		if err != nil {
			t.Fatalf("read cleaned Claude settings: %v", err)
		}
		if _, exists := env[key]; exists {
			t.Fatalf("owned cumulative temporality was retained: %+v", env)
		}
	})

	t.Run("user-owned delta", func(t *testing.T) {
		root := t.TempDir()
		path := filepath.Join(root, "settings.json")
		statePath := filepath.Join(root, "state.json")
		initial := fmt.Sprintf(`{"env":{%q:"delta"}}`, key)
		if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
			t.Fatalf("write Claude settings: %v", err)
		}
		if _, err := enableClaudeTokenTelemetry(path, statePath, endpoint, nil); err != nil {
			t.Fatalf("enable Claude token telemetry: %v", err)
		}
		_, env, _, _, err := readClaudeSettings(path)
		if err != nil {
			t.Fatalf("read Claude settings: %v", err)
		}
		if env[key] != "delta" {
			t.Fatalf("user-owned temporality changed: %+v", env)
		}
		ownership, err := readTokenTelemetryOwnership(statePath)
		if err != nil {
			t.Fatalf("read ownership: %v", err)
		}
		if _, owned := ownership.Targets["claude-code"].Env[key]; owned {
			t.Fatalf("user-owned temporality was incorrectly adopted: %+v", ownership)
		}
		if _, err := disableClaudeTokenTelemetry(path, statePath, nil); err != nil {
			t.Fatalf("disable Claude token telemetry: %v", err)
		}
		_, env, _, _, err = readClaudeSettings(path)
		if err != nil {
			t.Fatalf("read cleaned Claude settings: %v", err)
		}
		if env[key] != "delta" {
			t.Fatalf("cleanup changed user-owned temporality: %+v", env)
		}
	})
}

func TestEnableClaudeTokenTelemetryUpdatesOnlyOwnedEndpoint(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, ".claude", "settings.json")
	statePath := filepath.Join(root, ".obstudio", "token-telemetry.json")
	firstEndpoint := "http://127.0.0.1:4318/v1/logs"
	secondEndpoint := "http://127.0.0.1:5318/v1/logs"
	if _, err := enableClaudeTokenTelemetry(path, statePath, firstEndpoint, nil); err != nil {
		t.Fatalf("enable first endpoint: %v", err)
	}
	if _, err := enableClaudeTokenTelemetry(path, statePath, secondEndpoint, nil); err != nil {
		t.Fatalf("update owned endpoint: %v", err)
	}
	_, env, _, _, err := readClaudeSettings(path)
	if err != nil {
		t.Fatalf("read Claude settings: %v", err)
	}
	for key, want := range map[string]string{
		"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT":    secondEndpoint,
		"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT":  "http://127.0.0.1:5318/v1/traces",
		"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://127.0.0.1:5318/v1/metrics",
	} {
		if env[key] != want {
			t.Fatalf("Claude setting %s = %#v, want %q", key, env[key], want)
		}
	}
	ownership, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		t.Fatalf("read ownership: %v", err)
	}
	if got := ownership.Targets["claude-code"].Endpoint; got != secondEndpoint {
		t.Fatalf("owned endpoint = %q, want %q", got, secondEndpoint)
	}
}

func TestDisableClaudeTokenTelemetryPreservesModifiedOwnedSetting(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, ".claude", "settings.json")
	statePath := filepath.Join(root, ".obstudio", "token-telemetry.json")
	endpoint := "http://127.0.0.1:4318/v1/logs"
	if _, err := enableClaudeTokenTelemetry(path, statePath, endpoint, nil); err != nil {
		t.Fatalf("enableClaudeTokenTelemetry: %v", err)
	}
	config, env, _, _, err := readClaudeSettings(path)
	if err != nil {
		t.Fatalf("read Claude settings: %v", err)
	}
	env["OTEL_LOGS_EXPORT_INTERVAL"] = "7500"
	config["env"] = env
	data, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		t.Fatalf("marshal Claude settings: %v", err)
	}
	if err := os.WriteFile(path, append(data, '\n'), 0o600); err != nil {
		t.Fatalf("write modified Claude settings: %v", err)
	}
	result, err := disableClaudeTokenTelemetry(path, statePath, nil)
	if err != nil {
		t.Fatalf("disableClaudeTokenTelemetry: %v", err)
	}
	if result.State != "disabled-with-user-changes" {
		t.Fatalf("disable state = %q, want disabled-with-user-changes", result.State)
	}
	_, cleanedEnv, _, _, err := readClaudeSettings(path)
	if err != nil {
		t.Fatalf("read cleaned Claude settings: %v", err)
	}
	if cleanedEnv["OTEL_LOGS_EXPORT_INTERVAL"] != "7500" {
		t.Fatalf("user-modified owned value was removed: %+v", cleanedEnv)
	}
	if _, exists := cleanedEnv["OTEL_LOGS_EXPORTER"]; exists {
		t.Fatalf("unchanged Obstudio-owned values were retained: %+v", cleanedEnv)
	}
}

func TestDisableClaudeTokenTelemetryLeavesUnmanagedSettings(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "settings.json")
	initial := `{"env":{"CLAUDE_CODE_ENABLE_TELEMETRY":"1","OTEL_LOGS_EXPORTER":"otlp"}}`
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}
	result, err := disableClaudeTokenTelemetry(path, filepath.Join(t.TempDir(), "state.json"), nil)
	if err != nil {
		t.Fatalf("disableClaudeTokenTelemetry: %v", err)
	}
	if result.State != "unmanaged" {
		t.Fatalf("disable state = %q, want unmanaged", result.State)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read Claude settings: %v", err)
	}
	if string(out) != initial {
		t.Fatalf("unmanaged Claude settings were changed: %s", out)
	}
}

func TestConfigureClaudeTokenTelemetryPreservesConflictingSettings(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "settings.json")
	initial := `{"env":{"EXISTING":"preserved","OTEL_LOGS_EXPORTER":"console"}}`
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}
	_, err := enableClaudeTokenTelemetry(path, filepath.Join(t.TempDir(), "state.json"), "http://127.0.0.1:4318/v1/logs", nil)
	if err == nil || !strings.Contains(err.Error(), "OTEL_LOGS_EXPORTER") {
		t.Fatalf("expected conflicting Claude setting error, got %v", err)
	}
	out, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatalf("read Claude settings: %v", readErr)
	}
	if string(out) != initial {
		t.Fatalf("conflicting Claude settings were changed: %s", out)
	}
}

func TestEnableClaudeTokenTelemetryPreservesConflictingInheritedSettings(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, "settings.json")
	statePath := filepath.Join(root, "state.json")
	lookup := func(key string) (string, bool) {
		if key == "OTEL_EXPORTER_OTLP_ENDPOINT" {
			return "https://corporate.example:4318", true
		}
		return "", false
	}
	_, err := enableClaudeTokenTelemetry(path, statePath, "http://127.0.0.1:4318/v1/logs", lookup)
	if err == nil || !strings.Contains(err.Error(), "inherited environment") {
		t.Fatalf("enableClaudeTokenTelemetry() error = %v, want inherited routing conflict", err)
	}
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("Claude settings were written after inherited conflict: %v", err)
	}
	if _, err := os.Stat(statePath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("ownership was written after inherited conflict: %v", err)
	}
}

func TestClaudeTokenTelemetryRejectsMalformedOwnershipWithoutWriting(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, "settings.json")
	statePath := filepath.Join(root, "state.json")
	initial := `{"model":"sonnet"}`
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}
	if err := os.WriteFile(statePath, []byte(`{"version":999}`), 0o600); err != nil {
		t.Fatalf("write ownership: %v", err)
	}
	if _, err := enableClaudeTokenTelemetry(path, statePath, "http://127.0.0.1:4318/v1/logs", nil); err == nil || !strings.Contains(err.Error(), "unsupported version") {
		t.Fatalf("enableClaudeTokenTelemetry() error = %v", err)
	}
	if _, err := inspectClaudeTokenTelemetry(path, statePath, "http://127.0.0.1:4318/v1/logs", nil); err == nil || !strings.Contains(err.Error(), "unsupported version") {
		t.Fatalf("inspectClaudeTokenTelemetry() error = %v", err)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read Claude settings: %v", err)
	}
	if string(out) != initial {
		t.Fatalf("Claude settings changed despite malformed ownership: %s", out)
	}
}

func TestConfigureClaudeTokenTelemetryPreservesConflictingTraceSettings(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "settings.json")
	initial := `{"env":{"OTEL_TRACES_EXPORTER":"console"}}`
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}
	_, err := enableClaudeTokenTelemetry(path, filepath.Join(t.TempDir(), "state.json"), "http://127.0.0.1:4318/v1/logs", nil)
	if err == nil || !strings.Contains(err.Error(), "OTEL_TRACES_EXPORTER") {
		t.Fatalf("expected conflicting Claude trace setting error, got %v", err)
	}
	out, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatalf("read Claude settings: %v", readErr)
	}
	if string(out) != initial {
		t.Fatalf("conflicting Claude trace settings were changed: %s", out)
	}
}

func TestConfigureClaudeTokenTelemetryPreservesConflictingMetricSettings(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "settings.json")
	initial := `{"env":{"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT":"https://metrics.example/v1/metrics"}}`
	if err := os.WriteFile(path, []byte(initial), 0o644); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}
	_, err := enableClaudeTokenTelemetry(path, filepath.Join(t.TempDir(), "state.json"), "http://127.0.0.1:4318/v1/logs", nil)
	if err == nil || !strings.Contains(err.Error(), "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT") {
		t.Fatalf("expected conflicting Claude metric setting error, got %v", err)
	}
	out, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatalf("read Claude settings: %v", readErr)
	}
	if string(out) != initial {
		t.Fatalf("conflicting Claude metric settings were changed: %s", out)
	}
}

func TestEnableClaudeTokenTelemetryPreservesSignalSpecificTLSRouting(t *testing.T) {
	t.Parallel()

	for _, key := range []string{
		"CLAUDE_CODE_CLIENT_CERT",
		"CLAUDE_CODE_CLIENT_KEY",
		"CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
		"OTEL_EXPORTER_OTLP_LOGS_CERTIFICATE",
		"OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE",
		"OTEL_EXPORTER_OTLP_METRICS_CLIENT_KEY",
	} {
		t.Run(key, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "settings.json")
			initial := fmt.Sprintf(`{"env":{%q:"/user-owned/credential.pem"}}`, key)
			if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
				t.Fatalf("write Claude settings: %v", err)
			}
			_, err := enableClaudeTokenTelemetry(
				path,
				filepath.Join(t.TempDir(), "state.json"),
				"http://127.0.0.1:4318/v1/logs",
				nil,
			)
			if err == nil || !strings.Contains(err.Error(), key) {
				t.Fatalf("enableClaudeTokenTelemetry() error = %v, want %s routing conflict", err, key)
			}
			out, readErr := os.ReadFile(path)
			if readErr != nil {
				t.Fatalf("read Claude settings: %v", readErr)
			}
			if string(out) != initial {
				t.Fatalf("Claude TLS routing was changed: %s", out)
			}
		})
	}
}

func TestEnableClaudeTokenTelemetryPreservesDynamicHeadersHelper(t *testing.T) {
	t.Parallel()

	root := t.TempDir()
	path := filepath.Join(root, "settings.json")
	statePath := filepath.Join(root, "state.json")
	initial := `{"otelHeadersHelper":"/usr/local/bin/corporate-otel-headers"}`
	if err := os.WriteFile(path, []byte(initial), 0o600); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}
	_, err := enableClaudeTokenTelemetry(path, statePath, "http://127.0.0.1:4318/v1/logs", nil)
	if err == nil || !strings.Contains(err.Error(), "otelHeadersHelper") {
		t.Fatalf("enableClaudeTokenTelemetry() error = %v, want dynamic headers conflict", err)
	}
	out, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatalf("read Claude settings: %v", readErr)
	}
	if string(out) != initial {
		t.Fatalf("Claude dynamic headers configuration was changed: %s", out)
	}
	if _, statErr := os.Stat(statePath); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("ownership was written after dynamic headers conflict: %v", statErr)
	}
}

func TestEnableClaudeTokenTelemetryHonorsDisabledOTelSDK(t *testing.T) {
	t.Parallel()

	for _, tc := range []struct {
		name    string
		initial string
		lookup  func(string) (string, bool)
	}{
		{name: "Claude setting", initial: `{"env":{"OTEL_SDK_DISABLED":"true"}}`},
		{
			name:    "inherited environment",
			initial: `{}`,
			lookup: func(key string) (string, bool) {
				if key == "OTEL_SDK_DISABLED" {
					return "1", true
				}
				return "", false
			},
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := t.TempDir()
			path := filepath.Join(root, "settings.json")
			statePath := filepath.Join(root, "state.json")
			if err := os.WriteFile(path, []byte(tc.initial), 0o600); err != nil {
				t.Fatalf("write Claude settings: %v", err)
			}
			_, err := enableClaudeTokenTelemetry(path, statePath, "http://127.0.0.1:4318/v1/logs", tc.lookup)
			if err == nil || !strings.Contains(err.Error(), "OTEL_SDK_DISABLED") {
				t.Fatalf("enableClaudeTokenTelemetry() error = %v, want disabled SDK conflict", err)
			}
			out, readErr := os.ReadFile(path)
			if readErr != nil {
				t.Fatalf("read Claude settings: %v", readErr)
			}
			if string(out) != tc.initial {
				t.Fatalf("Claude settings were changed while OTel was disabled: %s", out)
			}
			if _, statErr := os.Stat(statePath); !errors.Is(statErr, os.ErrNotExist) {
				t.Fatalf("ownership was written while OTel was disabled: %v", statErr)
			}
		})
	}
}

func TestEnableClaudeTokenTelemetryNeverOverridesExistingOTLPRouting(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "settings.json")
	initial := map[string]any{
		"model": "sonnet",
		"env": map[string]any{
			"EXISTING":                            "preserved",
			"BETA_TRACING_ENDPOINT":               "https://corporate.example/v1/traces",
			"OTEL_EXPORTER_OTLP_ENDPOINT":         "https://corporate.example/v1/otlp",
			"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "https://corporate.example/v1/metrics",
			"OTEL_EXPORTER_OTLP_METRICS_PROTOCOL": "grpc",
			"OTEL_METRICS_EXPORTER":               "console",
			"OTEL_LOGS_EXPORTER":                  "console",
			"OTEL_TRACES_EXPORTER":                "console",
			"OTEL_LOGS_EXPORT_INTERVAL":           "60000",
			"OTEL_TRACES_EXPORT_INTERVAL":         "60000",
			"OTEL_METRIC_EXPORT_INTERVAL":         "60000",
		},
	}
	data, err := json.Marshal(initial)
	if err != nil {
		t.Fatalf("marshal Claude settings: %v", err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatalf("write Claude settings: %v", err)
	}
	statePath := filepath.Join(t.TempDir(), "state.json")
	_, err = enableClaudeTokenTelemetry(path, statePath, "http://127.0.0.1:4318/v1/logs", nil)
	if err == nil || !strings.Contains(err.Error(), "another value") {
		t.Fatalf("enableClaudeTokenTelemetry() error = %v, want conflict", err)
	}
	out, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read Claude settings: %v", err)
	}
	if string(out) != string(data) {
		t.Fatalf("conflicting Claude settings were changed:\n%s", out)
	}
	if _, err := os.Stat(statePath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("ownership state was written after conflict: %v", err)
	}
}

func TestTokenTelemetryCommandHasNoForceOption(t *testing.T) {
	t.Parallel()

	command := newTokenTelemetryEnableCommand()
	if flag := command.Flags().Lookup("force"); flag != nil {
		t.Fatalf("unsafe force flag is registered: %+v", flag)
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

func TestNormalizeTokenTelemetryTargets(t *testing.T) {
	t.Parallel()

	targets, err := normalizeTokenTelemetryTargets([]string{"codex,claude-code", "codex"})
	if err != nil {
		t.Fatalf("normalizeTokenTelemetryTargets: %v", err)
	}
	if got := strings.Join(targets, ","); got != "codex,claude-code" {
		t.Fatalf("targets = %q, want codex,claude-code", got)
	}
	if _, err := normalizeTokenTelemetryTargets([]string{"cursor"}); err == nil || !strings.Contains(err.Error(), "unsupported") {
		t.Fatalf("unsupported target error = %v", err)
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
	if command, _, err := root.Find([]string{"token-telemetry"}); err != nil || command == nil || command.Name() != "token-telemetry" {
		t.Fatalf("expected token-telemetry command, got command=%v err=%v", command, err)
	}
}

func TestResolveRunConfigAllowsLoopbackGRPCWithWildcardHTTP(t *testing.T) {
	t.Setenv("HOST", "0.0.0.0")
	t.Setenv("PORT", "3000")
	t.Setenv("OTLP_HTTP_PORT", "4318")
	t.Setenv("OTLP_GRPC_HOST", "127.0.0.1")
	t.Setenv("OTLP_GRPC_PORT", "4317")

	config := resolveRunConfig(runConfig{})
	if config.host != "0.0.0.0" {
		t.Fatalf("host = %q, want 0.0.0.0", config.host)
	}
	if config.otlpGRPCHost != "127.0.0.1" {
		t.Fatalf("otlpGRPCHost = %q, want 127.0.0.1", config.otlpGRPCHost)
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

	if err := upsertJSONMCPServer(path, "mcpServers", map[string]any{
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

func TestConfigureMCPAddsAuthenticatedRemoteHeaderAndPreservesKiroHeaders(t *testing.T) {
	t.Parallel()

	const mcpURL = "http://127.0.0.1:3000/mcp"
	configPath := filepath.Join(t.TempDir(), "mcp.json")
	initial := map[string]any{
		"mcpServers": map[string]any{
			"obstudio": map[string]any{
				"url": mcpURL,
				"headers": map[string]string{
					"authorization":   "Bearer stale-token",
					"X-Observer-Test": "preserved",
				},
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
	if err := configureMCP(target, "/tmp/obstudio", mcpURL, "new-control-token"); err != nil {
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
	headers, ok := config.MCPServers["obstudio"]["headers"].(map[string]any)
	if !ok {
		t.Fatalf("Kiro headers = %#v, want object", config.MCPServers["obstudio"]["headers"])
	}
	authorizationCount := 0
	for name, value := range headers {
		if strings.EqualFold(name, "Authorization") {
			authorizationCount++
			if value != "Bearer new-control-token" {
				t.Fatalf("Authorization = %#v, want refreshed bearer token", value)
			}
		}
	}
	if authorizationCount != 1 {
		t.Fatalf("Authorization header count = %d, want 1 in %#v", authorizationCount, headers)
	}
	if got := headers["X-Observer-Test"]; got != "preserved" {
		t.Fatalf("custom header = %#v, want preserved", got)
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(configPath)
		if err != nil {
			t.Fatalf("stat Kiro MCP config: %v", err)
		}
		if mode := info.Mode().Perm(); mode != 0o600 {
			t.Fatalf("authenticated MCP config mode = %#o, want 0600", mode)
		}
	}
	entries, err := os.ReadDir(filepath.Dir(configPath))
	if err != nil {
		t.Fatalf("read Kiro config directory: %v", err)
	}
	if len(entries) != 1 || entries[0].Name() != filepath.Base(configPath) {
		t.Fatalf("authenticated JSON config left temporary files: %#v", entries)
	}
}

func TestConfigureMCPRefreshPreservesJSONHeadersForEveryTarget(t *testing.T) {
	t.Parallel()

	const mcpURL = "http://127.0.0.1:3000/mcp"
	for _, targetName := range []string{"claude-code", "cursor", "windsurf", "copilot", "kiro"} {
		targetName := targetName
		t.Run(targetName, func(t *testing.T) {
			t.Parallel()

			configPath := filepath.Join(t.TempDir(), "mcp.json")
			target := targets[targetName].mcpConfig
			initial := map[string]any{
				string(target.serversKey): map[string]any{
					"obstudio": map[string]any{
						"url": mcpURL,
						"headers": map[string]any{
							"authorization":   "Bearer stale-token",
							"X-Observer-Test": "preserved",
						},
					},
				},
			}
			data, err := json.Marshal(initial)
			if err != nil {
				t.Fatalf("marshal initial %s MCP config: %v", targetName, err)
			}
			if err := os.WriteFile(configPath, data, 0o600); err != nil {
				t.Fatalf("write initial %s MCP config: %v", targetName, err)
			}

			target.path = func() string { return configPath }
			if err := configureMCP(target, "/tmp/obstudio", mcpURL, "new-control-token"); err != nil {
				t.Fatalf("configureMCP returned error: %v", err)
			}

			data, err = os.ReadFile(configPath)
			if err != nil {
				t.Fatalf("read %s MCP config: %v", targetName, err)
			}
			var config map[string]any
			if err := json.Unmarshal(data, &config); err != nil {
				t.Fatalf("unmarshal %s MCP config: %v", targetName, err)
			}
			servers, ok := config[string(target.serversKey)].(map[string]any)
			if !ok {
				t.Fatalf("%s server collection = %#v, want object", targetName, config[string(target.serversKey)])
			}
			server, ok := servers["obstudio"].(map[string]any)
			if !ok {
				t.Fatalf("%s obstudio server = %#v, want object", targetName, servers["obstudio"])
			}
			headers, ok := server["headers"].(map[string]any)
			if !ok {
				t.Fatalf("%s headers = %#v, want object", targetName, server["headers"])
			}
			authorizationCount := 0
			for name, value := range headers {
				if strings.EqualFold(name, "Authorization") {
					authorizationCount++
					if value != "Bearer new-control-token" {
						t.Fatalf("%s Authorization = %#v, want refreshed bearer token", targetName, value)
					}
				}
			}
			if authorizationCount != 1 {
				t.Fatalf("%s Authorization count = %d, want 1 in %#v", targetName, authorizationCount, headers)
			}
			if got := headers["X-Observer-Test"]; got != "preserved" {
				t.Fatalf("%s custom header = %#v, want preserved", targetName, got)
			}
		})
	}
}

func TestConfigureCodexMCPRefreshPreservesSameURLHeaders(t *testing.T) {
	t.Parallel()

	const mcpURL = "http://127.0.0.1:3000/mcp"
	tests := []struct {
		name    string
		content string
		want    string
	}{
		{
			name: "inline table",
			content: strings.Join([]string{
				`model = "gpt-5.4"`,
				``,
				`[mcp_servers.obstudio]`,
				`enabled = true`,
				`url = "` + mcpURL + `"`,
				`http_headers = { authorization = "Bearer stale-token", "X-Observer-Test" = 'preserved' }`,
				`enabled_tools = [`,
				`  "observer_status",`,
				`]`,
				``,
			}, "\n"),
			want: `"X-Observer-Test" = 'preserved'`,
		},
		{
			name: "header subtable",
			content: strings.Join([]string{
				`model = "gpt-5.4"`,
				``,
				`[mcp_servers.obstudio]`,
				`enabled = true`,
				`url = "` + mcpURL + `"`,
				``,
				`[mcp_servers.obstudio.http_headers]`,
				`authorization = "Bearer stale-token"`,
				`X-Observer-Test = "preserved"`,
				``,
			}, "\n"),
			want: `X-Observer-Test = "preserved"`,
		},
		{
			name: "quoted server table key",
			content: strings.Join([]string{
				`model = "gpt-5.4"`,
				``,
				`[mcp_servers."obstudio"]`,
				`enabled = true`,
				`url = "` + mcpURL + `"`,
				`http_headers = { authorization = "Bearer stale-token", "X-Observer-Test" = 'preserved' }`,
				``,
			}, "\n"),
			want: `"X-Observer-Test" = 'preserved'`,
		},
		{
			name: "whitespace separated header table key",
			content: strings.Join([]string{
				`model = "gpt-5.4"`,
				``,
				`[mcp_servers . obstudio]`,
				`enabled = true`,
				`url = "` + mcpURL + `"`,
				``,
				`[mcp_servers . obstudio . http_headers]`,
				`authorization = "Bearer stale-token"`,
				`X-Observer-Test = "preserved"`,
				``,
			}, "\n"),
			want: `X-Observer-Test = "preserved"`,
		},
	}

	for _, test := range tests {
		test := test
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()

			configPath := filepath.Join(t.TempDir(), "config.toml")
			if err := os.WriteFile(configPath, []byte(test.content), 0o600); err != nil {
				t.Fatalf("write initial Codex MCP config: %v", err)
			}
			target := targets["codex"].mcpConfig
			target.path = func() string { return configPath }
			if err := configureMCP(target, "/tmp/obstudio", mcpURL, "new-control-token"); err != nil {
				t.Fatalf("configureMCP returned error: %v", err)
			}

			data, err := os.ReadFile(configPath)
			if err != nil {
				t.Fatalf("read Codex MCP config: %v", err)
			}
			text := string(data)
			if !strings.Contains(text, test.want) {
				t.Fatalf("custom Codex header was not preserved; want %q in:\n%s", test.want, text)
			}
			if strings.Contains(text, "stale-token") {
				t.Fatalf("stale Codex Authorization was preserved:\n%s", text)
			}
			if strings.Count(strings.ToLower(text), "authorization") != 1 ||
				!strings.Contains(text, `Authorization = "Bearer new-control-token"`) {
				t.Fatalf("Codex Authorization was not replaced exactly once:\n%s", text)
			}
		})
	}
}

func TestConfigureCodexMCPReplacesLocalServerWithMultilineArgs(t *testing.T) {
	t.Parallel()

	const mcpURL = "http://127.0.0.1:3000/mcp"
	configPath := filepath.Join(t.TempDir(), "config.toml")
	original := strings.Join([]string{
		`[mcp_servers.obstudio]`,
		`command = "/tmp/old-obstudio"`,
		`args = [`,
		`  "--stdio",`,
		`]`,
		``,
	}, "\n")
	if err := os.WriteFile(configPath, []byte(original), 0o644); err != nil {
		t.Fatalf("write initial Codex MCP config: %v", err)
	}
	target := targets["codex"].mcpConfig
	target.path = func() string { return configPath }
	if err := configureMCP(target, "/tmp/obstudio", mcpURL, "new-control-token"); err != nil {
		t.Fatalf("configureMCP returned error: %v", err)
	}
	data, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("read Codex MCP config: %v", err)
	}
	text := string(data)
	if !strings.Contains(text, `url = "`+mcpURL+`"`) || strings.Contains(text, `--stdio`) {
		t.Fatalf("Codex local server was not replaced with the remote server:\n%s", text)
	}
}

func TestConfigureCodexMCPRejectsUnsafeHeaderSyntaxWithoutWriting(t *testing.T) {
	t.Parallel()

	const mcpURL = "http://127.0.0.1:3000/mcp"
	tests := []struct {
		name    string
		content string
	}{
		{
			name: "unquoted inline value",
			content: strings.Join([]string{
				`[mcp_servers.obstudio]`,
				`url = "` + mcpURL + `"`,
				`http_headers = { X-Observer-Test = unquoted }`,
				``,
			}, "\n"),
		},
		{
			name: "unquoted subtable value",
			content: strings.Join([]string{
				`[mcp_servers.obstudio]`,
				`url = "` + mcpURL + `"`,
				``,
				`[mcp_servers.obstudio.http_headers]`,
				`X-Observer-Test = unquoted`,
				``,
			}, "\n"),
		},
		{
			name: "ambiguous inline and subtable forms",
			content: strings.Join([]string{
				`[mcp_servers.obstudio]`,
				`url = "` + mcpURL + `"`,
				`http_headers = { X-Inline = "preserved" }`,
				``,
				`[mcp_servers.obstudio.http_headers]`,
				`X-Table = "preserved"`,
				``,
			}, "\n"),
		},
	}

	for _, test := range tests {
		test := test
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()

			configPath := filepath.Join(t.TempDir(), "config.toml")
			original := []byte(test.content)
			if err := os.WriteFile(configPath, original, 0o600); err != nil {
				t.Fatalf("write initial Codex MCP config: %v", err)
			}
			target := targets["codex"].mcpConfig
			target.path = func() string { return configPath }
			if err := configureMCP(target, "/tmp/obstudio", mcpURL, "new-control-token"); err == nil {
				t.Fatal("configureMCP unexpectedly accepted unsafe Codex header syntax")
			}
			got, err := os.ReadFile(configPath)
			if err != nil {
				t.Fatalf("read preserved Codex MCP config: %v", err)
			}
			if !bytes.Equal(got, original) {
				t.Fatalf("failed Codex refresh changed existing config:\n%s", got)
			}
		})
	}
}

func TestConfigureMCPRemovesSameURLKiroAuthorizationWithoutVerifiedReplacement(t *testing.T) {
	t.Parallel()

	const mcpURL = "http://127.0.0.1:3000/mcp"
	configPath := filepath.Join(t.TempDir(), "mcp.json")
	initial := map[string]any{
		"mcpServers": map[string]any{
			"obstudio": map[string]any{
				"url": mcpURL,
				"headers": map[string]string{
					"authorization":   "Bearer stale-token",
					"X-Observer-Test": "preserved",
				},
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
	headers, ok := config.MCPServers["obstudio"]["headers"].(map[string]any)
	if !ok {
		t.Fatalf("Kiro headers = %#v, want preserved custom headers", config.MCPServers["obstudio"]["headers"])
	}
	for name := range headers {
		if strings.EqualFold(name, "Authorization") {
			t.Fatalf("stale Authorization header was preserved in %#v", headers)
		}
	}
	if got := headers["X-Observer-Test"]; got != "preserved" {
		t.Fatalf("custom header = %#v, want preserved", got)
	}
}

func TestAuthenticatedJSONConfigWriteFailurePreservesExistingFile(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("directory permission failure is not reliable on Windows")
	}
	t.Parallel()

	directory := t.TempDir()
	configPath := filepath.Join(directory, "mcp.json")
	original := []byte(`{"mcpServers":{"other":{"url":"https://example.com/mcp"}}}`)
	if err := os.WriteFile(configPath, original, 0o600); err != nil {
		t.Fatalf("write original JSON config: %v", err)
	}
	if err := os.Chmod(directory, 0o500); err != nil {
		t.Fatalf("make JSON config directory read-only: %v", err)
	}
	defer os.Chmod(directory, 0o700)

	target := targets["kiro"].mcpConfig
	target.path = func() string { return configPath }
	err := configureMCP(target, "/tmp/obstudio", "http://127.0.0.1:3000/mcp", "control-token")
	if err == nil {
		t.Fatal("authenticated JSON config write unexpectedly succeeded")
	}
	got, readErr := os.ReadFile(configPath)
	if readErr != nil {
		t.Fatalf("read preserved JSON config: %v", readErr)
	}
	if !bytes.Equal(got, original) {
		t.Fatalf("failed atomic JSON write changed existing config: %q", got)
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

func TestConfigureCodexMCPAddsAuthenticatedRemoteHeader(t *testing.T) {
	t.Parallel()

	configPath := filepath.Join(t.TempDir(), "config.toml")
	target := targets["codex"].mcpConfig
	target.path = func() string { return configPath }
	if err := configureMCP(target, "/tmp/obstudio", "http://127.0.0.1:3000/mcp", "control-token"); err != nil {
		t.Fatalf("configureMCP returned error: %v", err)
	}
	data, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("read Codex MCP config: %v", err)
	}
	if !strings.Contains(string(data), `http_headers = { Authorization = "Bearer control-token" }`) {
		t.Fatalf("Codex MCP config is missing its authorization header:\n%s", data)
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(configPath)
		if err != nil {
			t.Fatalf("stat Codex MCP config: %v", err)
		}
		if mode := info.Mode().Perm(); mode != 0o600 {
			t.Fatalf("authenticated Codex MCP config mode = %#o, want 0600", mode)
		}
	}
	entries, err := os.ReadDir(filepath.Dir(configPath))
	if err != nil {
		t.Fatalf("read Codex config directory: %v", err)
	}
	if len(entries) != 1 || entries[0].Name() != filepath.Base(configPath) {
		t.Fatalf("authenticated Codex config left temporary files: %#v", entries)
	}
}

func TestAuthenticatedCodexConfigWriteFailurePreservesExistingFile(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("directory permission failure is not reliable on Windows")
	}
	t.Parallel()

	directory := t.TempDir()
	configPath := filepath.Join(directory, "config.toml")
	original := []byte("model = \"gpt-5.6\"\n")
	if err := os.WriteFile(configPath, original, 0o600); err != nil {
		t.Fatalf("write original Codex config: %v", err)
	}
	if err := os.Chmod(directory, 0o500); err != nil {
		t.Fatalf("make Codex config directory read-only: %v", err)
	}
	defer os.Chmod(directory, 0o700)

	target := targets["codex"].mcpConfig
	target.path = func() string { return configPath }
	err := configureMCP(target, "/tmp/obstudio", "http://127.0.0.1:3000/mcp", "control-token")
	if err == nil {
		t.Fatal("authenticated Codex config write unexpectedly succeeded")
	}
	got, readErr := os.ReadFile(configPath)
	if readErr != nil {
		t.Fatalf("read preserved Codex config: %v", readErr)
	}
	if !bytes.Equal(got, original) {
		t.Fatalf("failed atomic Codex write changed existing config: %q", got)
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
		{name: "IPv4 loopback HTTP", raw: "http://127.0.0.1:3000/mcp"},
		{name: "IPv4 loopback range HTTP", raw: "http://127.255.255.254:3000/mcp"},
		{name: "IPv6 loopback HTTP", raw: "http://[::1]:3000/mcp"},
		{name: "localhost HTTP", raw: "http://localhost:3000/mcp"},
		{name: "normalized localhost HTTP", raw: "http://LOCALHOST.:3000/mcp"},
		{name: "remote HTTPS", raw: "https://example.com/mcp"},
		{name: "missing scheme", raw: "127.0.0.1:3000/mcp", wantErr: true},
		{name: "missing host", raw: "http:///mcp", wantErr: true},
		{name: "wrong scheme", raw: "stdio://obstudio", wantErr: true},
		{name: "remote HTTP", raw: "http://example.com/mcp", wantErr: true},
		{name: "private network HTTP", raw: "http://10.0.0.1/mcp", wantErr: true},
		{name: "localhost lookalike HTTP", raw: "http://localhost.example.com/mcp", wantErr: true},
		{name: "loopback lookalike HTTP", raw: "http://127.0.0.1.example.com/mcp", wantErr: true},
		{name: "IPv6 non-loopback HTTP", raw: "http://[::2]/mcp", wantErr: true},
		{name: "ambiguous IPv4 shorthand HTTP", raw: "http://127.1:3000/mcp", wantErr: true},
		{name: "userinfo", raw: "https://user:password@example.com/mcp", wantErr: true},
		{name: "empty userinfo", raw: "https://@example.com/mcp", wantErr: true},
		{name: "fragment", raw: "https://example.com/mcp#token", wantErr: true},
		{name: "empty fragment", raw: "https://example.com/mcp#", wantErr: true},
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

func TestConfigureMCPRejectsInsecureSharedURLBeforeWritingToken(t *testing.T) {
	t.Parallel()

	configPath := filepath.Join(t.TempDir(), "mcp.json")
	target := mcpConfigTarget{
		format:     mcpConfigJSON,
		path:       func() string { return configPath },
		serversKey: "mcpServers",
	}
	err := configureMCP(target, "/tmp/obstudio", "http://observer.example.com/mcp", "must-not-be-written")
	if err == nil || !strings.Contains(err.Error(), "must use HTTPS") {
		t.Fatalf("configureMCP() error = %v, want HTTPS validation error", err)
	}
	if _, statErr := os.Stat(configPath); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("insecure shared URL unexpectedly wrote config: %v", statErr)
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

func TestDetectSharedObserverURLRejectsInsecureAdvertisedEndpoint(t *testing.T) {
	t.Parallel()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			Endpoints: map[string]string{
				"mcp": "http://observer.example.com/mcp",
			},
		})
	}))
	defer server.Close()

	if detected, ok := detectSharedObserverURL(server.URL, server.Client()); ok {
		t.Fatalf("expected insecure endpoint to be rejected, got %s", detected)
	}
}

func TestDetectSharedObserverURLRejectsInsecureRedirect(t *testing.T) {
	t.Parallel()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "http://observer.example.com/api/health", http.StatusFound)
	}))
	defer server.Close()

	if detected, ok := detectSharedObserverURL(server.URL, server.Client()); ok {
		t.Fatalf("expected insecure health redirect to be rejected, got %s", detected)
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

func TestCreateSkillSymlinksMigratesConflictingDirectoryOnce(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink tests are not reliable on Windows without elevated privileges")
	}
	t.Parallel()

	skillsRoot := t.TempDir()
	obstudioDir := filepath.Join(skillsRoot, "obstudio")
	bundledSkill := filepath.Join(obstudioDir, "otel-audit")
	if err := os.MkdirAll(bundledSkill, 0o755); err != nil {
		t.Fatalf("mkdir bundled skill: %v", err)
	}
	if err := os.WriteFile(filepath.Join(bundledSkill, "SKILL.md"), []byte("bundled"), 0o644); err != nil {
		t.Fatalf("write bundled SKILL.md: %v", err)
	}

	conflictingSkill := filepath.Join(skillsRoot, "otel-audit")
	if err := os.MkdirAll(conflictingSkill, 0o755); err != nil {
		t.Fatalf("mkdir conflicting skill: %v", err)
	}
	if err := os.WriteFile(filepath.Join(conflictingSkill, "user-file.txt"), []byte("preserve me"), 0o644); err != nil {
		t.Fatalf("write conflicting skill file: %v", err)
	}

	if err := createSkillSymlinks(skillsRoot, obstudioDir); err != nil {
		t.Fatalf("createSkillSymlinks with conflict: %v", err)
	}

	dest, err := os.Readlink(conflictingSkill)
	if err != nil {
		t.Fatalf("read migrated skill link: %v", err)
	}
	if dest != filepath.Join("obstudio", "otel-audit") {
		t.Fatalf("migrated skill target = %q, want %q", dest, filepath.Join("obstudio", "otel-audit"))
	}

	backup := filepath.Join(skillsRoot, skillBackupDirName, "otel-audit")
	data, err := os.ReadFile(filepath.Join(backup, "user-file.txt"))
	if err != nil {
		t.Fatalf("read preserved conflicting skill: %v", err)
	}
	if string(data) != "preserve me" {
		t.Fatalf("preserved conflicting skill = %q, want %q", data, "preserve me")
	}

	// Simulate the next upgrade: the managed link is removed and recreated,
	// while the one-time backup remains unchanged.
	removeSkillSymlinks(skillsRoot, obstudioDir)
	if err := createSkillSymlinks(skillsRoot, obstudioDir); err != nil {
		t.Fatalf("createSkillSymlinks on second upgrade: %v", err)
	}

	backupEntries, err := os.ReadDir(filepath.Join(skillsRoot, skillBackupDirName))
	if err != nil {
		t.Fatalf("read skill backups: %v", err)
	}
	if len(backupEntries) != 1 || backupEntries[0].Name() != "otel-audit" {
		t.Fatalf("skill backups after second upgrade = %v, want only otel-audit", backupEntries)
	}

	// If another non-managed path later appears at the same location, keep both
	// it and the original backup instead of accumulating or overwriting backups.
	if err := os.Remove(conflictingSkill); err != nil {
		t.Fatalf("remove managed skill link: %v", err)
	}
	if err := os.Mkdir(conflictingSkill, 0o755); err != nil {
		t.Fatalf("mkdir second conflicting skill: %v", err)
	}
	if err := os.WriteFile(filepath.Join(conflictingSkill, "second.txt"), []byte("second"), 0o644); err != nil {
		t.Fatalf("write second conflicting skill file: %v", err)
	}

	if err := createSkillSymlinks(skillsRoot, obstudioDir); err != nil {
		t.Fatalf("createSkillSymlinks with second conflict: %v", err)
	}
	if _, err := os.Stat(filepath.Join(conflictingSkill, "second.txt")); err != nil {
		t.Fatalf("second conflicting skill was modified: %v", err)
	}
	if _, err := os.Stat(filepath.Join(backup, "user-file.txt")); err != nil {
		t.Fatalf("original skill backup was modified: %v", err)
	}
}

func TestCreateSkillSymlinksRestoresConflictWhenSymlinkFails(t *testing.T) {
	t.Parallel()

	skillsRoot := t.TempDir()
	obstudioDir := filepath.Join(skillsRoot, "obstudio")
	bundledSkill := filepath.Join(obstudioDir, "otel-audit")
	if err := os.MkdirAll(bundledSkill, 0o755); err != nil {
		t.Fatalf("mkdir bundled skill: %v", err)
	}
	if err := os.WriteFile(filepath.Join(bundledSkill, "SKILL.md"), []byte("bundled"), 0o644); err != nil {
		t.Fatalf("write bundled SKILL.md: %v", err)
	}

	conflictingSkill := filepath.Join(skillsRoot, "otel-audit")
	if err := os.Mkdir(conflictingSkill, 0o755); err != nil {
		t.Fatalf("mkdir conflicting skill: %v", err)
	}
	if err := os.WriteFile(filepath.Join(conflictingSkill, "user-file.txt"), []byte("preserve me"), 0o644); err != nil {
		t.Fatalf("write conflicting skill file: %v", err)
	}

	symlinkErr := errors.New("forced symlink failure")
	err := createSkillSymlinksWith(
		skillsRoot,
		obstudioDir,
		func(string, string) error { return symlinkErr },
	)
	if !errors.Is(err, symlinkErr) {
		t.Fatalf("createSkillSymlinksWith error = %v, want %v", err, symlinkErr)
	}

	data, err := os.ReadFile(filepath.Join(conflictingSkill, "user-file.txt"))
	if err != nil {
		t.Fatalf("read restored conflicting skill: %v", err)
	}
	if string(data) != "preserve me" {
		t.Fatalf("restored conflicting skill = %q, want %q", data, "preserve me")
	}

	backup := filepath.Join(skillsRoot, skillBackupDirName, "otel-audit")
	if _, err := os.Lstat(backup); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("skill backup remains after rollback: %v", err)
	}
}

func TestCreateSkillSymlinksPreservesRelativeSymlinkTarget(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink tests are not reliable on Windows without elevated privileges")
	}
	t.Parallel()

	skillsRoot := t.TempDir()
	obstudioDir := filepath.Join(skillsRoot, "obstudio")
	bundledSkill := filepath.Join(obstudioDir, "otel-audit")
	if err := os.MkdirAll(bundledSkill, 0o755); err != nil {
		t.Fatalf("mkdir bundled skill: %v", err)
	}
	if err := os.WriteFile(filepath.Join(bundledSkill, "SKILL.md"), []byte("bundled"), 0o644); err != nil {
		t.Fatalf("write bundled SKILL.md: %v", err)
	}

	customSkill := filepath.Join(skillsRoot, "custom", "otel-audit")
	if err := os.MkdirAll(customSkill, 0o755); err != nil {
		t.Fatalf("mkdir custom skill: %v", err)
	}
	if err := os.WriteFile(filepath.Join(customSkill, "user-file.txt"), []byte("preserve me"), 0o644); err != nil {
		t.Fatalf("write custom skill file: %v", err)
	}

	conflictingSkill := filepath.Join(skillsRoot, "otel-audit")
	if err := os.Symlink(filepath.Join("custom", "otel-audit"), conflictingSkill); err != nil {
		t.Fatalf("create conflicting relative symlink: %v", err)
	}

	if err := createSkillSymlinks(skillsRoot, obstudioDir); err != nil {
		t.Fatalf("createSkillSymlinks with relative symlink conflict: %v", err)
	}

	backup := filepath.Join(skillsRoot, skillBackupDirName, "otel-audit")
	target, err := filepath.EvalSymlinks(backup)
	if err != nil {
		t.Fatalf("resolve preserved relative symlink: %v", err)
	}
	wantTarget, err := filepath.EvalSymlinks(customSkill)
	if err != nil {
		t.Fatalf("resolve custom skill: %v", err)
	}
	if target != wantTarget {
		t.Fatalf("preserved relative symlink target = %q, want %q", target, wantTarget)
	}
	if data, err := os.ReadFile(filepath.Join(backup, "user-file.txt")); err != nil {
		t.Fatalf("read preserved relative symlink target: %v", err)
	} else if string(data) != "preserve me" {
		t.Fatalf("preserved relative symlink file = %q, want %q", data, "preserve me")
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

	const controlToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mcpURL := server.URL + "/mcp"
		challenge := r.URL.Query().Get(api.HealthProofChallengeQuery)
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:           "obstudio",
			APIVersion:     "v1",
			ChallengeProof: api.HealthChallengeProof(testHealthProofSecret, controlToken, challenge, mcpURL),
			Endpoints:      map[string]string{"mcp": mcpURL},
		})
	}))
	defer server.Close()

	statePath := filepath.Join(t.TempDir(), "shared-observer.json")
	err := writeSharedObserverState(statePath, sharedObserverState{
		ControlToken:      controlToken,
		HealthProofSecret: testHealthProofSecret,
		HealthURL:         server.URL,
		MCPURL:            server.URL + "/mcp",
		PID:               42,
	})
	if err != nil {
		t.Fatalf("writeSharedObserverState returned error: %v", err)
	}

	detected, detectedToken, ok := detectSharedObserverURLFromStateFile(statePath, server.Client())
	if !ok {
		t.Fatal("expected state-file discovery to succeed")
	}
	if want := server.URL + "/mcp"; detected != want {
		t.Fatalf("detectSharedObserverURLFromStateFile = %q, want %q", detected, want)
	}
	if detectedToken != controlToken {
		t.Fatalf("detected control token = %q, want %q", detectedToken, controlToken)
	}
}

func TestDetectSharedObserverURLFromStateFileRejectsSpoofedHealth(t *testing.T) {
	t.Parallel()

	const staleControlToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	const impostorControlToken = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mcpURL := server.URL + "/mcp"
		challenge := r.URL.Query().Get(api.HealthProofChallengeQuery)
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			ChallengeProof: api.HealthChallengeProof(
				alternateHealthProofSecret,
				impostorControlToken,
				challenge,
				mcpURL,
			),
			Endpoints: map[string]string{"mcp": mcpURL},
		})
	}))
	defer server.Close()

	statePath := filepath.Join(t.TempDir(), "shared-observer.json")
	if err := writeSharedObserverState(statePath, sharedObserverState{
		ControlToken:      staleControlToken,
		HealthProofSecret: testHealthProofSecret,
		HealthURL:         server.URL,
		MCPURL:            server.URL + "/mcp",
		PID:               42,
	}); err != nil {
		t.Fatalf("write shared Observer state: %v", err)
	}

	if detectedURL, detectedToken, ok := detectSharedObserverURLFromStateFile(statePath, server.Client()); ok {
		t.Fatalf(
			"spoofed state discovery succeeded: URL = %q, token = %q",
			detectedURL,
			detectedToken,
		)
	}
}

func TestSharedObserverControlTokenProofRejectsDifferentEndpointProof(t *testing.T) {
	t.Parallel()

	const (
		controlToken    = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
		requestedMCPURL = "https://observer.example.test/team/mcp"
		internalMCPURL  = "http://127.0.0.1:3000/mcp"
	)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			ChallengeProof: api.HealthChallengeProof(
				testHealthProofSecret,
				controlToken,
				r.URL.Query().Get(api.HealthProofChallengeQuery),
				internalMCPURL,
			),
			Endpoints: map[string]string{"mcp": internalMCPURL},
		})
	}))
	defer server.Close()

	if sharedObserverControlTokenProofValid(
		server.URL,
		requestedMCPURL,
		controlToken,
		testHealthProofSecret,
		server.Client(),
	) {
		t.Fatal("proof bound to the internal endpoint verified for the requested public endpoint")
	}
}

func TestSharedObserverControlTokenProofRejectsCrossOriginRedirect(t *testing.T) {
	t.Parallel()

	const controlToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	targetHits := make(chan struct{}, 1)
	var target *httptest.Server
	target = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		targetHits <- struct{}{}
		mcpURL := target.URL + "/mcp"
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			ChallengeProof: api.HealthChallengeProof(
				testHealthProofSecret,
				controlToken,
				r.URL.Query().Get(api.HealthProofChallengeQuery),
				mcpURL,
			),
			Endpoints: map[string]string{"mcp": mcpURL},
		})
	}))
	defer target.Close()
	redirect := httptest.NewServer(http.RedirectHandler(target.URL+"/api/health", http.StatusTemporaryRedirect))
	defer redirect.Close()

	if sharedObserverControlTokenProofValid(
		redirect.URL,
		target.URL+"/mcp",
		controlToken,
		testHealthProofSecret,
		redirect.Client(),
	) {
		t.Fatal("cross-origin health redirect produced a valid control-token proof")
	}
	select {
	case <-targetHits:
		t.Fatal("proof request followed a cross-origin redirect")
	default:
	}
}

func TestDetectSharedObserverURLFromStateFileSupportsPublicMCPEndpoint(t *testing.T) {
	t.Parallel()

	const (
		controlToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
		publicMCPURL = "https://observer.example.test/team/mcp"
	)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			ChallengeProof: api.HealthChallengeProof(
				testHealthProofSecret,
				controlToken,
				r.URL.Query().Get(api.HealthProofChallengeQuery),
				publicMCPURL,
			),
			Endpoints: map[string]string{"mcp": publicMCPURL},
		})
	}))
	defer server.Close()

	statePath := filepath.Join(t.TempDir(), "shared-observer.json")
	if err := writeSharedObserverState(statePath, sharedObserverState{
		ControlToken:      controlToken,
		HealthProofSecret: testHealthProofSecret,
		HealthURL:         server.URL,
		MCPURL:            publicMCPURL,
	}); err != nil {
		t.Fatalf("write shared Observer state: %v", err)
	}
	detectedURL, detectedToken, ok := detectSharedObserverURLFromStateFile(statePath, server.Client())
	if !ok || detectedURL != publicMCPURL || detectedToken != controlToken {
		t.Fatalf(
			"public state discovery = (%q, %q, %t), want (%q, %q, true)",
			detectedURL,
			detectedToken,
			ok,
			publicMCPURL,
			controlToken,
		)
	}
}

func TestResolveMCPControlTokenRequiresMatchingSharedObserverURL(t *testing.T) {
	homeDir := t.TempDir()
	t.Setenv("HOME", homeDir)
	t.Setenv("USERPROFILE", homeDir)
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "")

	const controlToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mcpURL := server.URL + "/mcp"
		challenge := r.URL.Query().Get(api.HealthProofChallengeQuery)
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:           "obstudio",
			APIVersion:     "v1",
			ChallengeProof: api.HealthChallengeProof(testHealthProofSecret, controlToken, challenge, mcpURL),
			Endpoints:      map[string]string{"mcp": mcpURL},
		})
	}))
	defer server.Close()

	mcpURL := server.URL + "/mcp"
	if err := writeSharedObserverState(sharedObserverStatePath(), sharedObserverState{
		ControlToken:      controlToken,
		HealthProofSecret: testHealthProofSecret,
		HealthURL:         server.URL,
		MCPURL:            mcpURL,
	}); err != nil {
		t.Fatalf("write shared Observer state: %v", err)
	}
	if got := resolveMCPControlToken(mcpURL); got != controlToken {
		t.Fatalf("matching state token = %q, want %q", got, controlToken)
	}
	if got := resolveMCPControlToken("http://127.0.0.1:49999/mcp"); got != "" {
		t.Fatalf("mismatched state token = %q, want empty", got)
	}
}

func TestResolveMCPControlTokenSupportsLocalhostAlias(t *testing.T) {
	homeDir := t.TempDir()
	t.Setenv("HOME", homeDir)
	t.Setenv("USERPROFILE", homeDir)
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "")

	const controlToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	advertisedMCPURL := ""
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			ChallengeProof: api.HealthChallengeProof(
				testHealthProofSecret,
				controlToken,
				r.URL.Query().Get(api.HealthProofChallengeQuery),
				advertisedMCPURL,
			),
			Endpoints: map[string]string{"mcp": advertisedMCPURL},
		})
	}))
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen on IPv4 loopback: %v", err)
	}
	server.Listener = listener
	server.Start()
	defer server.Close()

	stateMCPURL := server.URL + "/mcp"
	advertisedMCPURL = stateMCPURL
	if err := writeSharedObserverState(sharedObserverStatePath(), sharedObserverState{
		ControlToken:      controlToken,
		HealthProofSecret: testHealthProofSecret,
		HealthURL:         server.URL + "/api/health",
		MCPURL:            stateMCPURL,
	}); err != nil {
		t.Fatalf("write shared Observer state: %v", err)
	}
	requestedMCPURL := strings.Replace(stateMCPURL, "127.0.0.1", "localhost", 1)
	advertisedURL, gotToken := resolveMCPControl(requestedMCPURL)
	if gotToken != controlToken || advertisedURL != stateMCPURL {
		t.Fatalf(
			"localhost alias control = (%q, %q), want adopted (%q, %q)",
			advertisedURL,
			gotToken,
			stateMCPURL,
			controlToken,
		)
	}
}

func TestResolveMCPControlTokenSupportsHTTPSPublicProxy(t *testing.T) {
	homeDir := t.TempDir()
	t.Setenv("HOME", homeDir)
	t.Setenv("USERPROFILE", homeDir)
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "")

	const controlToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	const advertisedMCPURL = "https://observer.example.test/team/mcp"
	requestedPath := make(chan string, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestedPath <- r.URL.Path
		if r.URL.Path != "/trusted/api/health" {
			http.NotFound(w, r)
			return
		}
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			ChallengeProof: api.HealthChallengeProof(
				testHealthProofSecret,
				controlToken,
				r.URL.Query().Get(api.HealthProofChallengeQuery),
				advertisedMCPURL,
			),
			Endpoints: map[string]string{"mcp": advertisedMCPURL},
		})
	}))
	defer server.Close()

	if err := writeSharedObserverState(sharedObserverStatePath(), sharedObserverState{
		ControlToken:      controlToken,
		HealthProofSecret: testHealthProofSecret,
		HealthURL:         server.URL + "/trusted/api/health",
		MCPURL:            advertisedMCPURL,
	}); err != nil {
		t.Fatalf("write shared Observer state: %v", err)
	}
	gotURL, gotToken := resolveMCPControl(advertisedMCPURL)
	if gotToken != controlToken || gotURL != advertisedMCPURL {
		t.Fatalf("public proxy control = (%q, %q), want (%q, %q)", gotURL, gotToken, advertisedMCPURL, controlToken)
	}
	if got := <-requestedPath; got != "/trusted/api/health" {
		t.Fatalf("public proxy health path = %q, want trusted local state URL", got)
	}
}

func TestSameSharedObserverControlEndpointCanonicalizesPublicAuthority(t *testing.T) {
	t.Parallel()

	if !sameSharedObserverControlEndpoint(
		"https://OBSERVER.Example.Test:443/team/mcp",
		"https://observer.example.test/team/mcp",
	) {
		t.Fatal("equivalent public Observer endpoints did not match")
	}
	for _, endpoint := range []string{
		"https://observer.example.test:444/team/mcp",
		"https://other.example.test/team/mcp",
		"https://observer.example.test/other/mcp",
		"https://observer.example.test/team/mcp?token=secret",
	} {
		if sameSharedObserverControlEndpoint("https://observer.example.test/team/mcp", endpoint) {
			t.Fatalf("different public Observer endpoint %q matched", endpoint)
		}
	}
}

func TestDetectInstallSharedObserverURLFromSourcesFallsBackWithoutProvedToken(t *testing.T) {
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "")
	t.Setenv(observerHealthProofSecretEnv, "")

	requested := make(chan struct{}, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		select {
		case requested <- struct{}{}:
		default:
		}
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			Endpoints:  map[string]string{"mcp": "http://127.0.0.1:3000/mcp"},
		})
	}))
	defer server.Close()

	detectedURL, detectedToken, ok := detectInstallSharedObserverURLFromSources(
		filepath.Join(t.TempDir(), "missing-state.json"),
		server.URL,
		server.Client(),
	)
	if ok || detectedURL != "" || detectedToken != "" {
		t.Fatalf(
			"tokenless install discovery = (%q, %q, %t), want empty result so install uses stdio",
			detectedURL,
			detectedToken,
			ok,
		)
	}
	select {
	case <-requested:
		t.Fatal("tokenless install discovery probed unauthenticated fallback health")
	default:
	}
}

func TestDetectInstallSharedObserverURLFromSourcesRequiresEnvironmentSecretsProof(t *testing.T) {
	const (
		environmentToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
		impostorToken    = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
	)
	for _, test := range []struct {
		name               string
		serverControlToken string
		serverProofSecret  string
		wantFound          bool
	}{
		{
			name:               "authentic proof",
			serverControlToken: environmentToken,
			serverProofSecret:  testHealthProofSecret,
			wantFound:          true,
		},
		{
			name:               "different control token",
			serverControlToken: impostorToken,
			serverProofSecret:  testHealthProofSecret,
		},
		{
			name:               "different proof secret",
			serverControlToken: environmentToken,
			serverProofSecret:  alternateHealthProofSecret,
		},
		{name: "missing proof"},
	} {
		t.Run(test.name, func(t *testing.T) {
			t.Setenv("OBSTUDIO_CONTROL_TOKEN", environmentToken)
			t.Setenv(observerHealthProofSecretEnv, testHealthProofSecret)

			var server *httptest.Server
			server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				mcpURL := server.URL + "/mcp"
				_ = json.NewEncoder(w).Encode(sharedObserverHealth{
					Kind:       "obstudio",
					APIVersion: "v1",
					ChallengeProof: api.HealthChallengeProof(
						test.serverProofSecret,
						test.serverControlToken,
						r.URL.Query().Get(api.HealthProofChallengeQuery),
						mcpURL,
					),
					Endpoints: map[string]string{"mcp": mcpURL},
				})
			}))
			defer server.Close()

			detectedURL, detectedToken, ok := detectInstallSharedObserverURLFromSources(
				filepath.Join(t.TempDir(), "missing-state.json"),
				server.URL,
				server.Client(),
			)
			if !test.wantFound {
				if ok || detectedURL != "" || detectedToken != "" {
					t.Fatalf(
						"unproved environment token discovery = (%q, %q, %t), want no HTTP MCP configuration",
						detectedURL,
						detectedToken,
						ok,
					)
				}
				return
			}
			if wantURL := server.URL + "/mcp"; !ok || detectedURL != wantURL || detectedToken != environmentToken {
				t.Fatalf(
					"proved environment token discovery = (%q, %q, %t), want (%q, %q, true)",
					detectedURL,
					detectedToken,
					ok,
					wantURL,
					environmentToken,
				)
			}
		})
	}
}

func TestResolveInstallSharedObserverRejectsExplicitURLWithoutProvedToken(t *testing.T) {
	homeDir := t.TempDir()
	t.Setenv("HOME", homeDir)
	t.Setenv("USERPROFILE", homeDir)
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "")
	t.Setenv(observerHealthProofSecretEnv, "")

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
		})
	}))
	defer server.Close()

	resolvedURL, controlToken, autodetected, err := resolveInstallSharedObserver(
		server.URL+"/mcp",
		server.Client(),
	)
	if err == nil || !strings.Contains(err.Error(), "OBSTUDIO_CONTROL_TOKEN") {
		t.Fatalf("explicit tokenless shared URL error = %v, want actionable control-token error", err)
	}
	if resolvedURL != "" || controlToken != "" || autodetected {
		t.Fatalf(
			"failed explicit shared URL = (%q, %q, %t), want no HTTP MCP configuration",
			resolvedURL,
			controlToken,
			autodetected,
		)
	}
}

func TestResolveInstallSharedObserverAcceptsExplicitURLWithProvedToken(t *testing.T) {
	homeDir := t.TempDir()
	t.Setenv("HOME", homeDir)
	t.Setenv("USERPROFILE", homeDir)

	const controlToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", controlToken)
	t.Setenv(observerHealthProofSecretEnv, testHealthProofSecret)

	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mcpURL := server.URL + "/mcp"
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			ChallengeProof: api.HealthChallengeProof(
				testHealthProofSecret,
				controlToken,
				r.URL.Query().Get(api.HealthProofChallengeQuery),
				mcpURL,
			),
			Endpoints: map[string]string{"mcp": mcpURL},
		})
	}))
	defer server.Close()

	resolvedURL, resolvedToken, autodetected, err := resolveInstallSharedObserver(
		server.URL+"/mcp",
		server.Client(),
	)
	if err != nil {
		t.Fatalf("resolve explicit shared Observer: %v", err)
	}
	if wantURL := server.URL + "/mcp"; resolvedURL != wantURL || resolvedToken != controlToken || autodetected {
		t.Fatalf(
			"proved explicit shared URL = (%q, %q, %t), want (%q, %q, false)",
			resolvedURL,
			resolvedToken,
			autodetected,
			wantURL,
			controlToken,
		)
	}
}

func TestResolveMCPControlTokenRequiresProofForExplicitEnvironmentSecrets(t *testing.T) {
	const (
		environmentToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
		impostorToken    = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
	)
	for _, test := range []struct {
		name               string
		serverControlToken string
		serverProofSecret  string
		wantToken          string
	}{
		{
			name:               "authentic proof",
			serverControlToken: environmentToken,
			serverProofSecret:  testHealthProofSecret,
			wantToken:          environmentToken,
		},
		{
			name:               "different control token",
			serverControlToken: impostorToken,
			serverProofSecret:  testHealthProofSecret,
		},
		{
			name:               "different proof secret",
			serverControlToken: environmentToken,
			serverProofSecret:  alternateHealthProofSecret,
		},
		{name: "missing proof"},
	} {
		t.Run(test.name, func(t *testing.T) {
			homeDir := t.TempDir()
			t.Setenv("HOME", homeDir)
			t.Setenv("USERPROFILE", homeDir)
			t.Setenv("OBSTUDIO_CONTROL_TOKEN", environmentToken)
			t.Setenv(observerHealthProofSecretEnv, testHealthProofSecret)

			var server *httptest.Server
			server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				mcpURL := server.URL + "/mcp"
				challenge := r.URL.Query().Get(api.HealthProofChallengeQuery)
				_ = json.NewEncoder(w).Encode(sharedObserverHealth{
					Kind:       "obstudio",
					APIVersion: "v1",
					ChallengeProof: api.HealthChallengeProof(
						test.serverProofSecret,
						test.serverControlToken,
						challenge,
						mcpURL,
					),
					Endpoints: map[string]string{"mcp": mcpURL},
				})
			}))
			defer server.Close()

			if got := resolveMCPControlToken(server.URL + "/mcp"); got != test.wantToken {
				t.Fatalf("resolved environment token = %q, want %q", got, test.wantToken)
			}
		})
	}
}

func TestUnauthenticatedHealthDiscoveryDoesNotReleaseStaleStateToken(t *testing.T) {
	homeDir := t.TempDir()
	t.Setenv("HOME", homeDir)
	t.Setenv("USERPROFILE", homeDir)
	t.Setenv("OBSTUDIO_CONTROL_TOKEN", "")

	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(sharedObserverHealth{
			Kind:       "obstudio",
			APIVersion: "v1",
			Endpoints:  map[string]string{"mcp": server.URL + "/mcp"},
		})
	}))
	defer server.Close()
	mcpURL := server.URL + "/mcp"

	if err := writeSharedObserverState(sharedObserverStatePath(), sharedObserverState{
		ControlToken: "stale-control-token",
		HealthURL:    server.URL,
		MCPURL:       mcpURL,
	}); err != nil {
		t.Fatalf("write shared Observer state: %v", err)
	}
	if detectedURL, ok := detectSharedObserverURL(server.URL, server.Client()); !ok || detectedURL != mcpURL {
		t.Fatalf("ordinary health discovery = (%q, %t), want (%q, true)", detectedURL, ok, mcpURL)
	}
	if got := resolveMCPControlToken(mcpURL); got != "" {
		t.Fatalf("unauthenticated health discovery released stale token %q", got)
	}
}

func TestWriteSharedObserverStateAtomicallyReplacesExistingState(t *testing.T) {
	t.Parallel()

	stateDir := t.TempDir()
	statePath := filepath.Join(stateDir, "shared-observer.json")
	if err := os.WriteFile(statePath, []byte("{"), 0o644); err != nil {
		t.Fatalf("write malformed existing state: %v", err)
	}

	want := sharedObserverState{
		BaseURL:      "http://127.0.0.1:41234",
		ControlToken: "shared-control-token",
		HealthURL:    "http://127.0.0.1:41234/api/health",
		MCPURL:       "http://127.0.0.1:41234/mcp",
		PID:          4242,
	}
	if err := writeSharedObserverState(statePath, want); err != nil {
		t.Fatalf("writeSharedObserverState returned error: %v", err)
	}

	got, err := readSharedObserverState(statePath)
	if err != nil {
		t.Fatalf("readSharedObserverState returned error: %v", err)
	}
	if got != want {
		t.Fatalf("readSharedObserverState = %#v, want %#v", got, want)
	}
	info, err := os.Stat(statePath)
	if err != nil {
		t.Fatalf("stat shared observer state: %v", err)
	}
	if runtime.GOOS != "windows" {
		if mode := info.Mode().Perm(); mode != 0o600 {
			t.Fatalf("shared observer state mode = %#o, want 0600", mode)
		}
	}
	entries, err := os.ReadDir(stateDir)
	if err != nil {
		t.Fatalf("read state directory: %v", err)
	}
	if len(entries) != 1 || entries[0].Name() != filepath.Base(statePath) {
		t.Fatalf("state directory contains temporary files after publish: %#v", entries)
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

func TestValidateRunConfigRejectsInvalidPublicMCPURL(t *testing.T) {
	t.Parallel()

	for _, publicMCPURL := range []string{
		"http://observer.example.test/mcp",
		"https://user:password@observer.example.test/mcp",
		"https://observer.example.test/mcp?token=secret",
		"https://observer.example.test/mcp?",
		"https://observer.example.test/mcp#fragment",
		"https://observer.example.test/" + strings.Repeat("x", observerPublicMCPURLMaxLength),
	} {
		err := validateRunConfig(runConfig{
			host:             "127.0.0.1",
			observerHTTPPort: "3000",
			otlpHTTPPort:     "4318",
			otlpGRPCPort:     "4317",
			publicMCPURL:     publicMCPURL,
		})
		if err == nil {
			t.Fatalf("validateRunConfig accepted invalid %s %q", observerPublicMCPURLEnv, publicMCPURL)
		}
	}
}

func TestNormalizePublicMCPURLCanonicalizesAdvertisedURL(t *testing.T) {
	t.Parallel()

	tests := map[string]string{
		"https://OBSERVER.Example.Test:443/team/":             "https://observer.example.test/team/mcp",
		"http://LOCALHOST.:80/":                               "http://localhost/mcp",
		"https://[2001:0DB8:0000:0000:0000:0000:0000:1]:443/": "https://[2001:db8::1]/mcp",
	}
	for input, want := range tests {
		got, err := normalizePublicMCPURL(input)
		if err != nil {
			t.Fatalf("normalizePublicMCPURL(%q): %v", input, err)
		}
		if got != want {
			t.Fatalf("normalizePublicMCPURL(%q) = %q, want %q", input, got, want)
		}
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

func TestBuildSharedObserverStateUsesConfiguredPublicMCPURL(t *testing.T) {
	t.Parallel()

	const publicMCPURL = "https://observer.example.test/team/mcp"
	state := buildSharedObserverState("127.0.0.1", "41234", publicMCPURL)
	if state.BaseURL != "http://127.0.0.1:41234" || state.HealthURL != "http://127.0.0.1:41234/api/health" {
		t.Fatalf("public MCP URL changed internal discovery endpoints: %#v", state)
	}
	if state.MCPURL != publicMCPURL {
		t.Fatalf("MCPURL = %q, want %q", state.MCPURL, publicMCPURL)
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

	statePath := filepath.Join(homeDir, sharedObserverStateDirName, sharedObserverStateFileName)
	healthyState, err := readSharedObserverState(statePath)
	if err != nil {
		t.Fatalf("read healthy shared observer state: %v", err)
	}
	contender := exec.Command(installedBinary)
	contender.Env = runEnv
	if output, err := contender.CombinedOutput(); err == nil {
		t.Fatalf("expected a second observer using the same listeners to fail, output:\n%s", output)
	}
	stateAfterConflict, err := readSharedObserverState(statePath)
	if err != nil {
		t.Fatalf("read shared observer state after listener conflict: %v", err)
	}
	if stateAfterConflict.PID != healthyState.PID {
		t.Fatalf(
			"failed contender replaced healthy shared observer state: PID = %d, want %d",
			stateAfterConflict.PID,
			healthyState.PID,
		)
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
