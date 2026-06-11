# GenAI Readiness Reference

Load this reference when a repo contains LLM, agent, workflow, tool/function
calling, retrieval/RAG, model gateway, or model-provider code, or when the user
asks about GenAI/LLM incident detection, debugging, or alerting.

## Goal

Create traces and metrics that can explain GenAI incidents quickly:
workflow latency, provider failure, model/config mismatch, excessive LLM/tool
fanout, token/context pressure, broken tools, retrieval degradation, fallback
behavior, capacity saturation, and release/config correlation.

Use OpenTelemetry GenAI semantic conventions first. Add custom attributes only
for service-owned workflow context when no OTel convention exists.

## Completion Contract

For each app-owned GenAI surface discovered in code, readiness is incomplete
until the gap is resolved in all applicable signal planes:

- **Trace:** add or prove a low-cardinality parent/child span for the operation
  using GenAI semantic attributes where they exist. Provider/model calls,
  agent/workflow invocation, tool execution, retrieval, streaming adapters,
  prompt/response parsing, safety decisions, and AI-derived data jobs must not
  be closed with metrics alone when the code can emit a meaningful span.
- **Metric:** add or prove detector-ready counters, histograms, or gauges for
  rate, error, duration, retry, timeout, rate-limit, fallback, token pressure,
  finish reason, parse failure, freshness, fanout, or readiness when that value
  can improve detection or routing.
- **Log/event:** add or prove trace-correlated structured logs or span events
  for lifecycle outcomes that operators otherwise search logs for, such as
  retry scheduled, fallback selected or failed, stream finished/truncated,
  response parse failed, tool validation failed, safety rejection, and job
  success/failure. Use span events when a durable log line is not appropriate.

The gap-closure matrix must include trace evidence, metric evidence, and
log/span-event evidence for each app-owned GenAI surface. A row may be marked
`prove existing instrumentation` only with file/line evidence for the relevant
signal plane. A row may be marked `mark out of scope with owner` only when the
repo cannot observe the value accurately or another service/deployment owner is
named. Do not call GenAI instrumentation complete while a patchable surface is
metric-only, trace-only, or log-only.

## Token/Context Pressure Contract

When audit identifies token/context pressure, context-window exhaustion, prompt
growth, tool-schema bloat, or per-turn fanout as a gap, treat the audit ledger
as the required signal contract. Do not close the gap just because one token
metric or context-window gauge was added.

Required signals should be listed separately when the repo can observe them:

- context budget percent.
- truncation rate.
- token-limit errors.
- prompt/tool schema size.
- LLM call count per turn.
- tool call count per turn.
- input and output token usage through `gen_ai.client.token.usage` when
  provider usage data is available.

If only token usage and context-window usage are implemented, mark the ledger
row as partial instead of filled. Use explicit wording such as: `Partial: token usage and context window added; truncation, token-limit error, prompt/tool schema size, and LLM-call fanout remain missing.`

## Audit Checklist

- LLM/provider clients: OpenAI-compatible APIs, Azure OpenAI, Gemini/Vertex AI,
  Anthropic, Bedrock, local model servers, model gateways, SDK wrappers.
- GenAI workflow code: assistant/chat endpoints, agent orchestration, workflow
  engines, tool/function dispatch, MCP servers/clients, RAG/retrieval paths.
- Model/config code: requested model, resolved response model, deployment name,
  provider/region selection, fallback policy, config version, readiness checks.
- Token/context pressure: input/output token counts, cache read/create tokens,
  prompt/context byte size, tool-call count, LLM-call count per workflow.
- Error and timeout classes: timeout, rate limit, throttle, provider 5xx,
  content/filter rejection, model unavailable, model not found, tool failure.
- Privacy: raw prompts, completions, retrieved documents, tool arguments, user
  identifiers, tenant identifiers, and secrets must not be recorded by default.

## Trace Shape

A mature GenAI trace should show the app workflow as the parent and GenAI work
as children:

```text
service workflow span
  agent/workflow span
    tool execution span
      nested service workflow span
        LLM inference span
        retrieval span
        nested agent/workflow span
          LLM inference span
```

This requires baseline distributed tracing in addition to GenAI semconv:
`service.name`, environment/version resource attributes, HTTP/job spans, W3C
context propagation across services/workers/tools, error status, and OTLP export.

## Span Conventions

Use stable, low-cardinality span names:

| Operation | Span name | Required/safe attributes |
|---|---|---|
| LLM inference | `{gen_ai.operation.name} {gen_ai.request.model}` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model` if available, `gen_ai.response.model` if available |
| Agent invocation | `invoke_agent {gen_ai.agent.name}` | `gen_ai.operation.name=invoke_agent`, `gen_ai.agent.name`; provider fields for remote agents when available |
| Workflow invocation | `invoke_workflow {gen_ai.workflow.name}` | `gen_ai.operation.name=invoke_workflow`, `gen_ai.workflow.name` when the framework has a real workflow concept |
| Tool execution | `execute_tool {gen_ai.tool.name}` | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name` |
| Retrieval | `retrieval {gen_ai.data_source.id}` | `gen_ai.operation.name=retrieval`, data source id/name only when low-cardinality |

Use predefined `gen_ai.operation.name` values when they apply: `chat`,
`generate_content`, `text_completion`, `embeddings`, `invoke_agent`,
`invoke_workflow`, `execute_tool`, and `retrieval`.

For failed GenAI spans, set span status to error and record `error.type` with a
low-cardinality class such as `timeout`, `rate_limit`, `provider_5xx`,
`model_not_found`, `model_unavailable`, `tool_error`, or `content_filter`.

## Metrics

Prefer OTel GenAI metrics where data is available:

- `gen_ai.client.operation.duration` for latency by operation/provider/model.
- `gen_ai.client.token.usage` for input/output token histograms with
  `gen_ai.token.type`.
- `gen_ai.client.operation.time_to_first_chunk` and
  `gen_ai.client.operation.time_per_output_chunk` for streaming workflows.

Do not report token metrics when token counts cannot be obtained efficiently or
accurately. When providers distinguish billable tokens from raw used tokens,
report billable tokens.

Add service-owned metrics only when OTel has no convention:

- workflow duration and outcome by workflow/surface/environment.
- LLM-call count and tool-call count per workflow request.
- model/config readiness failures by failure class.
- fallback selected, fallback failed, and region/provider failover outcomes.
- queue depth, memory, restart, and worker saturation for GenAI gateways/tools.

When applying instrumentation, close every safe app-owned GenAI gap discovered
by the scan. Each gap must resolve to `add instrumentation`,
`prove existing instrumentation`, or `mark out of scope with owner`. Do not pick
only the highest-value or easiest provider, token, stream, tool, retrieval,
model/config, prompt/response, safety, or AI-derived data gap when the repo owns
more patchable gaps.

Metric-only closure is not acceptable for app-owned provider/model calls,
streaming responses, tool execution, retrieval, prompt/response parsing,
safety/policy decisions, model/config resolution, or AI-derived data jobs when
the code can emit a diagnostic span or span event. Keep metrics for detectors,
but add or prove the trace/log evidence needed to localize the incident.

Do not use conversation, user, account, tenant, request, session, task, trace, or
raw tool argument values as metric dimensions.

## Detector and Dashboard Intents

Map incident patterns to concrete signals:

| Incident pattern | Detection/localization signal |
|---|---|
| Slow or timing-out assistant/workflow | workflow p90/p99, `gen_ai.client.operation.duration`, timeout rate by workflow/provider/model/environment |
| Extra LLM/tool fanout | LLM-call count, tool-call count, input/output tokens, context bytes per workflow request |
| Provider outage/latency | provider latency/error/timeout/rate-limit by provider/model/region/deployment |
| Model/config mismatch | model readiness check, failed model resolution, request vs response model, config version |
| Tool broken | tool success/error/latency by stable `gen_ai.tool.name` and failure class |
| Crash loop or memory growth | restart/crashloop, RSS/heap slope, GC pressure, queue backlog, profile-before-restart runbook link |
| Blast radius unclear | rollups by environment/region/workflow/model/provider/deployment/config version |

Dashboards should show the parent workflow, GenAI child operations, provider
health, token pressure, tool reliability, fallback behavior, release/config
context, and capacity signals together so operators can separate app-down,
workflow-degraded, provider-degraded, tool-degraded, and capacity-degraded
impact.

## Privacy and Cardinality

- Do not capture raw prompts, completions, tool arguments, retrieved documents,
  raw URLs, headers, tokens, secrets, user identifiers, or tenant identifiers by
  default.
- If content capture is explicitly required, make it opt-in, redact it, and keep
  it out of metric dimensions.
- Span names and metric attributes must be stable. Replace IDs and path
  variables with templates such as `{id}` or `{resource}`.
- Conversation/session/task IDs may be useful as trace attributes for drilldown
  only when policy allows; never use them for metrics, detectors, or dashboard
  group-by dimensions.
