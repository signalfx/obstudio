# GenAI Audit Contract

Load only when repository discovery finds GenAI/LLM ownership. Read this after
the shared `../../references/genai-readiness.md`; do not load it for non-GenAI
services.

**GenAI readiness assessment** -- when GenAI/LLM evidence exists, use
`../../references/genai-readiness.md` to check baseline trace continuity,
OpenTelemetry GenAI spans, semconv completeness, GenAI metrics, and
privacy/cardinality controls. Add or update `## GenAI Readiness` rows for
missing workflow, provider/model gateway, model/config rollout,
model/config compatibility, expected-vs-running model/config state,
tool/function execution or AI-owned session/stream lifecycle including MCP when
present, token/context pressure, retrieval/RAG, streaming response lifecycle,
fallback/failover, prompt/response assembly, safety/policy outcome,
AI-derived data freshness, memory/context, evaluation quality, framework bridge
coverage, content governance, cost ownership, or AI-owned cache/session state
signals. For each telemetry-distinct owned surface, write one separate
readiness row with its complete required signals. Keep workflow, provider/model,
tool/function, token/context, stream/session, retrieval, evaluation/data export,
and other distinct surfaces independently actionable for instrumentation
closure. For code-owned GenAI pathway gaps, explicitly check for token/context
pressure,
response parse failure, AI-derived data freshness, prompt/tool schema version,
LLM-call count, tool-call count, authentication/authorization result,
invalid-token or permission failure outcome, active AI-owned streams or
sessions, close reason family, stream duration/outcome, send/write failure,
memory hit/miss or stale/missing context, `gen_ai.evaluation.result` coverage,
evaluation score distribution, content capture mode/redaction/access owner, and
app-owned cost or owner-mapped billing source when those values are observable.
Classify these rows before creating findings:

- Telemetry closure rows may become findings when they name service-owned OTel
  spans, metrics, logs, attributes, exporter/resource setup, correlation,
  cardinality, or semantic-convention gaps.
- Governance/context rows stay in `## GenAI Readiness` unless the user
  explicitly asks for that audit domain. Content capture policy,
  redaction/retention/access ownership, safety/refusal policy, evaluation
  explanation policy, model rollout policy, and cost/billing ownership are not
  default service instrumentation findings.
- Evaluation telemetry can be a finding when the repository owns concrete OTel
  evaluation events or low-cardinality evaluator duration/error/no-data/
  freshness metrics. Do not bundle that with safety or content-governance work
  unless both are explicitly requested.
- Cost telemetry can be a finding only when the repository owns an authoritative
  pricing source or the user explicitly asks for FinOps/cost observability.
  Otherwise owner-map the external billing source in readiness context and do
  not create service instrumentation work.
For LLM/model-call coverage, apply the `LLM Inference Lifecycle Contract`:
audit the real lifecycle hook or client call site, not only the outer workflow
and final usage aggregation. In LangChain, LangGraph, DeepAgents, callback, or
event-stream based systems, look for `on_chat_model_start`,
`on_chat_model_end`, `on_chat_model_error`, or an equivalent model-call
callback. In direct provider SDK or model-gateway code, look for a span wrapping
the provider request or streaming generator. If token/model attributes are
present only on a workflow span, final usage event, turn-finalization path, or
other workflow-level token accounting, but no `chat`, `generate_content`,
`text_completion`, or equivalent inference span exists with
`gen_ai.operation.name`, `gen_ai.request.model`, and `gen_ai.response.model`
when known, mark trace and semconv coverage `partial`; do not mark LLM coverage
as `covered`. Keep the missing model-call lifecycle span and attributes in
`remaining_signals`.
Apply the `Single-Source GenAI Span Contract` from the GenAI readiness
reference before deciding trace coverage. Inventory framework/vendor bridges,
provider SDK hooks, callbacks, middleware, and auto-instrumentors that can emit
GenAI spans, then compare them with app-owned spans for the same logical
workflow, agent, chat/model call, tool call, retrieval, memory, or evaluation
operation. Mark trace and semconv coverage `partial` when a representative
trace or source proof shows both framework/vendor and app-owned spans for the
same logical operation, wrapper spans such as middleware or step execution being
counted as tools, duplicate model/tool call counts, divergent parentage, or
aggregate attributes written to the wrong canonical span. Required closure
evidence is one canonical GenAI span source per logical operation. A
representative trace must show one GenAI node per logical operation, expected
LLM and tool counts, stable model/tool names, correct workflow/agent parent
shape, and no wrapper-only spans counted as GenAI work.
Audit workflow naming as part of this proof. GenAI workflow names must preserve
the application's stable business workflow identity from constants, handlers,
workflow registrations, telemetry event names, docs, or prior trace names. Mark
workflow coverage `partial` when instrumentation invents names from HTTP
routes, request resources, session/storage concepts, or transport labels. For
example, `assistant_v3_turn` must not become `assistant_v3_session_turn` or
`POST /v2/assistant/sessions`.
Do not invent names from HTTP routes or session-derived labels.
Audit agent naming with the same rule. GenAI agent names must preserve the
application's stable agent identity from framework agent names, agent factory
names, classes, registration names, callback owner names, docs, or prior trace
names. Mark agent coverage `partial` when instrumentation invents generic
service-derived names. For example, a DeepAgents-backed agent should be
`deepagents`, not `assistant_v3_agent`, `assistant`, or `agent`.
Keep duplicate-span remediation in `remaining_signals` unless the audit proves
either the framework/vendor bridge is canonical and app duplicates are absent,
or app-owned spans are
canonical and overlapping framework/vendor GenAI instrumentation is disabled,
opted out, or suppressed by the app's discovered runtime mechanism.
When app-owned spans are canonical and the process uses preload, agent,
`opentelemetry-instrument`, `NODE_OPTIONS --require`, or another
auto-instrumentation bootstrap, audit the launch environment and startup
surfaces that run before the bootstrap. Mark duplicate-span remediation
`partial` if the only proof is App module code that mutates environment
variables after import, because that is not sufficient proof and framework
hooks may already be registered. Accept proof from Makefile
targets, service runner scripts, Docker or Helm env, VS Code launch configs,
procfiles, systemd units, shell env generators, or the exact documented run
command. Also accept generated env scripts when they are sourced before the
bootstrap.
Also audit parent-context proof for event-derived spans. In representative trace
evidence or tests, chat/model and tool spans must preserve the owning workflow/agent context
and prove a trace shape such as `workflow -> chat`, `workflow -> execute_tool`,
and follow-up `workflow -> chat` or `agent -> chat` edges. If they appear as
siblings of the workflow under a generic HTTP root span or generic server span,
mark the trace shape `partial` and keep parent-context propagation in
`remaining_signals`. Also check long-lived helper/setup spans such as memory
store, checkpointer, database session, stream-writer, or resource setup spans.
If callback-created chat/tool spans are parented to those helper spans instead
of the owning workflow/agent span, mark the trace shape `partial`; the
instrumentation must capture/re-enter the workflow/agent context before opening
helper spans and must not rely on whichever current span is active during
callback cleanup. Use this rule for memory store, checkpointer, database
session, stream-writer, or resource setup paths: helper spans must not become
the parent; capture the workflow/agent context before opening helper spans,
start event-derived `chat` and `execute_tool` spans with that captured context,
and write aggregate counters to the workflow span, not to whichever current span
is active. For async generator, SSE, WebSocket, ping-loop, or timeout
wrapper paths, check whether the stream is advanced with `create_task`, `wait`,
`anext`, or equivalent task handoff. If an OpenTelemetry current-span context
manager is kept open across those yield/task boundaries, mark the trace shape
`partial`; require an explicit workflow span/context handle that is passed into
the callback/event translator and ended manually. Also check whether that
workflow/agent context is carried through a request, turn input, event payload,
callback state, or config object that may be immutable/frozen. If the
instrumentation does not prove that app code will avoid mutating immutable,
frozen, or framework-owned carriers, keep parent-context propagation `partial`;
do not mutate those carriers in place. Treat a carrier as immutable/frozen when
source evidence shows frozen or readonly declarations, record/value types, no
mutation API, framework request immutability patterns, or existing code
constructs new copies instead of mutating.
Accept app-idiomatic copy/replacement proof such as Python
`dataclasses.replace`, `attrs.evolve`, pydantic `model_copy(update=...)` or v1
`copy(update=...)`; Java records, builders, or copy constructors; TypeScript
object spread, explicit `Readonly<T>` replacements, or `structuredClone` only
for plain-data carriers and never for live OTel `Context` or `Span` handles; Go
value copies with explicit field replacement; or the framework's request
clone/with-context API. If no safe copy path exists, require a separate
invocation-scoped sidecar context: a local object, context variable,
request-scoped map, or callback state keyed to the invocation lifecycle and
cleared after cleanup. Do not key sidecar context by raw user, tenant, session,
request, or trace IDs. Require a test or explicit static proof that the parent context is
passed downstream and the original immutable input remains unchanged; Python
tests should guard against `FrozenInstanceError` where frozen dataclasses or
models exist. Audit aggregate placement separately: if
`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
`gen_ai.usage.total_tokens`, `assistant.llm.calls`, or `assistant.tool.calls`
are written only to a generic HTTP root span, report misplaced aggregate GenAI
attributes and require moving them to the workflow span or most specific owning GenAI span.
A generic HTTP root span should not be the evidence for a GenAI flow card unless
it has an explicit GenAI workflow operation.
If incident evidence depends on missed, flapping, auto-resolved, or no-data alerts, record detector reliability evidence
as a `$splunk-configure` handoff instead of an app-owned GenAI instrumentation
prerequisite.

For GenAI services and demos, distinguish demo-only environment hints from
complete telemetry wiring. If a Makefile, README, script, or example command
sets only `OTEL_SERVICE_NAME` or `OTEL_EXPORTER_OTLP_ENDPOINT`, but the service
has no SDK setup, exporter setup, resource attributes, or framework
instrumentation, report that as incomplete resource/exporter configuration
rather than covered setup.

**GenAI readiness contract** -- the `## GenAI Readiness` table is the complete
GenAI observability ledger. Only telemetry closure rows from that ledger become
instrumentation findings; governance, product, cost, policy, and external-owner
rows remain context unless the user explicitly asks for that audit domain. For
every GenAI readiness gap, create or update a structured surface row with:
`surface`, `evidence`, `current_status`, `required_signals`,
`owner/source_files`, and `acceptance_criteria`. If an existing audit already
has extra metadata columns, keep the surface name as the human-facing
identifier in summaries and closure handoffs. Split a surface when required
signals have different owners or acceptance criteria. Required
signals must be concrete signal names or signal intents, not vague area labels.
Use owner values that map directly to instrumentation outcomes: `App-owned +
patchable`, `App-owned but unsafe/too large`, `Provider/platform-owned`, or
`Already covered`.

Status must be computed against every required signal:

| Ledger result | Rule |
|---|---|
| `covered` | Every required GenAI signal is proven existing with source path and signal name. |
| `partial` | Some required GenAI signals exist, but remaining required signals are named. |
| `missing` | No required app-owned GenAI signal exists. |
| `owner-mapped` | The repo cannot accurately observe the signal and the provider/platform/deployment owner plus exact missing source is named. |

Do not collapse a partial GenAI gap into `covered` because one metric or span
exists. The GenAI Readiness surface row is the source of truth for deciding
whether a selectable `$otel-instrument` finding is warranted.

Compute each GenAI surface independently. Generic HTTP/database/runtime or
infrastructure metrics do not improve a GenAI surface status unless they
satisfy that row's required workflow, model, tool, token, memory, evaluation,
or AI-path signals. Use `missing` when none of the required GenAI signals
exists, even if unrelated OTel metrics are source-active.
