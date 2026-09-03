package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
	"github.com/spf13/cobra"
)

const (
	codexTokenTelemetryBlockStart = "# BEGIN OBSTUDIO TOKEN TELEMETRY"
	codexTokenTelemetryBlockEnd   = "# END OBSTUDIO TOKEN TELEMETRY"
	codexTokenTelemetryLineMarker = "# OBSTUDIO TOKEN TELEMETRY"
	defaultRepositoryCorrelation  = "path"
	defaultTokenTelemetryEndpoint = "http://127.0.0.1:4318/v1/logs"
	tokenTelemetryStateFileName   = "token-telemetry.json"
	tokenTelemetryStateVersion    = 1
)

var tokenTelemetryTargets = []string{"codex", "claude-code"}

type claudeTelemetrySetting struct {
	key   string
	value string
}

type codexTelemetryExporter struct {
	key      string
	label    string
	endpoint string
}

type codexTelemetryTableExporter struct {
	found              bool
	otlpHTTPFound      bool
	otlpHTTPSectionEnd int
	endpoint           string
	endpointIndex      int
	endpointSet        bool
	protocol           string
	protocolIndex      int
	protocolSet        bool
}

type tokenTelemetryResult struct {
	ConfigPath string
	Detail     string
	State      string
	Target     string
}

type tokenTelemetryOwnership struct {
	RepositoryCorrelation map[string]tokenTelemetryRepositoryCorrelation `json:"repositoryCorrelation,omitempty"`
	Targets               map[string]tokenTelemetryTargetOwnership       `json:"targets,omitempty"`
	Version               int                                            `json:"version"`
}

type tokenTelemetryRepositoryCorrelation struct {
	Endpoint  string    `json:"endpoint"`
	Mode      string    `json:"mode"`
	UpdatedAt time.Time `json:"updatedAt"`
}

type tokenTelemetryTargetOwnership struct {
	ConfigPath    string            `json:"configPath"`
	Endpoint      string            `json:"endpoint"`
	Env           map[string]string `json:"env,omitempty"`
	Settings      map[string]string `json:"settings,omitempty"`
	TableSettings map[string]string `json:"tableSettings,omitempty"`
	SectionLine   string            `json:"sectionLine,omitempty"`
	UpdatedAt     time.Time         `json:"updatedAt"`
}

type codexTelemetryTableAddition struct {
	index   int
	key     string
	line    string
	replace bool
}

type tokenTelemetryOwnershipMutation func(*tokenTelemetryOwnership)
type tokenTelemetryOwnershipWriter func(string, tokenTelemetryOwnership) error

type codexManagedTelemetryBlock struct {
	settings    map[string]string
	sectionLine string
	otherLines  []string
}

func newTokenTelemetryCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "token-telemetry",
		Short: "Manage opt-in Codex and Claude token telemetry routed through Observer",
	}
	cmd.AddCommand(newTokenTelemetryEnableCommand())
	cmd.AddCommand(newTokenTelemetryDisableCommand())
	cmd.AddCommand(newTokenTelemetryStatusCommand())
	return cmd
}

func newTokenTelemetryEnableCommand() *cobra.Command {
	var requestedTargets []string
	var endpoint string
	var repositoryCorrelation string
	cmd := &cobra.Command{
		Use:   "enable",
		Short: "Opt in and route provider token telemetry through Observer",
		RunE: func(cmd *cobra.Command, _ []string) error {
			targets, err := normalizeTokenTelemetryTargets(requestedTargets)
			if err != nil {
				return err
			}
			endpoint, err = normalizeTokenTelemetryEndpoint(endpoint)
			if err != nil {
				return err
			}
			statePath := tokenTelemetryStatePath()
			correlationModeExplicit := cmd.Flags().Changed("repository-correlation")
			explicitCorrelationMode := ""
			if correlationModeExplicit {
				explicitCorrelationMode, err = normalizeRepositoryCorrelationMode(repositoryCorrelation)
				if err != nil {
					return err
				}
			}
			return runTokenTelemetryTargets(cmd, targets, "enable", func(target string) (tokenTelemetryResult, error) {
				return withTokenTelemetryStateTransaction(statePath, target, func() (tokenTelemetryResult, error) {
					correlationMode := explicitCorrelationMode
					if !correlationModeExplicit {
						resolvedMode, resolveErr := repositoryCorrelationModeForEnable(statePath, target)
						if resolveErr != nil {
							return tokenTelemetryResult{}, resolveErr
						}
						correlationMode = resolvedMode
					}
					if correlationMode != "off" && !isLoopbackRepositoryCorrelationEndpoint(endpoint) {
						return tokenTelemetryResult{}, errors.New("repository correlation requires a loopback Observer --endpoint")
					}
					result, enableErr := enableAgentTokenTelemetryWithOwnershipMutation(
						target,
						userHome(),
						statePath,
						endpoint,
						os.LookupEnv,
						setRepositoryCorrelationMutation(target, endpoint, correlationMode),
						writeTokenTelemetryOwnership,
					)
					if enableErr != nil {
						return tokenTelemetryResult{}, enableErr
					}
					result.Detail = appendTokenTelemetryDetail(result.Detail, repositoryCorrelationDetail(correlationMode))
					return result, nil
				})
			})
		},
	}
	cmd.Flags().StringSliceVar(&requestedTargets, "target", nil, "Provider target or comma-separated targets (codex, claude-code)")
	cmd.Flags().StringVar(&endpoint, "endpoint", defaultTokenTelemetryEndpoint, "Observer OTLP/HTTP logs endpoint ending in /v1/logs")
	cmd.Flags().StringVar(&repositoryCorrelation, "repository-correlation", "", "Repository attribution mode (off, name, path); new targets default to path, while name omits repository and workspace paths")
	cmd.MarkFlagRequired("target")
	return cmd
}

func newTokenTelemetryDisableCommand() *cobra.Command {
	var requestedTargets []string
	cmd := &cobra.Command{
		Use:   "disable",
		Short: "Remove unchanged OTLP routing managed by Obstudio",
		RunE: func(cmd *cobra.Command, _ []string) error {
			targets, err := normalizeTokenTelemetryTargets(requestedTargets)
			if err != nil {
				return err
			}
			statePath := tokenTelemetryStatePath()
			return runTokenTelemetryTargets(cmd, targets, "disable", func(target string) (tokenTelemetryResult, error) {
				return withTokenTelemetryStateTransaction(statePath, target, func() (tokenTelemetryResult, error) {
					result, disableErr := disableAgentTokenTelemetryWithOwnershipMutation(
						target,
						userHome(),
						statePath,
						os.LookupEnv,
						removeRepositoryCorrelationMutation(target),
						writeTokenTelemetryOwnership,
					)
					if disableErr != nil {
						return tokenTelemetryResult{}, disableErr
					}
					result.Detail = appendTokenTelemetryDetail(result.Detail, repositoryCorrelationDetail("off"))
					return result, nil
				})
			})
		},
	}
	cmd.Flags().StringSliceVar(&requestedTargets, "target", nil, "Provider target or comma-separated targets (codex, claude-code)")
	cmd.MarkFlagRequired("target")
	return cmd
}

func newTokenTelemetryStatusCommand() *cobra.Command {
	var requestedTargets []string
	var endpoint string
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Inspect provider token telemetry configuration and ownership",
		RunE: func(cmd *cobra.Command, _ []string) error {
			targets, err := normalizeTokenTelemetryTargets(requestedTargets)
			if err != nil {
				return err
			}
			if cmd.Flags().Changed("endpoint") {
				endpoint, err = normalizeTokenTelemetryEndpoint(endpoint)
				if err != nil {
					return err
				}
			} else {
				endpoint = ""
			}
			statePath := tokenTelemetryStatePath()
			return runTokenTelemetryTargets(cmd, targets, "inspect", func(target string) (tokenTelemetryResult, error) {
				return withTokenTelemetryStateTransaction(statePath, target, func() (tokenTelemetryResult, error) {
					result, inspectErr := inspectAgentTokenTelemetry(target, userHome(), statePath, endpoint, os.LookupEnv)
					if inspectErr != nil {
						return tokenTelemetryResult{}, inspectErr
					}
					mode, correlationErr := tokenTelemetryRepositoryCorrelationMode(statePath, target)
					if correlationErr != nil {
						return tokenTelemetryResult{}, correlationErr
					}
					result.Detail = appendTokenTelemetryDetail(result.Detail, repositoryCorrelationDetail(mode))
					return result, nil
				})
			})
		},
	}
	cmd.Flags().StringSliceVar(&requestedTargets, "target", nil, "Provider target or comma-separated targets (codex, claude-code)")
	cmd.Flags().StringVar(&endpoint, "endpoint", defaultTokenTelemetryEndpoint, "Expected Observer OTLP/HTTP logs endpoint ending in /v1/logs")
	cmd.MarkFlagRequired("target")
	return cmd
}

func normalizeTokenTelemetryTargets(requested []string) ([]string, error) {
	allowed := map[string]struct{}{"codex": {}, "claude-code": {}}
	seen := make(map[string]struct{})
	result := make([]string, 0, len(requested))
	for _, raw := range requested {
		for _, value := range strings.Split(raw, ",") {
			target := strings.TrimSpace(value)
			if _, ok := allowed[target]; !ok {
				return nil, fmt.Errorf("unsupported token telemetry target %q (supported: %s)", target, strings.Join(tokenTelemetryTargets, ", "))
			}
			if _, duplicate := seen[target]; duplicate {
				continue
			}
			seen[target] = struct{}{}
			result = append(result, target)
		}
	}
	if len(result) == 0 {
		return nil, fmt.Errorf("at least one token telemetry target is required (supported: %s)", strings.Join(tokenTelemetryTargets, ", "))
	}
	return result, nil
}

func normalizeRepositoryCorrelationMode(raw string) (string, error) {
	mode := strings.ToLower(strings.TrimSpace(raw))
	switch mode {
	case "off", "name", "path":
		return mode, nil
	default:
		return "", fmt.Errorf("unsupported --repository-correlation value %q (supported: off, name, path)", raw)
	}
}

func repositoryCorrelationModeForEnable(statePath, target string) (string, error) {
	state, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return "", err
	}
	if correlation, ok := state.RepositoryCorrelation[target]; ok {
		mode, normalizeErr := normalizeRepositoryCorrelationMode(correlation.Mode)
		if normalizeErr != nil {
			return "", fmt.Errorf("invalid stored repository correlation for %s: %w", target, normalizeErr)
		}
		return mode, nil
	}
	return defaultRepositoryCorrelation, nil
}

func isLoopbackRepositoryCorrelationEndpoint(endpoint string) bool {
	parsed, err := url.Parse(endpoint)
	if err != nil {
		return false
	}
	switch strings.ToLower(parsed.Hostname()) {
	case "127.0.0.1", "localhost", "::1":
		return true
	default:
		return false
	}
}

func repositoryCorrelationDetail(mode string) string {
	if mode == "" {
		mode = "off"
	}
	return "repository correlation: " + mode
}

func appendTokenTelemetryDetail(detail, addition string) string {
	if detail == "" {
		return addition
	}
	return detail + "; " + addition
}

func setTokenTelemetryRepositoryCorrelation(statePath, target, endpoint, mode string) error {
	state, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return err
	}
	setRepositoryCorrelationMutation(target, endpoint, mode)(&state)
	return writeTokenTelemetryOwnership(statePath, state)
}

func removeTokenTelemetryRepositoryCorrelation(statePath, target string) error {
	state, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return err
	}
	removeRepositoryCorrelationMutation(target)(&state)
	return writeTokenTelemetryOwnership(statePath, state)
}

func setRepositoryCorrelationMutation(target, endpoint, mode string) tokenTelemetryOwnershipMutation {
	return func(state *tokenTelemetryOwnership) {
		state.RepositoryCorrelation[target] = tokenTelemetryRepositoryCorrelation{
			Endpoint:  endpoint,
			Mode:      mode,
			UpdatedAt: time.Now().UTC(),
		}
	}
}

func removeRepositoryCorrelationMutation(target string) tokenTelemetryOwnershipMutation {
	return func(state *tokenTelemetryOwnership) {
		delete(state.RepositoryCorrelation, target)
	}
}

func commitTokenTelemetryOwnershipMutation(
	statePath string,
	state tokenTelemetryOwnership,
	mutation tokenTelemetryOwnershipMutation,
	writeOwnership tokenTelemetryOwnershipWriter,
) error {
	if mutation == nil {
		return nil
	}
	mutation(&state)
	return writeOwnership(statePath, state)
}

func tokenTelemetryRepositoryCorrelationMode(statePath, target string) (string, error) {
	state, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return "", err
	}
	correlation, ok := state.RepositoryCorrelation[target]
	if !ok {
		return "off", nil
	}
	return correlation.Mode, nil
}

func providerRepositoryCorrelationMode(statePath, provider string) string {
	target := strings.ToLower(strings.TrimSpace(provider))
	if target == "claude" {
		target = "claude-code"
	}
	if target != "codex" && target != "claude-code" {
		return ""
	}
	mode, err := tokenTelemetryRepositoryCorrelationMode(statePath, target)
	if err != nil {
		return "off"
	}
	mode, err = normalizeRepositoryCorrelationMode(mode)
	if err != nil {
		return "off"
	}
	return mode
}

func tokenTelemetryStatePath() string {
	if override := strings.TrimSpace(os.Getenv("OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH")); override != "" {
		return resolveTokenTelemetryStatePath(override, userHome())
	}
	return filepath.Join(userHome(), sharedObserverStateDirName, tokenTelemetryStateFileName)
}

func resolveTokenTelemetryStatePath(raw, home string) string {
	path := strings.TrimSpace(raw)
	if path == "~" {
		path = home
	} else if strings.HasPrefix(path, "~/") ||
		(filepath.Separator == '\\' && strings.HasPrefix(path, `~\`)) {
		path = filepath.Join(home, path[2:])
	} else if !filepath.IsAbs(path) {
		path = filepath.Join(home, path)
	}
	return filepath.Clean(path)
}

func sameTokenTelemetryConfigPath(left, right string) bool {
	leftInfo, leftErr := os.Stat(left)
	rightInfo, rightErr := os.Stat(right)
	if leftErr == nil && rightErr == nil && os.SameFile(leftInfo, rightInfo) {
		return true
	}
	return sameTokenTelemetryConfigPathForOS(left, right, runtime.GOOS)
}

func sameTokenTelemetryConfigPathForOS(left, right, goos string) bool {
	left = filepath.Clean(left)
	right = filepath.Clean(right)
	if goos == "windows" {
		return strings.EqualFold(left, right)
	}
	return left == right
}

func printTokenTelemetryResult(cmd *cobra.Command, result tokenTelemetryResult) {
	detail := ""
	if result.Detail != "" {
		detail = ": " + result.Detail
	}
	fmt.Fprintf(cmd.OutOrStdout(), "%s: %s (%s)%s\n", result.Target, result.State, result.ConfigPath, detail)
}

func runTokenTelemetryTargets(
	cmd *cobra.Command,
	targets []string,
	action string,
	operation func(string) (tokenTelemetryResult, error),
) error {
	var operationErrors []error
	for _, target := range targets {
		result, err := operation(target)
		if err != nil {
			operationErrors = append(operationErrors, fmt.Errorf("%s %s token telemetry: %w", action, target, err))
			continue
		}
		printTokenTelemetryResult(cmd, result)
	}
	return errors.Join(operationErrors...)
}

func normalizeTokenTelemetryEndpoint(raw string) (string, error) {
	trimmed := strings.TrimSpace(raw)
	parsed, err := url.Parse(trimmed)
	if err != nil {
		return "", fmt.Errorf("invalid --endpoint: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return "", fmt.Errorf("invalid --endpoint: %s must use http or https", trimmed)
	}
	if parsed.Host == "" {
		return "", fmt.Errorf("invalid --endpoint: %s is missing a host", trimmed)
	}
	if parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return "", errors.New("invalid --endpoint: credentials, query parameters, and fragments are not supported")
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/")
	if parsed.Path != "/v1/logs" {
		return "", fmt.Errorf("invalid --endpoint: %s must end with /v1/logs", trimmed)
	}
	return parsed.String(), nil
}

func tokenTelemetryTraceEndpoint(logsEndpoint string) (string, error) {
	return tokenTelemetryEndpointForSignal(logsEndpoint, "traces")
}

func tokenTelemetryMetricEndpoint(logsEndpoint string) (string, error) {
	return tokenTelemetryEndpointForSignal(logsEndpoint, "metrics")
}

func tokenTelemetryEndpointForSignal(logsEndpoint, signal string) (string, error) {
	parsed, err := url.Parse(logsEndpoint)
	if err != nil {
		return "", fmt.Errorf("derive token telemetry %s endpoint: %w", signal, err)
	}
	if parsed.Path != "/v1/logs" {
		return "", fmt.Errorf("derive token telemetry %s endpoint: %s must end with /v1/logs", signal, logsEndpoint)
	}
	parsed.Path = "/v1/" + signal
	return parsed.String(), nil
}

func enableAgentTokenTelemetry(
	target, home, statePath, endpoint string,
	lookupEnv func(string) (string, bool),
) (tokenTelemetryResult, error) {
	return enableAgentTokenTelemetryWithOwnershipMutation(
		target, home, statePath, endpoint, lookupEnv, nil, writeTokenTelemetryOwnership,
	)
}

func enableAgentTokenTelemetryWithOwnershipMutation(
	target, home, statePath, endpoint string,
	lookupEnv func(string) (string, bool),
	mutation tokenTelemetryOwnershipMutation,
	writeOwnership tokenTelemetryOwnershipWriter,
) (tokenTelemetryResult, error) {
	switch target {
	case "codex":
		path := codexTokenTelemetryConfigPath(home, lookupEnv)
		return enableCodexTokenTelemetryWithOwnershipMutation(path, statePath, endpoint, mutation, writeOwnership)
	case "claude-code":
		path := claudeTokenTelemetryConfigPath(home, lookupEnv)
		return enableClaudeTokenTelemetryWithOwnershipMutation(path, statePath, endpoint, lookupEnv, mutation, writeOwnership)
	default:
		return tokenTelemetryResult{}, fmt.Errorf("unsupported token telemetry target %q", target)
	}
}

func disableAgentTokenTelemetry(
	target, home, statePath string,
	lookupEnv func(string) (string, bool),
) (tokenTelemetryResult, error) {
	return disableAgentTokenTelemetryWithOwnershipMutation(
		target, home, statePath, lookupEnv, nil, writeTokenTelemetryOwnership,
	)
}

func disableAgentTokenTelemetryWithOwnershipMutation(
	target, home, statePath string,
	lookupEnv func(string) (string, bool),
	mutation tokenTelemetryOwnershipMutation,
	writeOwnership tokenTelemetryOwnershipWriter,
) (tokenTelemetryResult, error) {
	switch target {
	case "codex":
		path := codexTokenTelemetryConfigPath(home, lookupEnv)
		return disableOwnedCodexTokenTelemetryWithOwnershipMutation(path, statePath, mutation, writeOwnership)
	case "claude-code":
		path := claudeTokenTelemetryConfigPath(home, lookupEnv)
		return disableClaudeTokenTelemetryWithOwnershipMutation(path, statePath, lookupEnv, mutation, writeOwnership)
	default:
		return tokenTelemetryResult{}, fmt.Errorf("unsupported token telemetry target %q", target)
	}
}

func inspectAgentTokenTelemetry(
	target, home, statePath, endpoint string,
	lookupEnv func(string) (string, bool),
) (tokenTelemetryResult, error) {
	var path string
	switch target {
	case "codex":
		path = codexTokenTelemetryConfigPath(home, lookupEnv)
	case "claude-code":
		path = claudeTokenTelemetryConfigPath(home, lookupEnv)
	default:
		return tokenTelemetryResult{}, fmt.Errorf("unsupported token telemetry target %q", target)
	}
	resolvedEndpoint, err := tokenTelemetryStatusEndpoint(statePath, target, path, endpoint)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	if target == "codex" {
		return inspectOwnedCodexTokenTelemetry(path, statePath, resolvedEndpoint)
	}
	return inspectClaudeTokenTelemetry(path, statePath, resolvedEndpoint, lookupEnv)
}

func tokenTelemetryStatusEndpoint(statePath, target, configPath, explicitEndpoint string) (string, error) {
	if explicitEndpoint != "" {
		return explicitEndpoint, nil
	}
	ownership, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return "", err
	}
	if owned, ok := ownership.Targets[target]; ok &&
		sameTokenTelemetryConfigPath(owned.ConfigPath, configPath) && owned.Endpoint != "" {
		return owned.Endpoint, nil
	}
	if correlation, ok := ownership.RepositoryCorrelation[target]; ok && correlation.Endpoint != "" {
		return correlation.Endpoint, nil
	}
	return defaultTokenTelemetryEndpoint, nil
}

func codexTokenTelemetryConfigPath(home string, lookupEnv func(string) (string, bool)) string {
	return tokenTelemetryConfigPath(home, ".codex", "CODEX_HOME", lookupEnv, "config.toml")
}

func claudeTokenTelemetryConfigPath(home string, lookupEnv func(string) (string, bool)) string {
	return tokenTelemetryConfigPath(home, ".claude", "CLAUDE_CONFIG_DIR", lookupEnv, "settings.json")
}

func tokenTelemetryConfigPath(
	home, defaultDirectory, environmentKey string,
	lookupEnv func(string) (string, bool),
	fileName string,
) string {
	directory := filepath.Join(home, defaultDirectory)
	if configured, ok := lookupEnvironment(lookupEnv, environmentKey); ok && strings.TrimSpace(configured) != "" {
		directory = strings.TrimSpace(configured)
	}
	return filepath.Join(filepath.Clean(directory), fileName)
}

func enableCodexTokenTelemetry(path, statePath, endpoint string) (tokenTelemetryResult, error) {
	return enableCodexTokenTelemetryWithOwnershipMutation(
		path, statePath, endpoint, nil, writeTokenTelemetryOwnership,
	)
}

func enableCodexTokenTelemetryWithOwnershipMutation(
	path, statePath, endpoint string,
	mutation tokenTelemetryOwnershipMutation,
	writeOwnership tokenTelemetryOwnershipWriter,
) (tokenTelemetryResult, error) {
	ownership, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	prior, priorExists := ownership.Targets["codex"]
	if priorExists && !sameTokenTelemetryConfigPath(prior.ConfigPath, path) {
		return tokenTelemetryResult{}, fmt.Errorf(
			"ownership state %q belongs to Codex config %q; existing state and config were preserved",
			statePath,
			prior.ConfigPath,
		)
	}

	original, readErr := os.ReadFile(path)
	renderInput := original
	existed := readErr == nil
	if readErr != nil && !errors.Is(readErr, os.ErrNotExist) {
		return tokenTelemetryResult{}, fmt.Errorf("read Codex config %q: %w", path, readErr)
	}
	_, found, err := parseCodexManagedTelemetryBlock(string(original))
	if err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read managed token telemetry in %q: %w", path, err)
	}
	if found && !priorExists {
		unwrapped, unwrapErr := unwrapCodexTokenTelemetryBlock(string(original))
		if unwrapErr != nil {
			return tokenTelemetryResult{}, fmt.Errorf("unwrap unmanaged token telemetry in %q: %w", path, unwrapErr)
		}
		renderInput = []byte(unwrapped)
	}
	if priorExists {
		cleaned := string(original)
		if found {
			var removeErr error
			cleaned, _, _, _, removeErr = removeOwnedCodexTelemetry(cleaned, prior)
			if removeErr != nil {
				return tokenTelemetryResult{}, fmt.Errorf("read managed token telemetry in %q: %w", path, removeErr)
			}
		}
		renderInput = []byte(cleaned)
	}

	configured, _, tableSettings, err := renderCodexTokenTelemetry(path, renderInput, endpoint, true)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	configChanged := !bytes.Equal(original, configured)
	managed, managedFound, err := parseCodexManagedTelemetryBlock(string(configured))
	if err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read configured token telemetry in %q: %w", path, err)
	}
	beforeOwnership := cloneTokenTelemetryOwnership(ownership)
	if managedFound || len(tableSettings) > 0 {
		ownership.Targets["codex"] = tokenTelemetryTargetOwnership{
			ConfigPath:    path,
			Endpoint:      endpoint,
			Settings:      managed.settings,
			TableSettings: tableSettings,
			SectionLine:   managed.sectionLine,
			UpdatedAt:     time.Now().UTC(),
		}
	} else {
		delete(ownership.Targets, "codex")
	}
	if mutation != nil {
		mutation(&ownership)
	}
	beforeConfig := tokenTelemetryConfigSnapshot{Data: original, Exists: existed}
	afterConfig := tokenTelemetryConfigSnapshot{Data: configured, Exists: true}
	if !configChanged {
		afterConfig = beforeConfig
	}
	if err := publishTokenTelemetryConfigTransaction(
		statePath,
		"codex",
		path,
		beforeConfig,
		afterConfig,
		beforeOwnership,
		ownership,
		writeOwnership,
	); err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("write ownership state: %w", err)
	}
	return inspectOwnedCodexTokenTelemetry(path, statePath, endpoint)
}

func disableOwnedCodexTokenTelemetry(path, statePath string) (tokenTelemetryResult, error) {
	return disableOwnedCodexTokenTelemetryWithOwnershipMutation(
		path, statePath, nil, writeTokenTelemetryOwnership,
	)
}

func disableOwnedCodexTokenTelemetryWithOwnershipMutation(
	path, statePath string,
	mutation tokenTelemetryOwnershipMutation,
	writeOwnership tokenTelemetryOwnershipWriter,
) (tokenTelemetryResult, error) {
	result := tokenTelemetryResult{Target: "codex", ConfigPath: path, State: "disabled"}
	ownership, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	owned, ownedExists := ownership.Targets["codex"]
	if !ownedExists {
		data, readErr := os.ReadFile(path)
		if readErr != nil && !errors.Is(readErr, os.ErrNotExist) {
			return tokenTelemetryResult{}, fmt.Errorf("read Codex config %q: %w", path, readErr)
		}
		_, marked, markerErr := parseCodexManagedTelemetryBlock(string(data))
		if markerErr != nil {
			return tokenTelemetryResult{}, fmt.Errorf("read managed token telemetry in %q: %w", path, markerErr)
		}
		if marked {
			result.State = "unmanaged"
			result.Detail = "Obstudio markers have no ownership record; all marked content was retained"
			if err := commitTokenTelemetryOwnershipMutation(statePath, ownership, mutation, writeOwnership); err != nil {
				return tokenTelemetryResult{}, fmt.Errorf("write ownership state: %w", err)
			}
			return result, nil
		}
		configured, configuredErr := codexTokenTelemetryConfigured(path)
		if configuredErr != nil {
			return tokenTelemetryResult{}, configuredErr
		}
		if configured {
			result.State = "unmanaged"
			result.Detail = "no Obstudio ownership record exists; user-owned Codex OTel configuration was retained"
		} else {
			result.Detail = "no Obstudio ownership record exists"
		}
		if err := commitTokenTelemetryOwnershipMutation(statePath, ownership, mutation, writeOwnership); err != nil {
			return tokenTelemetryResult{}, fmt.Errorf("write ownership state: %w", err)
		}
		return result, nil
	}
	if !sameTokenTelemetryConfigPath(owned.ConfigPath, path) {
		return tokenTelemetryResult{}, fmt.Errorf(
			"ownership state %q belongs to Codex config %q; no files were changed",
			statePath,
			owned.ConfigPath,
		)
	}

	original, readErr := os.ReadFile(path)
	existed := readErr == nil
	if readErr != nil && !errors.Is(readErr, os.ErrNotExist) {
		return tokenTelemetryResult{}, fmt.Errorf("read Codex config %q: %w", path, readErr)
	}
	cleaned, tableFound, tableRemoved, tablePreserved, err := removeOwnedCodexTableSettings(string(original), owned)
	if err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read managed token telemetry in %q: %w", path, err)
	}
	cleaned, blockFound, blockRemoved, blockPreserved, err := removeOwnedCodexTelemetry(cleaned, owned)
	if err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read managed token telemetry in %q: %w", path, err)
	}
	found := tableFound || blockFound
	removed := tableRemoved + blockRemoved
	preserved := append(tablePreserved, blockPreserved...)
	sort.Strings(preserved)
	configChanged := found && cleaned != string(original)
	beforeOwnership := cloneTokenTelemetryOwnership(ownership)
	delete(ownership.Targets, "codex")
	if mutation != nil {
		mutation(&ownership)
	}
	beforeConfig := tokenTelemetryConfigSnapshot{Data: original, Exists: existed}
	afterConfig := beforeConfig
	if configChanged {
		afterConfig = tokenTelemetryConfigSnapshot{Data: []byte(cleaned), Exists: true}
	}
	if err := publishTokenTelemetryConfigTransaction(
		statePath,
		"codex",
		path,
		beforeConfig,
		afterConfig,
		beforeOwnership,
		ownership,
		writeOwnership,
	); err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("write ownership state: %w", err)
	}

	result.Detail = fmt.Sprintf("removed %d unchanged Obstudio-owned settings", removed)
	if len(preserved) > 0 {
		result.State = "disabled-with-user-changes"
		result.Detail += "; preserved modified settings: " + strings.Join(preserved, ", ")
	} else if configured, configuredErr := codexTokenTelemetryConfigured(path); configuredErr != nil {
		return tokenTelemetryResult{}, configuredErr
	} else if configured {
		result.State = "unmanaged"
		if found {
			result.Detail += "; user-owned Codex OTel configuration remains configured"
		} else {
			result.Detail += "; the managed block was absent and user-owned Codex OTel configuration was retained"
		}
	}
	return result, nil
}

func inspectOwnedCodexTokenTelemetry(path, statePath, endpoint string) (tokenTelemetryResult, error) {
	ownership, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	owned, ownedExists := ownership.Targets["codex"]
	ownedPathMatches := ownedExists && sameTokenTelemetryConfigPath(owned.ConfigPath, path)
	if endpoint == "" {
		endpoint = defaultTokenTelemetryEndpoint
		if ownedPathMatches && owned.Endpoint != "" {
			endpoint = owned.Endpoint
		}
	}
	result, err := inspectCodexTokenTelemetry(path, endpoint)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	data, readErr := os.ReadFile(path)
	if errors.Is(readErr, os.ErrNotExist) {
		return result, nil
	}
	if readErr != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read Codex config %q: %w", path, readErr)
	}
	block, found, err := parseCodexManagedTelemetryBlock(string(data))
	if err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read managed token telemetry in %q: %w", path, err)
	}
	if !ownedPathMatches {
		if found {
			return inspectUnownedMarkedCodexTokenTelemetry(path, endpoint)
		}
		return result, nil
	}
	if found {
		if mismatch := codexManagedBlockMismatch(block, owned); mismatch != "" {
			result.State = "modified"
			result.Detail = "owned configuration changed and will be preserved on disable: " + mismatch
			return result, nil
		}
	} else if len(owned.Settings) > 0 || owned.SectionLine != "" {
		result.State = "modified"
		result.Detail = "owned configuration changed and will be preserved on disable: the managed block is missing"
		return result, nil
	}
	tableMismatch, mismatchErr := codexOwnedTableSettingMismatch(string(data), owned)
	if mismatchErr != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read managed token telemetry in %q: %w", path, mismatchErr)
	}
	if tableMismatch != "" {
		result.State = "modified"
		result.Detail = "owned configuration changed and will be preserved on disable: " + tableMismatch
		return result, nil
	}
	if (result.State == "enabled-existing" || result.State == "enabled-managed") &&
		(len(owned.Settings) > 0 || len(owned.TableSettings) > 0) {
		suffix := ""
		if separator := strings.Index(result.Detail, "; "); separator >= 0 {
			suffix = result.Detail[separator:]
		}
		result.State = "enabled-managed"
		result.Detail = fmt.Sprintf(
			"Obstudio owns %d unchanged Codex exporter settings; Codex logs, traces, and metrics target Observer%s",
			len(owned.Settings)+len(owned.TableSettings),
			suffix,
		)
	}
	return result, nil
}

func inspectUnownedMarkedCodexTokenTelemetry(path, endpoint string) (tokenTelemetryResult, error) {
	result, err := inspectCodexTokenTelemetry(path, endpoint)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	if result.State == "enabled-managed" {
		result.State = "enabled-existing"
		result.Detail = strings.Replace(
			result.Detail,
			"Obstudio owns only the assignments inside its managed block",
			"matching exporters are active; marker content has no ownership record and remains user-owned",
			1,
		)
		return result, nil
	}
	if result.Detail == "" {
		result.Detail = "marker content has no ownership record and was preserved"
	} else {
		result.Detail += "; marker content has no ownership record and was preserved"
	}
	return result, nil
}

func configureCodexTokenTelemetry(path, endpoint string) error {
	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("read Codex config %q: %w", path, err)
	}
	configured, changed, _, err := renderCodexTokenTelemetry(path, data, endpoint, false)
	if err != nil || !changed {
		return err
	}
	return writeAgentConfig(path, configured)
}

func renderCodexTokenTelemetry(
	path string,
	data []byte,
	endpoint string,
	takeOverMatching bool,
) ([]byte, bool, map[string]string, error) {
	inputCodeLines, lexErr := codexTOMLCodeLines(strings.Split(string(data), "\n"))
	if lexErr != nil {
		return nil, false, nil, fmt.Errorf("parse Codex config %q: %w", path, lexErr)
	}
	if definition := unsupportedCodexOTelExporterDefinition(inputCodeLines); definition != "" {
		return nil, false, nil, fmt.Errorf("Codex OTel exporter in %q uses unsupported %s syntax; existing value was preserved", path, definition)
	}
	if err := validateCodexTOML(data); err != nil {
		return nil, false, nil, fmt.Errorf("parse Codex config %q: %w", path, err)
	}
	traceEndpoint, err := tokenTelemetryTraceEndpoint(endpoint)
	if err != nil {
		return nil, false, nil, err
	}
	metricEndpoint, err := tokenTelemetryMetricEndpoint(endpoint)
	if err != nil {
		return nil, false, nil, err
	}
	content, _, err := removeCodexTokenTelemetryBlock(string(data))
	if err != nil {
		return nil, false, nil, fmt.Errorf("read managed token telemetry in %q: %w", path, err)
	}
	lines := strings.Split(content, "\n")
	codeLines, lexErr := codexTOMLCodeLines(lines)
	if lexErr != nil {
		return nil, false, nil, fmt.Errorf("parse Codex config %q: %w", path, lexErr)
	}
	sectionStart, sectionEnd := findCodexOTelSection(codeLines)
	if definition := unsupportedCodexOTelExporterDefinition(codeLines); definition != "" {
		return nil, false, nil, fmt.Errorf("Codex OTel exporter in %q uses unsupported %s syntax; existing value was preserved", path, definition)
	}
	exporters := []codexTelemetryExporter{
		{key: "exporter", label: "log", endpoint: endpoint},
		{key: "trace_exporter", label: "trace", endpoint: traceEndpoint},
		{key: "metrics_exporter", label: "metrics", endpoint: metricEndpoint},
	}
	managedAssignments := make([]string, 0, len(exporters))
	tableAdditions := make([]codexTelemetryTableAddition, 0)
	tableSettings := make(map[string]string)
	for _, exporter := range exporters {
		state, stateErr := codexExporterConfigurationState(codeLines, sectionStart, sectionEnd, exporter)
		if stateErr != nil {
			return nil, false, nil, fmt.Errorf("inspect Codex OTel %s exporter in %q: %w", exporter.label, path, stateErr)
		}
		switch state {
		case "matching":
			if !takeOverMatching {
				continue
			}
		case "incomplete":
		case "conflict":
		default:
			managedAssignments = append(managedAssignments,
				fmt.Sprintf("%s = { otlp-http = { endpoint = %q, protocol = \"binary\" } }", exporter.key, exporter.endpoint))
			continue
		}
		additions, additionErr := codexExporterOverrideChanges(
			lines,
			codeLines,
			sectionStart,
			sectionEnd,
			exporter,
			takeOverMatching,
		)
		if additionErr != nil {
			return nil, false, nil, fmt.Errorf("override Codex OTel %s exporter in %q: %w", exporter.label, path, additionErr)
		}
		tableAdditions = append(tableAdditions, additions...)
		for _, addition := range additions {
			tableSettings[addition.key] = addition.line
		}
	}
	if len(managedAssignments) == 0 && len(tableAdditions) == 0 {
		return data, false, nil, nil
	}

	lines = insertCodexTelemetryTableAdditions(lines, tableAdditions)
	codeLines, lexErr = codexTOMLCodeLines(lines)
	if lexErr != nil {
		return nil, false, nil, fmt.Errorf("parse completed Codex config %q: %w", path, lexErr)
	}
	sectionStart, _ = findCodexOTelSection(codeLines)

	if len(managedAssignments) > 0 {
		managedLines := append([]string{codexTokenTelemetryBlockStart}, managedAssignments...)
		managedLines = append(managedLines, codexTokenTelemetryBlockEnd)
		if sectionStart >= 0 {
			insertAt := sectionStart + 1
			lines = insertStrings(lines, insertAt, managedLines)
		} else {
			insertAt := firstCodexOTelChildSection(codeLines)
			newSection := append([]string{codexTokenTelemetryBlockStart, "[otel]"}, managedAssignments...)
			newSection = append(newSection, codexTokenTelemetryBlockEnd)
			if insertAt >= 0 {
				lines = insertStrings(lines, insertAt, newSection)
			} else {
				content = strings.Join(lines, "\n")
				if content != "" && !strings.HasSuffix(content, "\n") {
					content += "\n"
				}
				content += strings.Join(newSection, "\n") + "\n"
				configured := []byte(content)
				if err := validateCodexTOML(configured); err != nil {
					return nil, false, nil, fmt.Errorf("validate completed Codex config %q: %w", path, err)
				}
				return configured, !bytes.Equal(data, configured), tableSettings, nil
			}
		}
	}

	content = strings.Join(lines, "\n")
	configured := []byte(content)
	if err := validateCodexTOML(configured); err != nil {
		return nil, false, nil, fmt.Errorf("validate completed Codex config %q: %w", path, err)
	}
	return configured, !bytes.Equal(data, configured), tableSettings, nil
}

func validateCodexTOML(data []byte) error {
	var config map[string]any
	_, err := toml.Decode(string(data), &config)
	return err
}

func codexExporterOverrideChanges(
	lines, codeLines []string,
	sectionStart, sectionEnd int,
	exporter codexTelemetryExporter,
	takeOverMatching bool,
) ([]codexTelemetryTableAddition, error) {
	assignmentIndexes := make([]int, 0, 1)
	if sectionStart >= 0 {
		for index := sectionStart + 1; index < sectionEnd; index++ {
			key, _, ok := tomlAssignment(codeLines[index])
			if ok && key == exporter.key {
				assignmentIndexes = append(assignmentIndexes, index)
			}
		}
	}
	table, err := codexExporterTable(codeLines, exporter.key)
	if err != nil {
		return nil, err
	}
	if len(assignmentIndexes) > 1 || (len(assignmentIndexes) == 1 && table.found) {
		return nil, errors.New("exporter is defined more than once")
	}
	if len(assignmentIndexes) == 1 {
		index := assignmentIndexes[0]
		line := ""
		_, value, _ := tomlAssignment(codeLines[index])
		if takeOverMatching && codexExporterTargetsEndpoint(value, exporter.endpoint) {
			line = markCodexTokenTelemetryLine(lines[index])
		} else {
			indent := lines[index][:len(lines[index])-len(strings.TrimLeft(lines[index], " \t"))]
			line = fmt.Sprintf("%s%s = { otlp-http = { endpoint = %q, protocol = \"binary\" } } %s", indent, exporter.key, exporter.endpoint, codexTokenTelemetryLineMarker)
		}
		return []codexTelemetryTableAddition{{
			index:   index,
			key:     exporter.key + ".assignment",
			line:    line,
			replace: true,
		}}, nil
	}
	if !table.found {
		return nil, errors.New("exporter definition is missing")
	}

	changes := make([]codexTelemetryTableAddition, 0, 2)
	if !table.endpointSet {
		changes = append(changes, codexTelemetryTableAddition{
			index: table.otlpHTTPSectionEnd,
			key:   exporter.key + ".endpoint",
			line:  fmt.Sprintf("endpoint = %q %s", exporter.endpoint, codexTokenTelemetryLineMarker),
		})
	} else if table.endpoint != exporter.endpoint || takeOverMatching {
		indent := lines[table.endpointIndex][:len(lines[table.endpointIndex])-len(strings.TrimLeft(lines[table.endpointIndex], " \t"))]
		line := fmt.Sprintf("%sendpoint = %q %s", indent, exporter.endpoint, codexTokenTelemetryLineMarker)
		if table.endpoint == exporter.endpoint {
			line = markCodexTokenTelemetryLine(lines[table.endpointIndex])
		}
		changes = append(changes, codexTelemetryTableAddition{
			index:   table.endpointIndex,
			key:     exporter.key + ".endpoint",
			line:    line,
			replace: true,
		})
	}
	if !table.protocolSet {
		changes = append(changes, codexTelemetryTableAddition{
			index: table.otlpHTTPSectionEnd,
			key:   exporter.key + ".protocol",
			line:  "protocol = \"binary\" " + codexTokenTelemetryLineMarker,
		})
	} else if !strings.EqualFold(table.protocol, "binary") || takeOverMatching {
		indent := lines[table.protocolIndex][:len(lines[table.protocolIndex])-len(strings.TrimLeft(lines[table.protocolIndex], " \t"))]
		line := indent + "protocol = \"binary\" " + codexTokenTelemetryLineMarker
		if strings.EqualFold(table.protocol, "binary") {
			line = markCodexTokenTelemetryLine(lines[table.protocolIndex])
		}
		changes = append(changes, codexTelemetryTableAddition{
			index:   table.protocolIndex,
			key:     exporter.key + ".protocol",
			line:    line,
			replace: true,
		})
	}
	if len(changes) == 0 {
		return nil, errors.New("exporter conflict could not be resolved")
	}
	return changes, nil
}

func markCodexTokenTelemetryLine(line string) string {
	line = strings.TrimSuffix(line, "\r")
	if strings.HasSuffix(strings.TrimSpace(line), codexTokenTelemetryLineMarker) {
		return line
	}
	return line + " " + codexTokenTelemetryLineMarker
}

func insertCodexTelemetryTableAdditions(
	lines []string,
	additions []codexTelemetryTableAddition,
) []string {
	insertions := make([]codexTelemetryTableAddition, 0, len(additions))
	for _, addition := range additions {
		if addition.replace {
			lineEnding := ""
			if strings.HasSuffix(lines[addition.index], "\r") {
				lineEnding = "\r"
			}
			lines[addition.index] = addition.line + lineEnding
			continue
		}
		insertions = append(insertions, addition)
	}
	sort.SliceStable(insertions, func(i, j int) bool {
		return insertions[i].index > insertions[j].index
	})
	for start := 0; start < len(insertions); {
		end := start + 1
		for end < len(insertions) && insertions[end].index == insertions[start].index {
			end++
		}
		inserted := make([]string, 0, end-start)
		for _, addition := range insertions[start:end] {
			inserted = append(inserted, addition.line)
		}
		lines = insertStrings(lines, insertions[start].index, inserted)
		start = end
	}
	return lines
}

func disableCodexTokenTelemetry(path string) (bool, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("read Codex config %q: %w", path, err)
	}
	content, found, err := removeCodexTokenTelemetryBlock(string(data))
	if err != nil {
		return false, fmt.Errorf("read managed token telemetry in %q: %w", path, err)
	}
	if !found {
		return false, nil
	}
	return true, writeAgentConfig(path, []byte(content))
}

func codexTokenTelemetryConfigured(path string) (bool, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("read Codex config %q: %w", path, err)
	}
	lines := strings.Split(string(data), "\n")
	codeLines, lexErr := codexTOMLCodeLines(lines)
	if lexErr != nil {
		return false, fmt.Errorf("parse Codex config %q: %w", path, lexErr)
	}
	sectionStart, sectionEnd := findCodexOTelSection(codeLines)
	if sectionStart >= 0 {
		for i := sectionStart + 1; i < sectionEnd; i++ {
			key, _, ok := codexTOMLSimpleAssignment(codeLines[i])
			if ok && (key == "exporter" || key == "trace_exporter" || key == "metrics_exporter") {
				return true, nil
			}
		}
	}
	for _, key := range []string{"exporter", "trace_exporter", "metrics_exporter"} {
		table, tableErr := codexExporterTable(codeLines, key)
		if tableErr != nil || table.endpointSet {
			return true, nil
		}
	}
	return false, nil
}

func inspectCodexTokenTelemetry(path, endpoint string) (tokenTelemetryResult, error) {
	result := tokenTelemetryResult{Target: "codex", ConfigPath: path, State: "disabled"}
	traceEndpoint, err := tokenTelemetryTraceEndpoint(endpoint)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	metricEndpoint, err := tokenTelemetryMetricEndpoint(endpoint)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		result.Detail = "Codex config does not exist"
		return result, nil
	}
	if err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read Codex config %q: %w", path, err)
	}
	_, managed, markerErr := removeCodexTokenTelemetryBlock(string(data))
	if markerErr != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read managed token telemetry in %q: %w", path, markerErr)
	}
	lines := strings.Split(string(data), "\n")
	codeLines, lexErr := codexTOMLCodeLines(lines)
	if lexErr != nil {
		return tokenTelemetryResult{}, fmt.Errorf("parse Codex config %q: %w", path, lexErr)
	}
	if definition := unsupportedCodexOTelExporterDefinition(codeLines); definition != "" {
		result.State = "conflict"
		result.Detail = "unsupported " + definition + " syntax was preserved"
		return result, nil
	}
	sectionStart, sectionEnd := findCodexOTelSection(codeLines)
	exporters := []codexTelemetryExporter{
		{key: "exporter", label: "log", endpoint: endpoint},
		{key: "trace_exporter", label: "trace", endpoint: traceEndpoint},
		{key: "metrics_exporter", label: "metrics", endpoint: metricEndpoint},
	}
	matching := 0
	missing := 0
	for _, exporter := range exporters {
		state, stateErr := codexExporterConfigurationState(codeLines, sectionStart, sectionEnd, exporter)
		if stateErr != nil {
			result.State = "conflict"
			result.Detail = stateErr.Error()
			return result, nil
		}
		switch state {
		case "matching":
			matching++
		case "missing", "incomplete":
			missing++
		default:
			result.State = "conflict"
			result.Detail = exporter.label + " exporter does not target Observer; enable replaces it and disable removes the managed route"
			return result, nil
		}
	}
	if matching == len(exporters) {
		result.State = "enabled-existing"
		if managed {
			result.State = "enabled-managed"
			result.Detail = "all Codex signal exporters target Observer; Obstudio owns only its managed assignments"
		} else {
			result.Detail = "all Codex signal exporters already targeted Observer and remain user-owned"
		}
		return result, nil
	}
	if missing == len(exporters) {
		result.Detail = "no Codex log, trace, or metrics exporter is configured for Observer"
		return result, nil
	}
	result.State = "partial"
	result.Detail = fmt.Sprintf("%d of %d required signal exporters target Observer", matching, len(exporters))
	return result, nil
}

func codexExporterConfigurationState(
	lines []string,
	sectionStart, sectionEnd int,
	exporter codexTelemetryExporter,
) (string, error) {
	indexes := make([]int, 0, 1)
	values := make([]string, 0, 1)
	if sectionStart >= 0 {
		for i := sectionStart + 1; i < sectionEnd; i++ {
			key, value, ok := tomlAssignment(lines[i])
			if ok && key == exporter.key {
				indexes = append(indexes, i)
				values = append(values, value)
			}
		}
	}
	tableExporter, err := codexExporterTable(lines, exporter.key)
	if err != nil {
		return "conflict", fmt.Errorf("%s exporter uses unsupported table syntax: %w", exporter.label, err)
	}
	if len(indexes) > 1 || (len(indexes) == 1 && tableExporter.found) {
		return "conflict", fmt.Errorf("%s exporter is defined more than once", exporter.label)
	}
	if len(indexes) == 1 {
		if codexExporterTargetsEndpoint(values[0], exporter.endpoint) {
			return "matching", nil
		}
		return "conflict", nil
	}
	if tableExporter.found {
		endpointMatches := !tableExporter.endpointSet || tableExporter.endpoint == exporter.endpoint
		protocolMatches := !tableExporter.protocolSet || strings.EqualFold(tableExporter.protocol, "binary")
		if tableExporter.endpointSet && tableExporter.protocolSet && endpointMatches && protocolMatches {
			return "matching", nil
		}
		if endpointMatches && protocolMatches {
			return "incomplete", nil
		}
		return "conflict", nil
	}
	return "missing", nil
}

func enableClaudeTokenTelemetry(
	path, statePath, endpoint string,
	lookupEnv func(string) (string, bool),
) (tokenTelemetryResult, error) {
	return enableClaudeTokenTelemetryWithOwnershipMutation(
		path, statePath, endpoint, lookupEnv, nil, writeTokenTelemetryOwnership,
	)
}

func enableClaudeTokenTelemetryWithOwnershipMutation(
	path, statePath, endpoint string,
	lookupEnv func(string) (string, bool),
	mutation tokenTelemetryOwnershipMutation,
	writeOwnership tokenTelemetryOwnershipWriter,
) (tokenTelemetryResult, error) {
	config, env, original, existed, err := readClaudeSettings(path)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	ownership, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	prior, priorExists := ownership.Targets["claude-code"]
	if priorExists && !sameTokenTelemetryConfigPath(prior.ConfigPath, path) {
		return tokenTelemetryResult{}, fmt.Errorf(
			"ownership state %q belongs to Claude settings %q; existing state and settings were preserved",
			statePath,
			prior.ConfigPath,
		)
	}

	required, defaults, err := claudeTokenTelemetrySettings(endpoint)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	required = append(required, claudeTokenTelemetryTakeoverSettings(env, endpoint, lookupEnv)...)

	managed := make(map[string]string)
	changed := false
	for _, setting := range required {
		if existing, exists := env[setting.key]; exists {
			existingString, ok := existing.(string)
			env[setting.key] = setting.value
			managed[setting.key] = setting.value
			if !ok || existingString != setting.value {
				changed = true
			}
			continue
		}
		env[setting.key] = setting.value
		managed[setting.key] = setting.value
		changed = true
	}
	for _, setting := range defaults {
		if existing, exists := env[setting.key]; exists {
			managedValue, owned := prior.Env[setting.key]
			existingString, stringValue := existing.(string)
			if priorExists && owned && stringValue && existingString == managedValue {
				if existingString != setting.value {
					env[setting.key] = setting.value
					changed = true
				}
				managed[setting.key] = setting.value
			}
			continue
		}
		if _, inherited := lookupEnvironment(lookupEnv, setting.key); inherited {
			continue
		}
		env[setting.key] = setting.value
		managed[setting.key] = setting.value
		changed = true
	}
	config["env"] = env

	beforeConfig := tokenTelemetryConfigSnapshot{Data: original, Exists: existed}
	afterConfig := beforeConfig
	if changed {
		out, marshalErr := json.MarshalIndent(config, "", "  ")
		if marshalErr != nil {
			return tokenTelemetryResult{}, fmt.Errorf("marshal Claude settings %q: %w", path, marshalErr)
		}
		afterConfig = tokenTelemetryConfigSnapshot{Data: append(out, '\n'), Exists: true}
	}

	beforeOwnership := cloneTokenTelemetryOwnership(ownership)
	if len(managed) > 0 {
		ownership.Targets["claude-code"] = tokenTelemetryTargetOwnership{
			ConfigPath: path,
			Endpoint:   endpoint,
			Env:        managed,
			UpdatedAt:  time.Now().UTC(),
		}
	} else {
		delete(ownership.Targets, "claude-code")
	}
	if mutation != nil {
		mutation(&ownership)
	}
	if err := publishTokenTelemetryConfigTransaction(
		statePath,
		"claude-code",
		path,
		beforeConfig,
		afterConfig,
		beforeOwnership,
		ownership,
		writeOwnership,
	); err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("write ownership state: %w", err)
	}
	return inspectClaudeTokenTelemetry(path, statePath, endpoint, lookupEnv)
}

func disableClaudeTokenTelemetry(
	path, statePath string,
	lookupEnv func(string) (string, bool),
) (tokenTelemetryResult, error) {
	return disableClaudeTokenTelemetryWithOwnershipMutation(
		path, statePath, lookupEnv, nil, writeTokenTelemetryOwnership,
	)
}

func disableClaudeTokenTelemetryWithOwnershipMutation(
	path, statePath string,
	lookupEnv func(string) (string, bool),
	mutation tokenTelemetryOwnershipMutation,
	writeOwnership tokenTelemetryOwnershipWriter,
) (tokenTelemetryResult, error) {
	result := tokenTelemetryResult{Target: "claude-code", ConfigPath: path, State: "disabled"}
	ownership, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	owned, ok := ownership.Targets["claude-code"]
	if !ok {
		_, env, _, _, readErr := readClaudeSettings(path)
		if readErr != nil {
			return tokenTelemetryResult{}, readErr
		}
		if claudeDetailedBetaTelemetryConfigured(env, lookupEnv) {
			result.State = "unmanaged"
			result.Detail = "no Obstudio ownership record exists; an active user-owned detailed-beta telemetry route was retained"
		} else if claudeTokenTelemetryConfigured(env, lookupEnv) {
			result.State = "unmanaged"
			result.Detail = "no Obstudio ownership record exists; user-owned Claude telemetry settings were retained"
		} else {
			result.Detail = "no Obstudio ownership record exists"
		}
		if err := commitTokenTelemetryOwnershipMutation(statePath, ownership, mutation, writeOwnership); err != nil {
			return tokenTelemetryResult{}, fmt.Errorf("write ownership state: %w", err)
		}
		return result, nil
	}
	if !sameTokenTelemetryConfigPath(owned.ConfigPath, path) {
		return tokenTelemetryResult{}, fmt.Errorf(
			"ownership state %q belongs to Claude settings %q; no files were changed",
			statePath,
			owned.ConfigPath,
		)
	}
	config, env, original, existed, err := readClaudeSettings(path)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	removed := make([]string, 0, len(owned.Env))
	preserved := make([]string, 0)
	configChanged := false
	beforeConfig := tokenTelemetryConfigSnapshot{Data: original, Exists: existed}
	afterConfig := beforeConfig
	if existed {
		keys := make([]string, 0, len(owned.Env))
		for key := range owned.Env {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			current, exists := env[key]
			if !exists {
				continue
			}
			if currentString, stringValue := current.(string); stringValue && currentString == owned.Env[key] {
				delete(env, key)
				removed = append(removed, key)
				configChanged = true
				continue
			}
			preserved = append(preserved, key)
		}
		if configChanged {
			if len(env) == 0 {
				delete(config, "env")
			} else {
				config["env"] = env
			}
			out, marshalErr := json.MarshalIndent(config, "", "  ")
			if marshalErr != nil {
				return tokenTelemetryResult{}, fmt.Errorf("marshal Claude settings %q: %w", path, marshalErr)
			}
			afterConfig = tokenTelemetryConfigSnapshot{Data: append(out, '\n'), Exists: true}
		}
	}
	beforeOwnership := cloneTokenTelemetryOwnership(ownership)
	delete(ownership.Targets, "claude-code")
	if mutation != nil {
		mutation(&ownership)
	}
	if !configChanged {
		afterConfig = beforeConfig
	}
	if err := publishTokenTelemetryConfigTransaction(
		statePath,
		"claude-code",
		path,
		beforeConfig,
		afterConfig,
		beforeOwnership,
		ownership,
		writeOwnership,
	); err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("write ownership state: %w", err)
	}
	result.Detail = fmt.Sprintf("removed %d unchanged Obstudio-managed settings", len(removed))
	if len(preserved) > 0 {
		result.State = "disabled-with-user-changes"
		result.Detail += "; preserved modified settings: " + strings.Join(preserved, ", ")
	} else if claudeDetailedBetaTelemetryConfigured(env, lookupEnv) {
		result.State = "unmanaged"
		result.Detail += "; active user-owned detailed-beta telemetry routing remains configured"
	} else if claudeTokenTelemetryConfigured(env, lookupEnv) {
		result.State = "unmanaged"
		result.Detail += "; user-owned Claude telemetry settings remain configured"
	}
	return result, nil
}

func inspectClaudeTokenTelemetry(
	path, statePath, endpoint string,
	lookupEnv func(string) (string, bool),
) (result tokenTelemetryResult, err error) {
	result = tokenTelemetryResult{Target: "claude-code", ConfigPath: path, State: "disabled"}
	defer func() {
		if err == nil {
			result.Detail = appendTokenTelemetryDetail(
				result.Detail,
				"result covers user-level Claude Code settings only; higher-precedence managed settings, including Claude Desktop Setup profiles, can override them",
			)
		}
	}()
	ownership, err := readTokenTelemetryOwnership(statePath)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	config, env, _, existed, err := readClaudeSettings(path)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	required, _, err := claudeTokenTelemetrySettings(endpoint)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	managed := map[string]string(nil)
	if owned, ok := ownership.Targets["claude-code"]; ok && sameTokenTelemetryConfigPath(owned.ConfigPath, path) {
		managed = owned.Env
	}
	if conflict := claudeOTLPRoutingConflict(config, env, required, endpoint, managed, lookupEnv); conflict != "" {
		result.State = "conflict"
		result.Detail = conflict
		return result, nil
	}
	detailedBetaAtObserver := claudeDetailedBetaRoutesToObserver(env, endpoint, lookupEnv)
	matching := 0
	missing := 0
	for _, setting := range required {
		value, exists, _ := claudeConfiguredOrInheritedValue(env, setting.key, lookupEnv)
		if !exists {
			missing++
			continue
		}
		if value != setting.value {
			result.State = "conflict"
			result.Detail = setting.key + " has a user-owned value"
			return result, nil
		}
		matching++
	}
	if matching == len(required) {
		result.State = "enabled-existing"
		result.Detail = "matching settings are user-owned"
		if owned, ok := ownership.Targets["claude-code"]; ok && sameTokenTelemetryConfigPath(owned.ConfigPath, path) && len(owned.Env) > 0 {
			result.State = "enabled-managed"
			result.Detail = fmt.Sprintf("Obstudio owns %d settings; Claude logs, traces, and metrics target Observer", len(owned.Env))
		}
		return result, nil
	}
	if missing == len(required) {
		if detailedBetaAtObserver {
			result.State = "unmanaged"
			result.Detail = "a user-owned detailed-beta route targets Observer for logs and traces; metrics are not configured by that route"
		} else if existed {
			result.Detail = "provider token telemetry is not configured"
		} else {
			result.Detail = "Claude settings do not exist and no matching inherited telemetry is configured"
		}
		return result, nil
	}
	result.State = "partial"
	result.Detail = fmt.Sprintf("%d of %d required settings match Observer", matching, len(required))
	if detailedBetaAtObserver {
		result.Detail += "; a user-owned detailed-beta route also targets Observer for logs and traces"
	}
	return result, nil
}

func claudeTokenTelemetrySettings(endpoint string) ([]claudeTelemetrySetting, []claudeTelemetrySetting, error) {
	traceEndpoint, err := tokenTelemetryTraceEndpoint(endpoint)
	if err != nil {
		return nil, nil, err
	}
	metricEndpoint, err := tokenTelemetryMetricEndpoint(endpoint)
	if err != nil {
		return nil, nil, err
	}
	required := []claudeTelemetrySetting{
		{key: "CLAUDE_CODE_ENABLE_TELEMETRY", value: "1"},
		{key: "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA", value: "1"},
		{key: "OTEL_LOGS_EXPORTER", value: "otlp"},
		{key: "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", value: "http/protobuf"},
		{key: "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", value: endpoint},
		{key: "OTEL_TRACES_EXPORTER", value: "otlp"},
		{key: "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", value: "http/protobuf"},
		{key: "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", value: traceEndpoint},
		{key: "OTEL_METRICS_EXPORTER", value: "otlp"},
		{key: "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL", value: "http/protobuf"},
		{key: "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", value: metricEndpoint},
	}
	defaults := []claudeTelemetrySetting{
		{key: "OTEL_LOGS_EXPORT_INTERVAL", value: "1000"},
		{key: "OTEL_TRACES_EXPORT_INTERVAL", value: "1000"},
		{key: "OTEL_METRIC_EXPORT_INTERVAL", value: "1000"},
		{key: "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE", value: "cumulative"},
	}
	return required, defaults, nil
}

func claudeTokenTelemetryTakeoverSettings(
	env map[string]any,
	endpoint string,
	lookupEnv func(string) (string, bool),
) []claudeTelemetrySetting {
	settings := make([]claudeTelemetrySetting, 0, 6)
	for _, setting := range []claudeTelemetrySetting{
		{key: "OTEL_EXPORTER_OTLP_ENDPOINT", value: strings.TrimSuffix(endpoint, "/v1/logs")},
		{key: "OTEL_EXPORTER_OTLP_PROTOCOL", value: "http/protobuf"},
	} {
		if _, exists, _ := claudeConfiguredOrInheritedValue(env, setting.key, lookupEnv); exists {
			settings = append(settings, setting)
		}
	}
	if raw, exists := env["OTEL_SDK_DISABLED"]; exists {
		value, stringValue := raw.(string)
		if !stringValue || tokenTelemetryBooleanEnabled(value) {
			settings = append(settings, claudeTelemetrySetting{key: "OTEL_SDK_DISABLED", value: "false"})
		}
	} else if inherited, exists := lookupEnvironment(lookupEnv, "OTEL_SDK_DISABLED"); exists && tokenTelemetryBooleanEnabled(inherited) {
		settings = append(settings, claudeTelemetrySetting{key: "OTEL_SDK_DISABLED", value: "false"})
	}
	if _, active := claudeDetailedBetaEndpoint(env, lookupEnv); active {
		settings = append(settings,
			claudeTelemetrySetting{key: "ENABLE_BETA_TRACING_DETAILED", value: "1"},
			claudeTelemetrySetting{
				key:   "BETA_TRACING_ENDPOINT",
				value: strings.TrimSuffix(endpoint, "/v1/logs"),
			},
		)
	}
	return settings
}

func claudeOTLPRoutingConflict(
	_ map[string]any,
	env map[string]any,
	required []claudeTelemetrySetting,
	endpoint string,
	_ map[string]string,
	lookupEnv func(string) (string, bool),
) string {
	if raw, exists := env["OTEL_SDK_DISABLED"]; exists {
		value, stringValue := raw.(string)
		if !stringValue || tokenTelemetryBooleanEnabled(value) {
			return "Claude setting OTEL_SDK_DISABLED disables provider token telemetry; enable replaces it and disable removes the managed override"
		}
	} else if value, exists := lookupEnvironment(lookupEnv, "OTEL_SDK_DISABLED"); exists && tokenTelemetryBooleanEnabled(value) {
		return "inherited environment OTEL_SDK_DISABLED disables provider token telemetry; enable adds a local override"
	}
	if conflict := claudeDetailedBetaRoutingConflict(env, endpoint, lookupEnv); conflict != "" {
		return conflict + "; enable replaces BETA_TRACING_ENDPOINT and disable removes the managed route"
	}
	for _, setting := range []claudeTelemetrySetting{
		{key: "OTEL_EXPORTER_OTLP_ENDPOINT", value: strings.TrimSuffix(endpoint, "/v1/logs")},
		{key: "OTEL_EXPORTER_OTLP_PROTOCOL", value: "http/protobuf"},
	} {
		if value, exists, source := claudeConfiguredOrInheritedValue(env, setting.key, lookupEnv); exists && value != setting.value {
			return fmt.Sprintf("%s %s does not match Observer; enable replaces it and disable removes the managed route", source, setting.key)
		}
	}

	expected := make(map[string]string, len(required))
	for _, setting := range required {
		expected[setting.key] = setting.value
	}
	for key, wanted := range expected {
		if existing, exists := env[key]; exists {
			value, stringValue := existing.(string)
			if !stringValue || value != wanted {
				return fmt.Sprintf("Claude setting %s does not match Observer; enable replaces it and disable removes the managed route", key)
			}
			continue
		}
		if inherited, ok := lookupEnvironment(lookupEnv, key); ok && inherited != wanted {
			return fmt.Sprintf("inherited environment setting %s does not match Observer; enable adds a local override", key)
		}
	}
	return ""
}

func claudeDetailedBetaRoutingConflict(
	env map[string]any,
	observerLogsEndpoint string,
	lookupEnv func(string) (string, bool),
) string {
	enabled, exists, enabledSource := claudeConfiguredOrInheritedValue(
		env,
		"ENABLE_BETA_TRACING_DETAILED",
		lookupEnv,
	)
	if !exists || !tokenTelemetryBooleanEnabled(enabled) {
		return ""
	}
	detailedEndpoint, exists, endpointSource := claudeConfiguredOrInheritedValue(
		env,
		"BETA_TRACING_ENDPOINT",
		lookupEnv,
	)
	if !exists || detailedEndpoint == "" {
		return ""
	}
	if claudeDetailedBetaEndpointMatchesObserver(detailedEndpoint, observerLogsEndpoint) {
		return ""
	}
	return fmt.Sprintf(
		"%s ENABLE_BETA_TRACING_DETAILED and %s BETA_TRACING_ENDPOINT override the standard OTLP logs and traces endpoints",
		enabledSource,
		endpointSource,
	)
}

func claudeDetailedBetaTelemetryConfigured(env map[string]any, lookupEnv func(string) (string, bool)) bool {
	_, active := claudeDetailedBetaEndpoint(env, lookupEnv)
	return active
}

func claudeDetailedBetaRoutesToObserver(
	env map[string]any,
	observerLogsEndpoint string,
	lookupEnv func(string) (string, bool),
) bool {
	endpoint, active := claudeDetailedBetaEndpoint(env, lookupEnv)
	return active && claudeDetailedBetaEndpointMatchesObserver(endpoint, observerLogsEndpoint)
}

func claudeDetailedBetaEndpoint(env map[string]any, lookupEnv func(string) (string, bool)) (string, bool) {
	enabled, exists, _ := claudeConfiguredOrInheritedValue(env, "ENABLE_BETA_TRACING_DETAILED", lookupEnv)
	if !exists || !tokenTelemetryBooleanEnabled(enabled) {
		return "", false
	}
	endpoint, exists, _ := claudeConfiguredOrInheritedValue(env, "BETA_TRACING_ENDPOINT", lookupEnv)
	return strings.TrimSpace(endpoint), exists && endpoint != ""
}

func claudeDetailedBetaEndpointMatchesObserver(detailedEndpoint, observerLogsEndpoint string) bool {
	detailed, err := url.Parse(strings.TrimSpace(detailedEndpoint))
	if err != nil || detailed.User != nil || detailed.RawQuery != "" || detailed.Fragment != "" {
		return false
	}
	observer, err := url.Parse(observerLogsEndpoint)
	if err != nil || observer.Path != "/v1/logs" {
		return false
	}
	observer.Path = ""
	return detailed.Scheme == observer.Scheme &&
		sameSharedObserverHostname(detailed.Hostname(), observer.Hostname()) &&
		effectiveURLPort(detailed) == effectiveURLPort(observer) &&
		detailed.EscapedPath() == observer.EscapedPath()
}

func tokenTelemetryBooleanEnabled(value string) bool {
	trimmed := strings.TrimSpace(value)
	return trimmed == "1" || strings.EqualFold(trimmed, "true")
}

func claudeTokenTelemetryConfigured(
	env map[string]any,
	lookupEnv func(string) (string, bool),
) bool {
	if claudeDetailedBetaTelemetryConfigured(env, lookupEnv) {
		return true
	}
	keys := []string{
		"CLAUDE_CODE_ENABLE_TELEMETRY",
		"CLAUDE_CODE_ENHANCED_TELEMETRY_BETA",
		"OTEL_LOGS_EXPORTER",
		"OTEL_TRACES_EXPORTER",
		"OTEL_METRICS_EXPORTER",
		"OTEL_EXPORTER_OTLP_ENDPOINT",
		"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
		"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
		"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
	}
	for _, key := range keys {
		if value, exists, _ := claudeConfiguredOrInheritedValue(env, key, lookupEnv); exists && strings.TrimSpace(value) != "" {
			return true
		}
	}
	return false
}

func claudeConfiguredOrInheritedValue(
	env map[string]any,
	key string,
	lookupEnv func(string) (string, bool),
) (string, bool, string) {
	if raw, exists := env[key]; exists {
		value, ok := raw.(string)
		if !ok {
			return "", true, "Claude setting"
		}
		return value, true, "Claude setting"
	}
	if value, exists := lookupEnvironment(lookupEnv, key); exists {
		return value, true, "inherited environment"
	}
	return "", false, ""
}

func lookupEnvironment(lookupEnv func(string) (string, bool), key string) (string, bool) {
	if lookupEnv == nil {
		return "", false
	}
	return lookupEnv(key)
}

func readClaudeSettings(path string) (map[string]any, map[string]any, []byte, bool, error) {
	config := make(map[string]any)
	data, err := os.ReadFile(path)
	existed := err == nil
	if err == nil {
		if err := validateJSONUniqueObjectKeys(data); err != nil {
			return nil, nil, nil, false, fmt.Errorf("parse Claude settings %q: %w", path, err)
		}
		decoder := json.NewDecoder(bytes.NewReader(data))
		decoder.UseNumber()
		if err := decoder.Decode(&config); err != nil {
			return nil, nil, nil, false, fmt.Errorf("parse Claude settings %q: %w", path, err)
		}
		if config == nil {
			config = make(map[string]any)
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, nil, nil, false, fmt.Errorf("read Claude settings %q: %w", path, err)
	}
	env := make(map[string]any)
	if existing, exists := config["env"]; exists {
		var ok bool
		env, ok = existing.(map[string]any)
		if !ok {
			return nil, nil, nil, false, fmt.Errorf("Claude settings %q has a non-object env value; existing value was preserved", path)
		}
	}
	return config, env, data, existed, nil
}

func validateJSONUniqueObjectKeys(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var readValue func() error
	readValue = func() error {
		token, err := decoder.Token()
		if err != nil {
			return err
		}
		delimiter, compound := token.(json.Delim)
		if !compound {
			return nil
		}
		switch delimiter {
		case '{':
			seen := make(map[string]struct{})
			for decoder.More() {
				keyToken, err := decoder.Token()
				if err != nil {
					return err
				}
				key, ok := keyToken.(string)
				if !ok {
					return errors.New("object key is not a string")
				}
				if _, duplicate := seen[key]; duplicate {
					return fmt.Errorf("duplicate object key %q", key)
				}
				seen[key] = struct{}{}
				if err := readValue(); err != nil {
					return err
				}
			}
		case '[':
			for decoder.More() {
				if err := readValue(); err != nil {
					return err
				}
			}
		default:
			return fmt.Errorf("unexpected JSON delimiter %q", delimiter)
		}
		closing, err := decoder.Token()
		if err != nil {
			return err
		}
		if closing != matchingJSONDelimiter(delimiter) {
			return fmt.Errorf("unexpected JSON closing delimiter %q", closing)
		}
		return nil
	}
	if err := readValue(); err != nil {
		return err
	}
	if _, err := decoder.Token(); err != io.EOF {
		if err == nil {
			return errors.New("multiple JSON values")
		}
		return err
	}
	return nil
}

func matchingJSONDelimiter(delimiter json.Delim) json.Delim {
	if delimiter == '{' {
		return '}'
	}
	return ']'
}

func readTokenTelemetryOwnership(path string) (tokenTelemetryOwnership, error) {
	state := tokenTelemetryOwnership{
		Version:               tokenTelemetryStateVersion,
		Targets:               make(map[string]tokenTelemetryTargetOwnership),
		RepositoryCorrelation: make(map[string]tokenTelemetryRepositoryCorrelation),
	}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return state, nil
	}
	if err != nil {
		return tokenTelemetryOwnership{}, fmt.Errorf("read token telemetry ownership %q: %w", path, err)
	}
	if err := validateJSONUniqueObjectKeys(data); err != nil {
		return tokenTelemetryOwnership{}, fmt.Errorf("parse token telemetry ownership %q: %w", path, err)
	}
	if err := json.Unmarshal(data, &state); err != nil {
		return tokenTelemetryOwnership{}, fmt.Errorf("parse token telemetry ownership %q: %w", path, err)
	}
	if state.Version != tokenTelemetryStateVersion {
		return tokenTelemetryOwnership{}, fmt.Errorf("token telemetry ownership %q uses unsupported version %d", path, state.Version)
	}
	if state.Targets == nil {
		state.Targets = make(map[string]tokenTelemetryTargetOwnership)
	}
	if state.RepositoryCorrelation == nil {
		state.RepositoryCorrelation = make(map[string]tokenTelemetryRepositoryCorrelation)
	}
	return state, nil
}

func writeTokenTelemetryOwnership(path string, state tokenTelemetryOwnership) error {
	if len(state.Targets) == 0 && len(state.RepositoryCorrelation) == 0 {
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return fmt.Errorf("remove token telemetry ownership %q: %w", path, err)
		}
		return nil
	}
	state.Version = tokenTelemetryStateVersion
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal token telemetry ownership %q: %w", path, err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("create parent directory for token telemetry ownership %q: %w", path, err)
	}
	return writeConfigFile(path, append(data, '\n'), 0o600, false)
}

func parseCodexManagedTelemetryBlock(content string) (codexManagedTelemetryBlock, bool, error) {
	block := codexManagedTelemetryBlock{settings: make(map[string]string)}
	lines := splitLines(content)
	codeLines, err := codexTOMLCodeLines(lines)
	if err != nil {
		return block, false, err
	}
	inBlock := false
	found := false
	for index, line := range lines {
		codeLine := codeLines[index]
		switch strings.TrimSpace(codeLine) {
		case codexTokenTelemetryBlockStart:
			if inBlock {
				return block, found, errors.New("nested managed block start")
			}
			if found {
				return block, found, errors.New("more than one managed block")
			}
			inBlock = true
			found = true
			continue
		case codexTokenTelemetryBlockEnd:
			if !inBlock {
				return block, found, errors.New("managed block end without start")
			}
			inBlock = false
			continue
		}
		if !inBlock {
			continue
		}
		if tomlStructuralLine(codeLine) == "[otel]" {
			if block.sectionLine != "" {
				return block, found, errors.New("managed block contains more than one [otel] section")
			}
			block.sectionLine = line
			continue
		}
		key, _, assignment := tomlAssignment(codeLine)
		if assignment && (key == "exporter" || key == "trace_exporter" || key == "metrics_exporter") {
			if _, duplicate := block.settings[key]; duplicate {
				return block, found, fmt.Errorf("managed block contains more than one %s assignment", key)
			}
			block.settings[key] = line
			continue
		}
		block.otherLines = append(block.otherLines, line)
	}
	if inBlock {
		return block, found, errors.New("managed block start without end")
	}
	return block, found, nil
}

func codexManagedBlockMismatch(block codexManagedTelemetryBlock, owned tokenTelemetryTargetOwnership) string {
	if block.sectionLine != owned.SectionLine {
		return "the managed [otel] section line changed"
	}
	if len(block.otherLines) > 0 {
		return "the managed block contains untracked content"
	}
	for key, current := range block.settings {
		expected, ok := owned.Settings[key]
		if !ok {
			return key + " was added inside the managed block"
		}
		if current != expected {
			return key + " changed"
		}
	}
	for key := range owned.Settings {
		if _, ok := block.settings[key]; !ok {
			return key + " is missing"
		}
	}
	return ""
}

func codexManagedBlockUnchanged(block codexManagedTelemetryBlock, owned tokenTelemetryTargetOwnership) bool {
	return codexManagedBlockMismatch(block, owned) == "" && len(block.settings) == len(owned.Settings)
}

func codexOwnedTableSettingMismatch(
	content string,
	owned tokenTelemetryTargetOwnership,
) (string, error) {
	if len(owned.TableSettings) == 0 {
		return "", nil
	}
	current, err := codexOwnedTableSettingLines(content, owned.TableSettings)
	if err != nil {
		return "", err
	}
	keys := make([]string, 0, len(owned.TableSettings))
	for key := range owned.TableSettings {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		line, exists := current[key]
		if !exists {
			return key + " is missing", nil
		}
		if line != owned.TableSettings[key] {
			return key + " changed", nil
		}
	}
	return "", nil
}

func codexOwnedTableSettingLines(
	content string,
	owned map[string]string,
) (map[string]string, error) {
	wanted := make(map[string]string, len(owned))
	for key, line := range owned {
		section, setting, ok := codexOwnedTableSettingLocation(key)
		lineKey, _, assignment := codexTOMLSimpleAssignment(tomlStructuralLine(line))
		if !ok || !assignment || lineKey != setting ||
			!strings.HasSuffix(strings.TrimSpace(line), " "+codexTokenTelemetryLineMarker) {
			return nil, fmt.Errorf("ownership contains unsupported Codex table setting %q", key)
		}
		wanted[section+"\x00"+setting] = key
	}
	lines := strings.Split(content, "\n")
	codeLines, err := codexTOMLCodeLines(lines)
	if err != nil {
		return nil, err
	}
	current := make(map[string]string, len(owned))
	section := ""
	for index, codeLine := range codeLines {
		structural := tomlStructuralLine(codeLine)
		if isTOMLTableHeader(structural) {
			section = structural
			continue
		}
		setting, _, ok := codexTOMLSimpleAssignment(structural)
		if !ok {
			continue
		}
		key, wantedSetting := wanted[section+"\x00"+setting]
		if !wantedSetting {
			continue
		}
		if _, duplicate := current[key]; duplicate {
			return nil, fmt.Errorf("%s is defined more than once", key)
		}
		current[key] = strings.TrimSuffix(lines[index], "\r")
	}
	return current, nil
}

func codexOwnedTableSettingLocation(key string) (string, string, bool) {
	exporter, setting, ok := strings.Cut(key, ".")
	if !ok {
		return "", "", false
	}
	switch exporter {
	case "exporter", "trace_exporter", "metrics_exporter":
		if setting == "assignment" {
			return "[otel]", exporter, true
		}
		if setting == "endpoint" || setting == "protocol" {
			return "[otel." + exporter + ".otlp-http]", setting, true
		}
		return "", "", false
	default:
		return "", "", false
	}
}

func removeOwnedCodexTableSettings(
	content string,
	owned tokenTelemetryTargetOwnership,
) (string, bool, int, []string, error) {
	if len(owned.TableSettings) == 0 {
		return content, false, 0, nil, nil
	}
	if _, err := codexOwnedTableSettingLines(content, owned.TableSettings); err != nil {
		return content, false, 0, nil, err
	}
	wanted := make(map[string]string, len(owned.TableSettings))
	for key := range owned.TableSettings {
		section, setting, ok := codexOwnedTableSettingLocation(key)
		if !ok {
			return content, false, 0, nil, fmt.Errorf("ownership contains unsupported Codex table setting %q", key)
		}
		wanted[section+"\x00"+setting] = key
	}
	lines := splitLines(content)
	codeLines, err := codexTOMLCodeLines(lines)
	if err != nil {
		return content, false, 0, nil, err
	}
	out := strings.Builder{}
	section := ""
	removed := 0
	preservedSet := make(map[string]struct{})
	for index, line := range lines {
		structural := tomlStructuralLine(codeLines[index])
		if isTOMLTableHeader(structural) {
			section = structural
			out.WriteString(line)
			continue
		}
		setting, _, assignment := codexTOMLSimpleAssignment(structural)
		key, tracked := wanted[section+"\x00"+setting]
		if !assignment || !tracked {
			out.WriteString(line)
			continue
		}
		current := strings.TrimSuffix(strings.TrimSuffix(line, "\n"), "\r")
		if current == owned.TableSettings[key] {
			removed++
			continue
		}
		preservedSet[key] = struct{}{}
		out.WriteString(line)
	}
	preserved := make([]string, 0, len(preservedSet))
	for key := range preservedSet {
		preserved = append(preserved, key)
	}
	sort.Strings(preserved)
	return out.String(), true, removed, preserved, nil
}

func removeOwnedCodexTelemetry(
	content string,
	owned tokenTelemetryTargetOwnership,
) (string, bool, int, []string, error) {
	if _, found, err := parseCodexManagedTelemetryBlock(content); err != nil || !found {
		return content, found, 0, nil, err
	}

	ownedLines := make(map[string]string, len(owned.Settings))
	for key, line := range owned.Settings {
		ownedLines[line] = key
	}
	lines := splitLines(content)
	codeLines, lexErr := codexTOMLCodeLines(lines)
	if lexErr != nil {
		return content, false, 0, nil, lexErr
	}
	out := strings.Builder{}
	inBlock := false
	inside := make([]string, 0)
	insideCode := make([]string, 0)
	removed := 0
	preservedSet := make(map[string]struct{})
	preserved := make([]string, 0)
	preserveOwnedSection := owned.SectionLine != "" && codexManagedSectionHasExternalContent(lines, codeLines)
	if preserveOwnedSection {
		preservedSet["[otel] settings outside managed block"] = struct{}{}
		preserved = append(preserved, "[otel] settings outside managed block")
	}
	flushBlock := func() {
		kept := make([]string, 0, len(inside))
		for index, line := range inside {
			if _, exactOwnedSetting := ownedLines[line]; exactOwnedSetting {
				removed++
				continue
			}
			if owned.SectionLine != "" && line == owned.SectionLine {
				continue
			}
			kept = append(kept, line)
			label := "managed block content"
			if key, _, ok := tomlAssignment(insideCode[index]); ok {
				label = key
			} else if structural := tomlStructuralLine(insideCode[index]); structural != "" {
				label = structural
			}
			if _, duplicate := preservedSet[label]; !duplicate {
				preservedSet[label] = struct{}{}
				preserved = append(preserved, label)
			}
		}
		if len(kept) == 0 && !preserveOwnedSection {
			return
		}
		for _, line := range inside {
			if owned.SectionLine != "" && line == owned.SectionLine {
				out.WriteString(line)
				break
			}
		}
		for _, line := range kept {
			out.WriteString(line)
		}
	}
	for index, line := range lines {
		switch strings.TrimSpace(codeLines[index]) {
		case codexTokenTelemetryBlockStart:
			inBlock = true
			inside = inside[:0]
			insideCode = insideCode[:0]
		case codexTokenTelemetryBlockEnd:
			flushBlock()
			inBlock = false
		default:
			if inBlock {
				inside = append(inside, line)
				insideCode = append(insideCode, codeLines[index])
			} else {
				out.WriteString(line)
			}
		}
	}
	sort.Strings(preserved)
	return out.String(), true, removed, preserved, nil
}

func removeCodexTokenTelemetryBlock(content string) (string, bool, error) {
	block, found, err := parseCodexManagedTelemetryBlock(content)
	if err != nil || !found {
		return content, found, err
	}
	lines := splitLines(content)
	codeLines, lexErr := codexTOMLCodeLines(lines)
	if lexErr != nil {
		return content, false, lexErr
	}
	preserveSection := block.sectionLine != "" && codexManagedSectionHasExternalContent(lines, codeLines)
	out := strings.Builder{}
	inBlock := false
	for index, line := range lines {
		switch strings.TrimSpace(codeLines[index]) {
		case codexTokenTelemetryBlockStart:
			inBlock = true
		case codexTokenTelemetryBlockEnd:
			inBlock = false
		default:
			if !inBlock || (preserveSection && line == block.sectionLine) {
				out.WriteString(line)
			}
		}
	}
	return out.String(), found, nil
}

func unwrapCodexTokenTelemetryBlock(content string) (string, error) {
	_, found, err := parseCodexManagedTelemetryBlock(content)
	if err != nil || !found {
		return content, err
	}
	lines := splitLines(content)
	codeLines, err := codexTOMLCodeLines(lines)
	if err != nil {
		return content, err
	}
	out := strings.Builder{}
	for index, line := range lines {
		switch strings.TrimSpace(codeLines[index]) {
		case codexTokenTelemetryBlockStart, codexTokenTelemetryBlockEnd:
			continue
		default:
			out.WriteString(line)
		}
	}
	return out.String(), nil
}

func codexManagedSectionHasExternalContent(lines, codeLines []string) bool {
	inBlock := false
	createdSection := false
	afterBlock := false
	for index := range lines {
		switch strings.TrimSpace(codeLines[index]) {
		case codexTokenTelemetryBlockStart:
			inBlock = true
			continue
		case codexTokenTelemetryBlockEnd:
			inBlock = false
			afterBlock = createdSection
			continue
		}
		structural := tomlStructuralLine(codeLines[index])
		if inBlock {
			createdSection = createdSection || structural == "[otel]"
			continue
		}
		if !afterBlock || structural == "" {
			continue
		}
		if isTOMLTableHeader(structural) {
			return false
		}
		return true
	}
	return false
}

func findCodexOTelSection(lines []string) (int, int) {
	for i, line := range lines {
		if tomlStructuralLine(line) != "[otel]" {
			continue
		}
		end := len(lines)
		for j := i + 1; j < len(lines); j++ {
			if isTOMLTableHeader(tomlStructuralLine(lines[j])) {
				end = j
				break
			}
		}
		return i, end
	}
	return -1, -1
}

func firstCodexOTelChildSection(lines []string) int {
	for i, line := range lines {
		trimmed := tomlStructuralLine(line)
		if strings.HasPrefix(trimmed, "[otel.") && strings.HasSuffix(trimmed, "]") {
			return i
		}
	}
	return -1
}

func unsupportedCodexOTelExporterDefinition(lines []string) string {
	section := ""
	otelSectionCount := 0
	for _, line := range lines {
		structural := tomlStructuralLine(line)
		if isTOMLTableHeader(structural) {
			section = structural
			if structural == "[otel]" {
				otelSectionCount++
				if otelSectionCount > 1 {
					return "duplicate [otel] table"
				}
			}
			compact := compactTOMLStructuralLine(structural)
			if compact != structural &&
				(strings.HasPrefix(compact, "[otel") || strings.HasPrefix(compact, "[[otel") ||
					strings.HasPrefix(compact, "[\"otel\"") || strings.HasPrefix(compact, "['otel'")) {
				return "noncanonical OTel table"
			}
			if strings.HasPrefix(compact, "[[otel") ||
				strings.HasPrefix(compact, "[\"otel\"") ||
				strings.HasPrefix(compact, "['otel'") {
				return "unsupported OTel table"
			}
			if strings.HasPrefix(compact, "[otel.") &&
				(strings.Contains(compact, "\"exporter\"") || strings.Contains(compact, "'exporter'")) {
				return "quoted exporter table"
			}
			for _, key := range []string{"exporter", "trace_exporter", "metrics_exporter"} {
				prefix := "[otel." + key
				if strings.HasPrefix(structural, prefix+".") &&
					structural != prefix+".otlp-http]" &&
					structural != prefix+".otlp-http.headers]" {
					return key + " table"
				}
			}
			continue
		}
		key, _, ok := tomlAssignment(line)
		if !ok {
			continue
		}
		normalizedKey := key
		if unquoted, quoted := tomlStringValue(key); quoted {
			normalizedKey = unquoted
		}
		if section == "" {
			path, pathErr := parseCodexTOMLDottedKey(key)
			if pathErr == nil && len(path) > 0 && path[0] == "otel" {
				return "root dotted-key"
			}
			for _, exporterKey := range []string{"exporter", "trace_exporter", "metrics_exporter"} {
				prefix := "otel." + exporterKey
				if key == prefix || strings.HasPrefix(key, prefix+".") ||
					(strings.Contains(key, "otel") && strings.Contains(key, exporterKey)) {
					return "root dotted-key"
				}
			}
		}
		if section == "[otel]" {
			if normalizedKey == "exporter" || normalizedKey == "trace_exporter" || normalizedKey == "metrics_exporter" {
				if normalizedKey != key {
					return "quoted exporter key"
				}
				continue
			}
			if strings.HasPrefix(key, "exporter.") || strings.HasPrefix(key, "trace_exporter.") || strings.HasPrefix(key, "metrics_exporter.") ||
				(strings.Contains(key, "exporter") && strings.ContainsAny(key, "'\"")) {
				return "dotted-key"
			}
		}
	}
	return ""
}

func compactTOMLStructuralLine(value string) string {
	result := strings.Builder{}
	quote := byte(0)
	for index := 0; index < len(value); index++ {
		char := value[index]
		if char == '\'' || char == '"' {
			if quote == 0 {
				quote = char
			} else if quote == char {
				quote = 0
			}
			result.WriteByte(char)
			continue
		}
		if quote == 0 && (char == ' ' || char == '\t') {
			continue
		}
		result.WriteByte(char)
	}
	return result.String()
}

func codexExporterTable(lines []string, exporterKey string) (codexTelemetryTableExporter, error) {
	result := codexTelemetryTableExporter{
		otlpHTTPSectionEnd: -1,
		endpointIndex:      -1,
		protocolIndex:      -1,
	}
	rootSection := "[otel." + exporterKey + "]"
	otlpSection := "[otel." + exporterKey + ".otlp-http]"
	headersSection := "[otel." + exporterKey + ".otlp-http.headers]"
	section := ""
	sectionCounts := make(map[string]int)
	endpointCount := 0
	protocolCount := 0
	for index, line := range lines {
		structural := tomlStructuralLine(line)
		if isTOMLTableHeader(structural) {
			if section == otlpSection && result.otlpHTTPSectionEnd < 0 {
				result.otlpHTTPSectionEnd = index
			}
			section = structural
			if structural == rootSection || structural == otlpSection || structural == headersSection {
				result.found = true
				sectionCounts[structural]++
				if sectionCounts[structural] > 1 {
					return result, fmt.Errorf("%s is defined more than once", structural)
				}
				if structural == otlpSection {
					result.otlpHTTPFound = true
				}
			}
			continue
		}
		if section != otlpSection {
			continue
		}
		key, value, ok, assignmentErr := codexTOMLSimpleAssignmentStrict(structural)
		if assignmentErr != nil {
			return result, fmt.Errorf("unsupported assignment in %s: %w", otlpSection, assignmentErr)
		}
		if !ok {
			if structural != "" {
				return result, fmt.Errorf("unsupported non-assignment in %s", otlpSection)
			}
			continue
		}
		switch key {
		case "endpoint":
			endpointCount++
			result.endpoint, ok = tomlStringValue(value)
			result.endpointIndex = index
			result.endpointSet = true
		case "protocol":
			protocolCount++
			result.protocol, ok = tomlStringValue(value)
			result.protocolIndex = index
			result.protocolSet = true
		default:
			continue
		}
		if !ok {
			return result, fmt.Errorf("%s must be a quoted string", key)
		}
	}
	if !result.found {
		return result, nil
	}
	if result.otlpHTTPFound && result.otlpHTTPSectionEnd < 0 {
		result.otlpHTTPSectionEnd = len(lines)
		if len(lines) > 0 && lines[len(lines)-1] == "" {
			result.otlpHTTPSectionEnd--
		}
	}
	if !result.otlpHTTPFound {
		return result, errors.New("otlp-http table is missing")
	}
	if endpointCount > 1 || protocolCount > 1 {
		return result, errors.New("otlp-http must not define endpoint or protocol more than once")
	}
	return result, nil
}

func tomlStringValue(value string) (string, bool) {
	trimmed := strings.TrimSpace(value)
	if len(trimmed) < 2 {
		return "", false
	}
	quote := trimmed[0]
	if (quote != '\'' && quote != '"') || trimmed[len(trimmed)-1] != quote {
		return "", false
	}
	return trimmed[1 : len(trimmed)-1], true
}

func codexTOMLCodeLines(lines []string) ([]string, error) {
	codeLines := make([]string, len(lines))
	multilineQuote := byte(0)
	for index, line := range lines {
		codeLines[index], multilineQuote = maskTOMLMultilineStrings(line, multilineQuote)
	}
	if multilineQuote != 0 {
		return nil, errors.New("unterminated TOML multiline string")
	}
	return codeLines, nil
}

func maskTOMLMultilineStrings(line string, multilineQuote byte) (string, byte) {
	masked := []byte(line)
	singleLineQuote := byte(0)
	escaped := false
	for index := 0; index < len(line); {
		char := line[index]
		if multilineQuote != 0 {
			if char == multilineQuote {
				runEnd := index + 1
				for runEnd < len(line) && line[runEnd] == multilineQuote {
					runEnd++
				}
				closeStart := index
				if multilineQuote == '"' && tomlByteEscaped(line, index) {
					closeStart++
				}
				maskTOMLBytes(masked, index, runEnd)
				if runEnd-closeStart >= 3 {
					multilineQuote = 0
				}
				index = runEnd
				continue
			}
			maskTOMLBytes(masked, index, index+1)
			index++
			continue
		}

		if singleLineQuote != 0 {
			if singleLineQuote == '"' && escaped {
				escaped = false
				index++
				continue
			}
			if singleLineQuote == '"' && char == '\\' {
				escaped = true
				index++
				continue
			}
			if char == singleLineQuote {
				singleLineQuote = 0
			}
			index++
			continue
		}

		if char == '#' {
			break
		}
		if char != '\'' && char != '"' {
			index++
			continue
		}
		runEnd := index + 1
		for runEnd < len(line) && line[runEnd] == char {
			runEnd++
		}
		if runEnd-index >= 3 {
			maskTOMLBytes(masked, index, index+3)
			multilineQuote = char
			index += 3
			continue
		}
		singleLineQuote = char
		escaped = false
		index++
	}
	return string(masked), multilineQuote
}

func maskTOMLBytes(value []byte, start, end int) {
	for index := start; index < end; index++ {
		if value[index] != '\n' && value[index] != '\r' {
			value[index] = ' '
		}
	}
}

func tomlByteEscaped(value string, index int) bool {
	backslashes := 0
	for index--; index >= 0 && value[index] == '\\'; index-- {
		backslashes++
	}
	return backslashes%2 == 1
}

func tomlStructuralLine(line string) string {
	quote := byte(0)
	escaped := false
	for i := 0; i < len(line); i++ {
		char := line[i]
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
		if char == '#' && quote == 0 {
			return strings.TrimSpace(line[:i])
		}
	}
	return strings.TrimSpace(line)
}

func tomlAssignment(line string) (string, string, bool) {
	trimmed := strings.TrimSpace(line)
	if trimmed == "" || strings.HasPrefix(trimmed, "#") {
		return "", "", false
	}
	parts := strings.SplitN(trimmed, "=", 2)
	if len(parts) != 2 {
		return "", "", false
	}
	return strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1]), true
}

func codexTOMLSimpleAssignment(line string) (string, string, bool) {
	key, value, ok := tomlAssignment(line)
	if !ok {
		return "", "", false
	}
	path, err := parseCodexTOMLDottedKey(key)
	if err != nil || len(path) != 1 {
		return key, value, true
	}
	return path[0], value, true
}

func codexTOMLSimpleAssignmentStrict(line string) (string, string, bool, error) {
	key, value, ok := tomlAssignment(line)
	if !ok {
		return "", "", false, nil
	}
	path, err := parseCodexTOMLDottedKey(key)
	if err != nil {
		return "", "", false, err
	}
	if len(path) != 1 {
		if len(path) > 0 && (path[0] == "endpoint" || path[0] == "protocol") {
			return "", "", false, fmt.Errorf("%s must be a simple key", path[0])
		}
		return key, value, true, nil
	}
	return path[0], value, true, nil
}

func codexExporterTargetsEndpoint(value, endpoint string) bool {
	withoutComment := tomlStructuralLine(value)
	if tomlInlineAssignmentCount(withoutComment, "otlp-http") != 1 {
		return false
	}
	otlpHTTP, ok := tomlInlineAssignmentValue(withoutComment, "otlp-http")
	if !ok {
		return false
	}
	if tomlInlineAssignmentCount(otlpHTTP, "endpoint") != 1 || tomlInlineAssignmentCount(otlpHTTP, "protocol") != 1 {
		return false
	}
	configuredEndpoint, endpointOK := tomlInlineAssignmentValue(otlpHTTP, "endpoint")
	configuredProtocol, protocolOK := tomlInlineAssignmentValue(otlpHTTP, "protocol")
	parsedEndpoint, endpointString := tomlStringValue(configuredEndpoint)
	parsedProtocol, protocolString := tomlStringValue(configuredProtocol)
	return endpointOK && protocolOK && endpointString && protocolString &&
		parsedEndpoint == endpoint && strings.EqualFold(parsedProtocol, "binary")
}

func tomlInlineAssignmentCount(value, key string) int {
	count := 0
	for index := 0; index < len(value); index++ {
		if _, ok := tomlInlineAssignmentValueStart(value, key, index); ok {
			count++
		}
	}
	return count
}

func tomlInlineAssignmentValue(value, key string) (string, bool) {
	for index := 0; index < len(value); index++ {
		cursor, ok := tomlInlineAssignmentValueStart(value, key, index)
		if !ok {
			continue
		}
		if cursor >= len(value) {
			return "", false
		}

		start := cursor
		switch value[cursor] {
		case '\'', '"':
			quote := value[cursor]
			cursor++
			escaped := false
			for cursor < len(value) {
				char := value[cursor]
				if quote == '"' && escaped {
					escaped = false
					cursor++
					continue
				}
				if quote == '"' && char == '\\' {
					escaped = true
					cursor++
					continue
				}
				cursor++
				if char == quote {
					return value[start:cursor], true
				}
			}
			return "", false
		case '{':
			depth := 0
			quote := byte(0)
			escaped := false
			for cursor < len(value) {
				char := value[cursor]
				if quote == '"' && escaped {
					escaped = false
					cursor++
					continue
				}
				if quote == '"' && char == '\\' {
					escaped = true
					cursor++
					continue
				}
				if quote != 0 {
					if char == quote {
						quote = 0
					}
					cursor++
					continue
				}
				if char == '\'' || char == '"' {
					quote = char
					cursor++
					continue
				}
				if char == '{' {
					depth++
				} else if char == '}' {
					depth--
					if depth == 0 {
						cursor++
						return value[start:cursor], true
					}
				}
				cursor++
			}
			return "", false
		default:
			for cursor < len(value) && value[cursor] != ',' && value[cursor] != '}' {
				cursor++
			}
			return strings.TrimSpace(value[start:cursor]), true
		}
	}
	return "", false
}

func tomlInlineAssignmentValueStart(value, key string, start int) (int, bool) {
	if start >= len(value) || !tomlInlineKeyStartBoundary(value, start) {
		return 0, false
	}
	cursor := start
	if value[cursor] == '\'' || value[cursor] == '"' {
		quote := value[cursor]
		cursor++
		escaped := false
		for cursor < len(value) {
			char := value[cursor]
			if quote == '"' && escaped {
				escaped = false
				cursor++
				continue
			}
			if quote == '"' && char == '\\' {
				escaped = true
				cursor++
				continue
			}
			cursor++
			if char == quote {
				break
			}
		}
		if cursor > len(value) || cursor == 0 || value[cursor-1] != quote {
			return 0, false
		}
		parsed, ok := tomlStringValue(value[start:cursor])
		if !ok || parsed != key {
			return 0, false
		}
	} else {
		if !strings.HasPrefix(value[start:], key) || !tomlInlineKeyBoundary(value, start, len(key)) {
			return 0, false
		}
		cursor += len(key)
	}
	for cursor < len(value) && (value[cursor] == ' ' || value[cursor] == '\t') {
		cursor++
	}
	if cursor >= len(value) || value[cursor] != '=' {
		return 0, false
	}
	cursor++
	for cursor < len(value) && (value[cursor] == ' ' || value[cursor] == '\t') {
		cursor++
	}
	return cursor, true
}

func tomlInlineKeyStartBoundary(value string, start int) bool {
	if start == 0 {
		return true
	}
	previous := value[start-1]
	return previous == '{' || previous == ',' || previous == ' ' || previous == '\t'
}

func tomlInlineKeyBoundary(value string, start, length int) bool {
	if start > 0 {
		previous := value[start-1]
		if previous != '{' && previous != ',' && previous != ' ' && previous != '\t' {
			return false
		}
	}
	end := start + length
	return end == len(value) || value[end] == '=' || value[end] == ' ' || value[end] == '\t'
}

func insertStrings(values []string, index int, inserted []string) []string {
	result := make([]string, 0, len(values)+len(inserted))
	result = append(result, values[:index]...)
	result = append(result, inserted...)
	result = append(result, values[index:]...)
	return result
}

func writeAgentConfig(path string, data []byte) error {
	return writeConfigFile(path, data, 0o600, true)
}

func writeConfigFile(path string, data []byte, mode os.FileMode, preserveExistingMode bool) error {
	return writeConfigFileWith(path, data, mode, preserveExistingMode, os.Rename)
}

func writeConfigFileWith(
	path string,
	data []byte,
	mode os.FileMode,
	preserveExistingMode bool,
	rename func(string, string) error,
) error {
	targetPath := path
	if info, err := os.Lstat(path); err == nil && info.Mode()&os.ModeSymlink != 0 {
		resolved, resolveErr := filepath.EvalSymlinks(path)
		if resolveErr != nil {
			return fmt.Errorf("resolve config symlink %q: %w", path, resolveErr)
		}
		targetPath = resolved
	} else if err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("inspect config path %q: %w", path, err)
	}

	parent := filepath.Dir(targetPath)
	if err := os.MkdirAll(parent, 0o755); err != nil {
		return fmt.Errorf("create parent directory for %q: %w", path, err)
	}
	targetInfo, targetErr := os.Stat(targetPath)
	targetExists := targetErr == nil
	if targetErr != nil && !errors.Is(targetErr, os.ErrNotExist) {
		return fmt.Errorf("inspect config %q: %w", path, targetErr)
	}
	if preserveExistingMode && targetExists {
		mode = targetInfo.Mode().Perm()
	}
	tempFile, err := os.CreateTemp(parent, "."+filepath.Base(targetPath)+".tmp-*")
	if err != nil {
		return fmt.Errorf("create temporary config for %q: %w", path, err)
	}
	tempPath := tempFile.Name()
	defer os.Remove(tempPath)
	closeWithError := func(writeErr error) error {
		if closeErr := tempFile.Close(); closeErr != nil {
			return errors.Join(writeErr, fmt.Errorf("close temporary config for %q: %w", path, closeErr))
		}
		return writeErr
	}
	if err := prepareConfigTempFileSecurity(tempPath, targetPath, targetExists, preserveExistingMode); err != nil {
		return closeWithError(fmt.Errorf("set security on temporary config for %q: %w", path, err))
	}
	if err := tempFile.Chmod(mode); err != nil {
		return closeWithError(fmt.Errorf("set permissions on temporary config for %q: %w", path, err))
	}
	if _, err := tempFile.Write(data); err != nil {
		return closeWithError(fmt.Errorf("write temporary config for %q: %w", path, err))
	}
	if err := tempFile.Sync(); err != nil {
		return closeWithError(fmt.Errorf("sync temporary config for %q: %w", path, err))
	}
	if err := tempFile.Close(); err != nil {
		return fmt.Errorf("close temporary config for %q: %w", path, err)
	}
	if err := rename(tempPath, targetPath); err != nil {
		return fmt.Errorf("publish config %q: %w", path, err)
	}
	return nil
}
