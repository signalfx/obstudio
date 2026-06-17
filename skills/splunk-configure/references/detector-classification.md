# Detector Classification Rules

Rules for mapping metrics from an otel-audit report into detector categories.
Apply these rules in order; the first match wins.

## Classification Rules

### GenAI

Classify GenAI metrics before generic latency, error, throughput, or
saturation categories, but require explicit GenAI context. A metric has GenAI
context when the audit contains a `## GenAI Readiness` section for the owning
workflow, or when the metric/dimensions contain explicit terms such as
`gen_ai`, `llm`, `inference`, `embedding`, `model_provider`,
`model.deployment`, `agent`, `function_call`, `execute_tool`, `retrieval`,
`rag`, `hallucination`, `toxicity`, `factuality`, or provider names. Do not classify generic `model`, `workflow`, `tool`, `config`, `canary`, `token`,
`session`, `chat`, `memory`, `context`, `evaluation`, `evaluator`, `quality`,
`cost`, or `billing` metrics as GenAI by name alone; many non-GenAI services
use those words. Those generic words require audit evidence that the owning
workflow is a GenAI/LLM path.

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

A metric is a **genai-memory-context** detector candidate when:

- The metric has GenAI context and the metric name contains one of:
  `memory`, `context`, `session_state`, `chat_history`, `conversation_state`,
  `search_memory`, `create_memory`, `update_memory`, `upsert_memory`,
  `delete_memory`
- AND it measures memory/context duration, outcome, error, timeout, hit/miss,
  stale result, missing context, record count, source/version, or
  permission/auth failure

A metric is a **genai-evaluation-quality** detector candidate when:

- The metric name starts with `gen_ai.evaluation.` or the metric has GenAI
  context and the metric name contains one of: `evaluation`, `evaluator`,
  `eval_score`, `quality`, `faithfulness`, `factuality`, `hallucination`,
  `toxicity`, `harmfulness`, `stereotyping`, `instruction_following`,
  `helpfulness`
- AND it measures evaluation score, score label/pass/fail, violation count,
  evaluator error/timeout, sample count/rate, no-data, freshness, or duration

A metric is a **genai-content-governance** detector or prerequisite candidate
when:

- The metric or audit evidence has GenAI context and contains one of:
  `content_capture`, `redaction`, `masking`, `pii`, `privacy`,
  `prompt_capture`, `response_capture`, `retrieval_capture`,
  `tool_argument_capture`
- AND it measures capture mode, redaction/truncation outcome, unsafe capture,
  policy rejection, audit/report outcome, or access/retention owner evidence.
  Do not alert on raw content; use this category mostly as an instrumentation or
  dashboard prerequisite.

A metric is a **genai-cost** detector candidate when:

- The metric has GenAI context and the metric name contains one of: `cost`,
  `spend`, `billing`, `price`, `charge`
- AND it measures app-computed request/model/provider cost, budget/quota
  consumption, billing export freshness, or cost calculation failure. If cost
  is not computed by the app from an accurate pricing map, owner-map the
  billing/provider source instead of generating an approximate detector.

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
metric name starts with "gen_ai." or audit has GenAI Readiness plus explicit genai/llm/inference/embedding/model-provider/agent/tool-call/retrieval/memory/evaluation keyword?
  -> YES -> genai-* detector using GenAI rules above
  -> NO

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

1. GenAI categories (provider/model/tool/retrieval/memory/evaluation/token/fanout/cost signals before generic RED)
2. Latency (duration histograms are unambiguous)
3. Error (error counters are high-value signals)
4. Throughput (general counters)
5. Saturation (gauges)
