# GenAI Audit Contract

Load this reference only when repository evidence shows GenAI/LLM ownership.
Also load `../../references/genai-readiness.md`; that shared reference defines
the current semantic-convention and readiness contracts.

## Readiness Assessment

Check baseline trace continuity, OpenTelemetry GenAI spans, semconv
completeness, GenAI metrics, and privacy/cardinality controls. Add or update
`## GenAI Readiness` rows for missing workflow, provider/model gateway,
model/config rollout, tool/function execution or AI-owned session/stream
lifecycle including MCP when present, token/context pressure, retrieval/RAG,
streaming response lifecycle, fallback/failover, prompt/response assembly,
safety/policy outcome, AI-derived data freshness, memory/context, evaluation
quality, framework bridge coverage, content governance, cost ownership, or
AI-owned cache/session state signals.

For each telemetry-distinct owned surface, write one separate readiness row
with its complete required signals. Keep workflow, provider/model,
tool/function, token/context, stream/session, retrieval, evaluation/data
export, and other distinct surfaces independently actionable for
instrumentation closure. For code-owned GenAI pathway gaps, explicitly check
for token/context pressure, response parse failure, AI-derived data freshness,
prompt/tool schema version, LLM-call count, tool-call count,
authentication/authorization result, invalid-token or permission failure
outcome, active AI-owned streams or sessions, close reason family, stream
duration/outcome, send/write failure, memory hit/miss or stale/missing context,
`gen_ai.evaluation.result` coverage, evaluation score distribution, content
capture mode/redaction/access owner, and app-owned cost or owner-mapped billing
source when those values are observable.

## Lifecycle And Single-Source Proof

Apply the `LLM Inference Lifecycle Contract`: audit the real lifecycle hook or
client call site, not only the outer workflow and final usage aggregation. In
LangChain, LangGraph, DeepAgents, callback, or event-stream based systems, look
for `on_chat_model_start`, `on_chat_model_end`, `on_chat_model_error`, or an
equivalent model-call callback. In direct provider SDK or model-gateway code,
look for a span wrapping the provider request or streaming generator. If
token/model attributes are present only on a workflow span, final usage event,
turn-finalization path, or other workflow-level token accounting, but no
`chat`, `generate_content`, `text_completion`, or equivalent inference span
exists with `gen_ai.operation.name`, `gen_ai.request.model`, and
`gen_ai.response.model` when known, mark trace and semconv coverage `partial`;
do not mark LLM coverage as `covered`. Keep the missing model-call lifecycle
span and attributes in `remaining_signals`.

Apply the `Single-Source GenAI Span Contract` before deciding trace coverage.
Inventory framework/vendor bridges, provider SDK hooks, callbacks, middleware,
and auto-instrumentors that can emit GenAI spans, then compare them with
app-owned spans for the same logical workflow, agent, chat/model call, tool
call, retrieval, memory, or evaluation operation. Mark trace and semconv
coverage `partial` when a representative trace or source proof shows both
framework/vendor and app-owned spans for the same logical operation, wrapper
spans such as middleware or step execution being counted as tools, duplicate
model/tool call counts, divergent parentage, or aggregate attributes written
to the wrong canonical span. Required closure evidence is one canonical GenAI
span source per logical operation. A representative trace must show one GenAI
node per logical operation, expected LLM and tool counts, stable model/tool
names, correct workflow/agent parent shape, and no wrapper-only spans counted
as GenAI work.

Preserve the application's stable business workflow identity from constants,
handlers, workflow registrations, telemetry event names, docs, or prior trace
names. Mark workflow coverage `partial` when instrumentation invents names from
HTTP routes, request resources, session/storage concepts, or transport labels.
For example, `assistant_v3_turn` must not become
`assistant_v3_session_turn` or `POST /v2/assistant/sessions`. Do not invent
names from HTTP routes or session-derived labels. Apply the same rule to the
stable agent identity from framework agent names, agent factories, classes,
registration names, callback owner names, docs, or prior trace names. A
DeepAgents-backed agent should be `deepagents`, not `assistant_v3_agent`,
`assistant`, or `agent`.

When source proves both an HTTP entry route and a stable GenAI workflow
identity, record the transport boundary on the existing single-source/workflow
ownership finding. Its `constraints` or `acceptance_criteria` must state that
the HTTP server span may remain the trace root but must not set
`gen_ai.operation.name=invoke_workflow` and must not become the GenAI workflow
card; the stable `invoke_workflow <workflow-name>` span remains the workflow
card. Do not create a second finding solely for this transport-to-workflow
boundary.

Keep duplicate-span remediation in `remaining_signals` unless the audit proves
either the framework/vendor bridge is canonical and app duplicates are absent,
or app-owned spans are canonical and overlapping framework/vendor GenAI
instrumentation is disabled, opted out, or suppressed by the app's discovered
runtime mechanism. When the process uses preload, an agent,
`opentelemetry-instrument`, `NODE_OPTIONS --require`, or another bootstrap,
audit launch environment and startup surfaces that run before bootstrap.
App-module environment mutation after import is not sufficient proof. Accept
Makefile targets, service runner scripts, Docker or Helm env, VS Code launch
configs, procfiles, systemd units, shell env generators, the exact documented
run command, or generated env scripts sourced before bootstrap.

## Parent Context And Immutable Handoff

In representative trace evidence or tests, chat/model and tool spans must
preserve the owning workflow/agent context and prove shapes such as
`workflow -> chat`, `workflow -> execute_tool`, and follow-up
`workflow -> chat` or `agent -> chat`. Sibling placement under a generic HTTP
root is partial coverage. Long-lived memory-store, checkpointer, database
session, stream-writer, or setup spans must not become the parent; capture the
workflow/agent context first, start event-derived spans with that captured
context, and write aggregates to the workflow span.

For async generator, SSE, WebSocket, ping-loop, or timeout wrapper paths, check
task handoff through `create_task`, `wait`, `anext`, or equivalents. An OTel
current-span context manager kept open across yield/task boundaries is partial;
require an explicit workflow span/context handle passed to the callback/event
translator and ended manually.

Do not mutate immutable, frozen, readonly, record/value, or framework-owned
carriers in place. Accept app-idiomatic copy/replacement such as Python
`dataclasses.replace`, `attrs.evolve`, pydantic `model_copy(update=...)` or v1
`copy(update=...)`; Java records, builders, or copy constructors; TypeScript
object spread or `Readonly<T>` replacements (`structuredClone` only for plain
data, never live OTel `Context` or `Span`); Go value copies with explicit field
replacement; or framework request clone/with-context APIs. If no safe copy path
exists, use an invocation-scoped sidecar context cleared after cleanup and
never keyed by raw user, tenant, session, request, or trace IDs. Require a test
or static proof that parent context passes downstream and the original input
remains unchanged; Python tests should guard against `FrozenInstanceError`.

If `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
`gen_ai.usage.total_tokens`, `assistant.llm.calls`, or `assistant.tool.calls`
exist only on a generic HTTP root span, report misplaced aggregate attributes
and require moving them to the workflow span or most specific owning GenAI
span. A generic HTTP root must not represent a GenAI flow card unless it has an
explicit GenAI workflow operation.

## Readiness Table Contract

The `## GenAI Readiness` table is the complete instrumentation contract, not
background context. Every row has `surface`, `evidence`, `current_status`,
`required_signals`, `owner/source_files`, and `acceptance_criteria`. Keep the
surface name as the human-facing identifier. Split surfaces whose required
signals have different owners or acceptance criteria. Required signals must be
concrete signal names or intents. Use owners `App-owned + patchable`,
`App-owned but unsafe/too large`, `Provider/platform-owned`, or
`Already covered`. For an `owner-mapped` row, the owner must include a concrete
external source after the category prefix, for example
`Provider/platform-owned: billing API`. `Provider/platform-owned` by itself or
a generic team label is not an exact owner and fails audit validation.

| Ledger result | Rule |
|---|---|
| `covered` | Every required GenAI signal is proven existing with source path and signal name. |
| `partial` | Some required GenAI signals exist, but remaining required signals are named. |
| `missing` | No required app-owned GenAI signal exists. |
| `owner-mapped` | The repo cannot accurately observe the signal and the provider/platform/deployment owner plus exact missing source is named. |

Compute each surface independently. Generic HTTP, database, runtime, or
infrastructure metrics do not improve a GenAI surface unless they satisfy that
row's workflow, model, tool, token, memory, evaluation, or AI-path signals.

## Audit-Specific Reporting Rules

- Keep GenAI readiness generic: no organization-specific service names,
  incident IDs, customer names, realms, or provider account names.
- Prefer OTel GenAI semantic conventions. Missing `gen_ai.request.model` is a
  gap when the requested model is available.
- In GenAI incident-evidence mode, map `incident class -> failure mechanism ->
  repo/service owner -> code surface -> signal -> MTTD impact -> remaining
  owner`, classifying gaps as `MTTD-improving`, `localization-only`,
  `provider/platform-owned`, or `unknown owner`.
- Treat provider/model gateway health, workflow outcome, tool/function
  execution or AI-owned session/stream lifecycle including MCP when present,
  retrieval/RAG freshness or quality, streaming lifecycle, token/context
  pressure, prompt/response build or parse outcome, safety/policy outcome,
  AI-derived data freshness, model/config rollout, and AI-owned cache/session
  state as gaps only when source or runtime evidence proves repository ownership.
- Name concrete detector-ready signals: token/context budget percent,
  truncation rate, token-limit errors, prompt/tool schema size, LLM call count,
  tool call count, response parse failure, AI-derived data freshness,
  prompt/tool schema version, model/config readiness and compatibility, and
  expected-vs-running model/config state.
- Missed, flapping, auto-resolved, or no-data alert evidence is a
  `$splunk-configure` detector-reliability handoff, not an app instrumentation
  prerequisite.
- Demo-only `OTEL_SERVICE_NAME` or `OTEL_EXPORTER_OTLP_ENDPOINT` hints without
  SDK setup, exporter setup, resource attributes, or framework instrumentation
  are incomplete resource/exporter configuration, not covered telemetry.

## Required Proof Vocabulary

Use these exact concepts when the matching source surface exists; they keep the
audit contract unambiguous for downstream closure.

- For an auto-instrumentation bootstrap, suppression must be configured in the
  launch environment before the bootstrap. App module code that mutates
  environment variables is not sufficient proof because framework hooks may
  already be registered.
- Never attach event-derived work to a generic server span.
- Preserve stable agent identity from framework agent names, agent factory
  names, registration names, callback owner names, and prior trace names. Do
  not substitute a generic service-derived identity.
- Event-derived spans must preserve the owning workflow/agent context. If they
  are siblings of the workflow under a generic HTTP root span or generic server
  span, parent-context proof is incomplete. Aggregate attributes belong on the
  workflow span or most specific owning GenAI span and missing proof stays in
  `remaining_signals`.
- For long-lived helper/setup spans such as memory store, checkpointer,
  database session, stream-writer, or resource setup, helper spans must not
  become the parent. Capture the workflow/agent context before opening helper
  spans, start event-derived `chat` and `execute_tool` spans with that context,
  and write aggregate counters to the workflow span rather than whichever
  current span is active. For an async generator using `create_task`, `anext`,
  or another task handoff across yield/task boundaries, carry an explicit
  span/context handle into the callback/event translator.
- Treat a carrier as immutable/frozen when source evidence shows readonly
  declarations, record/value types, no mutation API, framework ownership, or
  existing code constructs new copies. Do not mutate it. Use idiomatic
  copy/replacement: `dataclasses.replace`, `attrs.evolve`,
  `model_copy(update=...)`, Java records, TypeScript object spread,
  `Readonly<T>`, `structuredClone` only for plain-data carriers and never live
  OTel `Context` or `Span` handles, Go value copies, or the framework's request
  clone/with-context API. If no safe copy path exists, use an
  invocation-scoped sidecar context cleared after cleanup. Do not key sidecar
  context by raw user, tenant, session, request, or trace IDs. A test or
  explicit static proof must show the parent context is passed and the original
  immutable input remains unchanged, including a `FrozenInstanceError` guard
  where relevant.
- For immutable carriers, do not mutate the original value.
- The GenAI readiness contract is the complete instrumentation contract. Parse
  `surface`, `evidence`, `current_status`, `required_signals`, owner/source
  files, and acceptance criteria, retaining the surface name as the
  human-facing identifier.
- In GenAI incident-evidence mode, record the continuous mapping
  `incident class -> failure mechanism -> repo/service owner -> code surface -> signal -> MTTD impact -> remaining owner`.
- Check authentication/authorization result, invalid-token or permission
  failure outcome, send/write failure, evaluation quality,
  `gen_ai.evaluation.result`, evaluation score distribution, content capture
  mode/redaction/access owner, owner-mapped billing source, model/config
  compatibility, detector reliability evidence, and missed, flapping,
  auto-resolved, or no-data alerts when source ownership exists.
- Check the exact invalid-token or permission failure outcome.
- Keep content capture mode/redaction/access owner independently actionable.
- Record model/config compatibility and expected-vs-running model/config state.
- Preserve missed, flapping, auto-resolved, or no-data alerts as detector
  reliability evidence.
- Treat demo-only environment hints as incomplete unless SDK setup, exporter
  setup, resource attributes, and framework instrumentation prove a complete
  path.
