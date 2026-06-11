# Detector Classification Rules

Rules for mapping metrics from an otel-audit report into detector categories.
Apply these rules in order; the first match wins.

## Classification Rules

Apply GenAI-specific and incident-readiness categories before generic RED
categories. GenAI, impact classification, auth/edge, customer impact,
freshness, backpressure, dependency, and capacity signals are usually more
useful for incident detection and localization than generic throughput when the
metric names and dimensions make the domain clear.

### GenAI

Classify GenAI metrics before generic latency, error, dependency, throughput,
or saturation categories, but require explicit GenAI context. A metric has
GenAI context when the audit contains a `## GenAI Readiness` section for the
owning workflow, or when the metric/dimensions contain explicit terms such as
`gen_ai`, `llm`, `inference`, `embedding`, `model_provider`, `model.deployment`,
`agent`, `function_call`, `execute_tool`, `retrieval`, `rag`, or provider names.
Do not classify generic `model`, `workflow`, `tool`, `config`, `canary`, or
`chat` metrics as GenAI by name alone; many non-GenAI services use those words.

A metric is a **genai-latency** detector candidate when:

- The metric name is `gen_ai.client.operation.duration`
- OR the metric has GenAI context and the metric name contains one of:
  `gen_ai`, `llm`, `inference`, `completion`, `chat`, `embedding`, `agent`,
  `workflow`, `model_provider`, `model.deployment`
- AND it measures operation duration, workflow duration, first-token latency,
  first-chunk latency, stream chunk latency, or end-to-end response time

A metric is a **genai-token-pressure** detector candidate when:

- The metric name is `gen_ai.client.token.usage`
- OR the metric has GenAI context and the metric name contains one of: `token`,
  `prompt`, `completion`, `context`, `cache_read`, `cache_create`
- AND it measures input, output, total, cached, prompt, completion, context,
  request, or response token volume

A metric is a **genai-provider** detector candidate when:

- The metric has GenAI context and the metric name contains one of: `gen_ai`,
  `llm`, `provider`, `model_provider`, `model.deployment`, `inference`,
  `completion`, `embedding`
- AND it measures provider/model timeout, rate limit, throttle, 5xx,
  unavailable, retry, fallback selected, fallback failed, region, or deployment
  error signals

A metric is a **genai-tool** detector candidate when:

- The metric has GenAI context and the metric name contains one of: `tool`,
  `function_call`, `execute_tool`
- AND it measures tool duration, success, error, timeout, failure class, or
  tool-call count per workflow

A metric is a **genai-model-config** detector candidate when:

- The metric has GenAI context and the metric name contains one of:
  `request.model`, `response.model`, `model.config`, `model_config`,
  `model.deployment`, `deployment.readiness`, `model.readiness`,
  `model_resolution`, `config.version`, `feature_flag`, `canary`
- AND it measures model/deployment readiness, failed model resolution,
  requested-vs-response model mismatch, rollout, canary, config, or feature
  flag state

A metric is a **genai-workflow-fanout** detector candidate when:

- The metric has GenAI context and the metric name contains one of:
  `llm_call_count`, `model_call_count`, `tool_call_count`, `agent_call_count`,
  `workflow_fanout`, `nested_agent`, `workflow.timeout`, `workflow.outcome`
- AND it measures per-request LLM calls, tool calls, nested agent calls,
  workflow fanout, workflow outcome, or workflow timeout

A metric is a **genai-retrieval** detector candidate when:

- The metric has GenAI context and the metric name contains one of:
  `retrieval`, `rag`, `vector`, `embedding`, `rerank`
- AND it measures retrieval duration, errors, no-result rate, stale-result
  rate, vector search dependency health, or retrieval freshness

### Impact Classification

A metric is an **impact-classification** detector candidate when:

- The metric name contains one of: `impact`, `availability`, `synthetic`,
  `client_telemetry`, `workflow.state`, `workflow.outcome`, `degraded`,
  `unavailable`
- AND the metric can be grouped by low-cardinality workflow, region/environment,
  service, dependency, or release dimensions

These metrics distinguish app down from degraded API, workflow, auth, ingest,
or delivery impact. They should use critical thresholds for unavailable impact and
major/critical thresholds for degraded workflow impact.

### Auth/Edge

A metric is an **auth-edge** detector candidate when:

- The metric name contains one of: `login`, `auth`, `identity_provider`,
  `token`, `session`, `domain_route`, `domain.routing`, `domain-routing`,
  `dns`, `tls`, `cert`, `certificate`, `gateway`, `edge`, `edge.route`,
  `gateway.route`
- AND the metric measures duration, success, error, timeout, expiry, or
  unavailable outcomes

Auth/edge metrics should prioritize authentication, domain-routing, TLS, and
certificate failures because they often appear as generic HTTP failures unless
the service emits a more specific outcome or failure class.

### Customer Impact

A metric is a **customer-impact** detector candidate when:

- The metric name contains one of: `workflow`, `render`, `load`,
  `transaction`, `checkout`, `delivery`, `customer_impact`
- AND the metric measures duration, success, error, degraded, timeout, or
  unavailable outcomes

These metrics answer whether customers are down or degraded and should use
critical workflow success/error and latency thresholds.

### Freshness

A metric is a **freshness** detector candidate when:

- The metric name contains one of: `freshness`, `newest_event_age`,
  `event.age`, `ingest.lag`, `processing.lag`, `data.age`, `staleness`
- The metric measures age or lag as a gauge or histogram

Freshness metrics should use static warning/critical thresholds because stale
data is often customer-impacting before request RED signals move.

### Backpressure

A metric is a **backpressure** detector candidate when:

- The metric name contains one of: `queue.depth`, `queue.size`,
  `consumer.lag`, `oldest_message_age`, `rebalance`, `paused_consumer`,
  `blocked_consumer`, `backpressure`
- The source is a queue, worker, stream consumer, or async task processor

Backpressure metrics should use static thresholds for lag/depth/age and
sudden-change detection for rebalance count.

### Dependency

A metric is a **dependency** detector candidate when:

- The metric name contains one of: `dependency`, `client`, `external`,
  `datastore`, `database`, `search`, `cache`, `broker`, `stream`, `cloud`,
  `endpoint_health`, `target_health`, `availability`, `unavailable`,
  `unhealthy`
- AND the metric measures `.duration`, `error`, `timeout`, `retry`,
  `rate_limit`, `throttle`, `circuit_breaker`, endpoint health, target health,
  availability, unhealthy target count, or operation failure

Dependency metrics should be grouped by low-cardinality dependency and
operation dimensions when those dimensions exist.

### Capacity Saturation

A metric is a **capacity-saturation** detector candidate when:

- The metric name contains one of: `capacity`, `utilization`, `memory`, `heap`,
  `cpu`, `disk`, `filesystem`, `fs.`, `jvm`, `threadpool`, `thread_pool`,
  `worker.active`, `inflight`, `concurrency`, `desired`, `healthy`,
  `readiness`, `startup`, `healthcheck`, `quota`, `throttle`, `rate_limit`,
  `restart`, `crashloop`, `pod`, `node`, `task`, `process`, `hpa`, `asg`
- The metric is a gauge/up-down counter, or a counter for throttled/rejected
  work, restarts, crash-loop events, readiness/startup failures, healthcheck
  failures, desired-vs-healthy gaps, or quota/rate-limit breaches

Capacity-saturation metrics should use static thresholds for utilization/quota,
disk/filesystem pressure, startup/readiness/healthcheck failures, and
sudden-change detection for throttles/restarts.

For source-backed CPU utilization, create a CPU saturation detector only from
normalized CPU utilization. Do not use thread count, goroutine count, worker
count, or pool size as CPU saturation. If the audit only proves cumulative CPU time,
use it as a diagnostic rate with `rollup='rate'` and list normalized CPU
utilization as a missing prerequisite instead of claiming CPU saturation coverage.

### Release Context

A metric or metric dimension is a **release-context** candidate when:

- The metric or dimension name contains one of: `service.version`,
  `deployment.environment`, `deployment.region`, `deployment.platform`,
  `container.image.tag`, `artifact.version`, `artifact_version`,
  `config.version`, `config_version`, `feature_flag`, `canary`, `rollout`,
  `build.version`, or `image.tag`
- AND the value is stable and low-cardinality enough for dashboard filters,
  event overlays, or detector dimensions

Release-context data should be used to correlate incidents to releases,
config changes, platforms, regions, images, and canary/rollout batches. It is
not a standalone alert metric unless another rule also matches a health,
latency, error, dependency, or capacity signal. When a metric has both release
context and a detector-worthy signal, classify the metric by the detector-worthy
signal and use the release context as a dashboard filter or detector dimension.
Classify pure release/config/version metadata as `release-context` only after no
detector-worthy category matches.

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
  `disk`, `filesystem`, `goroutines`, `threads`
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
metric name starts with "gen_ai." or audit has GenAI Readiness plus explicit genai/llm/inference/embedding/model-provider/agent/tool-call/retrieval keyword?
  -> YES -> genai-* detector using GenAI rules above
  -> NO

metric name contains impact/availability/synthetic/client telemetry keyword?
  -> YES -> impact-classification detector
  -> NO

metric name contains specific auth/edge keyword?
  -> YES -> auth-edge detector
  -> NO

metric name contains customer workflow keyword?
  -> YES -> customer-impact detector
  -> NO

metric name contains freshness/lag/age keyword?
  -> YES -> freshness detector
  -> NO

metric name contains queue/backpressure keyword?
  -> YES -> backpressure detector
  -> NO

metric name contains capacity/disk/readiness/healthcheck/quota/throttle/restart keyword?
  -> YES -> capacity-saturation detector
  -> NO

metric name contains ".duration"?
  -> YES -> customer-impact or dependency keyword present?
    -> YES -> customer-impact or dependency detector
    -> NO  -> latency detector
  -> NO

metric name ends with ".total" or ".count"?
  -> YES -> customer-impact or dependency keyword present?
    -> YES -> customer-impact or dependency detector
    -> NO  -> contains error keyword?
      -> YES -> error detector
      -> NO  -> throughput detector
  -> NO

metric type is gauge AND name matches saturation keywords?
  -> YES -> capacity-saturation when incident/capacity keyword is present, otherwise saturation detector
  -> NO

metric or dimension contains service.version/deployment.region/deployment.platform/container.image.tag/artifact version/config/canary/rollout keyword?
  -> YES -> pure release-context dashboard filter or detector dimension, not standalone alert
  -> NO  -> skip (no detector)
```

## Priority Order

When a metric could match multiple categories (rare), use this priority:

1. GenAI categories (provider/model/tool/retrieval/token/fanout signals before generic RED)
2. Impact Classification (answers app-down vs degraded first)
3. Auth/Edge (auth/domain-routing/certificate failures are high-impact)
4. Customer Impact (answers user-visible workflow health)
5. Freshness (stale data is often invisible to request RED)
6. Backpressure (lag and queue pressure are early incident indicators)
7. Dependency (root-cause signals for downstream failures)
8. Capacity Saturation (resource/quota pressure before drops/outage)
9. Latency (generic duration histograms)
10. Error (generic error counters)
11. Throughput (general counters)
12. Saturation (generic gauges)
13. Release Context (dashboard filters and health-signal dimensions only after no detector-worthy category matches)
