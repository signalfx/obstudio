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

func main() {
	root := &cobra.Command{
		Use:     "obstudio",
		Short:   "Observability Studio -- local OTel collector, MCP server, and skill installer",
		Version: version,
		RunE: func(_ *cobra.Command, _ []string) error {
			run()
			return nil
		},
		SilenceUsage: true,
	}

	root.AddCommand(newInstallCmd())

	if err := root.Execute(); err != nil {
		os.Exit(1)
	}
}

func run() {
	s := store.New()
	v := validator.NewStore()
	validatorManager := validator.NewManager(v, s)
	s.SetInvalidateCallback(validatorManager.Reset)
	s.SetChangeCallback(validatorManager.MarkTelemetryChanged)
	startedAt := time.Now().UTC()

	host := envOr("HOST", "127.0.0.1")
	port := envOr("PORT", "3000")
	otlpHTTPPort := envOr("OTLP_HTTP_PORT", envOr("OTLP_PORT", "4318"))
	otlpGRPCPort := envOr("OTLP_GRPC_PORT", "4317")

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

	fmt.Fprintf(os.Stderr, "\nObservability Studio (collector)\n")
	fmt.Fprintf(os.Stderr, "  Telemetry Explorer:  http://%s\n", mainAddr)
	fmt.Fprintf(os.Stderr, "  OTLP/HTTP receiver:  http://%s\n", otlpHTTPAddr)
	fmt.Fprintf(os.Stderr, "  OTLP/gRPC receiver:  %s\n", otlpGRPCAddr)
	fmt.Fprintf(os.Stderr, "  MCP endpoint:        http://%s/mcp\n\n", mainAddr)

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
