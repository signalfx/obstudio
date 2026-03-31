package exporter

import (
	"context"

	"github.com/signalfx/obstudio/observer-go/internal/store"
	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/consumer"
	"go.opentelemetry.io/collector/exporter"
	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

const componentType = "obstudio"

func NewFactory(s *store.Store) exporter.Factory {
	return exporter.NewFactory(
		component.MustNewType(componentType),
		createDefaultConfig,
		exporter.WithTraces(makeCreateTraces(s), component.StabilityLevelDevelopment),
		exporter.WithMetrics(makeCreateMetrics(s), component.StabilityLevelDevelopment),
		exporter.WithLogs(makeCreateLogs(s), component.StabilityLevelDevelopment),
	)
}

func createDefaultConfig() component.Config {
	return &Config{}
}

func makeCreateTraces(s *store.Store) exporter.CreateTracesFunc {
	return func(_ context.Context, _ exporter.Settings, _ component.Config) (exporter.Traces, error) {
		return &tracesExporter{store: s}, nil
	}
}

func makeCreateMetrics(s *store.Store) exporter.CreateMetricsFunc {
	return func(_ context.Context, _ exporter.Settings, _ component.Config) (exporter.Metrics, error) {
		return &metricsExporter{store: s}, nil
	}
}

func makeCreateLogs(s *store.Store) exporter.CreateLogsFunc {
	return func(_ context.Context, _ exporter.Settings, _ component.Config) (exporter.Logs, error) {
		return &logsExporter{store: s}, nil
	}
}

type tracesExporter struct {
	store *store.Store
}

func (e *tracesExporter) Start(_ context.Context, _ component.Host) error { return nil }
func (e *tracesExporter) Shutdown(_ context.Context) error                { return nil }
func (e *tracesExporter) Capabilities() consumer.Capabilities {
	return consumer.Capabilities{MutatesData: false}
}
func (e *tracesExporter) ConsumeTraces(_ context.Context, td ptrace.Traces) error {
	e.store.AddSpans(convertTraces(td))
	return nil
}

type metricsExporter struct {
	store *store.Store
}

func (e *metricsExporter) Start(_ context.Context, _ component.Host) error { return nil }
func (e *metricsExporter) Shutdown(_ context.Context) error                { return nil }
func (e *metricsExporter) Capabilities() consumer.Capabilities {
	return consumer.Capabilities{MutatesData: false}
}
func (e *metricsExporter) ConsumeMetrics(_ context.Context, md pmetric.Metrics) error {
	e.store.AddMetrics(convertMetrics(md))
	return nil
}

type logsExporter struct {
	store *store.Store
}

func (e *logsExporter) Start(_ context.Context, _ component.Host) error { return nil }
func (e *logsExporter) Shutdown(_ context.Context) error                { return nil }
func (e *logsExporter) Capabilities() consumer.Capabilities {
	return consumer.Capabilities{MutatesData: false}
}
func (e *logsExporter) ConsumeLogs(_ context.Context, ld plog.Logs) error {
	e.store.AddLogs(convertLogs(ld))
	return nil
}
