# Go OpenTelemetry Guide

Language-specific instrumentation guidance for Go services.

---

## Auto-Instrumentation Library Map

Use packages from `go.opentelemetry.io/contrib`. Only add instrumentations
matching the frameworks and clients detected in the codebase.

| Dependency | Auto-instrumentation Package | What It Covers |
|------------|------------------------------|----------------|
| `net/http` (stdlib) | `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp` | HTTP server/client spans with route, method, status |
| `gorilla/mux` | `go.opentelemetry.io/contrib/instrumentation/github.com/gorilla/mux/otelmux` | Route-aware HTTP spans |
| `go-chi/chi` | `go.opentelemetry.io/contrib/instrumentation/github.com/go-chi/chi/otelchi` | Route-aware HTTP spans |
| `gin-gonic/gin` | `go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin` | Route-aware HTTP spans |
| `google.golang.org/grpc` | `go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc` | gRPC client/server spans and metrics |
| `database/sql` | `github.com/XSAM/otelsql` | SQL query spans with `db.statement` |
| `go-redis/redis` | `github.com/redis/go-redis/extra/redisotel` | Redis command spans |
| `runtime` | `go.opentelemetry.io/contrib/instrumentation/runtime` | Goroutine count, memory, GC metrics |
| `host` | `go.opentelemetry.io/contrib/instrumentation/host` | CPU, memory, network host metrics |
| `segmentio/kafka-go` | `go.opentelemetry.io/contrib/instrumentation/github.com/segmentio/kafka-go/otelsegmentio` | Kafka producer/consumer spans |
| `aws-sdk-go-v2` | `go.opentelemetry.io/contrib/instrumentation/github.com/aws/aws-sdk-go-v2/otelaws` | AWS service call spans |

**Never use `go.opentelemetry.io/otel/semconv/*` packages directly.** These
versioned semconv modules can cause runtime conflicts when different
dependencies pull in different schema versions. Use string attribute keys
instead.

---

## Dependencies

```bash
go get go.opentelemetry.io/otel \
  go.opentelemetry.io/otel/sdk \
  go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc \
  go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc \
  go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp \
  go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc
```

---

## SDK Initialization

Create a dedicated file for OTel setup that returns a shutdown function.
Call it early in `main()`.

**File**: `otel.go`

```go
package main

import (
	"context"
	"os"

	"go.opentelemetry.io/contrib/instrumentation/runtime"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

func initOTel(ctx context.Context) (func(context.Context) error, error) {
	res, err := resource.New(ctx,
		resource.WithAttributes(
			attribute.String("service.name",
				envOr("OTEL_SERVICE_NAME", "my-service")),
		),
	)
	if err != nil {
		return nil, err
	}

	traceExporter, err := otlptracehttp.New(ctx)
	if err != nil {
		return nil, err
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(traceExporter),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	metricExporter, err := otlpmetrichttp.New(ctx)
	if err != nil {
		return nil, err
	}

	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(metricExporter)),
		sdkmetric.WithResource(res),
	)
	otel.SetMeterProvider(mp)

	if err := runtime.Start(); err != nil {
		return nil, err
	}

	shutdown := func(ctx context.Context) error {
		if err := tp.Shutdown(ctx); err != nil {
			return err
		}
		return mp.Shutdown(ctx)
	}
	return shutdown, nil
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
```

### Using in main()

```go
func main() {
	ctx := context.Background()
	shutdown, err := initOTel(ctx)
	if err != nil {
		log.Fatalf("failed to initialize telemetry: %v", err)
	}
	defer shutdown(ctx)

	// ... start HTTP server, gRPC server, etc.
}
```

### Wrapping HTTP handlers

```go
import "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"

mux := http.NewServeMux()
mux.HandleFunc("/api/orders", handleOrders)

handler := otelhttp.NewHandler(mux, "server",
	otelhttp.WithMessageEvents(otelhttp.ReadEvents, otelhttp.WriteEvents),
)
http.ListenAndServe(":8080", handler)
```

For router-specific middleware (`otelmux`, `otelchi`, `otelgin`), wrap
the router instead of individual handlers.

### HTTP Client Instrumentation

```go
import "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"

client := &http.Client{
	Transport: otelhttp.NewTransport(http.DefaultTransport),
}
resp, err := client.Get("https://api.example.com/data")
```

### gRPC Instrumentation

```go
import "go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"

server := grpc.NewServer(
	grpc.StatsHandler(otelgrpc.NewServerHandler()),
)

conn, _ := grpc.Dial(target,
	grpc.WithStatsHandler(otelgrpc.NewClientHandler()),
)
```

---

## Custom Spans

Define package-level tracers. Use `tracer.Start()` with `defer span.End()`.

```go
import (
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
)

var tracer = otel.Tracer("my-service/orders")

func (s *OrderService) ProcessOrder(ctx context.Context, orderID string) (*Order, error) {
	ctx, span := tracer.Start(ctx, "orders.process",
		trace.WithAttributes(attribute.String("order.id", orderID)))
	defer span.End()

	order, err := s.repo.Get(ctx, orderID)
	if err != nil {
		span.RecordError(err)
		span.SetStatus(codes.Error, "failed to get order")
		return nil, err
	}

	span.SetAttributes(attribute.Float64("order.total", order.Total))
	return order, nil
}
```

**Context propagation**: always pass `ctx` through function calls and into
child spans. Goroutines must receive the parent context explicitly:

```go
go func(ctx context.Context) {
	ctx, span := tracer.Start(ctx, "orders.notify")
	defer span.End()
	notify(ctx, order)
}(ctx)
```

---

## Custom Metrics

Define package-level meters. Register metrics at init time.

```go
import (
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/metric"
)

var meter = otel.Meter("my-service")

var (
	ordersProcessed metric.Int64Counter
	orderDuration   metric.Float64Histogram
)

func initMetrics() error {
	var err error
	ordersProcessed, err = meter.Int64Counter("orders.processed.count",
		metric.WithDescription("Total orders processed"),
		metric.WithUnit("{orders}"))
	if err != nil {
		return err
	}

	orderDuration, err = meter.Float64Histogram("orders.process.duration",
		metric.WithDescription("Order processing duration"),
		metric.WithUnit("s"))
	if err != nil {
		return err
	}

	// Observable gauge with callback
	_, err = meter.Int64ObservableGauge("orders.queue.depth",
		metric.WithDescription("Current order queue depth"),
		metric.WithUnit("{orders}"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			o.Observe(int64(getQueueDepth()))
			return nil
		}))
	return err
}
```

Usage:

```go
ordersProcessed.Add(ctx, 1, metric.WithAttributes(
	attribute.String("order.type", "standard"),
))

start := time.Now()
processOrder(ctx, orderID)
orderDuration.Record(ctx, time.Since(start).Seconds(), metric.WithAttributes(
	attribute.String("order.type", "standard"),
))
```

---

## Error Handling

APM backends identify errors via `otel.status_code = ERROR`:

```go
span.SetStatus(codes.Error, "payment gateway timeout")
span.RecordError(err)
```

The `otelhttp` handler auto-sets ERROR on 5xx responses.

---

## OTLP Export Configuration

All configuration is via environment variables. Do not hardcode endpoints.
The `otlptracehttp` and `otlpmetrichttp` exporters read these automatically.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP HTTP endpoint |
| `OTEL_SERVICE_NAME` | (must be set) | Service identity in telemetry |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metric export interval (ms) |
| `OTEL_BSP_SCHEDULE_DELAY` | `5000` | Span batch export delay (ms) |

For local development with the Observer:

    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
    OTEL_METRIC_EXPORT_INTERVAL=1000 \
    OTEL_BSP_SCHEDULE_DELAY=100 \
    go run .

---

## Gotchas

- **No `semconv` packages**: never import `go.opentelemetry.io/otel/semconv/v1.x`.
  Different transitive dependencies may pull in different semconv versions,
  causing runtime schema conflicts. Use plain `attribute.String("key", "val")`
  with the correct semconv key names as strings.
- **Context is everything**: Go's OTel SDK relies on `context.Context` for
  span propagation. Always pass `ctx` through the call chain. Losing context
  breaks parent-child span relationships.
- **Goroutine context**: when spawning goroutines, pass the parent `ctx`
  explicitly. Do not capture it from a closure over a variable that may
  change.
- **`otel.Tracer` is cheap**: calling `otel.Tracer("name")` returns a
  lightweight handle. It is safe and idiomatic to call at package level.
- **Singleton providers**: `otel.SetTracerProvider` and `otel.SetMeterProvider`
  must only be called once. If existing OTel setup exists, extend it.
- **Shutdown order**: shut down the TracerProvider before the MeterProvider
  so in-flight spans are flushed before metrics.
- **`runtime.Start()`**: this registers goroutine count, memory, and GC
  metrics. Call it after the MeterProvider is set.
