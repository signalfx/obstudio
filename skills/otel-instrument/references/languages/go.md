# Go OpenTelemetry Guide

Language-specific instrumentation guidance for Go services.

---

## Auto-Instrumentation Library Map

Use packages from `go.opentelemetry.io/contrib`. Only add instrumentations
matching the frameworks and clients detected in the codebase.


| Dependency               | Auto-instrumentation Package                                                              | Signals         | What It Covers                                                                          |
| ------------------------ | ----------------------------------------------------------------------------------------- | --------------- | --------------------------------------------------------------------------------------- |
| `net/http` (stdlib)      | `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp`                           | spans + metrics | HTTP server/client spans and version-dependent duration/body-size metrics                |
| `gorilla/mux`            | `go.opentelemetry.io/contrib/instrumentation/github.com/gorilla/mux/otelmux`              | spans only      | Route-aware HTTP spans                                                                  |
| `go-chi/chi`             | `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp` + version-aware current-span/labeler annotation | spans + metrics | HTTP server spans/metrics with explicit low-cardinality chi route patterns              |
| `gin-gonic/gin`          | `go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin`            | spans only      | Route-aware HTTP spans                                                                  |
| `google.golang.org/grpc` | `go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc`             | spans + metrics | gRPC client/server spans and metrics                                                    |
| `database/sql`           | `github.com/XSAM/otelsql`                                                                 | spans only      | SQL query spans with `db.statement`                                                     |
| `github.com/redis/go-redis/v9` | `github.com/redis/go-redis/extra/redisotel/v9`                                    | spans + metrics | Redis command spans and client metrics                                                  |
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

Framework-specific middleware packages such as `otelgin` and `otelmux` only
emit **spans** -- they do not register HTTP server metric instruments.
`otelhttp.NewHandler` adds HTTP spans and metrics. Do not stack two
span-producing server middleware layers merely to get both behaviors: that
emits duplicate server spans.
The exact metric names and set depend on the selected `otelhttp` version and
`OTEL_SEMCONV_STABILITY_OPT_IN` behavior. Inspect the selected module source or
runtime output before declaring names; never infer `http.server.active_requests`
from the wrapper alone.

**Default rule:** use `otelhttp.NewHandler` as the sole outer server-span
producer. Add a non-span-producing route annotator inside it when route
patterns are needed. If you instead choose framework middleware for its span
naming, do not also wrap it with another span-producing handler; record that
the `otelhttp` server metrics are absent unless separately instrumented.

### chi

Preferred (spans + metrics):

```go
handler := otelhttp.NewHandler(r, "server")
http.ListenAndServe(":8080", handler)
```

There is no official OpenTelemetry Go contrib `otelchi` module. Do not probe
for or add the nonexistent
`go.opentelemetry.io/contrib/instrumentation/github.com/go-chi/chi/otelchi`
package. Inspect the selected `otelhttp` module source once before writing the
route wrapper. Use `otelhttp.WithRouteTag` only when that exact source exports
it; the API is absent in v0.65.0 and later. Do not discover the mismatch by
repeated compile-and-repair probes.

For v0.65.0 and later, annotate the current outer server span and its existing
metric labeler without starting a span:

```go
func withRoute(pattern string, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		route := attribute.String("http.route", pattern)
		trace.SpanFromContext(r.Context()).SetAttributes(route)
		if labeler, ok := otelhttp.LabelerFromContext(r.Context()); ok {
			labeler.Add(route)
		}
		next(w, r)
	}
}

r.Get("/tasks/{id}", withRoute("/tasks/{id}", getTask))
handler := otelhttp.NewHandler(r, "server")
```

When the selected pre-v0.65.0 source does export `WithRouteTag`, it may replace
the helper above, but adapt its returned `http.Handler` to chi's
`http.HandlerFunc` registration:

```go
r.Get("/tasks/{id}", otelhttp.WithRouteTag(
	"/tasks/{id}",
	http.HandlerFunc(getTask),
).ServeHTTP)
```

It sets `http.route` on the current span and the `otelhttp` metric labeler; it
does not rename the outer span. If route-pattern span names are an explicit
requirement, rename that current span after route matching and prove the name
in a recorder test; do not start a second server span.

### gin

Preferred (spans + metrics):

```go
handler := otelhttp.NewHandler(ginEngine, "server")
http.ListenAndServe(":8080", handler)
```

For route attributes or names plus `otelhttp` metrics, add a gin middleware
that reads the matched full path after `Next`, updates the current outer span,
and adds the same `http.route` value to the `otelhttp` labeler without starting
another span. Alternatively use `otelgin.Middleware` alone for route-aware
spans and record the missing `otelhttp` server metrics.

### gorilla/mux

Preferred (spans + metrics):

```go
handler := otelhttp.NewHandler(router, "server")
http.ListenAndServe(":8080", handler)
```

For route attributes or names plus `otelhttp` metrics, add non-span-producing
middleware that reads `mux.CurrentRoute(r).GetPathTemplate()`, updates the
current outer span, and adds the same `http.route` value to the `otelhttp`
labeler. Alternatively use `otelmux.Middleware` alone for route-aware spans and
record the missing `otelhttp` server metrics.

### Adding a new framework

Follow this template:

```
### {framework-name}

Preferred (spans + metrics):
  handler := otelhttp.NewHandler({router}, "server")

Route-aware spans without otelhttp metrics:
  {router}.Use({framework-package}.Middleware("server"))

Spans + metrics with route data:
  add non-span-producing middleware that annotates the outer otelhttp span and labeler
  handler := otelhttp.NewHandler({router}, "server")
```

---

## Dependencies

Read `go.mod` first. Use the cache-backed resolver only for the standard HTTP
bootstrap: the task needs `otelhttp`, core/SDK, and trace + metric OTLP-HTTP
exporters, and the project has no `go.opentelemetry.io` requirements or
main-module `replace`/`exclude` directives. Run it exactly once:

```bash
python3 -I \
  "<directory-containing-loaded-SKILL.md>/scripts/resolve_go_otel_versions.py" \
  --project "<service-root>"
```

Resolve the script from the loaded `otel-instrument` skill directory. Pass
`--gomodcache "<path>"` only when the selected project runtime uses a specific
cache; otherwise the helper reads `GOMODCACHE`, then `GOPATH`, then the default
Go cache location. The helper is dependency-free and read-only: it never runs
Go, invokes a shell, or edits `go.mod`/`go.sum`. For an already-instrumented
project, a non-HTTP service, a different exporter family, or a custom-only edit
that needs no dependency change, skip this fixed-bundle resolver. Preserve the
project's existing OTel family and use its configured Go dependency workflow.

There are exactly two authorized bootstrap branches.

**Full-closure branch.** Run the sibling runner's `--action go-get` when all
three resolver conditions are true:

- `status` is `complete`
- `complete` is `true`
- `go_get.ready` is `true`

Readiness means the file proxy contains non-empty `.mod`, `.info`, `.zip`, and
`.ziphash` artifacts for the full selected dependency closure of the existing
project plus `otelhttp`, core OTel, the SDK, and both OTLP HTTP exporters in one
compatible release family. Every selected module must support the project's Go
version. Metadata-only or direct-bundle-only versions are not runnable
candidates.

**Import-reachable probe branch.** When the resolver is incomplete and
`bootstrap_probe.eligible` is `true`, run exactly once:

```bash
python3 -I \
  "<directory-containing-loaded-SKILL.md>/scripts/run_go_otel_command.py" \
  --project "<service-root>" --action probe-bootstrap
```

The runner stages fixed standard-HTTP imports below its owned project-local
directory, executes one captured `go mod tidy` with the isolated file-only
proxy, verifies the source, directives, and exact pins, removes the stage and
read-only cache payloads without flooding output, and writes a drift-bound
accepted-plan ledger. `status: accepted` proves only import-reachable dependency
resolution for those fixed imports. It does not prove application compilation,
tests, instrumentation, export, or runtime telemetry. A blocked result is
terminal: leave dependencies unchanged and report its compact reason. Do not
read `candidate_rejections` to choose a version, run cache archaeology, or
substitute a manual `GOMODCACHE=... go ...` command.

After either a complete full-closure plan or an accepted bootstrap probe,
execute the exact pinned dependency edit with:

```bash
python3 -I \
  "<directory-containing-loaded-SKILL.md>/scripts/run_go_otel_command.py" \
  --project "<service-root>" --action go-get
```

The runner reloads the canonical sibling resolver, requires either its complete
plan or the matching probed ledger, snapshots `go.mod`/`go.sum`, and rolls both
back if `go get` or the post-edit invariant checks fail. On success it advances
the ledger to `applied`, bound to the new hashes, unchanged module/go/toolchain
directives, and exact intended OTel pins. It validates that owned paths stay
below the project with no symlink escape, scrubs conflicting inherited Go
environment values, and invokes Go with argv rather than a shell. Never copy
`go_get.env` into an `env KEY=value ...` command; values such as `GOVCS=*:off`,
empty values, and paths with spaces are intentionally handled by the runner.

On this resolver-backed bootstrap branch, use the same runner for every later
Go command in this run:

```bash
python3 -I <runner> --project "<service-root>" -- go mod tidy
python3 -I <runner> --project "<service-root>" -- go test ./...
python3 -I <runner> --project "<service-root>" -- go build ./...
python3 -I <runner> --project "<service-root>" -- go list ./...
python3 -I <runner> --project "<service-root>" -- go run <target>
```

Only `go mod tidy`, `go test`, `go build`, `go list`, and `go run` are accepted
as explicit follow-up commands. Dependency changes and cleanup require their
named actions, and external-tool flags such as `-exec`, `-toolexec`, and
`-vettool` are rejected. This keeps temporary dependency and build state inside
the two resolver-owned cache paths and prevents a second download/cache branch.
The runner is argv-safe and cache-isolated, not a sandbox: project builds,
tests, generators, and applications still execute trusted project code.

The environment isolates `HOME`, `GOPATH`, `GOMODCACHE`, and `GOCACHE` under
the project, uses the detected cache's download directory as a file-only
`GOPROXY`, disables the checksum database and VCS fallback, and forbids
automatic toolchain switching. Do not replace a pin with `@latest`, add an
unpinned OTel module, manually copy cache artifacts, probe the home cache, or
repeat version/cache commands when the plan is ready.

Treat both resolver and probe results as dependency candidates, not application
proof. After the edit, inspect the `go.mod`/`go.sum` diff, run the required
runner-backed tidy/build/test commands, and prove the imports used by the
implementation. The runner rejects directive, exact-pin, hash, or ledger drift;
do not bypass that rejection.

Defer cleanup until all source and report edits, verification decisions, final
code review, and required runner-backed Go validation are complete. Do not run
it merely because an initial tidy/test/build pass succeeded. If final review
causes an edit, repeat every affected runner-backed validation. Then, as the
final project command, run:
`python3 -I <runner> --project "<service-root>" --action cleanup`. The runner
removes its accepted-plan ledger, probe stage, and read-only owned caches with a
compact result. After cleanup, do not rerun the resolver, edit the project, or
run another Go command. Do not run `rm`, any `find` inspection/deletion,
recursive `chmod`, or another cleanup command. Never recover with a manual
`GOCACHE`, `GOMODCACHE`, or `go` branch. Some Go toolchains write small local
telemetry bookkeeping below the isolated `HOME`; that state cannot reach the
user's home directory and is not a build/module cache payload.

Run this cleanup exactly once after the applicable terminal check: the canonical
`instrumentation-final-gate`, the explicit canonical no-child validation when
verification was opted out or concretely blocked before an overlay could be
written, or the legacy no-audit validation defined by the skill. Successful
cleanup is the terminal boundary: emit the final response immediately. Do not
follow it with `git status`, `git diff`, a `go.sum` inspection, cache
inspection/removal, file or artifact listings, repeated validators/tests, or
duplicate final review. If cleanup fails, report that exact failure immediately
rather than starting a manual cleanup or inspection branch.

For `incomplete` or `no-candidate`, use only an eligible runner bootstrap probe.
If it is ineligible or blocked, do not execute `go_get`, inspect rejection rows
to choose pins, run a version/cache lookup, or start a probe loop. An
`existing-otel-dependencies` or unsupported main-module directive reason routes
back to the project's selected versions and normal dependency workflow; it does
not authorize an upgrade. Otherwise leave dependencies unchanged and report the
exact compact blocker.

---

## SDK Initialization

Create a dedicated file for OTel setup that returns a shutdown function.
Call it early in `main()`.
Honor the project's `go` directive when choosing standard-library APIs. This
template deliberately avoids `errors.Join` so it remains usable before Go 1.20;
do not replace the compatibility helper unless the project directive permits it.

**File**: `otel.go`

```go
package main

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

func initOTel(ctx context.Context) (func(context.Context) error, error) {
	res, err := resource.New(ctx,
		resource.WithFromEnv(),
		resource.WithTelemetrySDK(),
	)
	if err != nil {
		return nil, err
	}
	if _, present := res.Set().Value(attribute.Key("service.name")); !present {
		res, err = resource.Merge(res, resource.NewSchemaless(
			attribute.String("service.name", "my-service"),
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
		return nil, combineErrors(err, tp.Shutdown(ctx))
	}

	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(
			metricExporter,
			sdkmetric.WithInterval(metricExportInterval()),
			sdkmetric.WithTimeout(metricExportTimeout()),
		)),
		sdkmetric.WithResource(res),
	)
	otel.SetTracerProvider(tp)
	otel.SetMeterProvider(mp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	shutdown := func(ctx context.Context) error {
		return combineErrors(tp.Shutdown(ctx), mp.Shutdown(ctx))
	}
	return shutdown, nil
}

// combineErrors preserves the primary error and the secondary cleanup failure
// without requiring errors.Join, which was added in Go 1.20.
func combineErrors(primary, secondary error) error {
	if primary == nil {
		return secondary
	}
	if secondary == nil {
		return primary
	}
	return fmt.Errorf("%w; additional error: %v", primary, secondary)
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
	shutdown := func(context.Context) error { return nil }
	if otelShutdown, err := initOTel(ctx); err != nil {
		log.Printf("telemetry disabled: %v", err)
	} else {
		shutdown = otelShutdown
	}
	defer func() {
		if err := shutdown(ctx); err != nil {
			log.Printf("telemetry shutdown: %v", err)
		}
	}()

	// ... start HTTP server, gRPC server, etc.
}
```

Preserve the application's existing startup policy. The fail-open example
keeps a previously runnable service available when telemetry initialization
fails. Use fail-closed telemetry startup only when repository evidence or the
user explicitly makes telemetry readiness-critical. Add runtime/host metrics
only when requested or audit-required; the minimal HTTP setup intentionally
does not add `go.opentelemetry.io/contrib/instrumentation/runtime`.

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

For router-specific integration, see the Framework Selection Guide above. For
chi, use `otelhttp.WithRouteTag` only when the selected module source exports
it. With v0.65.0 and later, annotate the current span through
`trace.SpanFromContext` and the current request metrics through
`otelhttp.LabelerFromContext` without starting another span. `otelmux` and
`otelgin` emit spans; do not stack either under another span-producing wrapper.
Use a non-span-producing route annotator with the outer `otelhttp.NewHandler`
when both one server span and HTTP server metrics are required.

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

Use that pattern for actual application/transport errors and custom-span
failures. For an `otelhttp` SERVER span, preserve HTTP semantic conventions:
the handler auto-sets ERROR for 5xx responses, while an ordinary handled 4xx
response leaves span status unset. Do not add `RecordError`/`SetStatus` merely
because a handler intentionally returned 400, 404, or 409.

---

## OTLP Export Configuration

All configuration is via environment variables. Do not hardcode endpoints.
The `otlptracehttp` and `otlpmetrichttp` exporters read these automatically.


| Variable                      | Default                 | Purpose                       |
| ----------------------------- | ----------------------- | ----------------------------- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP HTTP endpoint            |
| `OTEL_SERVICE_NAME`           | (must be set)           | Service identity in telemetry |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000`                 | Metric export interval (ms)   |
| `OTEL_METRIC_EXPORT_TIMEOUT`  | `30000`                 | Metric export timeout (ms)    |
| `OTEL_BSP_SCHEDULE_DELAY`     | `5000`                  | Span batch export delay (ms)  |


For local development with the Observer:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
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
- **Metric export interval and timeout**: Always set `sdkmetric.WithInterval`
  and `sdkmetric.WithTimeout` on `sdkmetric.NewPeriodicReader`. Environment
  variables alone are not enough when constructing the reader manually.
- **Shutdown order**: shut down the TracerProvider before the MeterProvider
  so in-flight spans are flushed before metrics.
- **`runtime.Start()`**: this registers goroutine count, memory, and GC
  metrics. Call it after the MeterProvider is set.
