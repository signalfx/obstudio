# GenAI Instrumentation

Use this reference only when the main skill detects GenAI/LLM code or when the
source audit declares GenAI ownership. Apply it together with
`../../references/genai-readiness.md`; that shared reference defines the
cross-skill readiness and semantic-convention contract, while this reference
defines instrument-specific implementation, proof, closure, and finalization.

Require an accurate pricing map before app-computed cost is covered. Preserve
missed, flapping, auto-resolved, or no-data alerts as detector-reliability
evidence rather than inventing app lifecycle metrics.

## Contents

- [Audit-Driven Closure](#audit-driven-closure)
- [Scope And Detector-Ready Signals](#scope-and-detector-ready-signals)
- [GenAI Span Ownership And Context](#genai-span-ownership-and-context)
- [Finalization](#finalization)

## Audit-Driven Closure

### GenAI Readiness Contract

When `.observe/otel-audit.json` exists, use its `genai_readiness` rows and only
the findings selected in `.observe/otel-selection.json`. On the legacy fallback,
use `.observe/otel.md` `## GenAI Readiness`. Parse each row by human-readable
`surface` plus `required_signals`, owner/source files, and
`acceptance_criteria`. Use the surface name as the human-facing identifier
throughout implementation and reporting. The audit is a contract, but only the
bound selection defines code-change scope.

Reconcile every GenAI audit gap to a required instrumentation result:

| Audit Gap | Required Instrumentation Result |
|---|---|
| App-owned + patchable | Code added + tests |
| App-owned but unsafe/too large | Explicitly split into named follow-up batch |
| Provider/platform-owned | Owner mapped with exact missing source |
| Already covered | Proven with source path and signal name |

For each surface row, produce and maintain a closure matrix:
`surface -> required_signals -> implemented_signals -> tests ->
remaining_signals -> status`. The final gate is strict: the instrumentation
pass cannot say `covered`, `fixed`, `closed`, or `complete` unless every
required GenAI signal is either implemented with tests, proven existing with
source path and signal name, or explicitly owner-mapped with the exact missing
source. Optimize for honesty over broad progress. Partial closure is acceptable;
silent partial closure is the bug.

For every GenAI instrumentation run, include a concise closure summary in the
final response. It must name remaining GenAI signals, or say `Remaining signals: none`
only when the closure matrix has no partial rows. Do not use unqualified
phrases such as `expected coverage`, `covered`, or `complete` for a GenAI surface
unless the related row is fully closed by the matrix.

When the source audit declares GenAI ownership, write
`## GenAI Readiness Closure` in `.observe/otel-instrumentation.md` after
`## Audit Gap Closure`. Copy every `Surface` and its complete `Required Signals`
cell from the audit readiness table, then record `Implemented / proven`,
`Tests`, `Remaining signals`, and `Result`. Use one row per audit surface and
do not merge or omit partial, deferred, or owner-mapped surfaces. Use `Working`,
`Partial`, `Not working`, `Not proven`, `Not configured`, `Deferred`, or
`Owner-mapped`. `Working` requires `Remaining signals` to be exactly `None`;
all other results must name the remaining signal, blocker, or external owner.
Omit the section only when the source audit explicitly declares `No`. If the
ownership declaration and readiness table disagree, regenerate the source
audit before instrumentation.

When no source audit exists, do not create `## GenAI Readiness Closure` or
invent closure rows from the implementation pass. Record source-derived GenAI
readiness observations and remaining signals under `## Remaining Gaps`, and
state that a source audit is required before one-to-one readiness closure can
be claimed.

For canonical audits, treat `partial` or `missing` GenAI readiness work as
in scope only when its matching finding IDs are in the validated selection. On
the legacy fallback, an explicit user request to instrument those rows remains
the scope. Do not stop after auto-instrumentation for selected, app-owned
GenAI gaps.

## Scope And Detector-Ready Signals

When the user asks broadly to apply GenAI readiness skills, improve GenAI MTTD,
or fix found GenAI gaps, the desired coverage is **all discovered app-owned
GenAI gaps**, but that broad request is not selection authority for a canonical
audit. Inventory the matching selectable finding IDs and pause for the user to
supply exact `--ids` (or use an existing validated bound selection); do not
create or bind a selection from broad prose. After the user selects IDs, do not
silently reduce them to one representative or highest-value gap. Only on the
legacy no-audit path does the broad request directly authorize all safely
patchable discovered GenAI gaps.

Close code-evidenced AI pathway surfaces from
`../../references/genai-readiness.md`: provider/model gateway, agent/workflow
orchestration, tool/function execution or AI-owned session/stream lifecycle
including MCP when present, retrieval/RAG, streaming response lifecycle,
token/context pressure, safety/policy outcome, prompt/response assembly,
AI-derived data freshness, memory/context operations, evaluation quality,
content governance, framework bridge configuration, app-computed cost,
model/config rollout, and AI-owned cache/session state.

For evaluation quality surfaces, code evidence such as evaluator classes,
scoring functions, LLM-as-judge calls, feedback processors, `EvalScore` models,
faithfulness/similarity/expectation metrics, pass/fail labels, or quality
report exporters is enough to require eval instrumentation.
Metrics-only coverage does not satisfy selected-trace eval visibility. Add or
prove `gen_ai.evaluation.result` on the relevant workflow/evaluation span with
`gen_ai.evaluation.name`, `gen_ai.evaluation.score.value` when numeric scores
exist, `gen_ai.evaluation.score.label` when labels/verdicts exist, and safe
parent linkage. Also add or prove detector-ready score distribution, pass/fail
or violation count, sample count/rate, evaluator duration/error/no-data, and
freshness by low-cardinality workflow/model/evaluation name. If the service
only emits eval counters, histograms, logs, or report files, keep the evaluation quality surface partial
and name the missing span-level eval event and remaining detector metrics.

For MCP, JSON-RPC, and tool dispatch, normalize request metadata before adding
attributes or metric dimensions. Never record JSON-RPC request IDs, raw request
IDs, session IDs, trace IDs, user/account/tenant IDs, raw tool arguments, raw
payloads, prompts, completions, or retrieved content as metric dimensions.
Use stable method names only from an allowlist or from known route/tool registration; otherwise record a low-cardinality method family such as
`known_tool`, `unknown_method`, `invalid_request`, or `unsupported_method`.

Prefer detector-ready metrics and span attributes for outcome, duration,
timeout, retry, rate-limit, fallback, active AI-owned sessions/streams, close
reason family, send/write failure, freshness, empty/low-confidence retrieval,
token budget, prompt build failure, response parse failure, AI-derived data
freshness, prompt/tool schema version, model/config readiness,
model/config compatibility, expected-vs-running model/config state, truncation,
rejection, LLM-call fanout, tool-call fanout, evaluation score/outcome,
memory hit/miss or staleness, content capture mode/redaction, app-owned cost
source, and version dimensions when the service can observe them accurately.
Use OTel GenAI semconv names when possible: `gen_ai.evaluation.result`,
`gen_ai.evaluation.name`, `gen_ai.evaluation.score.value`,
`gen_ai.evaluation.score.label`, safe `gen_ai.evaluation.explanation`, memory
operation names such as `search_memory`, `create_memory`, `update_memory`,
`upsert_memory`, and `delete_memory`, and opt-in content attributes such as
`gen_ai.input.messages`, `gen_ai.output.messages`,
`gen_ai.system_instructions`, `gen_ai.retrieval.documents`,
`gen_ai.retrieval.query.text`, `gen_ai.tool.definitions`, and
`gen_ai.tool.call.arguments`. Treat framework bridges as covered only when
OTel-compatible GenAI semconv output and privacy settings are proven. Treat cost
as custom app-owned instrumentation only when the app owns an accurate pricing
map; otherwise owner-map the billing or provider source. Generic non-AI runtime,
platform, or job surfaces are out of scope for this GenAI section unless source
evidence shows they carry or block the AI pathway.
If GenAI incident evidence depends on missed, flapping, auto-resolved, or
no-data alerts, record detector reliability evidence as a `$splunk-configure`
handoff instead of adding app metrics for alert lifecycle behavior.

For AI-owned streaming generators, WebSocket/SSE handlers, callback bridges,
or protocol send loops, do not call stream lifecycle coverage complete without
a send/write failure signal. Add a counter, span event, or low-cardinality
outcome attribute for send/write failure when app code can observe it; otherwise
owner-map the missing source explicitly to the framework/server/platform.

For token/context pressure gaps, `gen_ai.client.token.usage` plus a
context-window usage gauge does not close a broader token-pressure gap unless
the audit contract only requires those two signals. If `required_signals`
include context budget percent, truncation rate, token-limit errors,
prompt/tool schema size, LLM call count per turn, or tool call count per turn,
mark the row partial until each signal is implemented, proven, or owner-mapped.
When the user broadly asks for GenAI readiness without a preexisting audit
contract, treat token/context pressure as requiring the same concrete signal
check: token usage, context budget percent, truncation, token-limit errors,
prompt/tool schema size or safe proxy, LLM-call count, and tool-call count when
the app can observe them.
Use this exact style when only token and context-window usage were added:
`Partial: token usage and context window added; truncation, token-limit error, prompt/tool schema size, and LLM-call fanout remain missing.`

If prompt/tool schema size cannot be measured safely, add a low-cardinality
detector-ready proxy metric such as schema JSON length bucket, schema field count,
prompt template length bucket, or tool count when the app can observe
it. Span attributes like prompt template version, schema version, or one-off
schema metadata help traces but do not close prompt/tool schema size pressure
by themselves. If no safe metric or detector-ready existing signal exists, the
closure matrix and final response must keep prompt/tool schema size in
`remaining_signals` with the owner and missing source. Do the same for LLM-call
and tool-call fanout: implement per-workflow counts when observable, prove an
existing signal, or keep them explicitly partial.

Final summaries, PR descriptions, and audit updates must not omit residual
truncation, token-limit, prompt/tool schema size, LLM-call fanout, or
tool-call fanout gaps when they were in the audit contract or when broad GenAI
readiness instrumentation discovered the token/context surface.

For tool/function execution, GenAI spans alone do not satisfy detector-ready
tool coverage. When app code observes tool execution, add or prove a
tool-specific duration histogram and tool error/timeout counter using a stable
tool name and low-cardinality failure class. If only spans are safe, keep tool
latency/error metrics in `remaining_signals` and do not claim detector-ready
tool coverage.

Do not call GenAI instrumentation complete when an app-owned provider/model,
workflow, tool/function execution or AI-owned session/stream including MCP when
present, retrieval, streaming, token/context, safety/policy, prompt/response,
AI-derived data, memory/context, evaluation quality, content governance,
framework bridge, app-computed cost, model/config rollout, or AI-owned
cache/session surface remains only listed as a follow-up, unless the user
explicitly narrowed scope.

### GenAI Span Ownership And Context

Create baseline distributed tracing plus OTel GenAI spans for inference,
`invoke_agent`, `invoke_workflow`, `plan`, `execute_tool`, `retrieval`, and
memory operations where code evidence exists. Emit
`gen_ai.client.operation.duration` and `gen_ai.client.token.usage` when the data
is available; use stable tool names; add low-cardinality `error.type`; and avoid
raw prompt, completion, retrieved content, memory record, tool argument,
evaluation explanation, user, tenant, session, task, request, trace, or raw URL
values in metric dimensions.

Apply the `Single-Source GenAI Span Contract` before adding manual spans.
Inventory framework/vendor bridges, provider SDK hooks, callbacks, middleware,
auto-instrumentors, and existing app spans that can emit GenAI telemetry.
Choose one canonical GenAI span source per logical operation: workflow, agent,
model call, tool call, retrieval, memory operation, or evaluation result. If a
framework/vendor bridge already emits correct GenAI semconv spans with
lifecycle, privacy, model/tool attributes, and parent context, keep that bridge
and add only missing workflow/agent context, aggregates, metrics, or owner
mappings; do not create duplicate app-owned `chat` or `execute_tool` spans for
those same operations. If app-owned spans are the canonical source, emit the
complete app-owned span set and disable, opt out of, or suppress overlapping
framework/vendor GenAI instrumentation using the discovered runtime mechanism,
such as instrumentor names, bridge settings, callback configuration, or
provider-hook opt-out flags. Do not hard-code this decision to one framework.
Keep HTTP/database/runtime auto-instrumentation when it does not create
duplicate GenAI nodes.

When the process uses preload, agent, `opentelemetry-instrument`,
`NODE_OPTIONS --require`, or another auto-instrumentation bootstrap, apply the
suppression in the launch environment before the bootstrap runs. Update the
actual startup surfaces the repo uses, such as Makefile targets, service runner
scripts, Docker or Helm env, VS Code launch configs, procfiles, systemd units,
shell env generators, or generated env scripts. App module code that mutates
environment variables after import is only defense in depth and is not
sufficient proof because framework hooks may already be registered.

Verification or static proof must show one GenAI node per logical operation,
no wrapper-only spans counted as tools, expected LLM/tool counts, stable
model/tool names, and workflow/agent parent shape such as
`invoke_workflow -> invoke_agent -> chat/execute_tool`. Required proof should
name stable model/tool names explicitly.

Preserve existing application stable business workflow identity when setting
`gen_ai.workflow.name` and workflow span names. Prefer constants, function or
handler names, workflow registrations, telemetry event names, docs, or prior
trace names. Do not derive GenAI workflow names from HTTP routes, request
resources, session/storage tables, or transport labels. If source evidence
shows a workflow is named `assistant_v3_turn`, keep `assistant_v3_turn`; never
rename it to `assistant_v3_session_turn`, `POST /v2/assistant/sessions`, or
another route/session-derived value. If the app has no stable workflow identity,
keep the HTTP route as the HTTP span and mark GenAI workflow coverage partial
instead of inventing a low-cardinality workflow name. Do not invent names from
HTTP routes or session-derived labels.

Preserve existing application stable agent identity when setting
`gen_ai.agent.name` and agent span names. Prefer framework agent names, agent
factory names, class names, registration names, callback owner names, docs, or
prior trace names. If source evidence shows a DeepAgents-backed agent, use the
discovered stable agent identity such as `deepagents`; never rename it to
`assistant_v3_agent`, `assistant`, `agent`, or another generic service-derived
wrapper name. If the app has no stable agent identity, keep agent coverage
partial instead of inventing one.

For app-owned LLM/model calls, apply the `LLM Inference Lifecycle Contract`.
Do not satisfy inference coverage with workflow-level token accounting,
final usage events, token usage, or model names only on the workflow span. Add or
prove a real model-call lifecycle span at the provider request boundary: start
before the call or stream starts, end after the response/terminal stream event,
and end with error status for exceptions, cancellations, provider timeouts, or
stream-close failures. In LangChain, LangGraph, DeepAgents, callback, or
event-stream based systems, hook `on_chat_model_start`, `on_chat_model_end`, and
`on_chat_model_error` or the equivalent lifecycle callbacks. In direct
SDK/model-gateway code, wrap the provider call or streaming generator. The span
must carry `gen_ai.operation.name` such as `chat`, `generate_content`, or
`text_completion`, `gen_ai.provider.name`, `gen_ai.request.model` when known,
`gen_ai.response.model` when known, and token usage on that inference span when
provider usage is available.

Preserve the owning workflow/agent context for event-derived GenAI spans. In
callback, stream, LangChain, LangGraph, or DeepAgents integrations, capture the
workflow/agent context and use it when starting chat/model and tool spans. Do
not let callback-created `chat` or `execute_tool` spans attach to a generic HTTP
root span as siblings of the workflow. A representative trace should prove a
shape such as `workflow -> chat`, `workflow -> execute_tool`, and follow-up
`workflow -> chat` or `agent -> chat` edges.

Capture that workflow/agent context before opening long-lived helper/setup
spans such as memory store, checkpointer, database session, stream-writer,
resource setup, or lifecycle wrappers. These helper spans must not become the
parent for model/tool lifecycle spans. Event-derived `chat` and `execute_tool`
spans must use the captured workflow/agent context, not whichever helper span
happens to be current when a callback is translated. Store the workflow/agent
span object or context explicitly so stream cleanup writes aggregates to that
owner even if the current span has changed.

Use this rule for memory store, checkpointer, database session, stream-writer,
or resource setup paths: helper spans must not become the parent; capture the
workflow/agent context before opening helper spans, start event-derived `chat`
and `execute_tool` spans with that captured context, and write aggregate
counters to the workflow span, not to whichever current span is active.

In async generator, SSE, WebSocket, ping-loop, timeout-wrapper, or task handoff
paths that advance a stream with `create_task`, `wait`, `anext`, or equivalent
scheduling, do not keep an OpenTelemetry current-span context manager open
across yield/task boundaries. Start the workflow/agent span with an explicit
parent context, store a workflow span/context handle, pass that handle into the
callback/event translator, and end the workflow span manually after stream
cleanup.

When the captured workflow/agent context must travel through a request, turn
input, event payload, callback state, or config object that may be
immutable/frozen or owned by a framework, do not mutate that carrier in place.
Treat a carrier as immutable/frozen when source evidence shows frozen or
readonly declarations, record/value types, no mutation API, framework request
immutability patterns, or existing code constructs new copies instead of
mutating.

Use the app's idiomatic copy/replacement API: Python `dataclasses.replace`,
`attrs.evolve`, pydantic `model_copy(update=...)` or v1 `copy(update=...)`;
Java records, builders, or copy constructors; TypeScript object spread,
explicit `Readonly<T>` replacements, or `structuredClone` only for plain-data
carriers and never for live OTel `Context` or `Span` handles; Go value copies
with explicit field replacement; or the framework's request clone/with-context
API. If no safe copy path exists, use a separate invocation-scoped sidecar
context: a local object, context variable, request-scoped map, or callback
state keyed to the invocation lifecycle and cleared after cleanup. Do not key
sidecar context by raw user, tenant, session, request, or trace IDs. Add a
focused test, or explicit static proof when the repo has no test harness, that
proves the parent context is passed downstream and the original immutable
input remains unchanged; for Python, guard against `FrozenInstanceError`
regressions when a frozen dataclass or model is present.

Put aggregate selected-trace GenAI attributes on the workflow span or
most specific owning GenAI span, not on a generic HTTP root span or generic server span.
This includes `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, `gen_ai.usage.total_tokens`,
`assistant.llm.calls`, and `assistant.tool.calls`. The HTTP root can remain the
server entrypoint, but it should not become the evidence for a GenAI flow card
unless it is explicitly instrumented as the workflow span.

If runtime telemetry verification is unavailable, perform a static
instrumentation proof before claiming GenAI trace coverage: identify the
model-call source file, the lifecycle hook or client wrapper, the created
inference span name, required `gen_ai.*` attributes, parent-context handoff,
aggregate-attribute placement, end/error path, and a focused test or compile
check. If the proof shows only workflow-level usage attributes and no inference
span, or chat/tool spans that are siblings of the workflow under a generic HTTP
root span, keep the surface partial in `remaining_signals`.

For local span-first trace explorers such as Obstudio, metrics alone are not enough
for a selected-trace summary. When provider usage, model, tool, memory,
evaluation, or fanout data is available, also set safe span attributes on the
most specific GenAI span and aggregate to the workflow span when useful:
`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
`gen_ai.usage.total_tokens`, `gen_ai.request.model`, `gen_ai.response.model`,
service-owned LLM/tool call counts, stable `gen_ai.tool.name`, memory operation
names, evaluation names/labels, and low-cardinality `error.type`.

For assistant, agent, or streaming workflows, instrument first non-ping event
or first chunk latency, timeout, cancellation, disconnect, close reason family,
and send/write failure. Normalize timeout classes such as
`first_event_timeout` instead of relying only on framework exception class
names, while still recording the exception on the span.

## Finalization

When the source audit declares GenAI ownership, include the complete
`GenAI Readiness Closure` matrix and list every non-`Working` remaining signal
in the final response.

For GenAI work without a source audit, explicitly list each unimplemented
token/context-pressure signal in the final response: context budget,
truncation, token-limit errors, prompt/tool schema size, LLM-call fanout, and
tool-call fanout. Do not collapse absent items into a generic readiness claim
and do not create a `GenAI Readiness Closure` table without source-audit rows.

For GenAI work, state which OTel GenAI operations were instrumented, which
GenAI metrics are expected, whether trace continuity should produce a nested
workflow/agent/tool/chat/retrieval shape, and which privacy/cardinality limits
were enforced.

For GenAI incident-evidence work, include a concise coverage summary by
incident class or repo surface: MTTD-improving, localization-only, or
uncovered. Name any remaining provider/model, workflow, tool/function
execution or AI-owned session/stream including MCP when present, retrieval,
streaming, token/context, prompt/response, safety/policy, AI-derived data,
model/config rollout, or AI-owned cache/session owner that still blocks
detector-ready coverage.
