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

	"github.com/spf13/cobra"
)

const (
	codexTokenTelemetryBlockStart = "# BEGIN OBSTUDIO TOKEN TELEMETRY"
	codexTokenTelemetryBlockEnd   = "# END OBSTUDIO TOKEN TELEMETRY"
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
	found    bool
	endpoint string
	protocol string
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
	ConfigPath  string            `json:"configPath"`
	Endpoint    string            `json:"endpoint"`
	Env         map[string]string `json:"env,omitempty"`
	Settings    map[string]string `json:"settings,omitempty"`
	SectionLine string            `json:"sectionLine,omitempty"`
	UpdatedAt   time.Time         `json:"updatedAt"`
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
		Short: "Manage opt-in Codex and Claude token telemetry without replacing user-owned OTLP routing",
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
		Short: "Opt in to provider token telemetry for Codex or Claude Code",
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
		Short: "Remove only token telemetry configuration owned by Obstudio",
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
	existed := readErr == nil
	if readErr != nil && !errors.Is(readErr, os.ErrNotExist) {
		return tokenTelemetryResult{}, fmt.Errorf("read Codex config %q: %w", path, readErr)
	}
	block, found, err := parseCodexManagedTelemetryBlock(string(original))
	if err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read managed token telemetry in %q: %w", path, err)
	}
	if found && !priorExists {
		result, inspectErr := inspectUnownedMarkedCodexTokenTelemetry(path, endpoint)
		if inspectErr != nil {
			return tokenTelemetryResult{}, inspectErr
		}
		if result.State == "enabled-existing" {
			if err := commitTokenTelemetryOwnershipMutation(statePath, ownership, mutation, writeOwnership); err != nil {
				return tokenTelemetryResult{}, fmt.Errorf("write ownership state: %w", err)
			}
			return result, nil
		}
		return tokenTelemetryResult{}, fmt.Errorf(
			"Codex config %q contains an Obstudio marker without matching ownership state and is not fully configured for Observer (%s: %s); existing configuration was preserved",
			path,
			result.State,
			result.Detail,
		)
	}
	if found && priorExists {
		if mismatch := codexManagedBlockMismatch(block, prior); mismatch != "" {
			return tokenTelemetryResult{}, fmt.Errorf(
				"Obstudio-owned Codex token telemetry in %q was modified (%s); existing configuration was preserved",
				path,
				mismatch,
			)
		}
		if endpoint == prior.Endpoint && codexManagedBlockUnchanged(block, prior) {
			result, inspectErr := inspectOwnedCodexTokenTelemetry(path, statePath, endpoint)
			if inspectErr != nil {
				return tokenTelemetryResult{}, inspectErr
			}
			if err := commitTokenTelemetryOwnershipMutation(statePath, ownership, mutation, writeOwnership); err != nil {
				return tokenTelemetryResult{}, fmt.Errorf("write ownership state: %w", err)
			}
			return result, nil
		}
	}

	configured, configChanged, err := renderCodexTokenTelemetry(path, original, endpoint)
	if err != nil {
		return tokenTelemetryResult{}, err
	}
	managed, managedFound, err := parseCodexManagedTelemetryBlock(string(configured))
	if err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read configured token telemetry in %q: %w", path, err)
	}
	beforeOwnership := cloneTokenTelemetryOwnership(ownership)
	if managedFound {
		ownership.Targets["codex"] = tokenTelemetryTargetOwnership{
			ConfigPath:  path,
			Endpoint:    endpoint,
			Settings:    managed.settings,
			SectionLine: managed.sectionLine,
			UpdatedAt:   time.Now().UTC(),
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
	cleaned, found, removed, preserved, err := removeOwnedCodexTelemetry(string(original), owned)
	if err != nil {
		return tokenTelemetryResult{}, fmt.Errorf("read managed token telemetry in %q: %w", path, err)
	}
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
	if !found {
		return result, nil
	}
	if !ownedPathMatches {
		return inspectUnownedMarkedCodexTokenTelemetry(path, endpoint)
	}
	if mismatch := codexManagedBlockMismatch(block, owned); mismatch != "" {
		result.State = "modified"
		result.Detail = "owned configuration changed and will be preserved on disable: " + mismatch
		return result, nil
	}
	if result.State == "enabled-managed" {
		result.Detail = "Obstudio owns only the unchanged assignments recorded in its ownership state"
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
		result.Detail = "matching exporters are active; marker content has no ownership record and remains user-owned"
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
	configured, changed, err := renderCodexTokenTelemetry(path, data, endpoint)
	if err != nil || !changed {
		return err
	}
	return writeAgentConfig(path, configured)
}

func renderCodexTokenTelemetry(path string, data []byte, endpoint string) ([]byte, bool, error) {
	traceEndpoint, err := tokenTelemetryTraceEndpoint(endpoint)
	if err != nil {
		return nil, false, err
	}
	content, _, err := removeCodexTokenTelemetryBlock(string(data))
	if err != nil {
		return nil, false, fmt.Errorf("read managed token telemetry in %q: %w", path, err)
	}
	lines := strings.Split(content, "\n")
	codeLines, lexErr := codexTOMLCodeLines(lines)
	if lexErr != nil {
		return nil, false, fmt.Errorf("parse Codex config %q: %w", path, lexErr)
	}
	sectionStart, sectionEnd := findCodexOTelSection(codeLines)
	if definition := unsupportedCodexOTelExporterDefinition(codeLines); definition != "" {
		return nil, false, fmt.Errorf("Codex OTel exporter in %q uses unsupported %s syntax; existing value was preserved", path, definition)
	}
	exporters := []codexTelemetryExporter{
		{key: "exporter", label: "log", endpoint: endpoint},
		{key: "trace_exporter", label: "trace", endpoint: traceEndpoint},
	}
	managedAssignments := make([]string, 0, len(exporters))
	for _, exporter := range exporters {
		state, stateErr := codexExporterConfigurationState(codeLines, sectionStart, sectionEnd, exporter)
		if stateErr != nil {
			return nil, false, fmt.Errorf("inspect Codex OTel %s exporter in %q: %w", exporter.label, path, stateErr)
		}
		if state == "matching" {
			continue
		}
		if state == "conflict" {
			return nil, false, fmt.Errorf("Codex OTel %s exporter in %q already has a user-owned value; existing configuration was preserved", exporter.label, path)
		}
		managedAssignments = append(managedAssignments,
			fmt.Sprintf("%s = { otlp-http = { endpoint = %q, protocol = \"binary\" } }", exporter.key, exporter.endpoint))
	}
	if len(managedAssignments) == 0 {
		return data, false, nil
	}

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
			if content != "" && !strings.HasSuffix(content, "\n") {
				content += "\n"
			}
			content += strings.Join(newSection, "\n") + "\n"
			configured := []byte(content)
			return configured, !bytes.Equal(data, configured), nil
		}
	}

	content = strings.Join(lines, "\n")
	configured := []byte(content)
	return configured, !bytes.Equal(data, configured), nil
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
			key, _, ok := tomlAssignment(codeLines[i])
			if ok && (key == "exporter" || key == "trace_exporter") {
				return true, nil
			}
		}
	}
	for _, key := range []string{"exporter", "trace_exporter"} {
		table, tableErr := codexExporterTable(codeLines, key)
		if tableErr != nil || table.found {
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
		case "missing":
			missing++
		default:
			result.State = "conflict"
			result.Detail = exporter.label + " exporter has a user-owned value"
			return result, nil
		}
	}
	if matching == len(exporters) {
		result.State = "enabled-existing"
		if managed {
			result.State = "enabled-managed"
			result.Detail = "Obstudio owns only the assignments inside its managed block"
		} else {
			result.Detail = "matching exporters already existed and remain user-owned"
		}
		return result, nil
	}
	if missing == len(exporters) {
		result.Detail = "no Codex log or trace exporter is configured for Observer"
		return result, nil
	}
	result.State = "partial"
	result.Detail = fmt.Sprintf("%d of %d required exporters target Observer", matching, len(exporters))
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
		if tableExporter.endpoint == exporter.endpoint && strings.EqualFold(tableExporter.protocol, "binary") {
			return "matching", nil
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

	managed := make(map[string]string)
	if priorExists {
		for key, value := range prior.Env {
			if current, ok := env[key].(string); ok && current == value {
				managed[key] = value
			}
		}
	}
	if conflict := claudeOTLPRoutingConflict(config, env, required, endpoint, managed, lookupEnv); conflict != "" {
		return tokenTelemetryResult{}, fmt.Errorf("%s; existing Claude OTLP configuration was preserved", conflict)
	}

	changed := false
	for _, setting := range required {
		if existing, exists := env[setting.key]; exists {
			existingString, ok := existing.(string)
			ownedValue, owned := managed[setting.key]
			if owned && ok && existingString == ownedValue {
				if existingString != setting.value {
					env[setting.key] = setting.value
					managed[setting.key] = setting.value
					changed = true
				}
				continue
			}
			if !ok || existingString != setting.value {
				return tokenTelemetryResult{}, fmt.Errorf(
					"Claude setting %s in %q already has a user-owned value; existing configuration was preserved",
					setting.key,
					path,
				)
			}
			continue
		}
		if inherited, ok := lookupEnvironment(lookupEnv, setting.key); ok {
			if inherited != setting.value {
				return tokenTelemetryResult{}, fmt.Errorf(
					"inherited environment setting %s already has a user-owned value; Claude settings were preserved",
					setting.key,
				)
			}
			delete(managed, setting.key)
			continue
		}
		env[setting.key] = setting.value
		managed[setting.key] = setting.value
		changed = true
	}
	for _, setting := range defaults {
		if existing, exists := env[setting.key]; exists {
			managedValue, owned := managed[setting.key]
			existingString, stringValue := existing.(string)
			if owned && stringValue && existingString == managedValue {
				if existingString != setting.value {
					env[setting.key] = setting.value
					managed[setting.key] = setting.value
					changed = true
				}
			} else {
				delete(managed, setting.key)
			}
			continue
		}
		if _, inherited := lookupEnvironment(lookupEnv, setting.key); inherited {
			delete(managed, setting.key)
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
		if claudeTokenTelemetryConfigured(env, lookupEnv) {
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
				continue
			}
			preserved = append(preserved, key)
		}
		if len(removed) > 0 {
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
			configChanged = true
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
	result.Detail = fmt.Sprintf("removed %d unchanged Obstudio-owned settings", len(removed))
	if len(preserved) > 0 {
		result.State = "disabled-with-user-changes"
		result.Detail += "; preserved modified settings: " + strings.Join(preserved, ", ")
	} else if claudeTokenTelemetryConfigured(env, lookupEnv) {
		result.State = "unmanaged"
		result.Detail += "; user-owned Claude telemetry settings remain configured"
	}
	return result, nil
}

func inspectClaudeTokenTelemetry(
	path, statePath, endpoint string,
	lookupEnv func(string) (string, bool),
) (tokenTelemetryResult, error) {
	result := tokenTelemetryResult{Target: "claude-code", ConfigPath: path, State: "disabled"}
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
			result.Detail = fmt.Sprintf("Obstudio owns %d settings; matching pre-existing settings remain user-owned", len(owned.Env))
		}
		return result, nil
	}
	if missing == len(required) {
		if existed {
			result.Detail = "provider token telemetry is not configured"
		} else {
			result.Detail = "Claude settings do not exist and no matching inherited telemetry is configured"
		}
		return result, nil
	}
	result.State = "partial"
	result.Detail = fmt.Sprintf("%d of %d required settings match Observer", matching, len(required))
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

func claudeOTLPRoutingConflict(
	config map[string]any,
	env map[string]any,
	required []claudeTelemetrySetting,
	endpoint string,
	managed map[string]string,
	lookupEnv func(string) (string, bool),
) string {
	if helper, exists := config["otelHeadersHelper"]; exists {
		value, stringValue := helper.(string)
		if !stringValue || strings.TrimSpace(value) != "" {
			return "Claude setting otelHeadersHelper is already configured; Obstudio will not redirect dynamically authenticated OTLP traffic"
		}
	}
	if value, exists, source := claudeConfiguredOrInheritedValue(env, "OTEL_SDK_DISABLED", lookupEnv); exists && tokenTelemetryBooleanEnabled(value) {
		return fmt.Sprintf("%s OTEL_SDK_DISABLED disables provider token telemetry", source)
	}

	expected := make(map[string]string, len(required))
	for _, setting := range required {
		expected[setting.key] = setting.value
	}
	for key, wanted := range expected {
		if existing, exists := env[key]; exists {
			value, stringValue := existing.(string)
			if ownedValue, owned := managed[key]; owned && stringValue && value == ownedValue {
				continue
			}
			if !stringValue || value != wanted {
				return fmt.Sprintf("Claude setting %s already has another value", key)
			}
			continue
		}
		if inherited, ok := lookupEnvironment(lookupEnv, key); ok && inherited != wanted {
			return fmt.Sprintf("inherited environment setting %s already has another value", key)
		}
	}

	baseEndpoint := strings.TrimSuffix(endpoint, "/v1/logs")
	genericExpected := map[string]struct {
		value     string
		overrides []string
	}{
		"OTEL_EXPORTER_OTLP_ENDPOINT": {
			value: baseEndpoint,
			overrides: []string{
				"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
				"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
				"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
			},
		},
		"OTEL_EXPORTER_OTLP_PROTOCOL": {
			value: "http/protobuf",
			overrides: []string{
				"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
				"OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
				"OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
			},
		},
	}
	for key, generic := range genericExpected {
		value, exists, source := claudeConfiguredOrInheritedValue(env, key, lookupEnv)
		if !exists || strings.TrimSpace(value) == "" {
			continue
		}
		if claudeSpecificSettingsOverrideGeneric(env, expected, managed, generic.overrides, lookupEnv) {
			continue
		}
		if key == "OTEL_EXPORTER_OTLP_ENDPOINT" {
			if strings.TrimRight(value, "/") != strings.TrimRight(generic.value, "/") {
				return fmt.Sprintf("%s %s already routes OTLP to another destination", source, key)
			}
			continue
		}
		if !strings.EqualFold(value, generic.value) {
			return fmt.Sprintf("%s %s already selects another OTLP protocol", source, key)
		}
	}

	sensitiveRoutingKeys := []string{
		"CLAUDE_CODE_CLIENT_CERT",
		"CLAUDE_CODE_CLIENT_KEY",
		"CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
		"OTEL_EXPORTER_OTLP_HEADERS",
		"OTEL_EXPORTER_OTLP_CERTIFICATE",
		"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE",
		"OTEL_EXPORTER_OTLP_CLIENT_KEY",
		"OTEL_EXPORTER_OTLP_LOGS_HEADERS",
		"OTEL_EXPORTER_OTLP_LOGS_CERTIFICATE",
		"OTEL_EXPORTER_OTLP_LOGS_CLIENT_CERTIFICATE",
		"OTEL_EXPORTER_OTLP_LOGS_CLIENT_KEY",
		"OTEL_EXPORTER_OTLP_TRACES_HEADERS",
		"OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE",
		"OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE",
		"OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY",
		"OTEL_EXPORTER_OTLP_METRICS_HEADERS",
		"OTEL_EXPORTER_OTLP_METRICS_CERTIFICATE",
		"OTEL_EXPORTER_OTLP_METRICS_CLIENT_CERTIFICATE",
		"OTEL_EXPORTER_OTLP_METRICS_CLIENT_KEY",
	}
	for _, key := range sensitiveRoutingKeys {
		if value, exists, source := claudeConfiguredOrInheritedValue(env, key, lookupEnv); exists && strings.TrimSpace(value) != "" {
			return fmt.Sprintf("%s %s is already configured; Obstudio will not redirect authenticated OTLP traffic", source, key)
		}
	}
	return ""
}

func claudeSpecificSettingsOverrideGeneric(
	env map[string]any,
	expected, managed map[string]string,
	keys []string,
	lookupEnv func(string) (string, bool),
) bool {
	for _, key := range keys {
		value, exists, _ := claudeConfiguredOrInheritedValue(env, key, lookupEnv)
		if !exists {
			return false
		}
		if ownedValue, owned := managed[key]; owned && value == ownedValue {
			continue
		}
		if value != expected[key] {
			return false
		}
	}
	return true
}

func tokenTelemetryBooleanEnabled(value string) bool {
	trimmed := strings.TrimSpace(value)
	return trimmed == "1" || strings.EqualFold(trimmed, "true")
}

func claudeTokenTelemetryConfigured(
	env map[string]any,
	lookupEnv func(string) (string, bool),
) bool {
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
		if assignment && (key == "exporter" || key == "trace_exporter") {
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
	return ""
}

func codexManagedBlockUnchanged(block codexManagedTelemetryBlock, owned tokenTelemetryTargetOwnership) bool {
	return codexManagedBlockMismatch(block, owned) == "" && len(block.settings) == len(owned.Settings)
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
			for _, key := range []string{"exporter", "trace_exporter"} {
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
			for _, exporterKey := range []string{"exporter", "trace_exporter"} {
				prefix := "otel." + exporterKey
				if key == "otel" || key == prefix || strings.HasPrefix(key, prefix+".") ||
					(strings.Contains(key, "otel") && strings.Contains(key, exporterKey)) {
					return "root dotted-key"
				}
			}
		}
		if section == "[otel]" {
			if normalizedKey == "exporter" || normalizedKey == "trace_exporter" {
				if normalizedKey != key {
					return "quoted exporter key"
				}
				continue
			}
			if strings.HasPrefix(key, "exporter.") || strings.HasPrefix(key, "trace_exporter.") ||
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
	result := codexTelemetryTableExporter{}
	rootSection := "[otel." + exporterKey + "]"
	otlpSection := "[otel." + exporterKey + ".otlp-http]"
	headersSection := "[otel." + exporterKey + ".otlp-http.headers]"
	section := ""
	sectionCounts := make(map[string]int)
	endpointCount := 0
	protocolCount := 0
	for _, line := range lines {
		structural := tomlStructuralLine(line)
		if isTOMLTableHeader(structural) {
			section = structural
			if structural == rootSection || structural == otlpSection || structural == headersSection {
				result.found = true
				sectionCounts[structural]++
				if sectionCounts[structural] > 1 {
					return result, fmt.Errorf("%s is defined more than once", structural)
				}
			}
			continue
		}
		if section != otlpSection {
			continue
		}
		key, value, ok := tomlAssignment(structural)
		if !ok {
			continue
		}
		switch key {
		case "endpoint":
			endpointCount++
			result.endpoint, ok = tomlStringValue(value)
		case "protocol":
			protocolCount++
			result.protocol, ok = tomlStringValue(value)
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
	if endpointCount != 1 || protocolCount != 1 {
		return result, errors.New("otlp-http must define exactly one endpoint and protocol")
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

func codexExporterTargetsEndpoint(value, endpoint string) bool {
	withoutComment := strings.TrimSpace(strings.SplitN(value, "#", 2)[0])
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
	quote := byte(0)
	escaped := false
	for index := 0; index < len(value); index++ {
		char := value[index]
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
		if quote == 0 && strings.HasPrefix(value[index:], key) && tomlInlineKeyBoundary(value, index, len(key)) {
			cursor := index + len(key)
			for cursor < len(value) && (value[cursor] == ' ' || value[cursor] == '\t') {
				cursor++
			}
			if cursor < len(value) && value[cursor] == '=' {
				count++
			}
		}
	}
	return count
}

func tomlInlineAssignmentValue(value, key string) (string, bool) {
	for index := 0; index < len(value); index++ {
		if !strings.HasPrefix(value[index:], key) || !tomlInlineKeyBoundary(value, index, len(key)) {
			continue
		}
		cursor := index + len(key)
		for cursor < len(value) && (value[cursor] == ' ' || value[cursor] == '\t') {
			cursor++
		}
		if cursor >= len(value) || value[cursor] != '=' {
			continue
		}
		cursor++
		for cursor < len(value) && (value[cursor] == ' ' || value[cursor] == '\t') {
			cursor++
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
