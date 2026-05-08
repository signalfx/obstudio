# Detector Classification Rules

Rules for mapping metrics from an otel-audit report into detector categories.
Apply these rules in order; the first match wins.

## Classification Rules

### Latency

A metric is a **latency** detector candidate when:

- The metric name contains `.duration` (e.g. `http.server.request.duration`,
  `rpc.server.duration`, `db.client.operation.duration`)
- The metric type is histogram

These metrics measure response time and are best monitored with p99 percentile
thresholds.

### Error

A metric is an **error** detector candidate when:

- The metric name ends in `.total` or `.count` AND contains one of these
  keywords: `error`, `errors`, `failure`, `failures`, `failed`, `invalid`,
  `rejected`, `timeout`, `exception`
- Examples: `http.server.errors.total`, `rpc.server.failure.count`,
  `orders.invalid.total`

These metrics measure failure rates and are best monitored with sudden-change
detection against recent baselines.

### Throughput

A metric is a **throughput** detector candidate when:

- The metric name ends in `.total` or `.count` AND does NOT contain any of the
  error keywords listed above
- Examples: `http.server.requests.total`, `orders.processed.count`,
  `messages.consumed.total`

These metrics measure request/event volume and are best monitored with
sudden-change detection (both drops and spikes).

### Saturation

A metric is a **saturation** detector candidate when:

- The metric type is gauge (observable gauge, up-down counter)
- The metric name contains one of: `connections`, `pool`, `buffer`, `queue`,
  `lag`, `utilization`, `capacity`, `active`, `pending`, `heap`, `memory`,
  `goroutines`, `threads`
- Examples: `db.pool.connections.active`, `process.runtime.go.goroutines`,
  `kafka.consumer.lag`, `jvm.memory.heap.used`

These metrics measure resource consumption and are best monitored with static
thresholds.

## Exclusion Rules

Skip a metric (do not generate a detector) when:

1. **Auto-instrumented library duplicates** -- If both a library auto-instrumented
   metric and a custom metric measure the same signal, prefer the custom metric.
   Common library sources to skip when custom equivalents exist:
   - `redisotel` metrics when custom Redis metrics are present
   - `otelhttp` metrics when custom HTTP metrics are present
   - `otelgrpc` metrics when custom gRPC metrics are present

2. **Runtime/host metrics without actionable thresholds** -- Skip generic
   runtime metrics that lack meaningful static thresholds unless the user
   explicitly requests them:
   - `process.runtime.go.gc.count`
   - `process.runtime.go.mem.heap_alloc` (unless saturation threshold is defined)

3. **Informational-only metrics** -- Metrics that are purely informational
   and not suitable for alerting:
   - `process.uptime`
   - Version gauges

## Decision Flowchart

```
metric name contains ".duration"?
  → YES → latency detector
  → NO ↓

metric name ends with ".total" or ".count"?
  → YES → contains error keyword?
    → YES → error detector
    → NO  → throughput detector
  → NO ↓

metric type is gauge AND name matches saturation keywords?
  → YES → saturation detector
  → NO  → skip (no detector)
```

## Priority Order

When a metric could match multiple categories (rare), use this priority:

1. Latency (duration histograms are unambiguous)
2. Error (error counters are high-value signals)
3. Throughput (general counters)
4. Saturation (gauges)
