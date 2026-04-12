package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
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

	defaultLocalObserverPort = 3000
	defaultLocalOTLPHTTPPort = 4318
	defaultLocalOTLPGRPCPort = 4317
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

type localInstallConfig struct {
	observerPort int
	otlpGRPCPort int
	otlpHTTPPort int
}

type installIO struct {
	interactive bool
	stdin       io.Reader
	stdout      io.Writer
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
	var observerPort int
	var otlpHTTPPort int
	var otlpGRPCPort int

	cmd := &cobra.Command{
		Use:   "install",
		Short: "Install skills and configure MCP for an AI coding agent",
		RunE: func(_ *cobra.Command, _ []string) error {
			return runInstall(target, sharedURL, observerPort, otlpHTTPPort, otlpGRPCPort, installIO{
				interactive: isInteractiveTerminal(os.Stdin, os.Stdout),
				stdin:       os.Stdin,
				stdout:      os.Stdout,
			})
		},
	}

	cmd.Flags().StringVar(&target, "target", "", "Agent target ("+supportedTargets()+")")
	cmd.Flags().StringVar(&sharedURL, "shared-url", "", "Use an existing HTTP MCP endpoint instead of auto-starting a local obstudio binary")
	cmd.Flags().IntVar(&observerPort, "port", 0, "Local Observer UI and MCP port for auto-started obstudio")
	cmd.Flags().IntVar(&otlpHTTPPort, "otlp-http-port", 0, "Local OTLP/HTTP receiver port for auto-started obstudio")
	cmd.Flags().IntVar(&otlpGRPCPort, "otlp-grpc-port", 0, "Local OTLP/gRPC receiver port for auto-started obstudio")
	cmd.MarkFlagRequired("target")

	return cmd
}

func runInstall(target, sharedURL string, observerPort, otlpHTTPPort, otlpGRPCPort int, console installIO) error {
	t, ok := targets[target]
	if !ok {
		return fmt.Errorf("unknown target: %s (supported: %s)", target, supportedTargets())
	}
	detectedURL, detectedSharedURL := detectSharedObserverURL(defaultSharedObserverHealth, http.DefaultClient)
	resolvedSharedURL, localConfig, autodetectedSharedURL, err := resolveInstallMode(
		sharedURL,
		detectedURL,
		detectedSharedURL,
		observerPort,
		otlpHTTPPort,
		otlpGRPCPort,
		console,
	)
	if err != nil {
		return err
	}
	if resolvedSharedURL != "" {
		source := "--shared-url"
		if autodetectedSharedURL {
			source = "detected shared observer URL"
		}
		if err := validateSharedURL(resolvedSharedURL, source); err != nil {
			return err
		}
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

	if _, installed, err := installSiblingRuntime(exePath, destDir, "weaver"); err != nil {
		return fmt.Errorf("failed to install validation runtime: %w", err)
	} else if installed {
		fmt.Println("  Validation runtime installed.")
	}

	localLaunchCommand := installedBinary
	if resolvedSharedURL == "" {
		localLauncher := launcherPath(installedBinary)
		if err := writeLocalLauncher(localLauncher, installedBinary, localConfig); err != nil {
			return fmt.Errorf("failed to write launcher: %w", err)
		}
		localLaunchCommand = localLauncher
		fmt.Println("  Launcher installed.")
	}

	mcpFile := t.mcpConfig.path()
	if err := configureMCP(t.mcpConfig, localLaunchCommand, resolvedSharedURL); err != nil {
		return fmt.Errorf("failed to configure MCP: %w", err)
	}
	if resolvedSharedURL == "" {
		fmt.Printf("  MCP configured in %s to launch a local obstudio process.\n", mcpFile)
		fmt.Printf("  Local endpoints: %s, %s, %s\n",
			fmt.Sprintf("http://127.0.0.1:%d", localConfig.observerPort),
			fmt.Sprintf("http://127.0.0.1:%d", localConfig.otlpHTTPPort),
			fmt.Sprintf("127.0.0.1:%d", localConfig.otlpGRPCPort),
		)
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

func defaultLocalInstallConfig() localInstallConfig {
	return localInstallConfig{
		observerPort: defaultLocalObserverPort,
		otlpGRPCPort: defaultLocalOTLPGRPCPort,
		otlpHTTPPort: defaultLocalOTLPHTTPPort,
	}
}

func resolveInstallMode(
	sharedURL, detectedURL string,
	detectedShared bool,
	observerPort, otlpHTTPPort, otlpGRPCPort int,
	console installIO,
) (string, localInstallConfig, bool, error) {
	if sharedURL != "" {
		if observerPort != 0 || otlpHTTPPort != 0 || otlpGRPCPort != 0 {
			return "", localInstallConfig{}, false, errors.New("--shared-url cannot be combined with --port, --otlp-http-port, or --otlp-grpc-port")
		}
		return sharedURL, defaultLocalInstallConfig(), false, nil
	}

	explicitLocalPorts := observerPort != 0 || otlpHTTPPort != 0 || otlpGRPCPort != 0
	if explicitLocalPorts {
		config, err := finalizeLocalInstallConfig(observerPort, otlpHTTPPort, otlpGRPCPort)
		return "", config, false, err
	}

	if detectedShared {
		if console.interactive {
			reader := bufio.NewReader(console.stdin)
			useShared, err := promptSharedReuseChoice(reader, console.stdout, detectedURL)
			if err != nil {
				return "", localInstallConfig{}, false, err
			}
			if useShared {
				return detectedURL, defaultLocalInstallConfig(), true, nil
			}
			useCustom, err := promptLocalPortMode(reader, console.stdout)
			if err != nil {
				return "", localInstallConfig{}, false, err
			}
			if !useCustom {
				return "", defaultLocalInstallConfig(), false, nil
			}
			config, err := promptCustomLocalInstallConfig(reader, console.stdout)
			if err != nil {
				return "", localInstallConfig{}, false, err
			}
			return "", config, false, nil
		} else {
			return detectedURL, defaultLocalInstallConfig(), true, nil
		}
	}

	if !console.interactive {
		return "", defaultLocalInstallConfig(), false, nil
	}

	reader := bufio.NewReader(console.stdin)
	useCustom, err := promptLocalPortMode(reader, console.stdout)
	if err != nil {
		return "", localInstallConfig{}, false, err
	}
	if !useCustom {
		return "", defaultLocalInstallConfig(), false, nil
	}

	config, err := promptCustomLocalInstallConfig(reader, console.stdout)
	if err != nil {
		return "", localInstallConfig{}, false, err
	}
	return "", config, false, nil
}

func finalizeLocalInstallConfig(observerPort, otlpHTTPPort, otlpGRPCPort int) (localInstallConfig, error) {
	config := defaultLocalInstallConfig()
	if observerPort != 0 {
		config.observerPort = observerPort
	}
	if otlpHTTPPort != 0 {
		config.otlpHTTPPort = otlpHTTPPort
	}
	if otlpGRPCPort != 0 {
		config.otlpGRPCPort = otlpGRPCPort
	}

	for _, port := range []int{config.observerPort, config.otlpHTTPPort, config.otlpGRPCPort} {
		if port < 1 || port > 65535 {
			return localInstallConfig{}, fmt.Errorf("port %d must be between 1 and 65535", port)
		}
	}
	if config.observerPort == config.otlpHTTPPort || config.observerPort == config.otlpGRPCPort || config.otlpHTTPPort == config.otlpGRPCPort {
		return localInstallConfig{}, errors.New("local Observer ports must be distinct")
	}
	return config, nil
}

func promptSharedReuseChoice(reader *bufio.Reader, out io.Writer, detectedURL string) (bool, error) {
	for {
		if out != nil {
			fmt.Fprintf(out, "Detected shared Observer MCP endpoint at %s\n", detectedURL)
			fmt.Fprintln(out, "1) Reuse detected shared backend")
			fmt.Fprintln(out, "2) Start local backend")
			fmt.Fprint(out, "Selection [1]: ")
		}
		line, err := reader.ReadString('\n')
		if err != nil && !errors.Is(err, io.EOF) {
			return false, err
		}
		switch strings.TrimSpace(line) {
		case "", "1":
			return true, nil
		case "2":
			return false, nil
		default:
			if out != nil {
				fmt.Fprintln(out, "Enter 1 or 2.")
			}
		}
	}
}

func promptLocalPortMode(reader *bufio.Reader, out io.Writer) (bool, error) {
	for {
		if out != nil {
			fmt.Fprintln(out, "Choose local Observer ports:")
			fmt.Fprintf(out, "1) Use default ports (%d / %d / %d)\n", defaultLocalObserverPort, defaultLocalOTLPHTTPPort, defaultLocalOTLPGRPCPort)
			fmt.Fprintln(out, "2) Choose custom ports")
			fmt.Fprint(out, "Selection [1]: ")
		}
		line, err := reader.ReadString('\n')
		if err != nil && !errors.Is(err, io.EOF) {
			return false, err
		}
		switch strings.TrimSpace(line) {
		case "", "1":
			return false, nil
		case "2":
			return true, nil
		default:
			if out != nil {
				fmt.Fprintln(out, "Enter 1 or 2.")
			}
		}
	}
}

func promptCustomLocalInstallConfig(reader *bufio.Reader, out io.Writer) (localInstallConfig, error) {
	observerPort, err := promptInstallPort(reader, out, "Observer UI port", defaultLocalObserverPort, nil)
	if err != nil {
		return localInstallConfig{}, err
	}
	otlpHTTPPort, err := promptInstallPort(reader, out, "OTLP HTTP port", defaultLocalOTLPHTTPPort, map[int]bool{observerPort: true})
	if err != nil {
		return localInstallConfig{}, err
	}
	otlpGRPCPort, err := promptInstallPort(reader, out, "OTLP gRPC port", defaultLocalOTLPGRPCPort, map[int]bool{observerPort: true, otlpHTTPPort: true})
	if err != nil {
		return localInstallConfig{}, err
	}
	return finalizeLocalInstallConfig(observerPort, otlpHTTPPort, otlpGRPCPort)
}

func promptInstallPort(reader *bufio.Reader, out io.Writer, label string, defaultPort int, disallowed map[int]bool) (int, error) {
	for {
		if out != nil {
			fmt.Fprintf(out, "%s [%d]: ", label, defaultPort)
		}
		line, err := reader.ReadString('\n')
		if err != nil && !errors.Is(err, io.EOF) {
			return 0, err
		}
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			if disallowed[defaultPort] {
				if out != nil {
					fmt.Fprintln(out, "Each local port must be different.")
				}
				continue
			}
			return defaultPort, nil
		}
		port, err := parseInstallPort(trimmed)
		if err != nil {
			if out != nil {
				fmt.Fprintln(out, err.Error())
			}
			continue
		}
		if disallowed[port] {
			if out != nil {
				fmt.Fprintln(out, "Each local port must be different.")
			}
			continue
		}
		return port, nil
	}
}

func parseInstallPort(raw string) (int, error) {
	port, err := strconv.Atoi(raw)
	if err != nil {
		return 0, errors.New("port must be an integer between 1 and 65535")
	}
	if port < 1 || port > 65535 {
		return 0, errors.New("port must be an integer between 1 and 65535")
	}
	return port, nil
}

func launcherPath(binaryPath string) string {
	base := strings.TrimSuffix(binaryPath, filepath.Ext(binaryPath))
	if runtime.GOOS == "windows" {
		return base + "-mcp.cmd"
	}
	return base + "-mcp"
}

func writeLocalLauncher(path, binaryPath string, config localInstallConfig) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create parent directory for %q: %w", path, err)
	}

	content := renderLocalLauncher(runtime.GOOS, binaryPath, config)
	if err := os.WriteFile(path, []byte(content), 0o755); err != nil {
		return fmt.Errorf("write launcher %q: %w", path, err)
	}
	if runtime.GOOS != "windows" {
		if err := os.Chmod(path, 0o755); err != nil {
			return fmt.Errorf("chmod launcher %q: %w", path, err)
		}
	}
	return nil
}

func renderLocalLauncher(goos, binaryPath string, config localInstallConfig) string {
	if goos == "windows" {
		return strings.Join([]string{
			"@echo off",
			`set "HOST=127.0.0.1"`,
			fmt.Sprintf(`set "PORT=%d"`, config.observerPort),
			fmt.Sprintf(`set "OTLP_HTTP_PORT=%d"`, config.otlpHTTPPort),
			fmt.Sprintf(`set "OTLP_GRPC_PORT=%d"`, config.otlpGRPCPort),
			fmt.Sprintf(`"%s" %%*`, binaryPath),
			"",
		}, "\r\n")
	}

	return strings.Join([]string{
		"#!/bin/sh",
		"set -eu",
		`export HOST="127.0.0.1"`,
		fmt.Sprintf("export PORT=%q", fmt.Sprintf("%d", config.observerPort)),
		fmt.Sprintf("export OTLP_HTTP_PORT=%q", fmt.Sprintf("%d", config.otlpHTTPPort)),
		fmt.Sprintf("export OTLP_GRPC_PORT=%q", fmt.Sprintf("%d", config.otlpGRPCPort)),
		fmt.Sprintf("exec %q \"$@\"", binaryPath),
		"",
	}, "\n")
}

func installSiblingRuntime(exePath, destDir, runtimeName string) (string, bool, error) {
	siblingName := runtimeName + filepath.Ext(exePath)
	siblingPath := filepath.Join(filepath.Dir(exePath), siblingName)

	info, err := os.Stat(siblingPath)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return "", false, nil
		}
		return "", false, fmt.Errorf("stat companion runtime %q: %w", siblingPath, err)
	}
	if info.IsDir() {
		return "", false, fmt.Errorf("companion runtime %q is a directory", siblingPath)
	}

	installedPath := filepath.Join(destDir, siblingName)
	if err := copyFile(siblingPath, installedPath); err != nil {
		return "", false, err
	}
	if err := os.Chmod(installedPath, 0o755); err != nil {
		return "", false, fmt.Errorf("chmod companion runtime %q: %w", installedPath, err)
	}
	return installedPath, true, nil
}

func isInteractiveTerminal(stdin, stdout *os.File) bool {
	if stdin == nil || stdout == nil {
		return false
	}

	stdinInfo, err := stdin.Stat()
	if err != nil || (stdinInfo.Mode()&os.ModeCharDevice) == 0 {
		return false
	}
	stdoutInfo, err := stdout.Stat()
	if err != nil || (stdoutInfo.Mode()&os.ModeCharDevice) == 0 {
		return false
	}
	return true
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
