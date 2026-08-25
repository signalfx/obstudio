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
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/audit"
	"github.com/signalfx/obstudio/observer/internal/dashboards"
	"github.com/signalfx/obstudio/observer/internal/freeaccount"
	"github.com/signalfx/obstudio/observer/internal/mcp"
	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
	"github.com/signalfx/obstudio/observer/internal/web"
)

var version = "dev"
var listenObserverHTTP = net.Listen

const (
	observerCloudBrowserLaunchTokenEnv     = "OBSTUDIO_CLOUD_BROWSER_LAUNCH_TOKEN"
	observerHealthProofSecretEnv           = "OBSTUDIO_HEALTH_PROOF_SECRET"
	observerHideCloudBrowserLaunchTokenEnv = "OBSTUDIO_HIDE_CLOUD_BROWSER_LAUNCH_TOKEN"
	observerPublicMCPURLEnv                = "OBSTUDIO_PUBLIC_MCP_URL"
	observerPublicMCPURLMaxLength          = 2048
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
	publicMCPURL     string
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
			return run(resolved)
		},
		SilenceUsage: true,
	}

	root.Flags().StringVar(&config.host, "host", "", "Bind address for the Observer UI, MCP HTTP endpoint, and OTLP/HTTP; also the OTLP/gRPC default")
	root.Flags().StringVar(&config.observerHTTPPort, "observer-http-port", "", "Observer web UI, REST API, and MCP HTTP port")
	root.Flags().StringVar(&config.envFile, "env-file", "", "Load KEY=VALUE settings from an env file before startup")

	root.AddCommand(newInstallCmd())
	root.AddCommand(newLifecycleCommands()...)
	root.AddCommand(newTokenTelemetryCommand())
	return root
}

func run(config runConfig) error {
	managedLaunchAuthorized := consumeManagedLaunchCapability()
	configureManagedLogging()
	if err := ensureObserverControlToken(); err != nil {
		log.Fatalf("configure Observer control token: %v", err)
	}
	if err := ensureObserverHealthProofSecret(); err != nil {
		log.Fatalf("configure Observer health proof secret: %v", err)
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
	publicMCPURL := ""
	if strings.TrimSpace(config.publicMCPURL) != "" {
		var err error
		publicMCPURL, err = normalizePublicMCPURL(config.publicMCPURL)
		if err != nil {
			log.Fatalf("configure public MCP URL: %v", err)
		}
	}
	observerState := buildSharedObserverState(host, port, publicMCPURL)

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

	observerOwner := envOr("OBSTUDIO_OWNER", "cli")
	observerMode := envOr("OBSTUDIO_MODE", "standalone")
	if observerMode == managedObserverMode && !managedLaunchAuthorized {
		observerMode = "standalone"
	}
	stopManaged := make(chan struct{}, 1)
	freeAccountSubmitter := freeaccount.New(freeaccount.Config{})
	mux := http.NewServeMux()
	api.Register(mux, s, v, validatorManager, api.ServerInfo{
		Kind:       "obstudio",
		APIVersion: "v1",
		Version:    version,
		Owner:      observerOwner,
		Mode:       observerMode,
		StartedAt:  startedAt,
		Exporters:  exporterInfo(splunkExportController, splunkTracesController),
	}, dashboards.Config{
		WorkspaceRoot: envOr("OBSTUDIO_WORKSPACE_ROOT", ""),
		SpecPath:      envOr("OBSTUDIO_DASHBOARDS_PREVIEW", ""),
	}, audit.Config{
		WorkspaceRoot: envOr("OBSTUDIO_WORKSPACE_ROOT", ""),
		ReportPath:    envOr("OBSTUDIO_AUDIT_REPORT", ""),
	}, api.HealthProofConfig{
		ControlToken: strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")),
		ProofSecret:  strings.TrimSpace(os.Getenv(observerHealthProofSecretEnv)),
		MCPURL:       observerState.MCPURL,
	}, splunkExportController, splunkTracesController,
		newSplunkExportConfigurationRefresher(config.envFile, splunkExportController, splunkTracesController),
		freeAccountSubmitter)
	if managedLaunchAuthorized && observerOwner == "cli" && observerMode == managedObserverMode {
		registerManagedStop(mux, strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")), stopManaged)
	}
	repositoryCorrelationModeResolver := mcp.RepositoryCorrelationModeResolver(func(provider string) string {
		return providerRepositoryCorrelationMode(tokenTelemetryStatePath(), provider)
	})
	mcp.Register(
		mux,
		s,
		v,
		validatorManager,
		splunkExportController,
		splunkTracesController,
		repositoryCorrelationModeResolver,
		freeAccountSubmitter,
	)
	webCleanup := web.Register(mux, s, v)

	srv := &http.Server{Addr: mainAddr, Handler: mux}
	mainListener, err := listenObserverHTTP("tcp", mainAddr)
	if err != nil {
		log.Fatalf("failed to start HTTP server: %v", err)
	}

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
	if managedLaunchAuthorized && observerOwner == "cli" && observerMode == managedObserverMode {
		managedPath := managedControlStatePath()
		if err := writeSharedObserverState(managedPath, observerState); err != nil {
			log.Printf("failed to write managed Observer state: %v", err)
			_ = mainListener.Close()
			webCleanup()
			validatorManager.Shutdown(ctx)
			rcv.Shutdown(ctx)
			splunkExportController.Shutdown(ctx)
			splunkTracesController.Shutdown(ctx)
			return fmt.Errorf("write managed Observer state: %w", err)
		} else {
			defer func() {
				if err := clearSharedObserverStateIfOwned(managedPath, observerState); err != nil {
					log.Printf("failed to clear managed Observer state: %v", err)
				}
			}()
		}
	}

	serveErrors := make(chan error, 1)
	go func() {
		if err := srv.Serve(mainListener); err != nil && err != http.ErrServerClosed {
			serveErrors <- err
		}
	}()

	fmt.Fprint(os.Stderr, renderStartupBanner(mainAddr, otlpHTTPAddr, otlpGRPCAddr))

	go mcp.RunStdio(
		s,
		os.Stdin,
		os.Stdout,
		v,
		validatorManager,
		splunkExportController,
		splunkTracesController,
		repositoryCorrelationModeResolver,
		freeAccountSubmitter,
	)

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	var runErr error
	select {
	case <-sig:
	case <-stopManaged:
	case err := <-serveErrors:
		runErr = fmt.Errorf("HTTP server failed: %w", err)
		log.Printf("%v", runErr)
	}
	fmt.Fprintf(os.Stderr, "\nShutting down...\n")

	shutCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	srv.Shutdown(shutCtx)
	webCleanup()
	validatorManager.Shutdown(shutCtx)
	rcv.Shutdown(shutCtx)
	splunkExportController.Shutdown(shutCtx)
	splunkTracesController.Shutdown(shutCtx)
	return runErr
}

func ensureObserverControlToken() error {
	if strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")) != "" {
		return nil
	}

	token := make([]byte, 32)
	if _, err := rand.Read(token); err != nil {
		return fmt.Errorf("generate control token: %w", err)
	}
	encoded := base64.RawURLEncoding.EncodeToString(token)
	if err := os.Setenv("OBSTUDIO_CONTROL_TOKEN", encoded); err != nil {
		return fmt.Errorf("store generated control token: %w", err)
	}
	return nil
}

func ensureObserverHealthProofSecret() error {
	configured := strings.TrimSpace(os.Getenv(observerHealthProofSecretEnv))
	if configured != "" {
		decoded, err := base64.RawURLEncoding.DecodeString(configured)
		if err != nil || len(decoded) != 32 || base64.RawURLEncoding.EncodeToString(decoded) != configured {
			return fmt.Errorf("%s must be exactly 32 bytes encoded as unpadded base64url", observerHealthProofSecretEnv)
		}
		if configured == strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")) {
			return fmt.Errorf("%s must differ from OBSTUDIO_CONTROL_TOKEN", observerHealthProofSecretEnv)
		}
		return nil
	}

	secret := make([]byte, 32)
	if _, err := rand.Read(secret); err != nil {
		return fmt.Errorf("generate health proof secret: %w", err)
	}
	if err := os.Setenv(observerHealthProofSecretEnv, base64.RawURLEncoding.EncodeToString(secret)); err != nil {
		return fmt.Errorf("store generated health proof secret: %w", err)
	}
	return nil
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
	keys := append(append([]string{}, splunkEnvFilePrecedenceKeys...), splunkEnvFileLegacyEndpointKeys...)
	for _, key := range keys {
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
		publicMCPURL:     valueOrEnv(config.publicMCPURL, observerPublicMCPURLEnv, ""),
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

		values = applyEnvFileShellPrecedence(values)
		if hasEnvMapKey(values, splunkEnvFileLegacyEndpointKeys...) {
			return activeSplunkExportConfigurationMatchesValues(values, metrics, traces)
		}

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

func activeSplunkExportConfigurationMatchesValues(
	values map[string]string,
	metrics splunkMetricsExportConfigurator,
	traces splunkTracesExportConfigurator,
) (bool, error) {
	expectedMetrics, err := splunkMetricsExporterConfigFromValues(values)
	if err != nil {
		return false, err
	}
	expectedTraces, err := splunkTracesExporterConfigFromValues(values)
	if err != nil {
		return false, err
	}

	actualMetrics := metrics.Config()
	actualTraces := traces.Config()
	if expectedMetrics.Timeout <= 0 {
		expectedMetrics.Timeout = actualMetrics.Timeout
	}
	if expectedTraces.Timeout <= 0 {
		expectedTraces.Timeout = actualTraces.Timeout
	}
	expectedMetrics.Realm = strings.TrimSpace(expectedMetrics.Realm)
	expectedMetrics.Endpoint = strings.TrimSpace(expectedMetrics.Endpoint)
	expectedMetrics.AccessToken = strings.TrimSpace(expectedMetrics.AccessToken)
	expectedTraces.Realm = strings.TrimSpace(expectedTraces.Realm)
	expectedTraces.Endpoint = strings.TrimSpace(expectedTraces.Endpoint)
	expectedTraces.AccessToken = strings.TrimSpace(expectedTraces.AccessToken)

	return actualMetrics == expectedMetrics && actualTraces == expectedTraces, nil
}

func splunkMetricsExporterConfigFromValues(values map[string]string) (otlp.SplunkMetricsExporterConfig, error) {
	timeout, err := durationValue("OBSTUDIO_SPLUNK_METRICS_TIMEOUT", values["OBSTUDIO_SPLUNK_METRICS_TIMEOUT"])
	if err != nil {
		return otlp.SplunkMetricsExporterConfig{}, err
	}
	return otlp.SplunkMetricsExporterConfig{
		Enabled:     envMapBool(values, "OBSTUDIO_SPLUNK_METRICS_EXPORT", "SPLUNK_METRICS_EXPORT"),
		Realm:       firstNonEmpty(values["OBSTUDIO_SPLUNK_REALM"], values["SPLUNK_REALM"]),
		Endpoint:    strings.TrimSpace(values["OBSTUDIO_SPLUNK_METRICS_ENDPOINT"]),
		AccessToken: strings.TrimSpace(values["SPLUNK_ACCESS_TOKEN"]),
		Timeout:     timeout,
	}, nil
}

func splunkTracesExporterConfigFromValues(values map[string]string) (otlp.SplunkTracesExporterConfig, error) {
	timeout, err := durationValue("OBSTUDIO_SPLUNK_TRACES_TIMEOUT", values["OBSTUDIO_SPLUNK_TRACES_TIMEOUT"])
	if err != nil {
		return otlp.SplunkTracesExporterConfig{}, err
	}
	return otlp.SplunkTracesExporterConfig{
		Enabled:     envMapBool(values, "OBSTUDIO_SPLUNK_TRACES_EXPORT", "SPLUNK_TRACES_EXPORT"),
		Realm:       firstNonEmpty(values["OBSTUDIO_SPLUNK_REALM"], values["SPLUNK_REALM"]),
		Endpoint:    strings.TrimSpace(values["OBSTUDIO_SPLUNK_TRACES_ENDPOINT"]),
		AccessToken: strings.TrimSpace(values["SPLUNK_ACCESS_TOKEN"]),
		Timeout:     timeout,
	}, nil
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
	return durationValue(key, os.Getenv(key))
}

func durationValue(key, rawValue string) (time.Duration, error) {
	value := strings.TrimSpace(rawValue)
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
	if publicMCPURL := strings.TrimSpace(config.publicMCPURL); publicMCPURL != "" {
		if len(publicMCPURL) > observerPublicMCPURLMaxLength {
			return fmt.Errorf("%s exceeds %d bytes", observerPublicMCPURLEnv, observerPublicMCPURLMaxLength)
		}
		if _, err := normalizePublicMCPURL(publicMCPURL); err != nil {
			return err
		}
	}
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

func normalizePublicMCPURL(raw string) (string, error) {
	normalized, err := normalizeSharedURL(raw, observerPublicMCPURLEnv)
	if err != nil {
		return "", err
	}
	parsed, err := url.Parse(normalized)
	if err != nil {
		return "", fmt.Errorf("invalid %s: %w", observerPublicMCPURLEnv, err)
	}
	if parsed.RawQuery != "" || parsed.ForceQuery {
		return "", fmt.Errorf("invalid %s: URL must not include a query", observerPublicMCPURLEnv)
	}
	hostname := strings.ToLower(parsed.Hostname())
	if address := net.ParseIP(hostname); address != nil {
		hostname = address.String()
	} else if strings.HasSuffix(hostname, ".") && isLoopbackSharedObserverHost(hostname) {
		hostname = strings.TrimSuffix(hostname, ".")
	}
	port := parsed.Port()
	if (parsed.Scheme == "https" && port == "443") || (parsed.Scheme == "http" && port == "80") {
		port = ""
	}
	if port != "" {
		parsed.Host = net.JoinHostPort(hostname, port)
	} else if strings.Contains(hostname, ":") {
		parsed.Host = "[" + hostname + "]"
	} else {
		parsed.Host = hostname
	}
	return parsed.String(), nil
}

func buildSharedObserverState(host, port string, publicMCPURLs ...string) sharedObserverState {
	connectHost := host
	switch connectHost {
	case "", "0.0.0.0", "::", "[::]":
		connectHost = "127.0.0.1"
	}

	baseURL := fmt.Sprintf("http://%s", net.JoinHostPort(connectHost, port))
	mcpURL := baseURL + "/mcp"
	if len(publicMCPURLs) > 0 && strings.TrimSpace(publicMCPURLs[0]) != "" {
		mcpURL = strings.TrimSpace(publicMCPURLs[0])
	}
	return sharedObserverState{
		BaseURL:           baseURL,
		ControlToken:      strings.TrimSpace(os.Getenv("OBSTUDIO_CONTROL_TOKEN")),
		HealthProofSecret: strings.TrimSpace(os.Getenv(observerHealthProofSecretEnv)),
		HealthURL:         baseURL + "/api/health",
		MCPURL:            mcpURL,
		PID:               os.Getpid(),
		UpdatedAt:         time.Now().UTC(),
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
	case "", "0.0.0.0":
		host = "127.0.0.1"
	case "::", "[::]":
		host = "::1"
	}
	if !strings.EqualFold(host, "localhost") {
		ip := net.ParseIP(strings.Trim(host, "[]"))
		if ip == nil || !ip.IsLoopback() {
			return "http://" + mainAddr
		}
	}
	baseURL := "http://" + net.JoinHostPort(host, port)
	if envBool(observerHideCloudBrowserLaunchTokenEnv) {
		return baseURL
	}
	launchToken := strings.TrimSpace(os.Getenv(observerCloudBrowserLaunchTokenEnv))
	if launchToken == "" {
		return baseURL
	}
	return baseURL + "/#obstudio-cloud-control=" + launchToken
}
