// Package otlp implements OTLP receivers and connection tracking for telemetry collection.
package otlp

import (
	"context"
	"fmt"
	"net"

	"github.com/signalfx/obstudio/observer-go/internal/store"
	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/config/configgrpc"
	"go.opentelemetry.io/collector/config/confignet"
	"go.opentelemetry.io/collector/config/configoptional"
	"go.opentelemetry.io/collector/consumer"
	"go.opentelemetry.io/collector/pdata/plog"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
	"go.opentelemetry.io/collector/receiver"
	"go.opentelemetry.io/collector/receiver/otlpreceiver"
	metricnoop "go.opentelemetry.io/otel/metric/noop"
	tracenoop "go.opentelemetry.io/otel/trace/noop"
	"go.uber.org/zap"
	"google.golang.org/grpc/metadata"
)

// Receiver wraps the OTLP gRPC and HTTP receivers with connection-tracking.
// Architecture:
//   - gRPC: proxy on public port → internal otlpreceiver on ephemeral port.
//     The gRPC proxy's StatsHandler tracks connections for disconnect detection.
//   - HTTP: handled directly by ConnTracker (no internal receiver needed).
//     Each request resolves the remote PID using platform-specific connection
//     ownership lookup for disconnect detection.
type Receiver struct {
	traces      receiver.Traces
	metrics     receiver.Metrics
	logs        receiver.Logs
	connTracker *ConnTracker
}

// minimalHost satisfies component.Host for starting receivers outside
// the collector framework.
type minimalHost struct{}

func (minimalHost) GetExtensions() map[component.ID]component.Component { return nil }

// pickEphemeralAddr returns a "127.0.0.1:<port>" address by binding to
// port 0, recording the OS-assigned port, then closing the listener so
// the otlpreceiver can bind to it.
func pickEphemeralAddr() (string, error) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", err
	}
	addr := ln.Addr().String()
	ln.Close()
	return addr, nil
}

// StartReceiver creates and starts OTLP receivers with connection tracking.
// For gRPC: an internal otlpreceiver listens on an ephemeral loopback port;
// the ConnTracker's gRPC proxy listens on grpcAddr and forwards traffic while
// tracking connections via StatsHandler.
// For HTTP: the ConnTracker handles OTLP/HTTP requests directly (decoding
// JSON/protobuf itself), resolving the remote process PID with
// platform-specific socket ownership lookup, and monitoring process liveness.
// No internal HTTP receiver is needed.
func StartReceiver(ctx context.Context, s *store.Store, grpcAddr, httpAddr string) (*Receiver, error) {
	internalGRPC, err := pickEphemeralAddr()
	if err != nil {
		return nil, fmt.Errorf("pick internal gRPC port: %w", err)
	}

	factory := otlpreceiver.NewFactory()

	grpcCfg := configgrpc.NewDefaultServerConfig()
	grpcCfg.NetAddr = confignet.AddrConfig{Endpoint: internalGRPC, Transport: confignet.TransportTypeTCP}
	grpcCfg.ReadBufferSize = 512 * 1024

	// Only gRPC protocol — HTTP is handled directly by ConnTracker.
	cfg := &otlpreceiver.Config{
		Protocols: otlpreceiver.Protocols{
			GRPC: configoptional.Some(grpcCfg),
		},
	}

	logger, err := zap.NewProduction(zap.IncreaseLevel(zap.WarnLevel))
	if err != nil {
		return nil, fmt.Errorf("create logger: %w", err)
	}
	settings := receiver.Settings{
		ID: component.MustNewID("otlp"),
		TelemetrySettings: component.TelemetrySettings{
			Logger:         logger,
			MeterProvider:  metricnoop.NewMeterProvider(),
			TracerProvider: tracenoop.NewTracerProvider(),
		},
	}

	// The gRPC proxy forwards a synthetic connection ID as incoming metadata to
	// the internal otlpreceiver so gRPC telemetry can be evicted per session,
	// similar to the Node implementation's per-connection source ownership.
	tracesConsumer, err := consumer.NewTraces(func(ctx context.Context, td ptrace.Traces) error {
		s.AddSpansForConnection(connIDFromContext(ctx), ConvertTraces(td))
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("create traces consumer: %w", err)
	}
	metricsConsumer, err := consumer.NewMetrics(func(ctx context.Context, md pmetric.Metrics) error {
		s.AddMetricsForConnection(connIDFromContext(ctx), ConvertMetrics(md))
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("create metrics consumer: %w", err)
	}
	logsConsumer, err := consumer.NewLogs(func(ctx context.Context, ld plog.Logs) error {
		s.AddLogsForConnection(connIDFromContext(ctx), ConvertLogs(ld))
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("create logs consumer: %w", err)
	}

	rcvTraces, err := factory.CreateTraces(ctx, settings, cfg, tracesConsumer)
	if err != nil {
		return nil, fmt.Errorf("create traces receiver: %w", err)
	}
	rcvMetrics, err := factory.CreateMetrics(ctx, settings, cfg, metricsConsumer)
	if err != nil {
		return nil, fmt.Errorf("create metrics receiver: %w", err)
	}
	rcvLogs, err := factory.CreateLogs(ctx, settings, cfg, logsConsumer)
	if err != nil {
		return nil, fmt.Errorf("create logs receiver: %w", err)
	}

	host := minimalHost{}

	// Track started receivers so we can clean up on partial failure.
	var started []component.Component

	if err := rcvTraces.Start(ctx, host); err != nil {
		return nil, fmt.Errorf("start traces receiver: %w", err)
	}
	started = append(started, rcvTraces)

	if err := rcvMetrics.Start(ctx, host); err != nil {
		shutdownAll(ctx, started)
		return nil, fmt.Errorf("start metrics receiver: %w", err)
	}
	started = append(started, rcvMetrics)

	if err := rcvLogs.Start(ctx, host); err != nil {
		shutdownAll(ctx, started)
		return nil, fmt.Errorf("start logs receiver: %w", err)
	}
	started = append(started, rcvLogs)

	ct, err := StartConnTracker(s, grpcAddr, httpAddr, internalGRPC)
	if err != nil {
		shutdownAll(ctx, started)
		return nil, fmt.Errorf("start connection tracker: %w", err)
	}

	return &Receiver{
		traces:      rcvTraces,
		metrics:     rcvMetrics,
		logs:        rcvLogs,
		connTracker: ct,
	}, nil
}

// Shutdown gracefully stops the connection tracker and all receivers.
// Returns the first error encountered during shutdown, if any.
func (r *Receiver) Shutdown(ctx context.Context) error {
	if r.connTracker != nil {
		r.connTracker.Shutdown()
	}
	var firstErr error
	for _, c := range []component.Component{r.traces, r.metrics, r.logs} {
		if err := c.Shutdown(ctx); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

func shutdownAll(ctx context.Context, components []component.Component) {
	for _, c := range components {
		c.Shutdown(ctx)
	}
}

func connIDFromContext(ctx context.Context) string {
	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return ""
	}
	values := md.Get(grpcConnIDMetadataKey)
	if len(values) == 0 {
		return ""
	}
	return values[0]
}
