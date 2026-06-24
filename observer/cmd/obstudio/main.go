// Package main implements the Observability Studio CLI entry point.
package main

import (
	"bufio"
	"context"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"github.com/signalfx/obstudio/observer/internal/api"
	"github.com/signalfx/obstudio/observer/internal/mcp"
	"github.com/signalfx/obstudio/observer/internal/otlp"
	"github.com/signalfx/obstudio/observer/internal/store"
	"github.com/signalfx/obstudio/observer/internal/validator"
	"github.com/signalfx/obstudio/observer/internal/web"
)

var version = "dev"

type runConfig struct {
	host             string
	observerHTTPPort string
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

	root.Flags().StringVar(&config.host, "host", "", "Bind address for the Observer UI, MCP HTTP endpoint, and OTLP receivers")
	root.Flags().StringVar(&config.observerHTTPPort, "observer-http-port", "", "Observer web UI, REST API, and MCP HTTP port")
	root.Flags().StringVar(&config.envFile, "env-file", "", "Load KEY=VALUE settings from an env file before startup")

	root.AddCommand(newInstallCmd())
	return root
}

func run(config runConfig) {
	s := store.New()
	v := validator.NewStore()
	validatorManager := validator.NewManager(v, s)
	s.SetInvalidateCallback(validatorManager.Reset)
	s.SetChangeCallback(validatorManager.MarkTelemetryChanged)
	startedAt := time.Now().UTC()

	host := config.host
	port := config.observerHTTPPort
	otlpHTTPPort := config.otlpHTTPPort
	otlpGRPCPort := config.otlpGRPCPort

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

	mainAddr := net.JoinHostPort(host, port)
	otlpHTTPAddr := net.JoinHostPort(host, otlpHTTPPort)
	otlpGRPCAddr := net.JoinHostPort(host, otlpGRPCPort)

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
	})
	mcp.Register(mux, s, v, validatorManager, splunkExportController)
	webCleanup := web.Register(mux, s, v)

	srv := &http.Server{Addr: mainAddr, Handler: mux}
	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("HTTP server failed: %v", err)
		}
	}()

	fmt.Fprint(os.Stderr, renderStartupBanner(mainAddr, otlpHTTPAddr, otlpGRPCAddr))

	go mcp.RunStdio(s, os.Stdin, os.Stdout, v, validatorManager, splunkExportController)

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
		if _, exists := os.LookupEnv(key); exists {
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
	return runConfig{
		host:             valueOrEnv(config.host, "HOST", "127.0.0.1"),
		observerHTTPPort: valueOrEnv(config.observerHTTPPort, "PORT", "3000"),
		otlpHTTPPort:     valueOrEnv(config.otlpHTTPPort, "OTLP_HTTP_PORT", envOr("OTLP_PORT", "4318")),
		otlpGRPCPort:     valueOrEnv(config.otlpGRPCPort, "OTLP_GRPC_PORT", "4317"),
	}
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
		BaseURL:   baseURL,
		HealthURL: baseURL + "/api/health",
		MCPURL:    baseURL + "/mcp",
		PID:       os.Getpid(),
		UpdatedAt: time.Now().UTC(),
	}
}

func renderStartupBanner(mainAddr, otlpHTTPAddr, otlpGRPCAddr string) string {
	return fmt.Sprintf(
		"\nObservability Studio (collector)\n"+
			"  Telemetry Explorer:  http://%s\n"+
			"  OTLP/HTTP receiver:  http://%s\n"+
			"  OTLP/gRPC receiver:  %s\n"+
			"  MCP endpoint:        http://%s/mcp\n"+
			"  Agent setup:         obstudio install --target=<agent>\n\n",
		mainAddr,
		otlpHTTPAddr,
		otlpGRPCAddr,
		mainAddr,
	)
}
