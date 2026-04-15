package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

type mcpConfigFormat string

const (
	mcpConfigJSON mcpConfigFormat = "json"
	mcpConfigTOML mcpConfigFormat = "toml"

	codexManagedBlockStart = "# BEGIN OBSTUDIO MCP CONFIG"
	codexManagedBlockEnd   = "# END OBSTUDIO MCP CONFIG"

	defaultSharedObserverBaseURL = "http://127.0.0.1:3000"
	defaultSharedObserverMCPURL  = defaultSharedObserverBaseURL + "/mcp"
	defaultSharedObserverHealth  = defaultSharedObserverBaseURL + "/api/health"
	sharedObserverHealthTimeout  = 750 * time.Millisecond
)

type mcpConfigTarget struct {
	format mcpConfigFormat
	path   func() string
}

type agentTarget struct {
	skillsDir func(string) string
	mcpConfig mcpConfigTarget
}

type codexMCPServer struct {
	URL     string
	Command string
	Args    []string
}

type sharedObserverHealth struct {
	APIVersion string            `json:"apiVersion"`
	Endpoints  map[string]string `json:"endpoints"`
	Kind       string            `json:"kind"`
}

var targets = map[string]agentTarget{
	"cursor": {
		skillsDir: func(home string) string { return filepath.Join(home, ".cursor", "skills", "obstudio") },
		mcpConfig: mcpConfigTarget{
			format: mcpConfigJSON,
			path:   func() string { return filepath.Join(userHome(), ".cursor", "mcp.json") },
		},
	},
	"claude-code": {
		skillsDir: func(home string) string { return filepath.Join(home, ".claude", "skills", "obstudio") },
		mcpConfig: mcpConfigTarget{
			format: mcpConfigJSON,
			path:   func() string { return filepath.Join(userHome(), ".claude", "settings.json") },
		},
	},
	"codex": {
		skillsDir: func(home string) string { return filepath.Join(home, ".codex", "skills", "obstudio") },
		mcpConfig: mcpConfigTarget{
			format: mcpConfigTOML,
			path:   func() string { return filepath.Join(userHome(), ".codex", "config.toml") },
		},
	},
}

func supportedTargets() string {
	names := make([]string, 0, len(targets))
	for k := range targets {
		names = append(names, k)
	}
	slices.Sort(names)
	return strings.Join(names, ", ")
}

func newInstallCmd() *cobra.Command {
	var target string
	var sharedURL string

	cmd := &cobra.Command{
		Use:   "install",
		Short: "Install skills and configure MCP for an AI coding agent",
		RunE: func(_ *cobra.Command, _ []string) error {
			return runInstall(target, sharedURL)
		},
	}

	cmd.Flags().StringVar(&target, "target", "", "Agent target ("+supportedTargets()+")")
	cmd.Flags().StringVar(&sharedURL, "shared-url", "", "Use an existing HTTP MCP endpoint instead of auto-starting a local obstudio binary")
	cmd.MarkFlagRequired("target")

	return cmd
}

func runInstall(target, sharedURL string) error {
	t, ok := targets[target]
	if !ok {
		return fmt.Errorf("unknown target: %s (supported: %s)", target, supportedTargets())
	}
	resolvedSharedURL := sharedURL
	autodetectedSharedURL := false
	if resolvedSharedURL == "" {
		if detectedURL, ok := detectSharedObserverURL(defaultSharedObserverHealth, http.DefaultClient); ok {
			resolvedSharedURL = detectedURL
			autodetectedSharedURL = true
		}
	}
	if resolvedSharedURL != "" {
		source := "--shared-url"
		if autodetectedSharedURL {
			source = "detected shared observer URL"
		}
		normalizedSharedURL, err := normalizeSharedURL(resolvedSharedURL, source)
		if err != nil {
			return err
		}
		resolvedSharedURL = normalizedSharedURL
	}

	home := userHome()
	destDir := t.skillsDir(home)

	fmt.Printf("Installing obstudio to %s\n", destDir)

	if err := os.RemoveAll(destDir); err != nil {
		return fmt.Errorf("failed to clean destination: %w", err)
	}

	skillsFS, err := fs.Sub(embeddedSkills, "_skills")
	if err != nil {
		return fmt.Errorf("failed to read embedded skills: %w", err)
	}

	if err := extractFS(skillsFS, destDir); err != nil {
		return fmt.Errorf("failed to extract skills: %w", err)
	}
	fmt.Println("  Skills installed (includes references).")

	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("failed to resolve executable path: %w", err)
	}
	exePath, _ = filepath.EvalSymlinks(exePath)

	installedBinaryName := "obstudio" + filepath.Ext(exePath)
	installedBinary := filepath.Join(destDir, installedBinaryName)
	if err := copyFile(exePath, installedBinary); err != nil {
		return fmt.Errorf("failed to copy binary: %w", err)
	}
	if err := os.Chmod(installedBinary, 0o755); err != nil {
		return fmt.Errorf("failed to set binary permissions: %w", err)
	}
	fmt.Println("  Binary installed.")

	mcpFile := t.mcpConfig.path()
	if err := configureMCP(t.mcpConfig, installedBinary, resolvedSharedURL); err != nil {
		return fmt.Errorf("failed to configure MCP: %w", err)
	}
	if resolvedSharedURL == "" {
		fmt.Printf("  MCP configured in %s to launch a local obstudio process.\n", mcpFile)
	} else if autodetectedSharedURL {
		fmt.Printf("  MCP configured in %s to reuse detected shared server %s.\n", mcpFile, resolvedSharedURL)
	} else {
		fmt.Printf("  MCP configured in %s to reuse %s.\n", mcpFile, resolvedSharedURL)
	}

	if resolvedSharedURL == "" {
		fmt.Println("\nDone. Restart your editor to activate the MCP server.")
		return nil
	}

	fmt.Println("\nDone. Start the shared obstudio server before opening your agent:")
	fmt.Println("  obstudio")
	return nil
}

func detectSharedObserverURL(healthURL string, client *http.Client) (string, bool) {
	if client == nil {
		client = http.DefaultClient
	}
	requestClient := *client
	if requestClient.Timeout == 0 {
		requestClient.Timeout = sharedObserverHealthTimeout
	}

	resp, err := requestClient.Get(healthURL)
	if err != nil {
		return "", false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", false
	}

	var health sharedObserverHealth
	if err := json.NewDecoder(resp.Body).Decode(&health); err != nil {
		return "", false
	}
	if health.Kind != "obstudio" || health.APIVersion != "v1" {
		return "", false
	}
	if mcpURL := strings.TrimSpace(health.Endpoints["mcp"]); mcpURL != "" {
		return mcpURL, true
	}
	return defaultSharedObserverMCPURL, true
}

func configureMCP(target mcpConfigTarget, binaryPath, sharedURL string) error {
	switch target.format {
	case mcpConfigJSON:
		server := map[string]any{}
		if sharedURL == "" {
			server["command"] = binaryPath
			server["args"] = []string{}
		} else {
			server["type"] = "http"
			server["url"] = sharedURL
		}
		return upsertJSONMCPServer(target.path(), server)
	case mcpConfigTOML:
		server := codexMCPServer{}
		if sharedURL == "" {
			server.Command = binaryPath
			server.Args = []string{}
		} else {
			server.URL = sharedURL
		}
		return upsertCodexMCPServer(target.path(), server)
	default:
		return fmt.Errorf("unsupported MCP config format: %s", target.format)
	}
}

func upsertJSONMCPServer(path string, server map[string]any) error {
	config := map[string]any{}

	data, err := os.ReadFile(path)
	if err == nil {
		if err := json.Unmarshal(data, &config); err != nil {
			return fmt.Errorf("failed to parse %s: %w", path, err)
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("read JSON MCP config %q: %w", path, err)
	}

	servers, ok := config["mcpServers"].(map[string]any)
	if !ok {
		servers = map[string]any{}
	}
	servers["obstudio"] = server
	config["mcpServers"] = servers

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create parent directory for %q: %w", path, err)
	}

	out, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal JSON MCP config %q: %w", path, err)
	}
	if err := os.WriteFile(path, append(out, '\n'), 0o644); err != nil {
		return fmt.Errorf("write JSON MCP config %q: %w", path, err)
	}
	return nil
}

func upsertCodexMCPServer(path string, server codexMCPServer) error {
	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("read codex MCP config %q: %w", path, err)
	}

	content := string(data)
	content = removeCodexManagedBlock(content)
	content = removeCodexServerSections(content)
	content = strings.TrimRight(content, "\n")
	if strings.TrimSpace(content) != "" {
		content += "\n\n"
	}
	content += renderCodexManagedBlock(server)

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create parent directory for %q: %w", path, err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		return fmt.Errorf("write codex MCP config %q: %w", path, err)
	}
	return nil
}

func renderCodexManagedBlock(server codexMCPServer) string {
	lines := []string{
		codexManagedBlockStart,
		"[mcp_servers.obstudio]",
		"enabled = true",
	}

	if server.URL != "" {
		lines = append(lines, fmt.Sprintf("url = %q", server.URL))
	} else {
		lines = append(lines,
			fmt.Sprintf("command = %q", server.Command),
			fmt.Sprintf("args = %s", renderTOMLStringArray(server.Args)),
		)
	}

	lines = append(lines, codexManagedBlockEnd)
	return strings.Join(lines, "\n") + "\n"
}

func renderTOMLStringArray(values []string) string {
	if len(values) == 0 {
		return "[]"
	}

	quoted := make([]string, 0, len(values))
	for _, value := range values {
		quoted = append(quoted, fmt.Sprintf("%q", value))
	}
	return "[" + strings.Join(quoted, ", ") + "]"
}

func removeCodexManagedBlock(content string) string {
	if content == "" {
		return content
	}

	lines := splitLines(content)
	out := strings.Builder{}
	skipping := false

	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		switch {
		case trimmed == codexManagedBlockStart:
			skipping = true
			continue
		case skipping && trimmed == codexManagedBlockEnd:
			skipping = false
			continue
		case skipping:
			continue
		default:
			out.WriteString(line)
		}
	}

	return out.String()
}

func removeCodexServerSections(content string) string {
	if content == "" {
		return content
	}

	lines := splitLines(content)
	out := strings.Builder{}
	skipping := false

	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if isTOMLTableHeader(trimmed) {
			if isCodexObstudioHeader(trimmed) {
				skipping = true
				continue
			}
			if skipping {
				skipping = false
			}
		}
		if skipping {
			continue
		}
		out.WriteString(line)
	}

	return out.String()
}

func isTOMLTableHeader(line string) bool {
	return strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]")
}

func isCodexObstudioHeader(line string) bool {
	return line == "[mcp_servers.obstudio]" || strings.HasPrefix(line, "[mcp_servers.obstudio.")
}

func splitLines(content string) []string {
	return strings.SplitAfter(content, "\n")
}

func validateSharedURL(raw, source string) error {
	parsed, err := url.Parse(raw)
	if err != nil {
		return fmt.Errorf("invalid %s: %w", source, err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return fmt.Errorf("invalid %s: %s must use http or https", source, raw)
	}
	if parsed.Host == "" {
		return fmt.Errorf("invalid %s: %s is missing a host", source, raw)
	}
	return nil
}

func normalizeSharedURL(raw, source string) (string, error) {
	if err := validateSharedURL(raw, source); err != nil {
		return "", err
	}

	parsed, err := url.Parse(raw)
	if err != nil {
		return "", fmt.Errorf("invalid %s: %w", source, err)
	}

	trimmedPath := strings.TrimRight(parsed.Path, "/")
	switch {
	case trimmedPath == "":
		parsed.Path = "/mcp"
	case strings.HasSuffix(trimmedPath, "/mcp"):
		parsed.Path = trimmedPath
	default:
		parsed.Path = trimmedPath + "/mcp"
	}
	return parsed.String(), nil
}

func extractFS(src fs.FS, destDir string) error {
	return fs.WalkDir(src, ".", func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}

		target := filepath.Join(destDir, path)

		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}

		data, err := fs.ReadFile(src, path)
		if err != nil {
			return err
		}

		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		return os.WriteFile(target, data, 0o644)
	})
}

func copyFile(src, dst string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return fmt.Errorf("read %q: %w", src, err)
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return fmt.Errorf("create parent directory for %q: %w", dst, err)
	}
	if err := os.WriteFile(dst, data, 0o644); err != nil {
		return fmt.Errorf("write %q: %w", dst, err)
	}
	return nil
}

func userHome() string {
	home, err := os.UserHomeDir()
	if err != nil {
		log.Fatalf("Failed to find home directory: %v", err)
	}
	return home
}
