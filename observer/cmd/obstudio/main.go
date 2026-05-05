// Package main implements the Observability Studio CLI entry point.
package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
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
}

func main() {
	var config runConfig
	root := &cobra.Command{
		Use:     "obstudio",
		Short:   "Observability Studio -- local OTel collector, MCP server, and skill installer",
		Version: version,
		RunE: func(_ *cobra.Command, _ []string) error {
			resolved := resolveRunConfig(config)
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
	root.Flags().StringVar(&config.otlpHTTPPort, "otlp-http-port", "", "OTLP/HTTP receiver port")
	root.Flags().StringVar(&config.otlpGRPCPort, "otlp-grpc-port", "", "OTLP/gRPC receiver port")

	root.AddCommand(newInstallCmd())

	if err := root.Execute(); err != nil {
		os.Exit(1)
	}
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

	rcv, err := otlp.StartReceiver(ctx, s, otlpGRPCAddr, otlpHTTPAddr)
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
	})
	mcp.Register(mux, s, v, validatorManager)
	webCleanup := web.Register(mux, s, v)

	srv := &http.Server{Addr: mainAddr, Handler: mux}
	go func() {
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("HTTP server failed: %v", err)
		}
	}()

	fmt.Fprint(os.Stderr, renderStartupBanner(mainAddr, otlpHTTPAddr, otlpGRPCAddr))

	go mcp.RunStdio(s, os.Stdin, os.Stdout, v, validatorManager)

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

func resolveRunConfig(config runConfig) runConfig {
	return runConfig{
		host:             valueOrEnv(config.host, "HOST", "127.0.0.1"),
		observerHTTPPort: valueOrEnv(config.observerHTTPPort, "PORT", "3000"),
		otlpHTTPPort:     valueOrEnv(config.otlpHTTPPort, "OTLP_HTTP_PORT", envOr("OTLP_PORT", "4318")),
		otlpGRPCPort:     valueOrEnv(config.otlpGRPCPort, "OTLP_GRPC_PORT", "4317"),
	}
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
