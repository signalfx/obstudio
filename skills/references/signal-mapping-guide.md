# Signal Mapping Guide

Reference for choosing the right OTel signal type for custom instrumentation.

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

## Trace-Derived Metrics

Many histogram metrics can be derived from trace span data by the
observability backend (Grafana Tempo, Jaeger, Splunk, etc.). This avoids
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
