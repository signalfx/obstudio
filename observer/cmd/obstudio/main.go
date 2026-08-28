// Package main implements the Observability Studio CLI entry point.
package main

import (
	"bufio"
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/audit"
	"github.com/signalfx/obstudio/observer/internal/dashboards"
	"github.com/signalfx/obstudio/observer/internal/mcp"
	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
	"github.com/signalfx/obstudio/observer/internal/web"
)

var version = "dev"

const (
	observerCloudBrowserSigningKeyEnv      = "OBSTUDIO_CLOUD_BROWSER_SIGNING_KEY"
	observerCloudBrowserSigningKeyFileName = "cloud-browser-signing-key-v1"
	observerCloudBrowserLaunchTokenEnv     = "OBSTUDIO_CLOUD_BROWSER_LAUNCH_TOKEN"
)

var splunkEnvFilePrecedenceKeys = []string{
	"OBSTUDIO_SPLUNK_REALM",
	"SPLUNK_REALM",
	"SPLUNK_ACCESS_TOKEN",
	"OBSTUDIO_SPLUNK_METRICS_EXPORT",
	"SPLUNK_METRICS_EXPORT",
	"OBSTUDIO_SPLUNK_TRACES_EXPORT",
	"SPLUNK_TRACES_EXPORT",
}

var splunkEnvFileLegacyEndpointKeys = []string{
	"OBSTUDIO_SPLUNK_METRICS_ENDPOINT",
	"OBSTUDIO_SPLUNK_TRACES_ENDPOINT",
	"OBSTUDIO_SPLUNK_METRICS_TIMEOUT",
	"OBSTUDIO_SPLUNK_TRACES_TIMEOUT",
}

var envFileShellPrecedence = struct {
	sync.Mutex
	keys map[string]struct{}
}{
	keys: map[string]struct{}{},
}

type runConfig struct {
	host             string
	observerHTTPPort string
	otlpGRPCHost     string
	otlpGRPCPort     string
	otlpHTTPPort     string
	envFile          string
}

func main() {
	var config runConfig
	root := newRootCmd(&config)

	if err := root.Execute(); err != nil {
		os.Exit(1)
	}
}

func newRootCmd(config *runConfig) *cobra.Command {
	root := &cobra.Command{
		Use:     "obstudio",
		Short:   "Observability Studio -- local OTel collector, MCP server, and skill installer",
		Version: version,
		RunE: func(_ *cobra.Command, _ []string) error {
			if err := loadConfiguredEnvFile(config.envFile); err != nil {
				return err
			}
			resolved := resolveRunConfig(*config)
			if err := validateRunConfig(resolved); err != nil {
				return err
			}
			run(resolved)
			return nil
		},
		SilenceUsage: true,
	}

	root.Flags().StringVar(&config.host, "host", "", "Bind address for the Observer UI, MCP HTTP endpoint, and OTLP/HTTP; also the OTLP/gRPC default")
	root.Flags().StringVar(&config.observerHTTPPort, "observer-http-port", "", "Observer web UI, REST API, and MCP HTTP port")
	root.Flags().StringVar(&config.envFile, "env-file", "", "Load KEY=VALUE settings from an env file before startup")

	root.AddCommand(newInstallCmd())
	return root
}

func run(config runConfig) {
	if err := ensureObserverControlToken(); err != nil {
		log.Fatalf("configure Observer control token: %v", err)
	}
	if err := ensureObserverCloudBrowserSigningKey(); err != nil {
		log.Fatalf("configure standalone browser cloud control: %v", err)
	}
	if err := ensureObserverCloudBrowserLaunchToken(); err != nil {
		log.Fatalf("configure standalone browser cloud launch: %v", err)
	}

	s := store.New()
	v := validator.NewStore()
	validatorManager := validator.NewManager(v, s)
	s.SetInvalidateCallback(validatorManager.Reset)
	s.SetChangeCallback(validatorManager.MarkTelemetryChanged)
	startedAt := time.Now().UTC()

	host := config.host
	port := config.observerHTTPPort
	otlpHTTPPort := config.otlpHTTPPort
	otlpGRPCHost := config.otlpGRPCHost
	otlpGRPCPort := config.otlpGRPCPort

	mainAddr := net.JoinHostPort(host, port)
	otlpHTTPAddr := net.JoinHostPort(host, otlpHTTPPort)
	otlpGRPCAddr := net.JoinHostPort(otlpGRPCHost, otlpGRPCPort)

	s.SetEndpoints(store.Endpoints{
		OTLPHTTP: "http://" + otlpHTTPAddr,
		OTLPgRPC: otlpGRPCAddr,
		REST:     "http://" + mainAddr,
	})

	ctx := context.Background()
	if err := validatorManager.Start(ctx); err != nil {
		log.Printf("validator startup failed: %v", err)
	}

	splunkConfig, err := splunkMetricsExporterConfigFromEnv()
	if err != nil {
		log.Fatalf("configure Splunk metrics export: %v", err)
	}
	splunkExportController, err := otlp.NewSplunkMetricsExportController(splunkConfig)
	if err != nil {
		log.Fatalf("configure Splunk metrics export: %v", err)
	}
	if splunkStatus := splunkExportController.Status(); splunkStatus.Configured {
		log.Printf(
			"[splunk-export] metrics forwarding enabled: endpoints=%s",
			strings.Join(splunkStatus.Endpoints, ","),
		)
	}

	splunkTracesConfig, err := splunkTracesExporterConfigFromEnv()
	if err != nil {
		log.Fatalf("configure Splunk traces export: %v", err)
	}
	splunkTracesController, err := otlp.NewSplunkTracesExportController(splunkTracesConfig)
	if err != nil {
		log.Fatalf("configure Splunk traces export: %v", err)
	}
	if tracesStatus := splunkTracesController.Status(); tracesStatus.Configured {
		log.Printf(
			"[splunk-traces] traces forwarding enabled: endpoints=%s",
			strings.Join(tracesStatus.Endpoints, ","),
		)
	}

	rcv, err := otlp.StartReceiver(ctx, s, otlpGRPCAddr, otlpHTTPAddr,
		otlp.WithMetricsExporter(splunkExportController),
		otlp.WithTracesExporter(splunkTracesController),
	)
	if err != nil {
		log.Fatalf("failed to start OTLP receiver: %v", err)
	}

	mux := http.NewServeMux()
	api.Register(mux, s, v, validatorManager, api.ServerInfo{
		Kind:       "obstudio",
		APIVersion: "v1",
		Version:    version,
		Owner:      envOr("OBSTUDIO_OWNER", "cli"),
		Mode:       envOr("OBSTUDIO_MODE", "standalone"),
		StartedAt:  startedAt,
		Exporters:  exporterInfo(splunkExportController, splunkTracesController),
	}, dashboards.Config{
		WorkspaceRoot: envOr("OBSTUDIO_WORKSPACE_ROOT", ""),
		SpecPath:      envOr("OBSTUDIO_DASHBOARDS_PREVIEW", ""),
	}, audit.Config{
		WorkspaceRoot: envOr("OBSTUDIO_WORKSPACE_ROOT", ""),
		ReportPath:    envOr("OBSTUDIO_AUDIT_REPORT", ""),
	}, splunkExportController, splunkTracesController,
		newSplunkExportConfigurationRefresher(config.envFile, splunkExportController, splunkTracesController))
	mcp.Register(mux, s, v, validatorManager, splunkExportController, splunkTracesController)
	webCleanup := web.Register(mux, s, v)

	srv := &http.Server{Addr: mainAddr, Handler: mux}
	mainListener, err := net.Listen("tcp", mainAddr)
	if err != nil {
		log.Fatalf("failed to start HTTP server: %v", err)
	}

	observerState := buildSharedObserverState(host, port)
	observerStatePath := sharedObserverStatePath()
	if err := writeSharedObserverState(observerStatePath, observerState); err != nil {
		log.Printf("failed to write shared observer state: %v", err)
	} else {
		defer func() {
			if err := clearSharedObserverStateIfOwned(observerStatePath, observerState); err != nil {
				log.Printf("failed to clear shared observer state: %v", err)
			}
		}()
	}

	go func() {
		if err := srv.Serve(mainListener); err != nil && err != http.ErrServerClosed {
			log.Fatalf("HTTP server failed: %v", err)
		}
	}()

	fmt.Fprint(os.Stderr, renderStartupBanner(mainAddr, otlpHTTPAddr, otlpGRPCAddr))

	go mcp.RunStdio(s, os.Stdin, os.Stdout, v, validatorManager, splunkExportController, splunkTracesController)

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	fmt.Fprintf(os.Stderr, "\nShutting down...\n")

	shutCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	srv.Shutdown(shutCtx)
	webCleanup()
	validatorManager.Shutdown(shutCtx)
	rcv.Shutdown(ctx)
	splunkExportController.Shutdown(shutCtx)
	splunkTracesController.Shutdown(shutCtx)
}

func ensureObserverControlToken() error {
	if strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")) != "" {
		return nil
	}

	token := make([]byte, 32)
	if _, err := rand.Read(token); err != nil {
		return fmt.Errorf("generate control token: %w", err)
	}
	if err := os.Setenv("OBSTUDIO_CONTROL_TOKEN", base64.RawURLEncoding.EncodeToString(token)); err != nil {
		return fmt.Errorf("store generated control token: %w", err)
	}
	return nil
}

func ensureObserverCloudBrowserSigningKey() error {
	return ensureObserverCloudBrowserSigningKeyAt(filepath.Join(
		userHome(),
		sharedObserverStateDirName,
		observerCloudBrowserSigningKeyFileName,
	))
}

func ensureObserverCloudBrowserSigningKeyAt(keyPath string) error {
	if configured := strings.TrimSpace(os.Getenv(observerCloudBrowserSigningKeyEnv)); configured != "" {
		if !isObserverCloudBrowserSigningKey(configured) {
			return errors.New("configured browser signing key must be 32 bytes of base64url")
		}
		return nil
	}

	replaceInvalid := false
	if persisted, err := os.ReadFile(keyPath); err == nil {
		key := strings.TrimSpace(string(persisted))
		if isObserverCloudBrowserSigningKey(key) {
			return os.Setenv(observerCloudBrowserSigningKeyEnv, key)
		}
		log.Printf("ignoring invalid persisted browser signing key at %s", keyPath)
		replaceInvalid = true
	} else if !errors.Is(err, os.ErrNotExist) {
		log.Printf("could not read persisted browser signing key at %s: %v", keyPath, err)
	}

	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return fmt.Errorf("generate browser signing key: %w", err)
	}
	encoded := base64.RawURLEncoding.EncodeToString(key)
	if replaceInvalid {
		if err := os.Remove(keyPath); err != nil && !errors.Is(err, os.ErrNotExist) {
			log.Printf("could not replace invalid browser signing key at %s: %v", keyPath, err)
		}
	}
	if err := persistObserverCloudBrowserSigningKey(keyPath, encoded); err != nil {
		if errors.Is(err, os.ErrExist) {
			persisted, readErr := os.ReadFile(keyPath)
			winner := strings.TrimSpace(string(persisted))
			if readErr == nil && isObserverCloudBrowserSigningKey(winner) {
				encoded = winner
			} else if readErr != nil {
				log.Printf("could not read concurrently persisted browser signing key at %s: %v", keyPath, readErr)
			} else {
				log.Printf("ignoring invalid concurrently persisted browser signing key at %s", keyPath)
			}
		} else {
			log.Printf("could not persist browser signing key at %s: %v", keyPath, err)
		}
	}
	if err := os.Setenv(observerCloudBrowserSigningKeyEnv, encoded); err != nil {
		return fmt.Errorf("store generated browser signing key: %w", err)
	}
	return nil
}

func isObserverCloudBrowserSigningKey(key string) bool {
	decoded, err := base64.RawURLEncoding.DecodeString(key)
	return err == nil && len(decoded) == 32 && base64.RawURLEncoding.EncodeToString(decoded) == key
}

func ensureObserverCloudBrowserLaunchToken() error {
	token := make([]byte, 32)
	if _, err := rand.Read(token); err != nil {
		return fmt.Errorf("generate browser launch token: %w", err)
	}
	if err := os.Setenv(observerCloudBrowserLaunchTokenEnv, base64.RawURLEncoding.EncodeToString(token)); err != nil {
		return fmt.Errorf("store generated browser launch token: %w", err)
	}
	return nil
}

func persistObserverCloudBrowserSigningKey(keyPath string, key string) error {
	if err := os.MkdirAll(filepath.Dir(keyPath), 0o700); err != nil {
		return err
	}
	tempFile, err := os.CreateTemp(filepath.Dir(keyPath), ".browser-signing-key-*")
	if err != nil {
		return err
	}
	tempPath := tempFile.Name()
	defer os.Remove(tempPath)
	if err := tempFile.Chmod(0o600); err != nil {
		tempFile.Close()
		return err
	}
	if _, err := tempFile.WriteString(key + "\n"); err != nil {
		tempFile.Close()
		return err
	}
	if err := tempFile.Close(); err != nil {
		return err
	}
	return os.Link(tempPath, keyPath)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envBool(key string) bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv(key))) {
	case "1", "true", "yes", "y", "on":
		return true
	default:
		return false
	}
}

func defaultEnvFilePath() string {
	return userHome() + "/.obstudio/env"
}

func configuredEnvFilePath(flagValue string) (string, bool) {
	if strings.TrimSpace(flagValue) != "" {
		return strings.TrimSpace(flagValue), true
	}
	if value := strings.TrimSpace(os.Getenv("OBSTUDIO_ENV_FILE")); value != "" {
		return value, true
	}
	return defaultEnvFilePath(), false
}

func loadConfiguredEnvFile(flagValue string) error {
	path, explicit := configuredEnvFilePath(flagValue)
	if strings.TrimSpace(path) == "" {
		return nil
	}
	rememberEnvFileShellPrecedence()
	if _, err := os.Stat(path); err != nil {
		if os.IsNotExist(err) && !explicit {
			return nil
		}
		return fmt.Errorf("load env file %q: %w", path, err)
	}
	if err := loadEnvFile(path); err != nil {
		return err
	}
	log.Printf("loaded env file: %s", path)
	return nil
}

func loadEnvFile(path string) error {
	file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open env file %q: %w", path, err)
	}
	defer file.Close()

	preExistingEnv := existingEnvKeys()
	seenFileKeys := map[string]struct{}{}
	scanner := bufio.NewScanner(file)
	lineNo := 0
	for scanner.Scan() {
		lineNo++
		key, value, ok, err := parseEnvLine(scanner.Text())
		if err != nil {
			return fmt.Errorf("parse env file %q line %d: %w", path, lineNo, err)
		}
		if !ok {
			continue
		}
		if _, seen := seenFileKeys[key]; seen {
			continue
		}
		seenFileKeys[key] = struct{}{}
		if _, preExisting := preExistingEnv[key]; preExisting {
			markEnvFileShellPrecedence(key)
			continue
		}
		if err := os.Setenv(key, value); err != nil {
			return fmt.Errorf("set env %q from %q line %d: %w", key, path, lineNo, err)
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("read env file %q: %w", path, err)
	}
	return nil
}

func existingEnvKeys() map[string]struct{} {
	keys := map[string]struct{}{}
	for _, entry := range os.Environ() {
		key, _, ok := strings.Cut(entry, "=")
		if ok {
			keys[key] = struct{}{}
		}
	}
	return keys
}

func rememberEnvFileShellPrecedence() {
	for _, key := range splunkEnvFilePrecedenceKeys {
		if _, ok := os.LookupEnv(key); ok {
			markEnvFileShellPrecedence(key)
		}
	}
}

func markEnvFileShellPrecedence(key string) {
	envFileShellPrecedence.Lock()
	defer envFileShellPrecedence.Unlock()
	envFileShellPrecedence.keys[key] = struct{}{}
}

func parseEnvLine(line string) (string, string, bool, error) {
	trimmed := strings.TrimSpace(line)
	if trimmed == "" || strings.HasPrefix(trimmed, "#") {
		return "", "", false, nil
	}
	if strings.HasPrefix(trimmed, "export ") {
		trimmed = strings.TrimSpace(strings.TrimPrefix(trimmed, "export "))
	}
	key, value, ok := strings.Cut(trimmed, "=")
	if !ok {
		return "", "", false, fmt.Errorf("expected KEY=VALUE")
	}
	key = strings.TrimSpace(key)
	if key == "" {
		return "", "", false, fmt.Errorf("missing key")
	}
	for _, r := range key {
		if (r >= 'A' && r <= 'Z') || (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '_' {
			continue
		}
		return "", "", false, fmt.Errorf("invalid key %q", key)
	}
	value = strings.TrimSpace(value)
	if len(value) >= 2 {
		quote := value[0]
		// Strip matching outer quotes. Escape sequences are not processed —
		// values are taken verbatim (consistent with Docker .env semantics).
		if (quote == '"' || quote == '\'') && value[len(value)-1] == quote {
			value = value[1 : len(value)-1]
		}
	}
	return key, value, true, nil
}

func resolveRunConfig(config runConfig) runConfig {
	host := valueOrEnv(config.host, "HOST", "127.0.0.1")
	return runConfig{
		host:             host,
		observerHTTPPort: valueOrEnv(config.observerHTTPPort, "PORT", "3000"),
		otlpHTTPPort:     valueOrEnv(config.otlpHTTPPort, "OTLP_HTTP_PORT", envOr("OTLP_PORT", "4318")),
		otlpGRPCHost:     valueOrEnv(config.otlpGRPCHost, "OTLP_GRPC_HOST", host),
		otlpGRPCPort:     valueOrEnv(config.otlpGRPCPort, "OTLP_GRPC_PORT", "4317"),
		envFile:          config.envFile,
	}
}

type splunkMetricsExportConfigurator interface {
	Config() otlp.SplunkMetricsExporterConfig
	Configure(otlp.SplunkMetricsExporterConfig) error
}

type splunkTracesExportConfigurator interface {
	Config() otlp.SplunkTracesExporterConfig
	Configure(otlp.SplunkTracesExporterConfig) error
}

func newSplunkExportConfigurationRefresher(
	flagValue string,
	metrics splunkMetricsExportConfigurator,
	traces splunkTracesExportConfigurator,
) api.SplunkExportConfigurationRefresher {
	return func() (bool, error) {
		path, explicit := configuredEnvFilePath(flagValue)
		values, err := readEnvFile(path)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) && !explicit {
				return false, nil
			}
			return false, err
		}

		envFileManagesCloud := firstNonEmpty(
			values["OBSTUDIO_SPLUNK_REALM"],
			values["SPLUNK_REALM"],
			values["SPLUNK_ACCESS_TOKEN"],
			values["OBSTUDIO_SPLUNK_METRICS_ENDPOINT"],
			values["OBSTUDIO_SPLUNK_TRACES_ENDPOINT"],
		) != "" ||
			hasEnvMapBool(values, "OBSTUDIO_SPLUNK_METRICS_EXPORT", "SPLUNK_METRICS_EXPORT") ||
			hasEnvMapBool(values, "OBSTUDIO_SPLUNK_TRACES_EXPORT", "SPLUNK_TRACES_EXPORT")
		if hasNonEmptyEnvKey(splunkEnvFileLegacyEndpointKeys...) {
			return envFileManagesCloud, nil
		}
		if hasEnvMapKey(values, splunkEnvFileLegacyEndpointKeys...) {
			return envFileManagesCloud, nil
		}
		values = applyEnvFileShellPrecedence(values)

		realm := firstNonEmpty(values["OBSTUDIO_SPLUNK_REALM"], values["SPLUNK_REALM"])
		accessToken := strings.TrimSpace(values["SPLUNK_ACCESS_TOKEN"])
		hasExportFlag := hasEnvMapBool(values, "OBSTUDIO_SPLUNK_METRICS_EXPORT", "SPLUNK_METRICS_EXPORT") ||
			hasEnvMapBool(values, "OBSTUDIO_SPLUNK_TRACES_EXPORT", "SPLUNK_TRACES_EXPORT")
		if realm == "" && accessToken == "" && !hasExportFlag {
			return false, nil
		}
		if accessToken == "" {
			return false, fmt.Errorf("env file must set SPLUNK_ACCESS_TOKEN")
		}
		if realm == "" {
			return false, fmt.Errorf("env file must set SPLUNK_REALM")
		}

		metricsEnabled := envMapBool(values, "OBSTUDIO_SPLUNK_METRICS_EXPORT", "SPLUNK_METRICS_EXPORT")
		tracesEnabled := envMapBool(values, "OBSTUDIO_SPLUNK_TRACES_EXPORT", "SPLUNK_TRACES_EXPORT")
		metricsConfig := otlp.SplunkMetricsExporterConfig{
			Enabled:     metricsEnabled,
			Realm:       realm,
			AccessToken: accessToken,
		}
		tracesConfig := otlp.SplunkTracesExporterConfig{
			Enabled:     tracesEnabled,
			Realm:       realm,
			AccessToken: accessToken,
		}

		previousMetrics := metrics.Config()
		previousTraces := traces.Config()
		metricsConfig.Timeout = previousMetrics.Timeout
		tracesConfig.Timeout = previousTraces.Timeout
		metricsChanged := metricsConfig != previousMetrics
		tracesChanged := tracesConfig != previousTraces
		if !metricsChanged && !tracesChanged {
			return true, nil
		}
		if metricsChanged {
			if err := metrics.Configure(metricsConfig); err != nil {
				return false, err
			}
		}
		if tracesChanged {
			if err := traces.Configure(tracesConfig); err != nil {
				if metricsChanged {
					if rollbackErr := metrics.Configure(previousMetrics); rollbackErr != nil {
						return false, fmt.Errorf("configure traces: %w; rollback metrics: %v", err, rollbackErr)
					}
				}
				return false, err
			}
		}
		return true, nil
	}
}

func applyEnvFileShellPrecedence(values map[string]string) map[string]string {
	envFileShellPrecedence.Lock()
	defer envFileShellPrecedence.Unlock()
	if len(envFileShellPrecedence.keys) == 0 {
		return values
	}
	effective := make(map[string]string, len(values)+len(envFileShellPrecedence.keys))
	for key, value := range values {
		effective[key] = value
	}
	for key := range envFileShellPrecedence.keys {
		value, ok := os.LookupEnv(key)
		if !ok || strings.TrimSpace(value) == "" {
			delete(effective, key)
		} else {
			effective[key] = value
		}
	}
	return effective
}

func readEnvFile(path string) (map[string]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open env file %q: %w", path, err)
	}
	defer file.Close()

	values := map[string]string{}
	scanner := bufio.NewScanner(file)
	lineNo := 0
	for scanner.Scan() {
		lineNo++
		key, value, ok, err := parseEnvLine(scanner.Text())
		if err != nil {
			return nil, fmt.Errorf("parse env file %q line %d: %w", path, lineNo, err)
		}
		if ok {
			if _, exists := values[key]; exists {
				continue
			}
			values[key] = value
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read env file %q: %w", path, err)
	}
	return values, nil
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			return trimmed
		}
	}
	return ""
}

func envMapBool(values map[string]string, keys ...string) bool {
	for _, key := range keys {
		switch strings.ToLower(strings.TrimSpace(values[key])) {
		case "1", "true", "yes", "y", "on":
			return true
		}
	}
	return false
}

func hasEnvMapBool(values map[string]string, keys ...string) bool {
	return envMapBool(values, keys...)
}

func hasEnvMapKey(values map[string]string, keys ...string) bool {
	for _, key := range keys {
		if _, ok := values[key]; ok {
			return true
		}
	}
	return false
}

func hasNonEmptyEnvKey(keys ...string) bool {
	for _, key := range keys {
		if strings.TrimSpace(os.Getenv(key)) != "" {
			return true
		}
	}
	return false
}

func splunkMetricsExporterConfigFromEnv() (otlp.SplunkMetricsExporterConfig, error) {
	timeout, err := durationEnv("OBSTUDIO_SPLUNK_METRICS_TIMEOUT")
	if err != nil {
		return otlp.SplunkMetricsExporterConfig{}, err
	}
	return otlp.SplunkMetricsExporterConfig{
		Enabled:     envBool("OBSTUDIO_SPLUNK_METRICS_EXPORT") || envBool("SPLUNK_METRICS_EXPORT"),
		Realm:       envOr("OBSTUDIO_SPLUNK_REALM", envOr("SPLUNK_REALM", "")),
		Endpoint:    envOr("OBSTUDIO_SPLUNK_METRICS_ENDPOINT", ""),
		AccessToken: envOr("SPLUNK_ACCESS_TOKEN", ""),
		Timeout:     timeout,
	}, nil
}

func splunkTracesExporterConfigFromEnv() (otlp.SplunkTracesExporterConfig, error) {
	timeout, err := durationEnv("OBSTUDIO_SPLUNK_TRACES_TIMEOUT")
	if err != nil {
		return otlp.SplunkTracesExporterConfig{}, err
	}
	return otlp.SplunkTracesExporterConfig{
		Enabled:     envBool("OBSTUDIO_SPLUNK_TRACES_EXPORT") || envBool("SPLUNK_TRACES_EXPORT"),
		Realm:       envOr("OBSTUDIO_SPLUNK_REALM", envOr("SPLUNK_REALM", "")),
		Endpoint:    envOr("OBSTUDIO_SPLUNK_TRACES_ENDPOINT", ""),
		AccessToken: envOr("SPLUNK_ACCESS_TOKEN", ""),
		Timeout:     timeout,
	}, nil
}

func durationEnv(key string) (time.Duration, error) {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return 0, nil
	}
	duration, err := time.ParseDuration(value)
	if err == nil {
		return duration, nil
	}
	seconds, parseErr := strconv.Atoi(value)
	if parseErr != nil {
		return 0, fmt.Errorf("%s must be a duration like 5s or a whole number of seconds", key)
	}
	return time.Duration(seconds) * time.Second, nil
}

func exporterInfo(metricsController *otlp.SplunkMetricsExportController, tracesController *otlp.SplunkTracesExportController) map[string]api.ExporterInfo {
	info := map[string]api.ExporterInfo{}
	if metricsController != nil {
		status := metricsController.Status()
		if status.Configured && len(status.Endpoints) > 0 {
			info["splunkMetrics"] = api.ExporterInfo{
				Enabled:  status.Enabled,
				Endpoint: status.Endpoints[0],
			}
		}
	}
	if tracesController != nil {
		status := tracesController.Status()
		if status.Configured && len(status.Endpoints) > 0 {
			info["splunkTraces"] = api.ExporterInfo{
				Enabled:  status.Enabled,
				Endpoint: status.Endpoints[0],
			}
		}
	}
	if len(info) == 0 {
		return nil
	}
	return info
}

func valueOrEnv(value, envKey, fallback string) string {
	if value != "" {
		return value
	}
	return envOr(envKey, fallback)
}

func validateRunConfig(config runConfig) error {
	ports := []struct {
		flagName string
		label    string
		value    string
	}{
		{flagName: "--observer-http-port", label: "Observer UI, REST API, and MCP HTTP", value: config.observerHTTPPort},
		{flagName: "--otlp-http-port", label: "OTLP/HTTP", value: config.otlpHTTPPort},
		{flagName: "--otlp-grpc-port", label: "OTLP/gRPC", value: config.otlpGRPCPort},
	}

	seen := map[int]string{}
	seenFlags := map[int]string{}
	for _, port := range ports {
		parsed, err := strconv.Atoi(port.value)
		if err != nil || parsed < 1 || parsed > 65_535 {
			return fmt.Errorf("%s must be a valid TCP port between 1 and 65535, got %q", port.flagName, port.value)
		}
		if otherLabel, ok := seen[parsed]; ok {
			return fmt.Errorf(
				"%s cannot use port %d; %s already uses that port (%s)",
				port.flagName,
				parsed,
				otherLabel,
				seenFlags[parsed],
			)
		}
		seen[parsed] = port.label
		seenFlags[parsed] = port.flagName
	}

	return nil
}

func buildSharedObserverState(host, port string) sharedObserverState {
	connectHost := host
	switch connectHost {
	case "", "0.0.0.0", "::", "[::]":
		connectHost = "127.0.0.1"
	}

	baseURL := fmt.Sprintf("http://%s", net.JoinHostPort(connectHost, port))
	return sharedObserverState{
		BaseURL:      baseURL,
		ControlToken: strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")),
		HealthURL:    baseURL + "/api/health",
		MCPURL:       baseURL + "/mcp",
		PID:          os.Getpid(),
		UpdatedAt:    time.Now().UTC(),
	}
}

func renderStartupBanner(mainAddr, otlpHTTPAddr, otlpGRPCAddr string) string {
	return fmt.Sprintf(
		"\nObservability Studio (collector)\n"+
			"  Telemetry Explorer:  %s\n"+
			"  OTLP/HTTP receiver:  http://%s\n"+
			"  OTLP/gRPC receiver:  %s\n"+
			"  MCP endpoint:        http://%s/mcp\n"+
			"  Agent setup:         obstudio install --target=<agent>[,<agent>...]\n\n",
		observerBrowserURL(mainAddr),
		otlpHTTPAddr,
		otlpGRPCAddr,
		mainAddr,
	)
}

func observerBrowserURL(mainAddr string) string {
	host, port, err := net.SplitHostPort(mainAddr)
	if err != nil {
		return "http://" + mainAddr
	}
	switch host {
	case "", "0.0.0.0", "::", "[::]":
		host = "127.0.0.1"
	}
	if !strings.EqualFold(host, "localhost") {
		ip := net.ParseIP(strings.Trim(host, "[]"))
		if ip == nil || !ip.IsLoopback() {
			return "http://" + mainAddr
		}
	}
	baseURL := "http://" + net.JoinHostPort(host, port)
	launchToken := strings.TrimSpace(os.Getenv(observerCloudBrowserLaunchTokenEnv))
	if launchToken == "" {
		return baseURL
	}
	return baseURL + "/#obstudio-cloud-control=" + launchToken
}
