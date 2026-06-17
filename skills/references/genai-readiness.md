# GenAI Readiness Reference

Load this reference when a repo contains LLM, agent, workflow, tool/function
calling, retrieval/RAG, model gateway, or model-provider code, or when the user
asks about GenAI/LLM incident detection, debugging, or alerting.

## Goal

Create traces and metrics that can explain GenAI incidents quickly:
workflow latency, provider failure, model/config mismatch, excessive LLM/tool
fanout, token/context pressure, broken tools, retrieval degradation, fallback
behavior, prompt/response parsing failures, AI-derived data freshness,
model/prompt/tool-schema compatibility, evaluation quality regressions, unsafe
content capture, memory/context degradation, cost spikes, and AI-path capacity
or state pressure.

Use OpenTelemetry GenAI semantic conventions first. Add custom attributes only
for service-owned workflow context when no OTel convention exists. Keep this
reference scoped to AI pathways. Generic app surfaces such as streams, jobs,
synthetic/canary checks, startup/deployment compatibility, input complexity,
capacity, and release context belong here only when source evidence shows they
exercise, carry, or block an AI workflow.

## Obstudio GenAI Trace UI Contract

Obstudio's GenAI trace view is span-first. If a value exists only in a metric
stream, the trace view may not be able to summarize it for one selected trace.
For a demoable selected-trace summary, emit both the detector metric and safe
span-level attributes when the service can observe the value.

| UI evidence | Required telemetry |
|---|---|
| GenAI trace detection | At least one span with `gen_ai.operation.name` |
| Workflow card | Span `invoke_workflow {workflow}` with `gen_ai.operation.name=invoke_workflow` and `gen_ai.workflow.name` |
| Agent card | Span `invoke_agent {agent}` with `gen_ai.operation.name=invoke_agent` and `gen_ai.agent.name` |
| LLM/chat card | Span `chat {model}` or another GenAI inference operation with `gen_ai.operation.name=chat`, `gen_ai.provider.name`, `gen_ai.request.model`, and `gen_ai.response.model` when known |
| Tool card | Span `execute_tool {tool}` with `gen_ai.operation.name=execute_tool` and stable `gen_ai.tool.name` |
| Retrieval card | Span `retrieval {source}` with `gen_ai.operation.name=retrieval` and a low-cardinality data source attribute |
| Tokens summary | `gen_ai.client.token.usage` metric with `gen_ai.token.type`; also set `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, and `gen_ai.usage.total_tokens` on the chat span or workflow span when available |
| LLM/tool call counts | Service-owned per-workflow attributes or metrics such as `assistant.llm.calls` and `assistant.tool.calls`, plus child spans when possible |
| Error badges | Span status ERROR plus low-cardinality `error.type` |
| Streaming timeout explanation | First event/chunk latency, stream close reason family, timeout/cancel/disconnect events, and workflow ERROR with `error.type=first_event_timeout` or another stable class |

If an audit gap mentions a local trace summary, Obstudio view, selected trace,
or demo trace, treat span-level selected-trace summary attributes as required
acceptance criteria in addition to detector metrics.

Do not put selected-trace aggregate GenAI usage on a generic HTTP root span or
generic server span. Attributes such as `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, `gen_ai.usage.total_tokens`,
`assistant.llm.calls`, and `assistant.tool.calls` belong on the workflow span or
the most specific owning GenAI span. A root HTTP span may wrap the whole request,
but it should not become a GenAI flow card unless it is explicitly the workflow
span with `gen_ai.operation.name=invoke_workflow`.

Workflow names must preserve the application's stable business workflow
identity. Prefer existing constants, handler names, telemetry event names,
workflow registrations, docs, or prior trace names over route-derived or
session-derived labels. Do not invent names from HTTP routes, transport
resources, or storage/session concepts. For example, an assistant turn workflow
that is already named `assistant_v3_turn` must stay `assistant_v3_turn`; do not
rename it to `assistant_v3_session_turn`, `POST /v2/assistant/sessions`, or
another request/route-derived value. If no stable workflow identity exists,
name the route as the HTTP span only and keep GenAI workflow coverage partial
until the app owner supplies or accepts a stable low-cardinality workflow name.

Agent names must preserve the application's stable agent identity with the same
discipline. Prefer framework agent names, agent factory names, class names,
registration names, callback owner names, docs, or prior trace names over
generic service-derived labels. For example, a DeepAgents-backed agent should be
named `deepagents` when that is the discovered agent identity; do not rename it
to `assistant_v3_agent`, `assistant`, `agent`, or another generic wrapper name.
If no stable agent identity exists, keep the agent row partial instead of
inventing a generic GenAI agent name.

## Single-Source GenAI Span Contract

Use one canonical GenAI span source per logical operation. Before adding manual
workflow, agent, chat, tool, retrieval, memory, or evaluation spans, inventory
existing framework/vendor bridges, provider SDK hooks, callbacks, middleware,
and auto-instrumentors that can already emit OTel GenAI spans for the same
operation. A representative trace should have one GenAI node per logical
operation: workflow, model call, tool call, retrieval, memory operation, or
evaluation result, not both a framework wrapper span and an app-owned duplicate
for the same work.

If the framework/vendor bridge is the canonical source, keep it and add only
missing app-owned workflow/agent context, safe aggregate attributes, metrics,
or owner mappings. Do not add duplicate app-owned `chat` or `execute_tool`
spans for operations that the bridge already emits with correct semconv,
privacy, model/tool attributes, lifecycle, and parent context.

If app-owned spans are the canonical source, add the complete app-owned
workflow/agent/chat/tool/retrieval/memory/evaluation spans and disable, opt out
of, or suppress overlapping framework/vendor GenAI instrumentation in that
process. The exact mechanism is runtime-specific: use discovered instrumentor
names, bridge settings, callback configuration, or provider-hook opt-out flags
instead of hard-coding one framework. Keep baseline HTTP/database/runtime
instrumentation when it does not create duplicate GenAI nodes.
For preload, javaagent, `opentelemetry-instrument`, `NODE_OPTIONS --require`,
or similar auto-instrumentation bootstraps, suppression must be configured in
the launch environment or startup wrapper before the bootstrap runs; otherwise
framework hooks may already be registered. App module code that mutates
environment variables after bootstrap is only defense in depth and is not
sufficient proof. Update the real startup surfaces that operators use, such as
Makefile targets, service runner scripts, Docker or Helm env, VS Code launch
configs, procfiles, systemd units, shell env generators, or generated env
scripts.

Mark trace/semconv coverage `partial` when a selected trace shows duplicate
GenAI nodes for the same logical operation, middleware or step-wrapper spans
counted as tools, framework and app spans racing for parentage, or divergent
aggregate counts. Closure proof requires one canonical GenAI span source per
logical operation. The selected trace must show one GenAI node per logical
operation, correct parent shape, expected LLM and tool counts, stable model/tool
names, and no wrapper-only spans counted as GenAI work. Required proof should
name stable model/tool names explicitly.

## LLM Inference Lifecycle Contract

Do not treat workflow-level token accounting as proof of LLM inference
instrumentation. A repo that owns a model call needs a model-call lifecycle span
at the code path that starts and finishes the provider call.

Required proof for each app-owned model-call surface:

- A low-cardinality inference span such as `chat {model}`,
  `generate_content {model}`, or `text_completion {model}` starts before the
  provider/model gateway request and ends after the response, stream terminal
  event, or error.
- The span has `gen_ai.operation.name` set to the actual inference operation,
  plus `gen_ai.provider.name`, `gen_ai.request.model` when the requested model
  is known, and `gen_ai.response.model` when the response model is known.
- Provider usage is recorded on the inference span when available:
  `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, and
  `gen_ai.usage.total_tokens`; aggregate to the workflow span only as a
  summary, not as a replacement for the inference span.
- Errors, cancellations, provider timeouts, rate limits, and stream-close
  failures set span error status, record the exception when available, and set
  low-cardinality `error.type`.
- Parent context links the inference span under the owning agent, workflow,
  model gateway, or tool span so selected-trace UIs can render the call path.

For event-derived instrumentation, preserve the owning workflow/agent context.
Capture or re-enter that context when handling callback events so model and tool
spans do not attach to the HTTP root span as siblings of the workflow. A
representative trace must show the intended trace shape, for example
`workflow -> chat`, `workflow -> execute_tool`, and any follow-up
`workflow -> chat` or `agent -> chat` edges. If chat/tool spans exist but are
siblings of the workflow under a generic server span, mark the surface
`partial` and keep parent-context propagation in `remaining_signals`.

Be explicit about long-lived helper/setup spans. Memory-store setup, checkpointer
setup, database session spans, stream-writer spans, and other helper/setup spans
may be active while callback events are translated. They must not become the
parent for model/tool lifecycle spans, and they must not receive selected-trace
aggregate attributes. Capture the workflow/agent context before opening those
helpers, start event-derived `chat` and `execute_tool` spans with that captured
context, and write aggregate counters/tokens to the captured workflow/agent span
object rather than using whatever current span is active during stream cleanup.
Use this rule for memory store, checkpointer, database session, stream-writer,
or resource setup paths: helper spans must not become the parent; capture the
workflow/agent context before opening helper spans, start event-derived `chat`
and `execute_tool` spans with that captured context, and write aggregate
counters to the workflow span, not to whichever current span is active.
For async generator, SSE, WebSocket, ping-loop, timeout-wrapper, or task handoff
paths that advance a stream with `create_task`, `wait`, `anext`, or equivalent
scheduling, do not keep an OpenTelemetry current-span context manager open across
yield/task boundaries. Start the workflow span with an explicit parent context,
store a workflow span/context handle, pass that handle into the callback/event
translator, and end the span manually after the stream closes.
When that workflow/agent context has to cross a request, turn input, event
payload, callback state, or config object that may be immutable/frozen, do not
mutate the carrier in place. Treat a carrier as immutable/frozen when source
evidence shows frozen or readonly declarations, record/value types, no mutation
API, framework request immutability patterns, or existing code constructs new
copies instead of mutating. Use an idiomatic copy/replacement API such as Python
`dataclasses.replace`, `attrs.evolve`, pydantic `model_copy(update=...)` or v1
`copy(update=...)`; Java records, builders, or copy constructors; TypeScript
object spread, explicit `Readonly<T>` replacements, or `structuredClone` only
for plain-data carriers and never for live OTel `Context` or `Span` handles; Go
value copies with explicit field replacement; or the framework's request
clone/with-context API. If no safe copy path exists, store the span/context
handle in a separate invocation-scoped sidecar context: a local object, context
variable, request-scoped map, or callback state keyed to the invocation
lifecycle and cleared after cleanup. Do not key sidecar context by raw user,
tenant, session, request, or trace IDs. Tests or explicit static proof must show
the parent context is passed downstream and the original immutable input remains
unchanged; in Python, cover `FrozenInstanceError` risk when a
frozen dataclass or model is present.

Framework bridges must be checked at the real lifecycle hook:

- LangChain, LangGraph, DeepAgents, and callback/event-stream based systems:
  instrument `on_chat_model_start`, `on_chat_model_end`, and
  `on_chat_model_error` or the equivalent callback lifecycle. Do not rely on
  final usage events such as `usage.total`, response aggregation, or
  turn-finalization events by themselves.
- Direct provider SDKs and model gateways: wrap the client call or streaming
  generator that sends the model request, not only the outer HTTP route or
  workflow function.
- Streaming responses: keep the inference span open until the model stream
  completes or fails, and record first chunk latency, finish reason, and
  stream close reason when observable.

Acceptance gate: for a representative prompt that reaches a model, the trace
must contain at least one inference span with `gen_ai.operation.name` equal to
`chat`, `generate_content`, `text_completion`, or another valid GenAI
inference operation. If token/model attributes exist only on a workflow span
and no inference span exists, mark the surface `partial` and keep the missing
model-call lifecycle span in `remaining_signals`. If inference spans exist but
are parented to a generic HTTP root span instead of the owning workflow/agent
span, mark the surface `partial` until the trace shape proves the correct
parent context.

## GenAI Semconv Source Contract

Before auditing or instrumenting GenAI code, reconcile detected AI surfaces
against the current official OpenTelemetry GenAI semantic conventions.

Source order:

1. `live official docs` from `open-telemetry/semantic-conventions-genai` when
   network access is available.
2. The bundled semconv snapshot in this reference when live docs cannot be
   fetched.

Check only relevant docs:

- Always check the GenAI README, model spans, agent spans, and metrics docs.
- Check GenAI events when content/event capture, evaluation, or logs are in
  scope.
- Check MCP docs when MCP client or server code is present.
- Check provider-specific docs only when that provider is detected in code or
  config.

Record provenance in audit and instrument output:
`GenAI semconv source -> repo/branch-or-commit/docs/date/live-or-snapshot`.

Build a semconv closure matrix before declaring coverage:
`surface -> official operation -> required attrs -> recommended attrs ->
metrics/events -> implemented -> proven existing -> remaining`.

Do not claim current semconv coverage unless every detected GenAI surface is
implemented, proven existing, or explicitly marked unavailable with owner and
source. Local operation and metric lists are examples only. If live official
docs disagree with bundled guidance, official docs win, while this skill's
privacy/cardinality rules remain enforced.

## Audit Checklist

- LLM/provider clients: hosted model APIs, OpenAI-compatible APIs, cloud model
  services, local or self-hosted model servers, model gateways, SDK wrappers.
- GenAI workflow code: assistant/chat endpoints, agent orchestration, workflow
  engines, tool/function dispatch, MCP servers/clients, RAG/retrieval paths.
- Framework bridges: LangChain, LangGraph, CrewAI, Strands, LlamaIndex,
  OpenInference, TraceLoop/OpenLLMetry, ADOT, and provider/framework OTel hooks.
- Model/config code: requested model, resolved response model, deployment name,
  provider/region selection, fallback policy, config version, readiness checks.
- Token/context pressure: input/output token counts, cache read/create tokens,
  prompt/context byte size, tool-call count, LLM-call count per workflow.
- Memory/context paths: memory store create/search/read/write/upsert/delete,
  context assembly, conversation/session state, AI cache state, and
  stale/missing context handling.
- Evaluation quality: LLM-as-judge, offline eval, online eval, human feedback,
  scoring, labels, explanations, sample rate, evaluator failures, and freshness.
- Cost accounting: provider usage-to-cost mapping, per-request/model/provider
  cost, billing export, quota/budget guardrails, or owner-mapped billing source.
- Prompt and response assembly: prompt/template version, response schema version,
  prompt build errors, response parse errors, payload size bucket, and workflow
  source without recording content.
- AI-derived data jobs: embedding/index refresh, evaluation, feedback, export,
  dataset refresh, prompt/cache population, and other AI-owned derived data
  paths.
- Model/config paths: requested model, response model, deployment readiness,
  prompt/tool schema version, feature flag, rollout/canary batch, and
  expected-vs-running model or config state.
- Error and timeout classes: timeout, rate limit, throttle, provider 5xx,
  content/filter rejection, model unavailable, model not found, tool failure.
- Privacy: raw prompts, completions, retrieved documents, tool arguments, user
  identifiers, tenant identifiers, secrets, and evaluation explanations must not
  be recorded by default.

## Incident-Evidence Mode

Use this mode when incidents, postmortems, alerts, tickets, or user-provided
failure examples involve GenAI, LLM, assistant/chat workflows, agent, MCP, RAG,
model gateway, tool/function, or streaming response behavior.

Build a coverage matrix before editing:

```text
incident class -> failure mechanism -> repo/service owner -> code surface -> signal -> MTTD impact -> remaining owner
```

- Classify the failure mechanism, not only the symptom. For example, separate
  provider timeout, model/config rollout mismatch, tool serialization failure,
  retrieval freshness, stream lifecycle leak, token/context limit, safety
  refusal spike, prompt/response parse failure, stale AI-derived data,
  missing synthetic/canary coverage of an AI path, and queue/capacity pressure
  in an AI gateway or tool runtime.
  Treat detector reliability evidence as relevant when alert behavior is part
  of the incident evidence.
- Mark a signal **MTTD-improving** only when it can drive a detector before or
  at first customer impact. Mark it **localization-only** when it mainly helps
  root-cause after another alert fires.
- Add or prove low-cardinality spans and metrics in the owning surface:
  provider/model gateway, agent orchestrator, workflow engine, tool/function or
  session/stream dispatcher, MCP dispatcher when present, retriever/vector
  store, streaming adapter, queue/worker, cache/session store,
  safety/content filter, prompt/response parser, AI-derived data job, or
  model/config resolver. Include lifecycle, job, synthetic/canary,
  startup/deployment, input-complexity, capacity, and release/config signals
  here only when the evidence shows they exercise or block an AI pathway.
- Do not call GenAI instrumentation complete while any app-owned GenAI provider,
  model/config, tool/session/stream lifecycle including MCP when present,
  retrieval, streaming, token/context, safety/policy, prompt/response parser,
  AI-derived data job, model rollout, or AI-owned state surface remains only
  listed as a follow-up, unless the user explicitly narrows scope. Non-AI
  generic readiness surfaces should be called out as out of scope rather than
  treated as GenAI completion criteria.

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

Prompt/tool schema pressure is detector-ready only when it is implemented or
proven as a metric or equivalent detector source, for example schema JSON length bucket,
schema field count, prompt template length bucket, or tool count. Span attributes such as prompt template version,
schema version, or isolated schema metadata are trace context; they do not close prompt/tool schema size pressure unless a detector can consume them as a stable signal. If the code cannot safely
emit such a signal, keep prompt/tool schema size in `remaining_signals` and name
the owner or missing source.

Every GenAI instrumentation result should include a closure summary in the final
response. `Remaining signals: none` is allowed only when each required GenAI
signal is implemented, proven existing, or owner-mapped. Otherwise list the
partial GenAI signals explicitly.

## Required GenAI Surface Patterns

When code evidence exists, audit and instrument these surfaces before declaring
GenAI readiness complete:

- **Provider/model gateway:** request/response model, deployment, provider,
  region, endpoint health, latency, timeout, retry, rate-limit/throttle,
  provider 5xx, circuit-breaker state, fallback/failover outcome,
  streaming first chunk latency, chunk cadence, partial completion, finish reason,
  failover readiness, fallback target readiness, content-filter or refusal
  outcome.
- **Agent/workflow orchestration:** workflow outcome and duration, step count,
  LLM-call count, tool-call count, retry/fallback branch, cancellation, timeout,
  recursion/depth guard, fanout, workflow name, workflow mode, feature flag,
  synthetic transaction outcome, and model/config version.
- **Tool/function execution and AI-owned sessions/streams:** stable tool or
  function name, MCP method name when present, authentication/authorization
  result, invalid-token or permission failure outcome, validation and
  serialization errors, tool start/success/error/timeout, output count or size,
  downstream dependency outcome, active sessions/streams, close reason family,
  stream duration/outcome, send/write failure, and session/stream lifecycle
  signals when the AI path owns a long-lived tool/session/stream.
  Tool execution spans alone are not detector-ready tool coverage. Prefer a
  tool-specific duration histogram and tool error/timeout counter by stable
  tool name and low-cardinality failure class when the app owns execution.
  MCP/JSON-RPC request IDs, raw request IDs, session IDs, trace IDs, raw
  payloads, prompts, completions, retrieved content, tool arguments, users,
  accounts, and tenants are not safe metric dimensions. Use stable tool or method names from known registration only; otherwise bucket method values into
  low-cardinality families such as `known_tool`, `unknown_method`,
  `invalid_request`, or `unsupported_method`.
- **RAG/retrieval:** embedding call outcome, vector/search dependency outcome,
  retrieval count, empty or low-confidence result, top-k, index/corpus/config
  version, freshness or last-ingest age, and cache hit/miss.
- **Token/context/cost pressure:** input, output, and cached tokens; context
  length or bytes; budget percent; truncation; token-limit errors; and
  per-workflow aggregated tokens and LLM calls. Use `gen_ai.client.token.usage`
  and provider/model attributes as the semconv source of usage. If the
  application owns an accurate pricing map, add a low-cardinality custom cost
  metric by workflow/provider/model and currency. If cost is computed by billing
  exports, provider dashboards, or finance systems, owner-map the exact source
  instead of inventing approximate in-process cost. Include payload size, input
  complexity, item count, or metadata-count signals only when they describe the
  AI prompt/context/tool path.
- **Prompt/response assembly:** prompt/template version, response schema or tool
  schema version, prompt build outcome, input validation failure, response parse
  failure, malformed or partial response outcome, payload size bucket, and
  workflow name/source included in low-cardinality payload metadata.
- **Safety/policy:** content-filter, refusal, moderation, guardrail, and policy
  outcome by stable policy class. Do not capture raw prompt, completion, or
  retrieved content.
- **AI-derived data freshness:** embedding/index refresh, evaluation, feedback,
  export, dataset refresh, prompt/cache population, record count,
  empty/partial result, destination outcome, drop reason, and schedule lag.
  Include job duration, last-success age, retry, backlog, and delivery/publish
  outcome when the job produces or refreshes AI-owned data.
- **Memory/context and AI runtime state overlay:** model warmup, model cache
  health, memory store create/search/read/write/upsert/delete, context assembly,
  conversation/session state, stale or missing context, per-session AI resource
  pressure, queue/capacity pressure in an AI gateway or tool runtime, and
  cache/session state that affects AI workflow correctness. Prefer GenAI memory
  operation names such as `create_memory_store`, `search_memory`,
  `create_memory`, `update_memory`, `upsert_memory`, `delete_memory`, and
  `delete_memory_store` when applicable. Include CPU, memory, disk, thread pool,
  restart/crashloop, and runtime health signals only when they are emitted by or
  scoped to the AI gateway/tool runtime.
- **Model/config compatibility:** requested model, response model, model or
  deployment readiness, prompt/template version, tool schema version,
  index/corpus version, workflow mode, feature flag, config version,
  rollout/canary batch, and expected-vs-running model or AI config state.
- **AI-path readiness overlays:** synthetic/canary, stream, offline/derived
  job, input-complexity, capacity, release, and deployment signals are GenAI
  readiness signals only when repo evidence shows they exercise, carry, or
  block an AI pathway. Treat missing AI-path coverage as synthetic/canary workflow-check blind spots.
  When incidents mention missed, flapping, auto-resolved, or no-data alerts,
  capture detector reliability evidence for `$splunk-configure`.

## Evaluation Quality Contract

When evaluator, scoring, feedback, or LLM-as-judge code exists, treat quality as
a GenAI surface. Prefer the OTel event `gen_ai.evaluation.result` with:

- `gen_ai.evaluation.name`.
- `gen_ai.evaluation.score.value` when the evaluator returns a numeric score.
- `gen_ai.evaluation.score.label` when the evaluator returns a label, verdict,
  pass/fail state, or bucket.
- `gen_ai.evaluation.explanation` only when content governance allows it.
- `gen_ai.response.id` or parent span linkage when available.

Add detector-ready app metrics when events are not detector-ready: score
distribution, pass/fail or violation count, sample count/rate, evaluator
duration/error/no-data, and evaluation freshness by low-cardinality
workflow/model/evaluation name. Do not mark evaluation quality complete when the
repo only emits job freshness, counters/histograms without
`gen_ai.evaluation.result`, or free-form evaluation text in logs or reports.
Metrics-only coverage does not satisfy selected-trace eval visibility.

## Content Capture Governance Contract

Semconv supports prompt, response, system instruction, retrieval document, and
tool definition/argument content through opt-in attributes such as
`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`,
`gen_ai.retrieval.documents`, `gen_ai.retrieval.query.text`,
`gen_ai.tool.definitions`, and `gen_ai.tool.call.arguments`. These fields are
sensitive.

Audit content capture as `disabled`, `metadata-only`, `redacted`, or
`full-content`. Instrumentation must default to no raw content. If content is
explicitly required, require an opt-in config, redaction/truncation hook, storage
destination, retention/access owner, and trace/log correlation evidence. Never
put raw content, identifiers, retrieved documents, URLs, tool arguments, memory
records, or evaluation explanations in metric names, metric dimensions, detector
group-bys, or span names.

## Framework Bridge Contract

Before adding custom GenAI wrappers, detect framework or provider bridges such
as LangChain, LangGraph, CrewAI, Strands, LlamaIndex, OpenInference,
TraceLoop/OpenLLMetry, ADOT, provider SDK hooks, or MCP instrumentation. Treat a
bridge as covered only when it is configured to emit OTel-compatible GenAI
semconv spans/events/metrics, the emitted signal names are proven, and the
privacy/content settings are understood. Otherwise add missing app-owned signals
around the owned workflow boundaries and owner-map the bridge/platform gaps.

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

For compact local demos, preserve this minimum shape:

```text
HTTP or job span
  invoke_workflow assistant_turn
    invoke_agent planner
      chat gpt-5.5
      execute_tool search
      retrieval vector_store
      chat gpt-5.5
```

## Span Conventions

Use stable, low-cardinality span names:

| Operation | Span name | Required/safe attributes |
|---|---|---|
| LLM inference | `{gen_ai.operation.name} {gen_ai.request.model}` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model` if available, `gen_ai.response.model` if available |
| Agent invocation | `invoke_agent {gen_ai.agent.name}` | `gen_ai.operation.name=invoke_agent`, `gen_ai.agent.name`; provider fields for remote agents when available |
| Workflow invocation | `invoke_workflow {gen_ai.workflow.name}` | `gen_ai.operation.name=invoke_workflow`, `gen_ai.workflow.name` when the framework has a real workflow concept |
| Planning | `plan {gen_ai.agent.name}` or `plan` | `gen_ai.operation.name=plan`, stable agent/workflow name when available; never raw chain-of-thought |
| Tool execution | `execute_tool {gen_ai.tool.name}` | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name` |
| Retrieval | `retrieval {gen_ai.data_source.id}` | `gen_ai.operation.name=retrieval`, data source id/name only when low-cardinality |
| Memory/context | `{gen_ai.operation.name}` | `gen_ai.operation.name` set to `create_memory_store`, `search_memory`, `create_memory`, `update_memory`, `upsert_memory`, `delete_memory`, or `delete_memory_store` when applicable |

Use predefined `gen_ai.operation.name` values when they apply: `chat`,
`generate_content`, `text_completion`, `embeddings`, `invoke_agent`,
`invoke_workflow`, `plan`, `execute_tool`, `retrieval`, `create_memory_store`,
`search_memory`, `create_memory`, `update_memory`, `upsert_memory`,
`delete_memory`, and `delete_memory_store`.

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
- evaluation score distributions, pass/fail counts, sample counts, evaluator
  error/no-data, and evaluation freshness when evaluation events are not directly
  detector-ready.
- memory/context operation duration, outcome, hit/miss, stale/missing context,
  record count bucket, source/version, and permission/auth failure when
  app-owned.
- queue depth, memory, restart, and worker saturation for GenAI gateways/tools.

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
| Missing or stale memory/context | memory/context duration, outcome, hit/miss, stale/missing context, source/version, permission failure |
| Quality regression | `gen_ai.evaluation.result`, evaluation score distribution, pass/fail or violation count, evaluator no-data/freshness |
| Unsafe content telemetry | content capture mode, redaction/truncation status, retention/access owner, raw-content dimension absence |
| Cost spike | token usage by provider/model/workflow and app-owned cost metric or owner-mapped billing source |
| Model/config incompatibility | failed model resolution, model/deployment readiness, request vs response model, config version, prompt/tool schema version |
| Synthetic/canary coverage of an AI path | synthetic/canary workflow-check outcome for the AI path, including model/provider/workflow mode when available |
| Prompt build or response parse failure | prompt/template version, response schema/tool schema version, prompt build outcome, response parse failure, payload size bucket |
| AI tool/session/stream leak, including MCP when present | lifecycle signals, auth result, send/write failure, close reason family, active stream/session count, stream duration/outcome, plus stable tool/MCP method and AI workflow mode |
| AI tool/session/stream memory growth, including MCP when present | AI-scoped capacity/state signals, plus stable tool/session/workflow dimensions |
| Streaming partials or slow first token | time to first chunk, chunk cadence, partial-completion outcome, finish reason |
| Retrieval stale, empty, or low quality | retrieval empty rate, low-confidence rate, index/corpus version, last-ingest age, vector/search dependency outcome |
| Token/context pressure | input/output/cache tokens, context budget percent, truncation rate, token-limit error rate, and AI prompt/context input complexity |
| AI-derived data stale or failed | embedding/index freshness, evaluation/feedback/export/dataset refresh result, empty/partial result, destination outcome, and AI-owned job health |
| Safety/refusal spike | content-filter/refusal/guardrail outcome by stable policy class |
| Model rollout or prompt/schema mismatch | expected-vs-running model/config/prompt/tool schema version and rollout/canary batch |
| Detector reliability concern in AI incident evidence | missed/flapping/auto-resolved/no-data alert evidence to hand off to `$splunk-configure` |
| Queue, worker, or state pressure in an AI gateway/tool runtime | AI-scoped capacity/backpressure signals plus stable AI workflow/provider/tool dimensions |
| Crash loop or memory growth affecting AI workflows | AI-scoped capacity/startup signals plus model/provider/workflow dimensions when available |
| Blast radius unclear | rollups by environment/region/workflow/model/provider/deployment/config version |

Dashboards should show the parent workflow, GenAI child operations, provider
health, token pressure, memory/context reliability, tool reliability,
evaluation quality, fallback behavior, cost, AI model/config context, and
AI-runtime pressure together so operators can separate workflow-degraded,
provider-degraded, tool-degraded, retrieval-degraded, quality-degraded,
cost-degraded, and token-pressure impact.

## Privacy and Cardinality

- Do not capture raw prompts, completions, tool arguments, retrieved documents,
  raw URLs, headers, tokens, secrets, user identifiers, or tenant identifiers by
  default.
- If content capture is explicitly required, make it opt-in, redact it, and keep
  it out of metric dimensions. Treat `gen_ai.input.messages`,
  `gen_ai.output.messages`, `gen_ai.system_instructions`,
  `gen_ai.retrieval.documents`, `gen_ai.retrieval.query.text`,
  `gen_ai.tool.definitions`, `gen_ai.tool.call.arguments`, and
  `gen_ai.evaluation.explanation` as sensitive.
- Span names and metric attributes must be stable. Replace IDs and path
  variables with templates such as `{id}` or `{resource}`.
- Conversation/session/task IDs may be useful as trace attributes for drilldown
  only when policy allows; never use them for metrics, detectors, or dashboard
  group-by dimensions.
