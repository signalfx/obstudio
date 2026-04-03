package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"os"

	obstudioexporter "github.com/signalfx/obstudio/observer-go/exporter"
	obstudioextension "github.com/signalfx/obstudio/observer-go/extension"
	"github.com/signalfx/obstudio/observer-go/internal/store"
	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/confmap"
	"go.opentelemetry.io/collector/confmap/provider/yamlprovider"
	"go.opentelemetry.io/collector/connector"
	"go.opentelemetry.io/collector/exporter"
	"go.opentelemetry.io/collector/extension"
	"go.opentelemetry.io/collector/otelcol"
	"go.opentelemetry.io/collector/processor"
	"go.opentelemetry.io/collector/receiver"
	"go.opentelemetry.io/collector/receiver/otlpreceiver"
	"go.opentelemetry.io/collector/service/telemetry/otelconftelemetry"
)

func main() {
	host := envOr("HOST", "127.0.0.1")
	port := envOr("PORT", "3000")
	otlpHTTPPort := envOr("OTLP_HTTP_PORT", envOr("OTLP_PORT", "4318"))
	otlpGRPCPort := envOr("OTLP_GRPC_PORT", "4317")

	mainAddr := net.JoinHostPort(host, port)
	otlpHTTPAddr := net.JoinHostPort(host, otlpHTTPPort)
	otlpGRPCAddr := net.JoinHostPort(host, otlpGRPCPort)

	s := store.New()

	expFactory := obstudioexporter.NewFactory(s)
	extFactory := obstudioextension.NewFactory(s)
	rcvFactory := otlpreceiver.NewFactory()

	factories := otelcol.Factories{
		Receivers:  map[component.Type]receiver.Factory{rcvFactory.Type(): rcvFactory},
		Processors: map[component.Type]processor.Factory{},
		Exporters:  map[component.Type]exporter.Factory{expFactory.Type(): expFactory},
		Extensions: map[component.Type]extension.Factory{extFactory.Type(): extFactory},
		Connectors: map[component.Type]connector.Factory{},
		Telemetry:  otelconftelemetry.NewFactory(),
	}

	configYAML := collectorConfig(mainAddr, otlpHTTPAddr, otlpGRPCAddr)

	col, err := otelcol.NewCollector(otelcol.CollectorSettings{
		BuildInfo: component.BuildInfo{
			Command:     "obstudio",
			Description: "Observability Studio — local OpenTelemetry collector",
			Version:     "0.1.0",
		},
		Factories: func() (otelcol.Factories, error) { return factories, nil },
		ConfigProviderSettings: otelcol.ConfigProviderSettings{
			ResolverSettings: confmap.ResolverSettings{
				URIs:              []string{"yaml:" + configYAML},
				ProviderFactories: []confmap.ProviderFactory{yamlprovider.NewFactory()},
			},
		},
	})
	if err != nil {
		log.Fatalf("failed to create collector: %v", err)
	}

	fmt.Printf("\nObservability Studio (collector)\n")
	fmt.Printf("  Telemetry Explorer:  http://%s\n", mainAddr)
	fmt.Printf("  OTLP/HTTP receiver:  http://%s\n", otlpHTTPAddr)
	fmt.Printf("  OTLP/gRPC receiver:  %s\n", otlpGRPCAddr)
	fmt.Printf("  MCP endpoint:        http://%s/mcp\n\n", mainAddr)

	if err := col.Run(context.Background()); err != nil {
		log.Fatalf("collector run failed: %v", err)
	}
}

func collectorConfig(mainAddr, otlpHTTPAddr, otlpGRPCAddr string) string {
	return fmt.Sprintf(`receivers:
  otlp:
    protocols:
      grpc:
        endpoint: %s
      http:
        endpoint: %s

exporters:
  obstudio: {}

extensions:
  obstudio:
    endpoint: %s

service:
  telemetry:
    metrics:
      level: none
    logs:
      level: warn
  extensions: [obstudio]
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [obstudio]
    metrics:
      receivers: [otlp]
      exporters: [obstudio]
    logs:
      receivers: [otlp]
      exporters: [obstudio]
`, otlpGRPCAddr, otlpHTTPAddr, mainAddr)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
