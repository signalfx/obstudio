package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/signalfx/obstudio/observer/internal/api"
)

type mcpConfigFormat string

type mcpServersKey string

type privateConfigTemporary interface {
	Name() string
	Stat() (os.FileInfo, error)
	Write([]byte) (int, error)
	Sync() error
	Close() error
}

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
	serversKey            mcpServersKey
	includeLocalType      bool
	includeRemoteType     bool
	preserveFields        []string
	preserveSameURLFields []string
}

type agentTarget struct {
	skillsDir func(string) string
	mcpConfig mcpConfigTarget
}

type codexMCPServer struct {
	URL           string
	Command       string
	Args          []string
	Authorization string
	Headers       []codexMCPHeader
}

type codexMCPHeader struct {
	Name      string
	TOMLKey   string
	TOMLValue string
}

type sharedObserverHealth struct {
	APIVersion     string            `json:"apiVersion"`
	ChallengeProof string            `json:"challengeProof,omitempty"`
	Endpoints      map[string]string `json:"endpoints"`
	Kind           string            `json:"kind"`
	Mode           string            `json:"mode"`
	Owner          string            `json:"owner"`
	Version        string            `json:"version"`
}

type sharedObserverState struct {
	BaseURL           string    `json:"baseUrl,omitempty"`
	ControlToken      string    `json:"controlToken,omitempty"`
	HealthProofSecret string    `json:"healthProofSecret,omitempty"`
	HealthURL         string    `json:"healthUrl,omitempty"`
	MCPURL            string    `json:"mcpUrl,omitempty"`
	PID               int       `json:"pid,omitempty"`
	UpdatedAt         time.Time `json:"updatedAt,omitempty"`
}

var targets = map[string]agentTarget{
	"cursor": {
		skillsDir: func(home string) string { return filepath.Join(home, ".cursor", "skills", "obstudio") },
		mcpConfig: mcpConfigTarget{
			format:                mcpConfigJSON,
			path:                  func() string { return filepath.Join(userHome(), ".cursor", "mcp.json") },
			serversKey:            "mcpServers",
			includeRemoteType:     true,
			preserveSameURLFields: []string{"headers"},
		},
	},
	"claude-code": {
		skillsDir: func(home string) string { return filepath.Join(home, ".claude", "skills", "obstudio") },
		mcpConfig: mcpConfigTarget{
			format:                mcpConfigJSON,
			path:                  func() string { return filepath.Join(userHome(), ".claude.json") },
			serversKey:            "mcpServers",
			includeRemoteType:     true,
			preserveSameURLFields: []string{"headers"},
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
			serversKey:            "mcpServers",
			preserveFields:        []string{"autoApprove", "disabled", "disabledTools", "timeout"},
			preserveSameURLFields: []string{"headers", "env", "oauth", "oauthScopes"},
		},
	},
	"windsurf": {
		skillsDir: func(home string) string { return filepath.Join(home, ".codeium", "windsurf", "skills", "obstudio") },
		mcpConfig: mcpConfigTarget{
			format:                mcpConfigJSON,
			path:                  func() string { return filepath.Join(userHome(), ".codeium", "windsurf", "mcp_config.json") },
			serversKey:            "mcpServers",
			includeRemoteType:     true,
			preserveSameURLFields: []string{"headers"},
		},
	},
	"copilot": {
		mcpConfig: mcpConfigTarget{
			format:                mcpConfigJSON,
			path:                  func() string { return filepath.Join(userConfigDir(), "Code", "User", "mcp.json") },
			serversKey:            "servers",
			includeLocalType:      true,
			includeRemoteType:     true,
			preserveSameURLFields: []string{"headers"},
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

	cmd := &cobra.Command{
		Use:   "install",
		Short: "Install skills and configure MCP for one or more AI coding agents",
		RunE: func(cmd *cobra.Command, _ []string) error {
			targetNames, err := normalizeInstallTargets(requestedTargets)
			if err != nil {
				return err
			}
			release, err := acquireManagedLifecycleLock()
			if err != nil {
				return err
			}
			defer release()
			return runInstallTargets(targetNames, sharedURL)
		},
	}

	cmd.Flags().StringSliceVar(&requestedTargets, "target", nil, "Agent target or comma-separated targets ("+supportedTargets()+")")
	cmd.Flags().StringVar(&sharedURL, "shared-url", "", "Use an existing HTTP MCP endpoint instead of auto-starting a local obstudio binary")
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
	resolvedSharedURL, controlToken, autodetectedSharedURL, err := resolveInstallSharedObserver(
		sharedURL,
		http.DefaultClient,
	)
	if err != nil {
		return err
	}

	home := userHome()
	destDir := filepath.Join(home, sharedObserverStateDirName, "bin")

	if t.skillsDir != nil {
		destDir = t.skillsDir(home)
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
	} else {
		fmt.Printf("Installing obstudio to %s\n", destDir)
		fmt.Println("  Skills installation not supported for this target; skipping.")
	}

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
	if err := configureMCP(t.mcpConfig, installedBinary, resolvedSharedURL, controlToken); err != nil {
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
	if managedObserverMatchesURL(resolvedSharedURL, http.DefaultClient) {
		fmt.Println("\nUpdate installed. Run `obstudio restart` when convenient to activate the new version.")
		return nil
	}

	fmt.Printf("\nDone. Start the shared obstudio server before using %s:\n", target)
	fmt.Println("  obstudio")
	return nil
}

func resolveInstallSharedObserver(
	requestedURL string,
	client *http.Client,
) (resolvedURL, controlToken string, autodetected bool, err error) {
	if requestedURL == "" {
		if os.Getenv(disableSharedObserverDetectionEnv) != "" {
			return "", "", false, nil
		}
		detectedURL, detectedToken, ok := detectInstallSharedObserverURL(client)
		detectedToken = strings.TrimSpace(detectedToken)
		if !ok || detectedToken == "" {
			return "", "", false, nil
		}
		normalized, normalizeErr := normalizeSharedURL(detectedURL, "detected shared observer URL")
		if normalizeErr != nil {
			return "", "", false, normalizeErr
		}
		return normalized, detectedToken, true, nil
	}

	normalized, err := normalizeSharedURL(requestedURL, "--shared-url")
	if err != nil {
		return "", "", false, err
	}
	advertisedURL, verifiedToken := resolveMCPControlWithClient(normalized, client)
	if verifiedToken == "" {
		return "", "", false, errors.New(
			"could not verify Observer control for --shared-url; use its private shared state or set OBSTUDIO_CONTROL_TOKEN and OBSTUDIO_HEALTH_PROOF_SECRET, then ensure its health endpoint is reachable",
		)
	}
	return advertisedURL, verifiedToken, false, nil
}

func managedObserverMatchesURL(sharedURL string, client *http.Client) bool {
	health, state, err := managedObserverHealth(client)
	if err != nil || health.Owner != "cli" || health.Mode != managedObserverMode {
		return false
	}
	managedEndpoint, managedErr := canonicalManagedEndpoint(state.MCPURL)
	configuredEndpoint, configuredErr := canonicalManagedEndpoint(sharedURL)
	return managedErr == nil && configuredErr == nil && managedEndpoint == configuredEndpoint
}

func canonicalManagedEndpoint(raw string) (string, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || parsed.Scheme == "" || parsed.Hostname() == "" {
		return "", errors.New("invalid managed endpoint URL")
	}
	host := strings.TrimSuffix(strings.ToLower(parsed.Hostname()), ".")
	if host == "localhost" {
		host = "127.0.0.1"
	} else if ip := net.ParseIP(host); ip != nil {
		host = ip.String()
	}
	port := parsed.Port()
	if port == "" {
		if strings.EqualFold(parsed.Scheme, "http") {
			port = "80"
		} else if strings.EqualFold(parsed.Scheme, "https") {
			port = "443"
		}
	}
	return strings.ToLower(parsed.Scheme) + "://" + net.JoinHostPort(host, port) + strings.TrimRight(parsed.EscapedPath(), "/"), nil
}

func detectInstallSharedObserverURL(client *http.Client) (string, string, bool) {
	return detectInstallSharedObserverURLFromSources(
		sharedObserverStatePath(),
		defaultSharedObserverHealth,
		client,
	)
}

func detectInstallSharedObserverURLFromSources(
	statePath string,
	fallbackHealthURL string,
	client *http.Client,
) (string, string, bool) {
	if detectedURL, controlToken, ok := detectSharedObserverURLFromStateFile(statePath, client); ok {
		return detectedURL, controlToken, true
	}

	controlToken := strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN"))
	proofSecret := strings.TrimSpace(os.Getenv(observerHealthProofSecretEnv))
	if controlToken == "" || proofSecret == "" {
		return "", "", false
	}
	detectedURL, ok := detectSharedObserverURL(fallbackHealthURL, client)
	if !ok {
		return "", "", false
	}
	advertisedURL, ok := proveSharedObserverControlToken(
		fallbackHealthURL,
		detectedURL,
		controlToken,
		proofSecret,
		client,
	)
	if !ok {
		return "", "", false
	}
	return advertisedURL, controlToken, true
}

func detectConfiguredSharedObserverURL(client *http.Client) (string, bool) {
	state, err := readSharedObserverState(sharedObserverStatePath())
	if err == nil && strings.TrimSpace(state.HealthURL) != "" {
		if detectedURL, ok := detectSharedObserverURL(state.HealthURL, client); ok {
			return detectedURL, true
		}
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
	health, ok := fetchSharedObserverHealth(healthURL, "", client)
	if !ok {
		return "", false
	}
	if mcpURL := strings.TrimSpace(health.Endpoints["mcp"]); mcpURL != "" {
		normalized, err := normalizeSharedURL(mcpURL, "detected shared observer URL")
		if err != nil {
			return "", false
		}
		return normalized, true
	}
	return defaultSharedObserverMCPURL, true
}

func fetchSharedObserverHealth(healthURL, challenge string, client *http.Client) (sharedObserverHealth, bool) {
	if err := validateSharedURL(healthURL, "shared observer health URL"); err != nil {
		return sharedObserverHealth{}, false
	}
	requestURL := healthURL
	if challenge != "" {
		parsed, err := url.Parse(healthURL)
		if err != nil {
			return sharedObserverHealth{}, false
		}
		query := parsed.Query()
		query.Set(api.HealthProofChallengeQuery, challenge)
		parsed.RawQuery = query.Encode()
		requestURL = parsed.String()
	}
	if client == nil {
		client = http.DefaultClient
	}
	requestClient := *client
	if requestClient.Timeout == 0 {
		requestClient.Timeout = sharedObserverHealthTimeout
	}
	if challenge != "" {
		requestClient.CheckRedirect = func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		}
	} else {
		originalCheckRedirect := requestClient.CheckRedirect
		requestClient.CheckRedirect = func(req *http.Request, via []*http.Request) error {
			if err := validateSharedURL(req.URL.String(), "shared observer health redirect"); err != nil {
				return err
			}
			if originalCheckRedirect != nil {
				return originalCheckRedirect(req, via)
			}
			if len(via) >= 10 {
				return fmt.Errorf("stopped after 10 redirects")
			}
			return nil
		}
	}

	resp, err := requestClient.Get(requestURL)
	if err != nil {
		return sharedObserverHealth{}, false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return sharedObserverHealth{}, false
	}

	var health sharedObserverHealth
	if err := json.NewDecoder(resp.Body).Decode(&health); err != nil {
		return sharedObserverHealth{}, false
	}
	if health.Kind != "obstudio" || health.APIVersion != "v1" {
		return sharedObserverHealth{}, false
	}
	return health, true
}

func detectSharedObserverURLFromStateFile(statePath string, client *http.Client) (string, string, bool) {
	state, err := readSharedObserverState(statePath)
	if err != nil {
		return "", "", false
	}

	healthURL := strings.TrimSpace(state.HealthURL)
	controlToken := strings.TrimSpace(state.ControlToken)
	proofSecret := strings.TrimSpace(state.HealthProofSecret)
	if healthURL == "" || controlToken == "" || proofSecret == "" {
		return "", "", false
	}
	stateMCPURL, err := normalizeSharedURL(strings.TrimSpace(state.MCPURL), "shared observer state")
	if err != nil {
		return "", "", false
	}
	advertisedMCPURL, ok := proveSharedObserverControlToken(
		healthURL,
		stateMCPURL,
		controlToken,
		proofSecret,
		client,
	)
	if !ok {
		return "", "", false
	}
	return advertisedMCPURL, controlToken, true
}

func sharedObserverControlTokenProofValid(
	healthURL string,
	mcpProofURL string,
	controlToken string,
	proofSecret string,
	client *http.Client,
) bool {
	_, ok := proveSharedObserverControlToken(healthURL, mcpProofURL, controlToken, proofSecret, client)
	return ok
}

func proveSharedObserverControlToken(
	healthURL string,
	intendedMCPURL string,
	controlToken string,
	proofSecret string,
	client *http.Client,
) (string, bool) {
	challenge, err := api.NewHealthProofChallenge()
	if err != nil {
		return "", false
	}
	health, ok := fetchSharedObserverHealth(healthURL, challenge, client)
	if !ok {
		return "", false
	}
	advertisedRaw := health.Endpoints["mcp"]
	advertisedMCPURL, err := normalizeSharedURL(advertisedRaw, "advertised shared observer URL")
	if err != nil || advertisedRaw != advertisedMCPURL || !sameSharedObserverControlEndpoint(intendedMCPURL, advertisedMCPURL) {
		return "", false
	}
	if !api.VerifyHealthChallengeProof(
		proofSecret,
		controlToken,
		challenge,
		advertisedRaw,
		health.ChallengeProof,
	) {
		return "", false
	}
	return advertisedMCPURL, true
}

func sharedObserverStatePath() string {
	return filepath.Join(userHome(), sharedObserverStateDirName, sharedObserverStateFileName)
}

func readSharedObserverState(statePath string) (sharedObserverState, error) {
	if err := validatePrivateConfigDirectory(filepath.Dir(statePath)); err != nil {
		return sharedObserverState{}, fmt.Errorf("validate shared observer state parent %q: %w", filepath.Dir(statePath), err)
	}
	data, err := readPrivateConfigFile(statePath)
	if err != nil {
		return sharedObserverState{}, fmt.Errorf("read private shared observer state %q: %w", statePath, err)
	}

	var state sharedObserverState
	if err := json.Unmarshal(data, &state); err != nil {
		return sharedObserverState{}, fmt.Errorf("parse shared observer state %q: %w", statePath, err)
	}
	return state, nil
}

func resolveMCPControlToken(sharedURL string) string {
	_, controlToken := resolveMCPControl(sharedURL)
	return controlToken
}

func resolveMCPControl(sharedURL string) (string, string) {
	return resolveMCPControlWithClient(sharedURL, http.DefaultClient)
}

func resolveMCPControlWithClient(sharedURL string, client *http.Client) (string, string) {
	if sharedURL == "" {
		return "", ""
	}
	healthURL, err := sharedObserverHealthURLForMCPURL(sharedURL)
	if err != nil {
		return sharedURL, ""
	}
	state, stateErr := readSharedObserverState(sharedObserverStatePath())
	stateMatchesEndpoint := false
	if stateErr == nil && strings.TrimSpace(state.HealthURL) != "" {
		stateMCPURL, normalizeErr := normalizeSharedURL(strings.TrimSpace(state.MCPURL), "shared observer state")
		if normalizeErr == nil && sameSharedObserverControlEndpoint(sharedURL, stateMCPURL) {
			healthURL = strings.TrimSpace(state.HealthURL)
			stateMatchesEndpoint = true
		}
	}
	if token := strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")); token != "" {
		proofSecret := strings.TrimSpace(os.Getenv(observerHealthProofSecretEnv))
		if proofSecret == "" && stateMatchesEndpoint {
			proofSecret = strings.TrimSpace(state.HealthProofSecret)
		}
		if advertisedURL, ok := proveSharedObserverControlToken(healthURL, sharedURL, token, proofSecret, client); ok {
			return advertisedURL, token
		}
	}

	if stateErr != nil {
		return sharedURL, ""
	}
	controlToken := strings.TrimSpace(state.ControlToken)
	proofSecret := strings.TrimSpace(state.HealthProofSecret)
	advertisedURL, ok := proveSharedObserverControlToken(
		healthURL,
		sharedURL,
		controlToken,
		proofSecret,
		client,
	)
	if !ok {
		return sharedURL, ""
	}
	return advertisedURL, controlToken
}

func sharedObserverHealthURLForMCPURL(mcpURL string) (string, error) {
	parsed, err := url.Parse(mcpURL)
	if err != nil {
		return "", err
	}
	trimmedPath := strings.TrimRight(parsed.Path, "/")
	if !strings.HasSuffix(trimmedPath, "/mcp") {
		return "", errors.New("shared Observer MCP URL does not end in /mcp")
	}
	parsed.Path = strings.TrimSuffix(trimmedPath, "/mcp") + "/api/health"
	parsed.RawPath = ""
	parsed.RawQuery = ""
	return parsed.String(), nil
}

func writeSharedObserverState(statePath string, state sharedObserverState) error {
	if err := os.MkdirAll(filepath.Dir(statePath), 0o700); err != nil {
		return fmt.Errorf("create parent directory for %q: %w", statePath, err)
	}

	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal shared observer state %q: %w", statePath, err)
	}
	if err := writePrivateConfigAtomically(statePath, append(data, '\n')); err != nil {
		return fmt.Errorf("write private shared observer state %q: %w", statePath, err)
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

func configureMCP(target mcpConfigTarget, binaryPath, sharedURL string, controlTokens ...string) error {
	if sharedURL != "" {
		normalized, err := normalizeSharedURL(sharedURL, "shared observer URL")
		if err != nil {
			return err
		}
		sharedURL = normalized
	}
	controlToken := ""
	if len(controlTokens) > 0 {
		controlToken = strings.TrimSpace(controlTokens[0])
	}
	var err error
	switch target.format {
	case mcpConfigJSON:
		server := map[string]any{}
		if sharedURL == "" {
			if target.includeLocalType {
				server["type"] = "stdio"
			}
			server["command"] = binaryPath
			server["args"] = []string{}
		} else {
			if target.includeRemoteType {
				server["type"] = "http"
			}
			server["url"] = sharedURL
			if controlToken != "" {
				server["headers"] = map[string]any{"Authorization": "Bearer " + controlToken}
			}
		}
		err = upsertJSONMCPServer(target.path(), target.serversKey, server, target.preserveFields, target.preserveSameURLFields, controlToken != "")
	case mcpConfigTOML:
		server := codexMCPServer{}
		if sharedURL == "" {
			server.Command = binaryPath
			server.Args = []string{}
		} else {
			server.URL = sharedURL
			if controlToken != "" {
				server.Authorization = "Bearer " + controlToken
			}
		}
		err = upsertCodexMCPServer(target.path(), server, controlToken != "")
	default:
		return fmt.Errorf("unsupported MCP config format: %s", target.format)
	}
	if err != nil {
		return err
	}
	return nil
}

func upsertJSONMCPServer(path string, serversKey mcpServersKey, server map[string]any, preserveFields, preserveSameURLFields []string, privateWrites ...bool) error {
	if serversKey == "" {
		return fmt.Errorf("serversKey is not configured for this target — open an issue at https://github.com/signalfx/obstudio/issues to request support")
	}

	config := map[string]any{}

	data, err := os.ReadFile(path)
	if err == nil {
		if err := json.Unmarshal(data, &config); err != nil {
			return fmt.Errorf("failed to parse %s: %w", path, err)
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("read JSON MCP config %q: %w", path, err)
	}

	servers, ok := config[string(serversKey)].(map[string]any)
	if !ok {
		servers = map[string]any{}
	}
	if existing, ok := servers["obstudio"].(map[string]any); ok {
		existingURL, existingHasURL := existing["url"].(string)
		serverURL, serverHasURL := server["url"].(string)
		if existingHasURL && serverHasURL && existingURL != "" && existingURL == serverURL {
			for _, field := range preserveSameURLFields {
				if value, exists := existing[field]; exists {
					if field == "headers" {
						mergedHeaders := make(map[string]any)
						desiredHeaders, _ := server[field].(map[string]any)
						if existingHeaders, ok := value.(map[string]any); ok {
							for name, headerValue := range existingHeaders {
								if strings.EqualFold(name, "Authorization") {
									continue
								}
								mergedHeaders[name] = headerValue
							}
						}
						if desiredHeaders != nil {
							for desiredName := range desiredHeaders {
								for existingName := range mergedHeaders {
									if strings.EqualFold(existingName, desiredName) {
										delete(mergedHeaders, existingName)
									}
								}
							}
							for name, headerValue := range desiredHeaders {
								mergedHeaders[name] = headerValue
							}
						}
						if len(mergedHeaders) > 0 {
							server[field] = mergedHeaders
						}
						continue
					}
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
	config[string(serversKey)] = servers

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create parent directory for %q: %w", path, err)
	}

	out, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal JSON MCP config %q: %w", path, err)
	}
	data = append(out, '\n')
	privateWrite := len(privateWrites) > 0 && privateWrites[0]
	if headers, ok := server["headers"].(map[string]any); ok {
		for name := range headers {
			if strings.EqualFold(name, "Authorization") {
				privateWrite = true
				break
			}
		}
	}
	if privateWrite {
		if err := writePrivateConfigAtomically(path, data); err != nil {
			return fmt.Errorf("write private JSON MCP config %q: %w", path, err)
		}
		return nil
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		return fmt.Errorf("write JSON MCP config %q: %w", path, err)
	}
	return nil
}

func upsertCodexMCPServer(path string, server codexMCPServer, privateWrites ...bool) error {
	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("read codex MCP config %q: %w", path, err)
	}

	content := string(data)
	if server.URL != "" {
		server.Headers, err = preservedCodexMCPHeaders(content, server.URL)
		if err != nil {
			return fmt.Errorf("inspect existing codex MCP headers in %q: %w", path, err)
		}
	}
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
	if (len(privateWrites) > 0 && privateWrites[0]) || len(server.Headers) > 0 {
		if err := writePrivateConfigAtomically(path, []byte(content)); err != nil {
			return fmt.Errorf("write private codex MCP config %q: %w", path, err)
		}
		return nil
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		return fmt.Errorf("write codex MCP config %q: %w", path, err)
	}
	return nil
}

func writePrivateConfigAtomically(path string, data []byte) error {
	directory := filepath.Dir(path)
	if err := validatePrivateConfigDirectory(directory); err != nil {
		return fmt.Errorf("validate private config directory: %w", err)
	}
	if targetInfo, err := os.Lstat(path); err == nil {
		if targetInfo.Mode()&os.ModeSymlink != 0 || !targetInfo.Mode().IsRegular() {
			return errors.New("private config target is not a regular file")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("inspect private config target: %w", err)
	}
	temporary, err := createPrivateConfigTemporary(directory, "."+filepath.Base(path)+".tmp-")
	if err != nil {
		return fmt.Errorf("create temporary config: %w", err)
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	temporaryInfo, err := temporary.Stat()
	if err != nil {
		_ = temporary.Close()
		return fmt.Errorf("stat temporary config: %w", err)
	}
	if err := verifyPrivateConfigPathIdentity(temporaryPath, temporaryInfo); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("verify temporary config before writing: %w", err)
	}
	if _, err := temporary.Write(data); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("write temporary config: %w", err)
	}
	if err := temporary.Sync(); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("sync temporary config: %w", err)
	}
	if err := validatePrivateConfigDirectory(directory); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("revalidate private config directory: %w", err)
	}
	if err := verifyPrivateConfigPathIdentity(temporaryPath, temporaryInfo); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("verify temporary config before publishing: %w", err)
	}
	if err := publishPrivateConfigFile(temporary, temporaryInfo, path); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("publish temporary config: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return fmt.Errorf("close published config: %w", err)
	}
	if err := securePrivateConfigFile(path); err != nil {
		return fmt.Errorf("verify published private config: %w", err)
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
		headers := make([]string, 0, len(server.Headers)+1)
		for _, header := range server.Headers {
			headers = append(headers, fmt.Sprintf("%s = %s", header.TOMLKey, header.TOMLValue))
		}
		if server.Authorization != "" {
			headers = append(headers, fmt.Sprintf("Authorization = %q", server.Authorization))
		}
		if len(headers) > 0 {
			lines = append(lines, "http_headers = { "+strings.Join(headers, ", ")+" }")
		}
	} else {
		lines = append(lines,
			fmt.Sprintf("command = %q", server.Command),
			fmt.Sprintf("args = %s", renderTOMLStringArray(server.Args)),
		)
	}

	lines = append(lines, codexManagedBlockEnd)
	return strings.Join(lines, "\n") + "\n"
}

func preservedCodexMCPHeaders(content, desiredURL string) ([]codexMCPHeader, error) {
	if strings.TrimSpace(content) == "" {
		return nil, nil
	}

	lines := strings.Split(content, "\n")
	codeLines, err := codexTOMLCodeLines(lines)
	if err != nil {
		return nil, err
	}

	const (
		codexSectionOther = iota
		codexSectionObstudio
		codexSectionObstudioHeaders
	)
	section := codexSectionOther
	rootSections := 0
	headerTables := 0
	inlineHeaderTables := 0
	urlAssignments := 0
	existingURL := ""
	headers := make([]codexMCPHeader, 0)
	headerNames := make(map[string]struct{})

	for index, codeLine := range codeLines {
		structural := tomlStructuralLine(codeLine)
		if structural == "" {
			continue
		}
		if tablePath, ok := parseCodexTOMLTablePath(structural); ok {
			switch {
			case slices.Equal(tablePath, []string{"mcp_servers", "obstudio"}):
				rootSections++
				if rootSections > 1 {
					return nil, errors.New("mcp_servers.obstudio is defined more than once")
				}
				section = codexSectionObstudio
			case slices.Equal(tablePath, []string{"mcp_servers", "obstudio", "http_headers"}):
				headerTables++
				if headerTables > 1 {
					return nil, errors.New("mcp_servers.obstudio.http_headers is defined more than once")
				}
				section = codexSectionObstudioHeaders
			default:
				section = codexSectionOther
			}
			continue
		}
		if isTOMLTableHeader(structural) {
			section = codexSectionOther
			continue
		}

		switch section {
		case codexSectionObstudio:
			line := tomlStructuralLine(lines[index])
			keyText, valueText, ok := splitCodexTOMLAssignment(line)
			if !ok {
				if codexManagedMCPKeyPrefix(line) {
					return nil, fmt.Errorf("invalid assignment in mcp_servers.obstudio: %q", line)
				}
				continue
			}
			key, err := parseCodexTOMLKey(keyText)
			if err != nil {
				if codexManagedMCPKeyPrefix(keyText) {
					return nil, fmt.Errorf("invalid key in mcp_servers.obstudio: %w", err)
				}
				continue
			}
			switch key {
			case "url":
				urlAssignments++
				if urlAssignments > 1 {
					return nil, errors.New("mcp_servers.obstudio.url is defined more than once")
				}
				existingURL, err = parseCodexTOMLString(valueText)
				if err != nil {
					return nil, fmt.Errorf("invalid mcp_servers.obstudio.url: %w", err)
				}
			case "http_headers":
				inlineHeaderTables++
				if inlineHeaderTables > 1 {
					return nil, errors.New("mcp_servers.obstudio.http_headers is defined more than once")
				}
				entries, err := splitCodexInlineTable(valueText)
				if err != nil {
					return nil, fmt.Errorf("invalid mcp_servers.obstudio.http_headers: %w", err)
				}
				for _, entry := range entries {
					header, err := parseCodexMCPHeader(entry)
					if err != nil {
						return nil, fmt.Errorf("invalid mcp_servers.obstudio.http_headers entry: %w", err)
					}
					if err := appendCodexMCPHeader(&headers, headerNames, header); err != nil {
						return nil, err
					}
				}
			}
		case codexSectionObstudioHeaders:
			line := tomlStructuralLine(lines[index])
			header, err := parseCodexMCPHeader(line)
			if err != nil {
				return nil, fmt.Errorf("invalid mcp_servers.obstudio.http_headers entry: %w", err)
			}
			if err := appendCodexMCPHeader(&headers, headerNames, header); err != nil {
				return nil, err
			}
		}
	}

	if rootSections == 0 {
		return nil, nil
	}
	if headerTables > 0 && inlineHeaderTables > 0 {
		return nil, errors.New("mcp_servers.obstudio.http_headers uses both inline and table forms")
	}
	if urlAssignments == 0 || existingURL != desiredURL {
		return nil, nil
	}

	preserved := make([]codexMCPHeader, 0, len(headers))
	for _, header := range headers {
		if !strings.EqualFold(header.Name, "Authorization") {
			preserved = append(preserved, header)
		}
	}
	return preserved, nil
}

func codexManagedMCPKeyPrefix(value string) bool {
	trimmed := strings.TrimSpace(value)
	for _, key := range []string{"url", "http_headers", `'url'`, `'http_headers'`, `"url"`, `"http_headers"`} {
		if !strings.HasPrefix(trimmed, key) {
			continue
		}
		if len(trimmed) == len(key) || trimmed[len(key)] == '=' || trimmed[len(key)] == ' ' || trimmed[len(key)] == '\t' {
			return true
		}
	}
	return false
}

func appendCodexMCPHeader(headers *[]codexMCPHeader, names map[string]struct{}, header codexMCPHeader) error {
	normalized := strings.ToLower(header.Name)
	if _, exists := names[normalized]; exists {
		return fmt.Errorf("mcp_servers.obstudio.http_headers contains duplicate header %q", header.Name)
	}
	names[normalized] = struct{}{}
	*headers = append(*headers, header)
	return nil
}

func parseCodexMCPHeader(entry string) (codexMCPHeader, error) {
	keyText, valueText, ok := splitCodexTOMLAssignment(entry)
	if !ok {
		return codexMCPHeader{}, fmt.Errorf("expected a header assignment, got %q", entry)
	}
	name, err := parseCodexTOMLKey(keyText)
	if err != nil {
		return codexMCPHeader{}, err
	}
	if !validHTTPHeaderName(name) {
		return codexMCPHeader{}, fmt.Errorf("%q is not a valid HTTP header name", name)
	}
	if _, err := parseCodexTOMLString(valueText); err != nil {
		return codexMCPHeader{}, fmt.Errorf("header %q must have a single-line string value: %w", name, err)
	}
	return codexMCPHeader{
		Name:      name,
		TOMLKey:   strings.TrimSpace(keyText),
		TOMLValue: strings.TrimSpace(valueText),
	}, nil
}

func splitCodexTOMLAssignment(line string) (string, string, bool) {
	quote := byte(0)
	escaped := false
	for index := 0; index < len(line); index++ {
		char := line[index]
		if quote == '"' && escaped {
			escaped = false
			continue
		}
		if quote == '"' && char == '\\' {
			escaped = true
			continue
		}
		if char == '\'' || char == '"' {
			if quote == 0 {
				quote = char
			} else if quote == char {
				quote = 0
			}
			continue
		}
		if char == '=' && quote == 0 {
			key := strings.TrimSpace(line[:index])
			value := strings.TrimSpace(line[index+1:])
			return key, value, key != "" && value != ""
		}
	}
	return "", "", false
}

func splitCodexInlineTable(value string) ([]string, error) {
	trimmed := strings.TrimSpace(value)
	if len(trimmed) < 2 || trimmed[0] != '{' || trimmed[len(trimmed)-1] != '}' {
		return nil, errors.New("expected an inline table")
	}
	inner := strings.TrimSpace(trimmed[1 : len(trimmed)-1])
	if inner == "" {
		return nil, nil
	}

	entries := make([]string, 0)
	start := 0
	quote := byte(0)
	escaped := false
	for index := 0; index < len(inner); index++ {
		char := inner[index]
		if quote == '"' && escaped {
			escaped = false
			continue
		}
		if quote == '"' && char == '\\' {
			escaped = true
			continue
		}
		if char == '\'' || char == '"' {
			if quote == 0 {
				quote = char
			} else if quote == char {
				quote = 0
			}
			continue
		}
		if quote != 0 {
			continue
		}
		switch char {
		case '{', '}':
			return nil, errors.New("nested inline tables are not supported for HTTP headers")
		case ',':
			entry := strings.TrimSpace(inner[start:index])
			if entry == "" {
				return nil, errors.New("empty inline-table entry")
			}
			entries = append(entries, entry)
			start = index + 1
		}
	}
	if quote != 0 || escaped {
		return nil, errors.New("unterminated quoted string")
	}
	entry := strings.TrimSpace(inner[start:])
	if entry == "" {
		return nil, errors.New("trailing comma in inline table")
	}
	return append(entries, entry), nil
}

func parseCodexTOMLKey(value string) (string, error) {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return "", errors.New("empty key")
	}
	if trimmed[0] == '\'' || trimmed[0] == '"' {
		return parseCodexTOMLString(trimmed)
	}
	for _, char := range trimmed {
		if (char < 'a' || char > 'z') && (char < 'A' || char > 'Z') &&
			(char < '0' || char > '9') && char != '_' && char != '-' {
			return "", fmt.Errorf("invalid bare TOML key %q", trimmed)
		}
	}
	return trimmed, nil
}

func parseCodexTOMLTablePath(line string) ([]string, bool) {
	trimmed := strings.TrimSpace(line)
	if len(trimmed) < 3 || trimmed[0] != '[' || trimmed[len(trimmed)-1] != ']' ||
		strings.HasPrefix(trimmed, "[[") || strings.HasSuffix(trimmed, "]]") {
		return nil, false
	}
	path, err := parseCodexTOMLDottedKey(trimmed[1 : len(trimmed)-1])
	return path, err == nil
}

func parseCodexTOMLDottedKey(value string) ([]string, error) {
	path := make([]string, 0, 3)
	for index := 0; ; {
		for index < len(value) && (value[index] == ' ' || value[index] == '\t') {
			index++
		}
		if index == len(value) {
			return nil, errors.New("empty dotted key segment")
		}

		start := index
		if value[index] == '\'' || value[index] == '"' {
			quote := value[index]
			index++
			closed := false
			for index < len(value) {
				char := value[index]
				if quote == '"' && char == '\\' {
					if index+1 >= len(value) {
						return nil, errors.New("unterminated quoted key escape")
					}
					index += 2
					continue
				}
				index++
				if char == quote {
					closed = true
					break
				}
			}
			if !closed {
				return nil, errors.New("unterminated quoted key")
			}
		} else {
			for index < len(value) && value[index] != '.' && value[index] != ' ' && value[index] != '\t' {
				index++
			}
		}

		key, err := parseCodexTOMLKey(value[start:index])
		if err != nil {
			return nil, err
		}
		path = append(path, key)
		for index < len(value) && (value[index] == ' ' || value[index] == '\t') {
			index++
		}
		if index == len(value) {
			return path, nil
		}
		if value[index] != '.' {
			return nil, fmt.Errorf("expected dot after key %q", key)
		}
		index++
	}
}

func parseCodexTOMLString(value string) (string, error) {
	trimmed := strings.TrimSpace(value)
	if len(trimmed) < 2 {
		return "", errors.New("expected a quoted string")
	}
	quote := trimmed[0]
	if (quote != '\'' && quote != '"') || trimmed[len(trimmed)-1] != quote {
		return "", errors.New("expected a single-line quoted string")
	}
	if quote == '\'' {
		inner := trimmed[1 : len(trimmed)-1]
		if strings.ContainsRune(inner, '\'') || containsInvalidTOMLControl(inner) {
			return "", errors.New("invalid single-line literal string")
		}
		return inner, nil
	}
	for index := 1; index < len(trimmed)-1; index++ {
		char := trimmed[index]
		if char < 0x20 && char != '\t' {
			return "", errors.New("invalid control character in basic string")
		}
		if char != '\\' {
			continue
		}
		index++
		if index >= len(trimmed)-1 {
			return "", errors.New("unterminated escape sequence")
		}
		switch trimmed[index] {
		case 'b', 't', 'n', 'f', 'r', '"', '\\':
		case 'u':
			if !validHexEscape(trimmed, index+1, 4) {
				return "", errors.New("invalid \\u escape")
			}
			index += 4
		case 'U':
			if !validHexEscape(trimmed, index+1, 8) {
				return "", errors.New("invalid \\U escape")
			}
			index += 8
		default:
			return "", fmt.Errorf("unsupported TOML escape \\%c", trimmed[index])
		}
	}
	decoded, err := strconv.Unquote(trimmed)
	if err != nil {
		return "", err
	}
	return decoded, nil
}

func containsInvalidTOMLControl(value string) bool {
	for _, char := range value {
		if (char >= 0 && char <= 0x08) || (char >= 0x0a && char <= 0x1f) || char == 0x7f {
			return true
		}
	}
	return false
}

func validHexEscape(value string, start, length int) bool {
	if start+length > len(value)-1 {
		return false
	}
	for _, char := range value[start : start+length] {
		if (char < '0' || char > '9') && (char < 'a' || char > 'f') && (char < 'A' || char > 'F') {
			return false
		}
	}
	return true
}

func validHTTPHeaderName(value string) bool {
	if value == "" {
		return false
	}
	for _, char := range value {
		if (char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') || (char >= '0' && char <= '9') {
			continue
		}
		if !strings.ContainsRune("!#$%&'*+-.^_`|~", char) {
			return false
		}
	}
	return true
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
		structural := tomlStructuralLine(line)
		if isTOMLTableHeader(structural) {
			if isCodexObstudioHeader(structural) {
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
	path, ok := parseCodexTOMLTablePath(line)
	return ok && len(path) >= 2 && path[0] == "mcp_servers" && path[1] == "obstudio"
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
		return fmt.Errorf("invalid %s: URL must use http or https", source)
	}
	if parsed.Host == "" || parsed.Hostname() == "" {
		return fmt.Errorf("invalid %s: URL is missing a host", source)
	}
	if parsed.User != nil {
		return fmt.Errorf("invalid %s: URL must not include user information", source)
	}
	if parsed.Fragment != "" || strings.Contains(raw, "#") {
		return fmt.Errorf("invalid %s: URL must not include a fragment", source)
	}
	if parsed.Scheme == "http" && !isLoopbackSharedObserverHost(parsed.Hostname()) {
		return fmt.Errorf("invalid %s: URL must use HTTPS unless the host is loopback", source)
	}
	return nil
}

func isLoopbackSharedObserverHost(hostname string) bool {
	normalized := strings.ToLower(strings.TrimSpace(hostname))
	if strings.HasSuffix(normalized, ".") && !strings.HasSuffix(normalized, "..") {
		normalized = strings.TrimSuffix(normalized, ".")
	}
	if normalized == "localhost" {
		return true
	}
	ip := net.ParseIP(normalized)
	return ip != nil && ip.IsLoopback()
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

func sameSharedObserverControlEndpoint(left, right string) bool {
	leftNormalized, err := normalizeSharedURL(left, "shared Observer endpoint")
	if err != nil {
		return false
	}
	rightNormalized, err := normalizeSharedURL(right, "advertised shared Observer endpoint")
	if err != nil {
		return false
	}
	if leftNormalized == rightNormalized {
		return true
	}
	leftURL, _ := url.Parse(leftNormalized)
	rightURL, _ := url.Parse(rightNormalized)
	return sameSharedObserverHostname(leftURL.Hostname(), rightURL.Hostname()) &&
		leftURL.Scheme == rightURL.Scheme &&
		effectiveURLPort(leftURL) == effectiveURLPort(rightURL) &&
		leftURL.EscapedPath() == rightURL.EscapedPath() &&
		leftURL.RawQuery == rightURL.RawQuery
}

func sameSharedObserverHostname(left, right string) bool {
	if isLocalhostIPv4Alias(left) && isLocalhostIPv4Alias(right) {
		return true
	}
	canonicalize := func(hostname string) string {
		hostname = strings.ToLower(hostname)
		if address := net.ParseIP(hostname); address != nil {
			return address.String()
		}
		return hostname
	}
	return canonicalize(left) == canonicalize(right)
}

func isLocalhostIPv4Alias(hostname string) bool {
	normalized := strings.TrimSuffix(strings.ToLower(hostname), ".")
	return normalized == "localhost" || normalized == "127.0.0.1"
}

func effectiveURLPort(parsed *url.URL) string {
	if parsed.Port() != "" {
		return parsed.Port()
	}
	if parsed.Scheme == "https" {
		return "443"
	}
	return "80"
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
				fmt.Printf(
					"  Existing skill %s and backup %s preserved; managed discovery link skipped.\n",
					link,
					plan.backup,
				)
				continue
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

func userConfigDir() string {
	dir, err := os.UserConfigDir()
	if err != nil {
		log.Fatalf("Failed to find config directory: %v", err)
	}

	return dir
}
