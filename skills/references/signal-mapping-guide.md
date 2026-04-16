# Signal Mapping Guide

Reference for mapping KPIs to OpenTelemetry signal types across languages.

---

## Signal Type Decision Tree

Use this to decide which signal(s) an SLI needs:

```
Is the SLI a point-in-time measurement of current state?
  YES → Gauge metric (Category: Custom) in Metrics table
  NO  ↓

Is the SLI counting occurrences of an event?
  YES → Counter metric (Metrics table) + consider Log event (Logs table) for context
  NO  ↓

Is the SLI measuring duration or distribution?
  YES → Histogram metric
        Can it be derived from trace span duration?
          YES → Category: Derived in Metrics table (no explicit emission needed)
          NO  → Category: Custom or OOB in Metrics table
  NO  ↓

Is the SLI tracking a request/operation flow?
  YES → Span entry in Spans table
  NO  → Log event in Logs table
```

### When an SLI maps to multiple signals

A single SLI often appears in the SLIs column of more than one signal table.

| Scenario | Signal Tables | Rationale |
|----------|---------------|-----------|
| Error during operation | Metrics (counter) + Spans (span error) + Logs (details) | Counter for alerting, span for context, log for debugging |
| Slow operation | Spans + Metrics (Derived histogram, or Custom if not trace-derived) | Span shows where time was spent |
| State transition | Logs (event) + Metrics (gauge) | Log captures before/after, gauge shows current |
| Throughput | Metrics (counter) only | Simple monotonic count, trace overhead not justified |
| Resource utilization | Metrics (gauge) only | Periodic observation, no request context |

---

## Trace-Derived Metrics

Many histogram metrics can be derived from trace span data by the
observability backend (Splunk, Grafana Tempo, Jaeger). This avoids
double-counting and reduces instrumentation effort.

### When to use trace-derived metrics

- The span already captures the operation's start and end time
- The backend supports span-to-metrics conversion (most modern backends do)
- You need percentile distributions (p50, p95, p99)

### When to use explicit metrics instead

- High-cardinality dimensions not suitable for spans
- The operation is too lightweight to justify a span
- You need real-time counter aggregation faster than trace pipelines
- The metric must survive when tracing is sampled

### Common trace-derivable SLIs

| SLI | Span Name Pattern | Derived Metric |
|-----|-------------------|----------------|
| HTTP request latency | `GET /api/resource` | Duration histogram by route |
| DB query latency | `redis.get`, `sql.query` | Duration histogram by operation |
| RPC call latency | `grpc.client/service.Method` | Duration histogram by method |
| Message processing time | `broker.consume` | Duration histogram by topic |

---

## Metric Type Reference

| Type | OTel API | Use Case | Example |
|-----------|-------------------------------|-----------------------------------------------|--------------------------------------|
| Counter | `Int64Counter` / `Float64Counter` | Monotonically increasing counts | Requests served, errors occurred |
| Histogram | `Float64Histogram` | Distributions (latency, size) | Request duration, payload size |
| Gauge | `Int64ObservableGauge` | Point-in-time snapshots | Active connections, queue depth |
| UpDownCounter | `Int64UpDownCounter` | Values that increase and decrease | In-flight requests, items in cache |

### Naming conventions

- Use dots as separators: `http.server.request.duration`
- Include units in the metric name or unit field: `duration` (seconds), `size` (bytes), `count`
- Standard suffixes: `.count`, `.duration`, `.total`, `.size`
- Prefix with component: `http.`, `db.`, `broker.`, `cache.`

---

## Language-Specific OTel Patterns

### Go

```go
import (
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/attribute"
    "go.opentelemetry.io/otel/codes"
    "go.opentelemetry.io/otel/metric"
    "go.opentelemetry.io/otel/trace"
)

// Package-level tracer and meter
var (
    tracer = otel.Tracer("myservice/repository")
    meter  = otel.Meter("myservice")
)

// Counter
opCount, _ := meter.Int64Counter("repository.operations.count",
    metric.WithDescription("Total repository operations"),
    metric.WithUnit("{operations}"))

// Histogram
opDuration, _ := meter.Float64Histogram("repository.operation.duration",
    metric.WithDescription("Repository operation duration"),
    metric.WithUnit("s"))

// Gauge (observable)
meter.Int64ObservableGauge("repository.pool.active",
    metric.WithDescription("Active connections in pool"),
    metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
        o.Observe(getActiveConns())
        return nil
    }))

// Span with attributes and error handling
func (r *Repo) Get(ctx context.Context, id string) (*Item, error) {
    ctx, span := tracer.Start(ctx, "repository.get",
        trace.WithAttributes(attribute.String("item.id", id)))
    defer span.End()

    item, err := r.db.Get(ctx, id)
    if err != nil {
        span.RecordError(err)
        span.SetStatus(codes.Error, "get failed")
        return nil, err
    }
    return item, nil
}
```

### Python

```python
from opentelemetry import trace, metrics

tracer = trace.get_tracer("myservice.repository")
meter = metrics.get_meter("myservice")

op_counter = meter.create_counter(
    "repository.operations.count",
    description="Total repository operations",
    unit="{operations}",
)

op_histogram = meter.create_histogram(
    "repository.operation.duration",
    description="Repository operation duration",
    unit="s",
)

@tracer.start_as_current_span("repository.get", attributes={"item.id": item_id})
def get_item(item_id: str):
    span = trace.get_current_span()
    try:
        result = db.get(item_id)
        op_counter.add(1, {"operation": "get"})
        return result
    except Exception as e:
        span.record_exception(e)
        span.set_status(trace.StatusCode.ERROR, str(e))
        raise
```

### Node.js (TypeScript)

```typescript
import { trace, metrics, SpanStatusCode } from '@opentelemetry/api';

const tracer = trace.getTracer('myservice/repository');
const meter = metrics.getMeter('myservice');

const opCounter = meter.createCounter('repository.operations.count', {
  description: 'Total repository operations',
  unit: '{operations}',
});

const opHistogram = meter.createHistogram('repository.operation.duration', {
  description: 'Repository operation duration',
  unit: 's',
});

async function getItem(id: string): Promise<Item> {
  return tracer.startActiveSpan('repository.get', { attributes: { 'item.id': id } },
    async (span) => {
      try {
        const result = await db.get(id);
        opCounter.add(1, { operation: 'get' });
        return result;
      } catch (err) {
        span.recordException(err);
        span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
        throw err;
      } finally {
        span.end();
      }
    });
}
```

### Java

```java
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.metrics.Meter;
import io.opentelemetry.api.metrics.LongCounter;

// With Java agent auto-instrumentation, most HTTP/DB spans are automatic.
// Use annotations for custom spans:

@WithSpan("repository.get")
public Item getItem(@SpanAttribute("item.id") String id) {
    Span span = Span.current();
    try {
        Item result = db.get(id);
        opCounter.add(1, Attributes.of(stringKey("operation"), "get"));
        return result;
    } catch (Exception e) {
        span.recordException(e);
        span.setStatus(StatusCode.ERROR, e.getMessage());
        throw e;
    }
}
```

---

## Standard Auto-Instrumentation KPIs by Language

These signals are provided automatically when using OTel auto-instrumentation
libraries. Mark them as `OOB` category in the Spans and Metrics tables.

| Signal Category | Go | Python | Node.js | Java |
|-------------------------|-----------------------|--------------------|-----------------------|---------------------|
| HTTP server metrics | otelmux / otelhttp | opentelemetry-instrumentation-flask/django/fastapi | @opentelemetry/instrumentation-http | javaagent (Servlet) |
| HTTP client metrics | otelhttp RoundTripper | opentelemetry-instrumentation-requests/httpx | @opentelemetry/instrumentation-http | javaagent |
| Database spans | otelredis / otelsql | opentelemetry-instrumentation-sqlalchemy/psycopg2 | @opentelemetry/instrumentation-pg/mysql | javaagent (JDBC) |
| gRPC spans/metrics | otelgrpc | opentelemetry-instrumentation-grpc | @opentelemetry/instrumentation-grpc | javaagent |
| Runtime metrics | runtime/metrics | opentelemetry-instrumentation-system-metrics | (manual setup) | javaagent (JVM) |
| Message queue spans | (manual) | opentelemetry-instrumentation-celery/kafka | @opentelemetry/instrumentation-kafkajs | javaagent (Kafka) |

---

## Structured Log Events for Trace Correlation

When adding log events that should correlate with traces:

1. Always include `trace_id` and `span_id` from the current context
2. Use structured fields, not string interpolation
3. For errors, also call `span.RecordError()` so the trace shows the error
4. Use span events (`span.AddEvent()`) for significant occurrences within a span

### Log event naming convention

- `{component}.{entity}.{action}` for state changes: `opamp.agent.registered`
- `{component}.{operation}.{outcome}` for results: `broker.publish.failed`
- `{component}.{resource}.{condition}` for alerts: `health.agent.status_changed`
