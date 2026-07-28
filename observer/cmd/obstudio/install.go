package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"github.com/spf13/cobra"
	"golang.org/x/term"
)

type mcpConfigFormat string

const (
	mcpConfigJSON mcpConfigFormat = "json"
	mcpConfigTOML mcpConfigFormat = "toml"

	codexManagedBlockStart = "# BEGIN OBSTUDIO MCP CONFIG"
	codexManagedBlockEnd   = "# END OBSTUDIO MCP CONFIG"

	defaultSharedObserverBaseURL      = "http://127.0.0.1:3000"
	defaultSharedObserverMCPURL       = defaultSharedObserverBaseURL + "/mcp"
	defaultSharedObserverHealth       = defaultSharedObserverBaseURL + "/api/health"
	sharedObserverHealthTimeout       = 750 * time.Millisecond
	disableSharedObserverDetectionEnv = "OBSTUDIO_DISABLE_SHARED_OBSERVER_DETECTION"

	sharedObserverStateDirName  = ".obstudio"
	sharedObserverStateFileName = "shared-observer.json"
	skillBackupDirName          = ".obstudio-skill-backups"
)

type mcpConfigTarget struct {
	format                mcpConfigFormat
	path                  func() string
	includeRemoteType     bool
	preserveFields        []string
	preserveSameURLFields []string
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

type sharedObserverState struct {
	BaseURL   string    `json:"baseUrl,omitempty"`
	HealthURL string    `json:"healthUrl,omitempty"`
	MCPURL    string    `json:"mcpUrl,omitempty"`
	PID       int       `json:"pid,omitempty"`
	UpdatedAt time.Time `json:"updatedAt,omitempty"`
}

var targets = map[string]agentTarget{
	"cursor": {
		skillsDir: func(home string) string { return filepath.Join(home, ".cursor", "skills", "obstudio") },
		mcpConfig: mcpConfigTarget{
			format:            mcpConfigJSON,
			path:              func() string { return filepath.Join(userHome(), ".cursor", "mcp.json") },
			includeRemoteType: true,
		},
	},
	"claude-code": {
		skillsDir: func(home string) string { return filepath.Join(home, ".claude", "skills", "obstudio") },
		mcpConfig: mcpConfigTarget{
			format:            mcpConfigJSON,
			path:              func() string { return filepath.Join(userHome(), ".claude.json") },
			includeRemoteType: true,
		},
	},
	"codex": {
		skillsDir: func(home string) string { return filepath.Join(home, ".codex", "skills", "obstudio") },
		mcpConfig: mcpConfigTarget{
			format: mcpConfigTOML,
			path:   func() string { return filepath.Join(userHome(), ".codex", "config.toml") },
		},
	},
	"kiro": {
		skillsDir: func(home string) string { return filepath.Join(home, ".kiro", "skills", "obstudio") },
		mcpConfig: mcpConfigTarget{
			format:                mcpConfigJSON,
			path:                  func() string { return filepath.Join(userHome(), ".kiro", "settings", "mcp.json") },
			preserveFields:        []string{"autoApprove", "disabled", "disabledTools", "timeout"},
			preserveSameURLFields: []string{"headers", "env", "oauth", "oauthScopes"},
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
	var requestedTargets []string
	var sharedURL string
	var connectRemoteO11y bool

	cmd := &cobra.Command{
		Use:   "install",
		Short: "Install skills and configure MCP for one or more AI coding agents",
		RunE: func(cmd *cobra.Command, _ []string) error {
			targetNames, err := normalizeInstallTargets(requestedTargets)
			if err != nil {
				return err
			}
			if err := runInstallTargets(targetNames, sharedURL); err != nil {
				return err
			}
			var connectFlag *bool
			if cmd.Flags().Changed("connect-remote-o11y") {
				connectFlag = &connectRemoteO11y
			}
			return maybeConnectRemoteO11y(targetNames, connectFlag, os.Stdin, os.Stdout)
		},
	}

	cmd.Flags().StringSliceVar(&requestedTargets, "target", nil, "Agent target or comma-separated targets ("+supportedTargets()+")")
	cmd.Flags().StringVar(&sharedURL, "shared-url", "", "Use an existing HTTP MCP endpoint instead of auto-starting a local obstudio binary")
	cmd.Flags().BoolVar(&connectRemoteO11y, "connect-remote-o11y", false, "Also connect the installed target(s) to the Splunk Observability remote MCP server (via npx @splunk/o11y-mcp-connect)")
	cmd.MarkFlagRequired("target")

	return cmd
}

func normalizeInstallTargets(requested []string) ([]string, error) {
	normalized := make([]string, 0, len(requested))
	seen := make(map[string]struct{}, len(requested))
	for _, rawTarget := range requested {
		target := strings.TrimSpace(rawTarget)
		if target == "" {
			return nil, fmt.Errorf("target cannot be empty (supported: %s)", supportedTargets())
		}
		if _, ok := targets[target]; !ok {
			return nil, fmt.Errorf("unknown target: %s (supported: %s)", target, supportedTargets())
		}
		if _, duplicate := seen[target]; duplicate {
			continue
		}
		seen[target] = struct{}{}
		normalized = append(normalized, target)
	}
	if len(normalized) == 0 {
		return nil, fmt.Errorf("at least one target is required (supported: %s)", supportedTargets())
	}
	return normalized, nil
}

func runInstallTargets(requested []string, sharedURL string) error {
	targetNames, err := normalizeInstallTargets(requested)
	if err != nil {
		return err
	}
	for _, target := range targetNames {
		if err := runInstall(target, sharedURL); err != nil {
			return fmt.Errorf("install target %s: %w", target, err)
		}
	}
	return nil
}

func runInstall(target, sharedURL string) error {
	t, ok := targets[target]
	if !ok {
		return fmt.Errorf("unknown target: %s (supported: %s)", target, supportedTargets())
	}
	resolvedSharedURL := sharedURL
	autodetectedSharedURL := false
	if resolvedSharedURL == "" && os.Getenv(disableSharedObserverDetectionEnv) == "" {
		if detectedURL, ok := detectConfiguredSharedObserverURL(http.DefaultClient); ok {
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
	skillsRoot := filepath.Dir(destDir)

	fmt.Printf("Installing obstudio to %s\n", destDir)

	removeSkillSymlinks(skillsRoot, destDir)

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

	if err := createSkillSymlinks(skillsRoot, destDir); err != nil {
		return fmt.Errorf("failed to create skill symlinks: %w", err)
	}
	fmt.Println("  Skill symlinks created for agent discovery.")

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
	weaverInstalled, externalWeaver, err := ensureInstallWeaverRuntime(exePath, destDir, resolvedSharedURL == "")
	if err != nil {
		return fmt.Errorf("failed to install Weaver runtime: %w", err)
	}
	if weaverInstalled {
		fmt.Println("  Weaver runtime installed.")
	} else if externalWeaver != "" && resolvedSharedURL == "" {
		fmt.Printf("  Weaver runtime resolved via %s.\n", externalWeaver)
	}

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
		fmt.Printf("\nDone. Restart %s to activate the MCP server.\n", target)
		return nil
	}

	fmt.Printf("\nDone. Start the shared obstudio server before using %s:\n", target)
	fmt.Println("  obstudio")
	return nil
}

// connectorIDEByTarget maps an obstudio install target to the --ide name the
// splunk-o11y-mcp-connect CLI expects. kiro has no entry: the connector only
// covers vscode/cursor/codex/claude-code.
var connectorIDEByTarget = map[string]string{
	"cursor":      "cursor",
	"claude-code": "claude-code",
	"codex":       "codex",
}

// mapTargetsToConnectorIDEs returns the connector --ide names for the given
// obstudio targets, preserving order and dropping unsupported targets (kiro).
func mapTargetsToConnectorIDEs(targetNames []string) []string {
	ides := make([]string, 0, len(targetNames))
	for _, target := range targetNames {
		if ide, ok := connectorIDEByTarget[target]; ok {
			ides = append(ides, ide)
		}
	}
	return ides
}

// unsupportedConnectorTargets returns the given obstudio targets that have no
// splunk-o11y-mcp-connect --ide equivalent (currently just kiro), preserving
// order, so a mixed selection (e.g. cursor,kiro) can still report the gap
// instead of silently dropping it.
func unsupportedConnectorTargets(targetNames []string) []string {
	unsupported := make([]string, 0, len(targetNames))
	for _, target := range targetNames {
		if _, ok := connectorIDEByTarget[target]; !ok {
			unsupported = append(unsupported, target)
		}
	}
	return unsupported
}

// shouldConnectRemoteO11y decides whether to invoke the remote-connect step.
// connectFlag is nil when --connect-remote-o11y was never passed, and
// non-nil with the explicit value otherwise -- an explicit false must
// suppress both the connection and the interactive prompt, the same as an
// explicit true skips straight to connecting. Only a nil flag falls through
// to asking on an interactive TTY; a non-TTY session with a nil flag skips
// silently, since this step is opt-in and must never block or fail an
// obstudio install.
func shouldConnectRemoteO11y(connectFlag *bool, isInteractive bool, answer string) bool {
	if connectFlag != nil {
		return *connectFlag
	}
	if !isInteractive {
		return false
	}
	answer = strings.ToLower(strings.TrimSpace(answer))
	return answer == "y" || answer == "yes"
}

// remoteO11yConnectArgs builds the argv (excluding the "npx" binary itself)
// for shelling out to the core connector.
func remoteO11yConnectArgs(ides []string) []string {
	return []string{"-y", "@splunk/o11y-mcp-connect", "connect", "--ide", strings.Join(ides, ",")}
}

const manualSetupPointer = "see the manual config snippets in the splunk-o11y-mcp-connect repo's docs/manual-setup.md."

// isInteractiveTerminal reports whether stdin is an actual terminal, not just
// a character device -- os.ModeCharDevice alone is also set for /dev/null,
// which would otherwise make a caller that redirects stdin from /dev/null
// (including exec.Cmd's default) look interactive and print the [y/N]
// prompt, violating the promised silent non-interactive behavior.
func isInteractiveTerminal(stdin io.Reader) bool {
	file, ok := stdin.(*os.File)
	if !ok {
		return false
	}
	return term.IsTerminal(int(file.Fd()))
}

// maybeConnectRemoteO11y optionally shells out to the O11Y MCP connector
// after a local install completes, so the user can also point the same
// target(s) at the remote Splunk Observability MCP server. obstudio never
// collects or sees the realm/token itself: stdio is inherited so the
// connector's own masked prompt (or SPLUNK_O11Y_REALM/SPLUNK_O11Y_TOKEN env
// vars, if the caller set them) handles credentials directly. A failure here
// is reported as a warning, never a failed install -- the local setup this
// command exists for has already succeeded.
func maybeConnectRemoteO11y(targetNames []string, connectFlag *bool, stdin io.Reader, stdout io.Writer) error {
	isInteractive := false
	var answer string
	if connectFlag == nil {
		isInteractive = isInteractiveTerminal(stdin)
		if isInteractive {
			fmt.Fprint(stdout, "\nAlso connect to the Splunk Observability remote MCP server? [y/N]: ")
			// Read byte-by-byte rather than via bufio.NewReader: a buffered
			// reader's fill() can slurp already-queued input past this
			// answer's newline (e.g. a pasted "y\n<realm>\n<token>\n" block)
			// into its own internal buffer and drop it, since stdin is
			// handed to the npx child directly afterward rather than
			// through this same reader.
			answer, _ = readLine(stdin)
		}
	}

	// Decide opt-in before looking at target support, so a non-interactive
	// run with no flag skips silently regardless of which targets were
	// selected -- including a kiro-only selection, which must not print a
	// note the user never asked to see.
	if !shouldConnectRemoteO11y(connectFlag, isInteractive, answer) {
		return nil
	}

	if unsupported := unsupportedConnectorTargets(targetNames); len(unsupported) > 0 {
		fmt.Fprintf(stdout, "\nNote: the O11Y remote MCP connector doesn't support %s yet -- %s\n", strings.Join(unsupported, ", "), manualSetupPointer)
	}

	ides := mapTargetsToConnectorIDEs(targetNames)
	if len(ides) == 0 {
		return nil
	}

	if _, err := exec.LookPath("npx"); err != nil {
		fmt.Fprintf(stdout, "  npx not found on PATH -- %s\n", manualSetupPointer)
		return nil
	}

	fmt.Fprintf(stdout, "\nConnecting %s to the Splunk Observability remote MCP server...\n", strings.Join(ides, ", "))
	cmd := exec.Command("npx", remoteO11yConnectArgs(ides)...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		fmt.Fprintf(stdout, "  Warning: connecting to the remote O11Y MCP server failed: %v -- %s\n", err, manualSetupPointer)
	}
	return nil
}

// readLine reads a single newline-terminated line one byte at a time so it
// never reads past the newline into input meant for a later reader (the npx
// child process, which is handed the same underlying stdin right after this
// call returns).
func readLine(r io.Reader) (string, error) {
	var line []byte
	buf := make([]byte, 1)
	for {
		n, err := r.Read(buf)
		if n > 0 {
			if buf[0] == '\n' {
				return string(line), nil
			}
			line = append(line, buf[0])
		}
		if err != nil {
			return string(line), err
		}
	}
}

func detectConfiguredSharedObserverURL(client *http.Client) (string, bool) {
	if detectedURL, ok := detectSharedObserverURLFromStateFile(sharedObserverStatePath(), client); ok {
		return detectedURL, true
	}
	return detectSharedObserverURL(defaultSharedObserverHealth, client)
}

func ensureInstallWeaverRuntime(exePath, destDir string, requireLocalRuntime bool) (bool, string, error) {
	installed, err := copySiblingWeaverRuntime(exePath, destDir)
	if err != nil {
		return false, "", err
	}
	if installed {
		return true, filepath.Join(destDir, installedWeaverName(exePath)), nil
	}
	if external := externalWeaverRuntime(); external != "" {
		return false, external, nil
	}
	if requireLocalRuntime {
		return false, "", errors.New("Weaver runtime not found beside obstudio or on PATH; validation requires the bundled weaver binary from the release archive")
	}
	return false, "", nil
}

func installedWeaverName(exePath string) string {
	if filepath.Ext(exePath) == ".exe" {
		return "weaver.exe"
	}
	return "weaver"
}

func externalWeaverRuntime() string {
	if custom := strings.TrimSpace(os.Getenv("WEAVER_PATH")); custom != "" {
		if _, err := os.Stat(custom); err == nil {
			return custom
		}
	}
	if resolved, err := exec.LookPath("weaver"); err == nil {
		return resolved
	}
	return ""
}

func copySiblingWeaverRuntime(exePath, destDir string) (bool, error) {
	candidates := []string{filepath.Join(filepath.Dir(exePath), "weaver")}
	if filepath.Ext(exePath) == ".exe" {
		candidates = append(candidates, filepath.Join(filepath.Dir(exePath), "weaver.exe"))
	}

	for _, candidate := range candidates {
		info, err := os.Stat(candidate)
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return false, err
		}
		if info.IsDir() {
			continue
		}

		destPath := filepath.Join(destDir, filepath.Base(candidate))
		if err := copyFile(candidate, destPath); err != nil {
			return false, err
		}
		if err := os.Chmod(destPath, 0o755); err != nil {
			return false, err
		}
		return true, nil
	}

	return false, nil
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

func detectSharedObserverURLFromStateFile(statePath string, client *http.Client) (string, bool) {
	state, err := readSharedObserverState(statePath)
	if err != nil {
		return "", false
	}

	healthURL := strings.TrimSpace(state.HealthURL)
	if healthURL == "" {
		return "", false
	}
	return detectSharedObserverURL(healthURL, client)
}

func sharedObserverStatePath() string {
	return filepath.Join(userHome(), sharedObserverStateDirName, sharedObserverStateFileName)
}

func readSharedObserverState(statePath string) (sharedObserverState, error) {
	data, err := os.ReadFile(statePath)
	if err != nil {
		return sharedObserverState{}, err
	}

	var state sharedObserverState
	if err := json.Unmarshal(data, &state); err != nil {
		return sharedObserverState{}, fmt.Errorf("parse shared observer state %q: %w", statePath, err)
	}
	return state, nil
}

func writeSharedObserverState(statePath string, state sharedObserverState) error {
	if err := os.MkdirAll(filepath.Dir(statePath), 0o755); err != nil {
		return fmt.Errorf("create parent directory for %q: %w", statePath, err)
	}

	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal shared observer state %q: %w", statePath, err)
	}

	stateDir := filepath.Dir(statePath)
	tempFile, err := os.CreateTemp(stateDir, "."+filepath.Base(statePath)+".tmp-*")
	if err != nil {
		return fmt.Errorf("create temporary shared observer state for %q: %w", statePath, err)
	}
	tempPath := tempFile.Name()
	defer os.Remove(tempPath)

	if err := tempFile.Chmod(0o644); err != nil {
		tempFile.Close()
		return fmt.Errorf("set permissions on temporary shared observer state for %q: %w", statePath, err)
	}
	if _, err := tempFile.Write(append(data, '\n')); err != nil {
		tempFile.Close()
		return fmt.Errorf("write temporary shared observer state for %q: %w", statePath, err)
	}
	if err := tempFile.Close(); err != nil {
		return fmt.Errorf("close temporary shared observer state for %q: %w", statePath, err)
	}
	if err := os.Rename(tempPath, statePath); err != nil {
		return fmt.Errorf("publish shared observer state %q: %w", statePath, err)
	}
	return nil
}

func clearSharedObserverStateIfOwned(statePath string, state sharedObserverState) error {
	current, err := readSharedObserverState(statePath)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return err
	}

	if current.PID != state.PID || current.MCPURL != state.MCPURL || current.HealthURL != state.HealthURL {
		return nil
	}
	if err := os.Remove(statePath); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

func configureMCP(target mcpConfigTarget, binaryPath, sharedURL string) error {
	switch target.format {
	case mcpConfigJSON:
		server := map[string]any{}
		if sharedURL == "" {
			server["command"] = binaryPath
			server["args"] = []string{}
		} else {
			if target.includeRemoteType {
				server["type"] = "http"
			}
			server["url"] = sharedURL
		}
		return upsertJSONMCPServer(target.path(), server, target.preserveFields, target.preserveSameURLFields)
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

func upsertJSONMCPServer(path string, server map[string]any, preserveFields, preserveSameURLFields []string) error {
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
	if existing, ok := servers["obstudio"].(map[string]any); ok {
		existingURL, existingHasURL := existing["url"].(string)
		serverURL, serverHasURL := server["url"].(string)
		if existingHasURL && serverHasURL && existingURL != "" && existingURL == serverURL {
			for _, field := range preserveSameURLFields {
				if value, exists := existing[field]; exists {
					server[field] = value
				}
			}
		}
		for _, field := range preserveFields {
			if value, exists := existing[field]; exists {
				server[field] = value
			}
		}
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

// createSkillSymlinks creates relative symlinks in skillsRoot for each skill
// directory (contains SKILL.md) found inside obstudioDir. This makes skills
// discoverable by agents that expect each skill as a direct child of the
// skills root. References are inlined per-skill at build time, so no
// top-level references symlink is needed. Existing non-managed paths are
// preserved in a stable, per-skill backup location before the link is created.
func createSkillSymlinks(skillsRoot, obstudioDir string) error {
	return createSkillSymlinksWith(skillsRoot, obstudioDir, os.Symlink)
}

func createSkillSymlinksWith(
	skillsRoot,
	obstudioDir string,
	symlink func(string, string) error,
) error {
	type symlinkPlan struct {
		name               string
		link               string
		target             string
		backup             string
		existingLinkTarget string
		backupLinkTarget   string
		preserveAsSymlink  bool
	}

	obstudioName := filepath.Base(obstudioDir)
	entries, err := os.ReadDir(obstudioDir)
	if err != nil {
		return fmt.Errorf("read obstudio dir: %w", err)
	}

	backupRoot := filepath.Join(skillsRoot, skillBackupDirName)
	plans := make([]symlinkPlan, 0, len(entries))
	needsBackupRoot := false
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		name := e.Name()
		if _, statErr := os.Stat(filepath.Join(obstudioDir, name, "SKILL.md")); statErr != nil {
			continue
		}
		link := filepath.Join(skillsRoot, name)
		target := filepath.Join(obstudioName, name)

		plan := symlinkPlan{name: name, link: link, target: target}
		info, statErr := os.Lstat(link)
		switch {
		case statErr == nil:
			if info.Mode()&os.ModeSymlink != 0 {
				dest, readErr := os.Readlink(link)
				if readErr != nil {
					return fmt.Errorf("read existing skill symlink %s: %w", link, readErr)
				}
				if dest == target {
					continue
				}
				plan.existingLinkTarget = dest
				plan.preserveAsSymlink = true
			}

			plan.backup = filepath.Join(backupRoot, name)
			if _, backupErr := os.Lstat(plan.backup); backupErr == nil {
				return fmt.Errorf(
					"cannot replace existing skill %s: one-time backup already exists at %s",
					link,
					plan.backup,
				)
			} else if !errors.Is(backupErr, os.ErrNotExist) {
				return fmt.Errorf("inspect skill backup %s: %w", plan.backup, backupErr)
			}
			if plan.preserveAsSymlink {
				plan.backupLinkTarget = plan.existingLinkTarget
				if !filepath.IsAbs(plan.existingLinkTarget) {
					resolvedTarget := filepath.Join(filepath.Dir(plan.link), plan.existingLinkTarget)
					backupTarget, relErr := filepath.Rel(filepath.Dir(plan.backup), resolvedTarget)
					if relErr != nil {
						return fmt.Errorf("preserve relative skill symlink %s: %w", link, relErr)
					}
					plan.backupLinkTarget = backupTarget
				}
			}
			needsBackupRoot = true
		case errors.Is(statErr, os.ErrNotExist):
		default:
			return fmt.Errorf("inspect existing skill path %s: %w", link, statErr)
		}
		plans = append(plans, plan)
	}

	if needsBackupRoot {
		if err := ensureSkillBackupDir(backupRoot); err != nil {
			return err
		}
	}

	for _, plan := range plans {
		if plan.backup != "" {
			if plan.preserveAsSymlink {
				if err := os.Symlink(plan.backupLinkTarget, plan.backup); err != nil {
					return fmt.Errorf("preserve existing skill symlink %s in %s: %w", plan.link, plan.backup, err)
				}
				if err := os.Remove(plan.link); err != nil {
					if cleanupErr := os.Remove(plan.backup); cleanupErr != nil {
						return fmt.Errorf(
							"remove existing skill symlink %s: %w (also failed to remove backup %s: %v)",
							plan.link,
							err,
							plan.backup,
							cleanupErr,
						)
					}
					return fmt.Errorf("remove existing skill symlink %s: %w", plan.link, err)
				}
			} else if err := os.Rename(plan.link, plan.backup); err != nil {
				return fmt.Errorf("preserve existing skill %s in %s: %w", plan.link, plan.backup, err)
			}
			fmt.Printf("  Existing skill %s preserved in %s.\n", plan.name, plan.backup)
		}

		if err := symlink(plan.target, plan.link); err != nil {
			if plan.backup != "" {
				var rollbackErr error
				if plan.preserveAsSymlink {
					rollbackErr = os.Symlink(plan.existingLinkTarget, plan.link)
					if rollbackErr == nil {
						rollbackErr = os.Remove(plan.backup)
					}
				} else {
					rollbackErr = os.Rename(plan.backup, plan.link)
				}
				if rollbackErr != nil {
					return fmt.Errorf(
						"symlink %s -> %s: %w (rollback failed for %s: %v)",
						plan.link,
						plan.target,
						err,
						plan.link,
						rollbackErr,
					)
				}
			}
			return fmt.Errorf("symlink %s -> %s: %w", plan.link, plan.target, err)
		}
	}
	return nil
}

func ensureSkillBackupDir(path string) error {
	info, err := os.Lstat(path)
	switch {
	case err == nil:
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return fmt.Errorf("skill backup path is not a directory: %s", path)
		}
		return nil
	case errors.Is(err, os.ErrNotExist):
		if err := os.Mkdir(path, 0o700); err != nil {
			return fmt.Errorf("create skill backup directory %s: %w", path, err)
		}
		return nil
	default:
		return fmt.Errorf("inspect skill backup directory %s: %w", path, err)
	}
}

// removeSkillSymlinks removes symlinks in skillsRoot whose targets point into
// obstudioDir. Other entries are left untouched.
func removeSkillSymlinks(skillsRoot, obstudioDir string) {
	obstudioName := filepath.Base(obstudioDir)
	prefix := obstudioName + string(filepath.Separator)

	entries, err := os.ReadDir(skillsRoot)
	if err != nil {
		return
	}
	for _, e := range entries {
		if e.Type()&os.ModeSymlink == 0 {
			continue
		}
		link := filepath.Join(skillsRoot, e.Name())
		dest, err := os.Readlink(link)
		if err != nil {
			continue
		}
		if strings.HasPrefix(dest, prefix) || dest == obstudioName {
			_ = os.Remove(link)
		}
	}
}

func userHome() string {
	home, err := os.UserHomeDir()
	if err != nil {
		log.Fatalf("Failed to find home directory: %v", err)
	}
	return home
}
