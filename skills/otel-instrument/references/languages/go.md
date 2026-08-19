# Go OpenTelemetry Guide

Language-specific instrumentation guidance for Go services.

---

## Auto-Instrumentation Library Map

Use packages from `go.opentelemetry.io/contrib`. Only add instrumentations
matching the frameworks and clients detected in the codebase.


| Dependency               | Auto-instrumentation Package                                                              | Signals         | What It Covers                                                                          |
| ------------------------ | ----------------------------------------------------------------------------------------- | --------------- | --------------------------------------------------------------------------------------- |
| `net/http` (stdlib)      | `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp`                           | spans + metrics | HTTP server/client spans, `http.server.request.duration`, `http.server.active_requests` |
| `gorilla/mux`            | `go.opentelemetry.io/contrib/instrumentation/github.com/gorilla/mux/otelmux`              | spans only      | Route-aware HTTP spans                                                                  |
| `go-chi/chi`             | `go.opentelemetry.io/contrib/instrumentation/github.com/go-chi/chi/otelchi`               | spans only      | Route-aware HTTP spans                                                                  |
| `gin-gonic/gin`          | `go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin`            | spans only      | Route-aware HTTP spans                                                                  |
| `google.golang.org/grpc` | `go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc`             | spans + metrics | gRPC client/server spans and metrics                                                    |
| `database/sql`           | `github.com/XSAM/otelsql`                                                                 | spans only      | SQL query spans with `db.statement`                                                     |
| `go-redis/redis`         | `github.com/redis/go-redis/extra/redisotel`                                               | spans only      | Redis command spans                                                                     |
| `runtime`                | `go.opentelemetry.io/contrib/instrumentation/runtime`                                     | metrics only    | Goroutine count, memory, GC metrics                                                     |
| `host`                   | `go.opentelemetry.io/contrib/instrumentation/host`                                        | metrics only    | CPU, memory, network host metrics                                                       |
| `segmentio/kafka-go`     | `go.opentelemetry.io/contrib/instrumentation/github.com/segmentio/kafka-go/otelsegmentio` | spans only      | Kafka producer/consumer spans                                                           |
| `aws-sdk-go-v2`          | `go.opentelemetry.io/contrib/instrumentation/github.com/aws/aws-sdk-go-v2/otelaws`        | spans only      | AWS service call spans                                                                  |


**Never use `go.opentelemetry.io/otel/semconv/`* packages directly.** These
versioned semconv modules can cause runtime conflicts when different
dependencies pull in different schema versions. Use string attribute keys
instead.

---

## Framework Selection Guide

Framework-specific middleware packages (otelchi, otelgin, otelmux) only emit
**spans** -- they do not register HTTP server metric instruments. To get full
request count, error status, and request-duration coverage, wrap the outermost
handler with
`otelhttp.NewHandler`, which emits both spans and metrics.

**Default rule:** always use `otelhttp.NewHandler` as the outermost wrapper.
Add framework middleware inside only when you need route-pattern span names.

### chi

Preferred (spans + metrics):

```go
handler := otelhttp.NewHandler(r, "server")
http.ListenAndServe(":8080", handler)
```

If you also need chi route patterns in span names, add `otelchi` as inner
middleware:

```go
r.Use(otelchi.Middleware("server"))
handler := otelhttp.NewHandler(r, "server")
```

### gin

Preferred (spans + metrics):

```go
handler := otelhttp.NewHandler(ginEngine, "server")
http.ListenAndServe(":8080", handler)
```

Combined with route-aware span names:

```go
ginEngine.Use(otelgin.Middleware("server"))
handler := otelhttp.NewHandler(ginEngine, "server")
```

### gorilla/mux

Preferred (spans + metrics):

```go
handler := otelhttp.NewHandler(router, "server")
http.ListenAndServe(":8080", handler)
```

Combined with route-aware span names:

```go
router.Use(otelmux.Middleware("server"))
handler := otelhttp.NewHandler(router, "server")
```

### Adding a new framework

Follow this template:

```
### {framework-name}

Preferred (spans + metrics):
  handler := otelhttp.NewHandler({router}, "server")

Combined with route-aware span names:
  {router}.Use({framework-package}.Middleware("server"))
  handler := otelhttp.NewHandler({router}, "server")
```

---

## Dependencies

Resolve versions against the existing `go` directive and locked OTel modules
before editing `go.mod`. Bridge modules are independently versioned and their
latest release can require a newer Go toolchain. Never use an unversioned
`go get` that changes the project's `go` or `toolchain` directive. For example,
a Go 1.22-compatible set is:

```bash
go get go.opentelemetry.io/otel@v1.35.0 \
  go.opentelemetry.io/otel/sdk@v1.35.0 \
  go.opentelemetry.io/otel/sdk/log@v0.11.0 \
  go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp@v0.11.0 \
  go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp@v1.35.0 \
  go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp@v1.35.0 \
  go.opentelemetry.io/contrib/bridges/otelslog@v0.10.0 \
  go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp@v0.60.0 \
  go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc@v0.60.0
```

Use that set only when it is compatible with the project's existing module
graph; otherwise select a mutually compatible published set and record the
evidence. If no official bridge release supports the selected Go toolchain and
SDK, report `unsupported-stack` instead of upgrading the toolchain implicitly.

The example below assumes the application uses `log/slog` (and the standard
`log` package routed through the default slog logger) and therefore installs
`go.opentelemetry.io/contrib/bridges/otelslog`. Add exactly one official bridge
matching the detected logging stack: `otelzap`, `otellogrus`, `otelzerolog`, or
`otellogr` are the corresponding official alternatives for zap, Logrus,
zerolog, and logr. Do not add every bridge speculatively, and do not combine a
bridge with another hook or exporter that sends the same record.

---

## SDK Initialization

Create a dedicated file for OTel setup that returns a shutdown function.
Call it early in `main()`.

**File**: `otel.go`

```go
package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"log/slog"
	"os"
	"strconv"
	"strings"
	"time"

	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/contrib/instrumentation/runtime"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	otellogglobal "go.opentelemetry.io/otel/log/global"
	"go.opentelemetry.io/otel/propagation"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

const localObserverLogsEndpoint = "http://localhost:4318/v1/logs"

func initOTel(
	ctx context.Context,
	existingLogHandler slog.Handler,
) (func(context.Context) error, error) {
	res, err := resource.New(ctx,
		resource.WithFromEnv(),
		resource.WithTelemetrySDK(),
		resource.WithProcess(),
		resource.WithOS(),
		resource.WithContainer(),
		resource.WithHost(),
	)
	if err != nil {
		return nil, err
	}
	serviceNameKey := attribute.Key("service.name")
	serviceName := strings.TrimSpace(os.Getenv("OTEL_SERVICE_NAME"))
	if serviceName == "" {
		if _, exists := res.Set().Value(serviceNameKey); !exists {
			serviceName = "my-service"
		}
	}
	if serviceName != "" {
		res, err = resource.Merge(res, resource.NewSchemaless(
			serviceNameKey.String(serviceName),
		))
		if err != nil {
			return nil, err
		}
	}

	traceExporter, err := otlptracehttp.New(ctx)
	if err != nil {
		return nil, err
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(traceExporter),
		sdktrace.WithResource(res),
	)

	metricExporter, err := otlpmetrichttp.New(ctx)
	if err != nil {
		_ = tp.Shutdown(ctx)
		return nil, err
	}

	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(
			metricExporter,
			sdkmetric.WithInterval(metricExportInterval()),
			sdkmetric.WithTimeout(metricExportTimeout()),
		)),
		sdkmetric.WithResource(res),
	)

	var lp *sdklog.LoggerProvider
	var applicationLogHandler slog.Handler
	if useDefaultLocalLogExport() {
		if existingLogHandler == nil {
			_ = tp.Shutdown(ctx)
			_ = mp.Shutdown(ctx)
			return nil, errors.New("existing log handler is required to preserve its sink")
		}
		logExporter, err := newApplicationLogExporter(ctx)
		if err != nil {
			_ = tp.Shutdown(ctx)
			_ = mp.Shutdown(ctx)
			return nil, err
		}

		lp = sdklog.NewLoggerProvider(
			sdklog.WithResource(res),
			sdklog.WithProcessor(sdklog.NewBatchProcessor(logExporter)),
		)
		applicationLogHandler = otelslog.NewHandler(
			"my-service",
			otelslog.WithLoggerProvider(lp),
		)
	}

	otel.SetTracerProvider(tp)
	otel.SetMeterProvider(mp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))
	if lp != nil {
		otellogglobal.SetLoggerProvider(lp)
		slog.SetDefault(slog.New(fanoutHandler{
			existingLogHandler,
			applicationLogHandler,
		}))
	}

	if err := runtime.Start(); err != nil {
		if lp != nil {
			_ = lp.Shutdown(ctx)
		}
		_ = tp.Shutdown(ctx)
		_ = mp.Shutdown(ctx)
		return nil, err
	}

	shutdown := func(ctx context.Context) error {
		var errs []error
		if lp != nil {
			errs = append(errs, lp.Shutdown(ctx))
		}
		errs = append(errs, tp.Shutdown(ctx), mp.Shutdown(ctx))
		return errors.Join(errs...)
	}
	return shutdown, nil
}

func useDefaultLocalLogExport() bool {
	configured := strings.ToLower(strings.TrimSpace(
		os.Getenv("OTEL_LOGS_EXPORTER"),
	))
	return configured == "" || configured == "otlp"
}

func newApplicationLogExporter(ctx context.Context) (*otlploghttp.Exporter, error) {
	protocol := strings.ToLower(strings.TrimSpace(
		os.Getenv("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL"),
	))
	if protocol != "" && protocol != "http/protobuf" {
		return nil, fmt.Errorf(
			"select the official exporter matching OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=%q",
			protocol,
		)
	}

	logsHeaders := strings.TrimSpace(os.Getenv("OTEL_EXPORTER_OTLP_LOGS_HEADERS"))
	if strings.TrimSpace(os.Getenv("OTEL_EXPORTER_OTLP_HEADERS")) != "" && logsHeaders == "" {
		return nil, errors.New(
			"move generic OTLP headers to trace/metric signal variables, or set explicit logs headers",
		)
	}

	endpoint := strings.TrimSpace(os.Getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"))
	if endpoint == "" {
		endpoint = localObserverLogsEndpoint
	}
	opts := []otlploghttp.Option{otlploghttp.WithEndpointURL(endpoint)}
	if logsHeaders == "" {
		// Prevent a future generic header from becoming the log credential.
		opts = append(opts, otlploghttp.WithHeaders(map[string]string{}))
	}
	return otlploghttp.New(ctx, opts...)
}

// fanoutHandler preserves every existing slog sink while adding one OTel
// bridge. Do not install it when preflight finds another OTel log bridge.
type fanoutHandler []slog.Handler

func (h fanoutHandler) Enabled(ctx context.Context, level slog.Level) bool {
	for _, handler := range h {
		if handler.Enabled(ctx, level) {
			return true
		}
	}
	return false
}

func (h fanoutHandler) Handle(ctx context.Context, record slog.Record) error {
	var errs []error
	for _, handler := range h {
		if handler.Enabled(ctx, record.Level) {
			errs = append(errs, handler.Handle(ctx, record.Clone()))
		}
	}
	return errors.Join(errs...)
}

func (h fanoutHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	handlers := make(fanoutHandler, len(h))
	for i, handler := range h {
		handlers[i] = handler.WithAttrs(attrs)
	}
	return handlers
}

func (h fanoutHandler) WithGroup(name string) slog.Handler {
	handlers := make(fanoutHandler, len(h))
	for i, handler := range h {
		handlers[i] = handler.WithGroup(name)
	}
	return handlers
}

// standardLogHandler snapshots an existing standard logger before
// slog.SetDefault rewires log.Default. It preserves its writer, prefix, and
// flags while otelslog receives the same record. Native slog applications
// should pass their existing slog.Handler directly instead.
type standardLogHandler struct {
	logger *log.Logger
	attrs  []slog.Attr
	groups []string
}

func preserveStandardLogger(current *log.Logger) slog.Handler {
	return standardLogHandler{
		logger: log.New(current.Writer(), current.Prefix(), current.Flags()),
	}
}

func (h standardLogHandler) Enabled(context.Context, slog.Level) bool {
	return true
}

func (h standardLogHandler) Handle(_ context.Context, record slog.Record) error {
	parts := []string{record.Message}
	appendAttr := func(attr slog.Attr) bool {
		attr.Value = attr.Value.Resolve()
		keyParts := append(append([]string(nil), h.groups...), attr.Key)
		key := strings.Join(keyParts, ".")
		parts = append(parts, fmt.Sprintf("%s=%v", key, attr.Value.Any()))
		return true
	}
	for _, attr := range h.attrs {
		appendAttr(attr)
	}
	record.Attrs(appendAttr)
	return h.logger.Output(2, strings.Join(parts, " "))
}

func (h standardLogHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	h.attrs = append(append([]slog.Attr(nil), h.attrs...), attrs...)
	return h
}

func (h standardLogHandler) WithGroup(name string) slog.Handler {
	h.groups = append(append([]string(nil), h.groups...), name)
	return h
}

func metricExportInterval() time.Duration {
	if v := os.Getenv("OTEL_METRIC_EXPORT_INTERVAL"); v != "" {
		millis, err := strconv.Atoi(v)
		if err == nil && millis > 0 {
			return time.Duration(millis) * time.Millisecond
		}
	}
	return time.Second
}

func metricExportTimeout() time.Duration {
	if v := os.Getenv("OTEL_METRIC_EXPORT_TIMEOUT"); v != "" {
		millis, err := strconv.Atoi(v)
		if err == nil && millis > 0 {
			return time.Duration(millis) * time.Millisecond
		}
	}
	return 500 * time.Millisecond
}
```

The explicit `sdkmetric.WithInterval` and `sdkmetric.WithTimeout` are required
for local and eval runs. Do not rely on metric reader defaults; they can be too
slow for short-lived runtime checks, causing valid HTTP metrics to never reach
the collector before the process stops.

### Using in main()

```go
func main() {
	ctx := context.Background()
	// This service uses log.Default(). Snapshot its writer, prefix, and flags
	// before slog.SetDefault rewires it. Native slog apps pass their existing
	// handler here instead.
	existingLogHandler := preserveStandardLogger(log.Default())
	shutdown, err := initOTel(ctx, existingLogHandler)
	if err != nil {
		log.Fatalf("failed to initialize telemetry: %v", err)
	}
	defer shutdown(ctx)

	// ... start HTTP server, gRPC server, etc.
}
```

The example snapshots the detected standard logger, then fans each record out
to that preserved sink and one `otelslog` handler. This keeps its writer,
prefix, and flags while the standard `log` package continues through the
default slog logger on supported Go versions. If source-location flags or a
custom `Output` implementation cannot be reproduced exactly, leave the stack
unchanged and report `unsupported-stack`. For a native slog app, reuse its
actual handler rather than this adapter. Do not pass Go's untouched built-in
`slog.Default().Handler()` into the fan-out: `slog.SetDefault` also rewires the
standard logger, so calling that captured default handler can recurse. For a
project-owned `*slog.Logger`, apply the same fan-out at its construction site
instead of changing the process default.

Use context-aware logging inside traced work so `otelslog` can correlate the
record:

```go
slog.InfoContext(ctx, "order accepted", "order.type", "standard")
```

An unset `OTEL_LOGS_EXPORTER` is treated as `otlp`. Exact `none` and every
other explicit value skip the app-owned provider and bridge: `none` is the
operator opt-out, while another value belongs to an existing or
operator-configured exporter and must not be supplemented by local OTLP. Prove
that its provider/exporter/bridge actually exists; if only the environment
value exists, report `Not configured`. The
example assumes preflight found no existing log provider or bridge. If it did,
reuse that owner rather than registering another `LoggerProvider` or exporting
the same record twice.

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

For router-specific middleware (`otelmux`, `otelchi`, `otelgin`), see the
Framework Selection Guide above. These packages emit spans only -- always
use `otelhttp.NewHandler` as the outermost wrapper for HTTP server metrics.

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

Before adding a custom counter or histogram for an outcome that happens
inside a request `otelhttp.NewHandler` already wraps, check whether it
belongs as an attribute on `http.server.request.duration` instead — see
`../../SKILL.md` `#### Implementation Rules` and the `Go:` entry under
`#### Language-Specific Musts` for the `otelhttp.LabelerFromContext` pattern.
Only define a new instrument when the signal does not correlate 1:1 with a
single request (a queue-depth gauge, a background job outcome).

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

Use environment variables for operator-owned configuration. The only endpoint
literal in the SDK example is the signal-specific local Observer logs fallback,
which prevents a generic direct-cloud endpoint from becoming the implicit log
destination. The `otlptracehttp` and `otlpmetrichttp` exporters read their
configuration automatically.


| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Common OTLP HTTP endpoint |
| `OTEL_LOGS_EXPORTER` | `otlp` for Obstudio instrumentation | `none` disables the added local log pipeline; another explicit value remains operator-owned |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | `http://localhost:4318/v1/logs` for host/native Obstudio runs | Signal-specific local application-log destination |
| `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL` | `http/protobuf` for the shown local baseline | Select a matching official exporter for another explicit protocol |
| `OTEL_EXPORTER_OTLP_LOGS_HEADERS` | unset | Signal-specific operator log headers; generic cloud headers are rejected from the log path |
| `OTEL_SERVICE_NAME` | (must be set) | Service identity in telemetry |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metric export interval (ms) |
| `OTEL_METRIC_EXPORT_TIMEOUT` | `30000` | Metric export timeout (ms) |
| `OTEL_BSP_SCHEDULE_DELAY` | `5000` | Span batch export delay (ms) |


For local development with the Observer:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
OTEL_LOGS_EXPORTER=otlp \
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4318/v1/logs \
OTEL_METRIC_EXPORT_INTERVAL=1000 \
OTEL_METRIC_EXPORT_TIMEOUT=500 \
OTEL_BSP_SCHEDULE_DELAY=100 \
go run .
```

When creating `sdkmetric.NewPeriodicReader`, pass
`sdkmetric.WithInterval(metricExportInterval())` and
`sdkmetric.WithTimeout(metricExportTimeout())`, where the helper functions read
`OTEL_METRIC_EXPORT_INTERVAL` and `OTEL_METRIC_EXPORT_TIMEOUT`. This makes HTTP
metrics from `otelhttp`, including `http.server.request.duration` or the older
`http.server.duration` name, export promptly to Observer.

For Docker or Compose, use the checked-in local Observer service address (for
example `http://observer:4318/v1/logs`) instead of loopback. Preserve an
explicit `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`; do not derive the log destination
from `OTEL_EXPORTER_OTLP_ENDPOINT` when that generic value might point directly
to cloud ingest.

### Local Observer application logs and cloud boundary

Local OTLP application logs are the default for a detected supported Go
logging stack. An explicit `OTEL_LOGS_EXPORTER` or
`OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` wins; `none` omits the added provider,
processor, exporter, and bridge while the original stdout/file sink continues.
When traces or metrics use direct-cloud signal endpoints, keep the default logs
endpoint on local Observer. Never copy a Splunk ingest URL, realm, access token,
generic cloud header, cloud exporter, or forwarding flag into log
configuration. If an explicit logs endpoint is direct-cloud, preserve it as
operator configuration but do not add or claim an Obstudio-owned log pipeline;
report the boundary conflict for operator resolution. Obstudio cloud
forwarding remains traces and metrics only.

Add an in-memory SDK log test and a full local Observer runtime check. Emit one
sanitized application record at each required severity both outside and inside
an active span, then assert its exact body/category, severity, shared resource
including `service.name`, and trace/span IDs for the active-span record. Prove
the original stdout/file sink still receives it, exactly one OTel record exists
per application log call, `OTEL_LOGS_EXPORTER=none` produces no OTel record
while preserving the original sink, and the record is visible in the Obstudio
Explorer. When trace/metric cloud export is enabled, also prove no cloud log
endpoint, header, exporter, or forwarding path was configured.

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
- **Singleton providers**: `otel.SetTracerProvider`, `otel.SetMeterProvider`,
  and `global.SetLoggerProvider` must only be called once. If existing OTel
  setup exists, extend it.
- **One log bridge**: use only the official bridge matching the detected logger
  and prove one OTel record per call. Keep context-aware calls such as
  `slog.InfoContext` so active trace/span IDs reach the log record.
- **Metric export interval and timeout**: Always set `sdkmetric.WithInterval`
  and `sdkmetric.WithTimeout` on `sdkmetric.NewPeriodicReader`. Environment
  variables alone are not enough when constructing the reader manually.
- **Shutdown order**: shut down the LoggerProvider, TracerProvider, and
  MeterProvider so their batch processors flush before process exit. Attempt
  every shutdown even when an earlier one returns an error.
- **`runtime.Start()`**: this registers goroutine count, memory, and GC
  metrics. Call it after the MeterProvider is set.
