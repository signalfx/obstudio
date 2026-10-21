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

Use OpenTelemetry GenAI semantic conventions for the emitted signals. Add custom attributes only
for service-owned workflow context when no OTel convention exists. Keep this
reference scoped to AI pathways. Generic app surfaces such as streams, jobs,
synthetic/canary checks, startup/deployment compatibility, input complexity,
capacity, and release context belong here only when source evidence shows they
exercise, carry, or block an AI workflow.

## GenAI Instrumentation Selection

Choose the span producer from the application's actual runtime, separately from
its export destination:

| Runtime evidence | Default instrumentation path |
|---|---|
| Existing Galileo integration, including Galileo plus native OTel | Preserve Galileo's native creators, resource clients, configuration and export path plus legitimate existing OTel sinks. Fill uncovered OTel signals without duplicate operations. Resolve project and stream through the installed Galileo client's supported APIs; do not substitute Splunk AO configuration or Studio routing for that native destination. |
| Existing OTel instrumentation for any signal, framework bridge, or application spans without Galileo | Preserve existing producers, providers and exporters. Enrich existing spans through supported hooks; add OTel spans, metrics and logs only for proven uncovered operations. Generic HTTP spans, a metrics-only or logs-only pipeline, and an active export-only provider all select this incremental path even when GenAI coverage is missing. Do not introduce Splunk AO instrumentation or a new SDK dependency to fill those gaps. |
| Existing Splunk AO span creation | Preserve it and fill its version-specific gaps without duplicate operation spans. |
| Agent runtime with no existing telemetry instrumentation and a compatible supported Splunk AO SDK for its language | Introduce Splunk AO instrumentation by default, using SDK `@log` for supported function boundaries. If its exact contract cannot meet requirements, assess the supported SDK creator and then the source-proven per-operation public OTel exception below. An unused dependency, evaluation-only import or ordinary stdout logger alone does not establish runtime OTel instrumentation. |
| Agent runtime whose language has no compatible supported Splunk AO SDK | Use that language's supported native OpenTelemetry libraries and framework instrumentation. Add application-owned spans for remaining source-proven GenAI operations and apply the same Required GenAI Coverage Profile and both vendors' compatibility mappings. AO SDK absence does not block instrumentation or reduce semantic acceptance. |

Classify the actual target process before choosing a creator. Trace source-active
or externally bootstrapped providers, instrumentors and exporters for each signal
from startup to its call sites. Missing GenAI attributes do not make an already
instrumented application fresh. Unknown producer ownership is an evidence gap;
preserve it while resolving that gap. Keep signal coverage scoring independent
of this preservation decision.

Record a before/after operation inventory with each existing creator, provider,
exporter destination and observable fields. Prove the same existing operation
still emits once, retains its parent/context and safe fields, and preserves
existing metric/log values. Exercise the real startup and configured export
path alongside any added operation. Do not disable an existing framework
instrumentor or replace its spans to make a duplicate check pass. If supported
enrichment cannot resolve a privacy or semantic defect, report the exact
limitation and a manual decision rather than silently substituting a producer.
Every source-owned agent runtime requires project, dedicated Agent Stream and
runtime-routing assessment, independently of creator choice or a separate AO
request. Missing app-owned bindings are `default` configuration findings;
existing native OTel and an incompatible AO SDK never exclude them. Follow
`splunk-agent-observability.md`: native OTel uses SDK-free resource APIs and
supported trace headers; Galileo uses its native project/log-stream APIs and
export configuration; existing AO uses its supported SDK path. Preserve an
explicit destination and any explicit user exclusion. Ordinary non-agent model
or workflow code alone does not impose product adoption. This assessment does
not claim that resources are absent globally or authorize audit-time creation.

For a fresh Python agent, read the **Fresh Agent SDK Instrumentation** section
of `splunk-agent-observability.md` before authoring the audit finding or code.
The fresh-app default does not require a separate SDK-choice question. Record
the intended SDK API and installed-version support in the selected finding.
`add_splunk_ao_span_processor` is export-only and cannot satisfy this choice.
For that fresh default, assess intended AO project/Agent Stream/routing through
the shared AO reference even when no SDK import exists. Keep product findings
separate from ordinary GenAI findings and respect selected adoption scope.
If a checked SDK path cannot meet an operation's required semantics, apply the
per-operation compatibility exception in `splunk-agent-observability.md`: a
named application-owned function decorator may use a supported public OTel
creator for that exact boundary while preserving the provider, selected AO
export and supported SDK creators elsewhere. Label its producer as application
OTel. This requires concrete SDK source/probe limits and a complete safe field,
context and lifecycle mapping; it does not authorize a whole-app rewrite.
If no supported repair exists, name the exact prerequisite and keep the surface
partial. Explicit user choices override the default. Existing valid producers
remain the default for already instrumented operations.

For a fresh runtime, check SDK support for the actual language from current official
documentation, package metadata and public APIs; record the sources and date.
Do not infer another language's support from Python examples, invent a package,
or install a Python sidecar to obtain span creation. When a compatible AO SDK
is unavailable, select native OTel directly without requiring a failing AO
installation or gateway. If a bounded source check cannot establish AO SDK
support, record that uncertainty and use the native path rather than blocking
supported telemetry work. Keep a real native-library or field limitation scoped
to its affected operation/signal, with an explicit remaining gap.

The native path has the same per-operation content, parameter, usage,
correlation, privacy, schema, lifecycle and complete-trace acceptance below.
Inspect actual emitted fields; native OTel installation and an OTLP exporter
alone do not produce GenAI semantics. Use language-native wrappers or supported
hooks for function boundaries instead of assuming Python `@log` syntax. Keep
Project/Agent Stream resolution and destination-specific trace routing
independent of the creator through the SDK-free resource path.

For every new or repaired function hook, assess its language's supported
decorator or wrapper pattern first.
Within the selected Splunk AO producer path, use SDK `@log` wherever the chosen release supports the actual function and
required safe content, semantics, lifecycle and export path. This includes
ordinary sync/async functions, methods, serial nested calls and bounded plain
sync/async iteration; async generators alone are not a reason to avoid it.
Do not decorate an operation already captured by a framework/provider wrapper.
When SDK `@log` has a concrete incompatible contract, keep the function decorator
pattern through an application-owned decorator invoking the documented chosen
creator for that same operation. Manual scopes remain appropriate for genuine
non-function or externally managed lifetimes. Preserve existing valid producers
and explicit supported choices; do not rewrite working instrumentation merely
to change its syntax.

Resolve the latest compatible published library release set at task time from
official metadata and the project resolver, checking runtime, peers, APIs and
existing constraints together. This applies to every library, including SDKs,
schema packages, framework integrations, bridges and exporters. Fixed release
numbers and historical version thresholds do not belong in skill recipes.
Record exact chosen versions, source/date and compatibility probes in each run
report; an existing constrained compatible set may be retained with its reason.

## Required GenAI Coverage Profile

For GenAI audit, instrumentation, and verification, require applicable,
observable semantic attributes and content as acceptance criteria. Consult the
current official OTel conventions and schemas, plus
[Galileo's integration recommendations](https://docs.galileo.ai/sdk-api/third-party-integrations/opentelemetry-and-openinference/integration-recommendations)
and
[Splunk AO's integration recommendations](https://agent-observability-docs.splunk.com/sdk-api/third-party-integrations/opentelemetry-and-openinference/integration-recommendations).
OTel's published `Opt-In` level remains accurate provenance; it is not a reason
to omit an applicable field or pass metadata-only instrumentation under this
profile. Record `official level -> vendor requirement -> skill acceptance ->
applicability/source value -> emitted -> proven -> remaining` per operation.

Require actual, bounded, redacted input/output messages for workflow, agent,
and model operations; actual tool arguments/results and the vendor's tool
message mappings or supported OpenInference equivalents; retrieval query and
document output when the application really retrieves AI context. Require
effective system instructions, actual offered tool definitions, real prompt
variables, request parameters, response identity/finish reasons, usage,
streaming flags/timing, and opaque conversation/tool-call correlation where
applicable and observable. Do not invent unavailable values, provider defaults,
identifiers, prompt variables, token counts, or successful output for failures.
Model system-role messages embedded in chat history belong in input messages;
separate system instructions apply only when the API supplies them separately.

The vendor agent tables additionally require provider identity, and their tool
tables call for message mappings alongside arguments/results. Preserve these
as vendor compatibility checks when the latest OTel operation table differs.
For each applicable `execute_tool` span, reconcile the actual call arguments
and terminal result with this vendor content contract:

| Tool value | GenAI mapping on the same tool span | Supported OpenInference alternative |
|---|---|---|
| Redacted actual arguments | `gen_ai.tool.call.arguments` and `gen_ai.input.messages` | `input.value` |
| Redacted actual result, when produced | `gen_ai.tool.call.result` and `gen_ai.output.messages` | `output.value` |

Arguments/results alone leave the vendor message mapping missing. Messages on
an agent, model, parent, sibling, event on another span, or duplicate wrapper
cannot close a tool's fields. Use current typed-parts schemas and a supported
serialization of those same sanitized arguments/results, not unrelated chat
history or placeholders. Preserve source types/structure where supported,
actual safe call identity, configured limits and truthful truncation/gap reasons.
Track whether a result was produced separately from its value: a successful
`null`, `false`, zero or empty collection is still an actual result and must
retain its truthful mapping. An error/cancel/timeout with no produced result
must record error status/type and an explicit output applicability reason;
never synthesize successful output.

Audit must put each missing applicable field in the owning canonical finding's
`required_fix`, per-tool `expected_telemetry`, acceptance and verification
scenario, then check those fields before handoff. Instrumentation must inspect
what the chosen SDK or preserved producer actually emits and fill missing
mappings through supported same-span application hooks from pre-SDK sanitized
values. SDK installation, creator method names or exporter setup prove no field.
Verification must match by the tool span's trace/span ID, validate each mapping
against the observed sanitized arguments/result and current schema, and report
missing, malformed or mismatched fields individually. Restricted capture of an
otherwise available value remains partial with a reason, even when its safety test passes. Source-unavailable output on a failed
operation is N/A only with the corresponding lifecycle and no-result evidence.

Use current OTel typed-parts schemas rather than copying older vendor
role/content examples. Do not convert HTTP, database authorization, ASGI, or
setup helpers into GenAI workflows/retrievers because a backend labels them
`workflow`. Unsupported SDK mapping is an enrichment gap, not an automatic pass.
An explicit user-selected restricted content scope stays restricted, but missing
required fields remain partial against this profile; do not export forbidden
content or declare full coverage. Do not let an old blanket no-content/no-ID
audit constraint silently override a newer user requirement; refresh and bind
the selected scope before implementation.

## Required GenAI Report Evidence

Every GenAI audit, implementation plan/report and verification review must
include the following three compact tables. This also applies to supplemental
fixture reviews and plan-only tasks. Populate them from the actual source and
captured evidence; general promises or citations do not replace the rows.
In canonical flow, keep the assessments in canonical evidence and the relevant
finding/acceptance fields; supplemental Markdown/JSON must agree with them.

**Operation and producer receipt**

| Operation and actual source boundary | Exact creator or preserved hook | Kind and parent | Version and example/source revision | Source-to-safe content hook | Proof and remaining gap |
|---|---|---|---|---|---|

Give each real agent, model, tool, applicable workflow/retrieval and auxiliary
model call its own row. Join the named API to the boundary in that row. Record
the concrete official example filename/path as well as its revision/date and
package version; a repository URL or revision alone is not example evidence.
Distinguish an API inspected in SDK source from a method actually exercised by
that example: the logger basic example illustrates trace/LLM/conclude, while
`flush`, `terminate` and unexercised creators need their own signature/source
receipt. For a custom fresh Python agent, compare the named-method table,
**Public Schema Span Helpers** and **Same SDK Span Content Enrichment** in
`splunk-agent-observability.md`: e.g. supported `add_agent_span` at the actual
agent, `add_llm_span` at each model request and `add_tool_span` at each tool,
or the documented schema helper at a boundary it supports. Identify the
selected SDK creator, proposed or installed version, and exact example revision;
a proposed version checked against latest examples is not proof of installed
or emitted support.
For a native field gap, name the safe SDK carrier and the exact same-span
application hook, selected sink/exporter registration and version proof. A
generic future hook promise is Partial. The checked Python exporter adapter
uses `SpanExporter.export` and a `ReadableSpan` view with original context and
parent; it does not create operation spans. Source-only plans may propose this
concrete path while keeping registration, installed support and emissions
unproven. Audit binds that path or the precise blocker in the owning finding;
verification checks actual identity/value/safety evidence, not the API name.
Before declaring a logger hook prerequisite external, assess the shared AO
reference's Public Schema Span Helpers against each real operation. A supported
yielded-span setter is an actionable same-span path; keep its finalizer, provider
binding and exact unsupported fields/kinds explicit. A logger-only limitation
must not block independent operations that another supported SDK creator covers.
Record INTERNAL for an in-process agent/tool, CLIENT for a separate-process
model, and their actual parents. A `start_trace`/`conclude` envelope is not an
emitted workflow; `add_workflow_span` applies only to a real composed workflow.
For an existing producer, name the original creator and same-span enrichment
hook rather than selecting a new SDK. Add explicit GenAI **N/A** rows for
ordinary HTTP/ASGI/auth/SQL/setup helpers present in source or supplied facts.

**Field acceptance and provenance**

| Operation and field | Official OTel level | Galileo/Splunk AO expectation | Required profile acceptance | Actual source value or absence | Capture API/schema/redaction | Emitted/proven or remaining |
|---|---|---|---|---|---|---|

Use separate rows for input messages, output messages, separate instructions,
offered tool definitions, arguments/results and vendor tool input/output
message wrappers. Include provider/model identity, known request parameters,
response/finish/usage/stream fields and supplied opaque correlation IDs.
Write the published level explicitly: e.g. messages, instructions and tool
definitions are OTel **Opt-In**, but applicable safe content is **required by
this profile**. Record vendor INTERNAL-agent provider and tool-message
requirements separately. Do not relabel OTel's standard or omit provenance
from the canonical audit. Use current typed-parts schemas; unavailable values
and failed successful outputs are absent with a reason, not invented. Preserve
safe source-provided conversation/tool-call IDs as span-only correlation when
the bound capture contract permits them; do not add an unnecessary approval
question or silently drop them. Keep IDs out of metrics and span names.
For each tool execution, explicitly assess `gen_ai.agent.name` from the active
owning agent, `gen_ai.conversation.id` from the available safe conversation
context, and `gen_ai.tool.description` from the actual tool definition. Parent
attributes do not supply these fields on the tool's own span. For agent
invocations, apply the inspected model applicability footnote: populate
`gen_ai.request.model` for a known fixed single-model agent, not an agent that
permits multiple models or dynamic selection. Keep the actual requested model
on its inference span; a service-owned selected-model field may describe
dynamic agent context. An unused demo-mode argument is not model evidence.
Assess a configured `gen_ai.agent.description` when available; do not invent
agent metadata by paraphrasing a system prompt or README.
Bind applicable missing fields to the owning finding and span assertions, with
source-backed reasons where unavailable. Preserve the inspected official
conditional/recommended levels separately from this profile's required known
field acceptance; do not invent an agent ID, model or conversation.

Specify concrete capture settings and where they are applied before every
exporter. Preserve an existing stricter policy; otherwise propose/implement
`redacted`, at most 16 messages, 64 parts per message and 8192 UTF-8 bytes per content
attribute. Redact credentials, tokens, email and identified sensitive source
fields before the SDK receives them. Bound text parts before serialization so
JSON stays valid; preserve useful safe content and mark truncation with an
application attribute. If structured data cannot fit safely, record that gap
rather than export malformed JSON or a placeholder. These are adjustable
application limits, not OTel-prescribed limits. Plan-only reports must give
numeric proposed settings and hooks; fixture-only reviews mark configuration
unproven and give the precise acceptance test. Require a sentinel-absence test
over native records, attributes/events and wire payload as applicable.

Use representation-sensitive negative cases for the selected capture policy.
Parsing JSON is not sanitization: recurse into decoded scalar strings as well
as containers, without repeatedly decoding the same scalar. Remove protected
values, not only their labels, in source-shaped `hidden_reasoning=...` and
`private_prompt=...` text. A typed part with `type: reasoning` is protected by
its discriminator even though its payload key is merely `content`; inspect
that semantic type before traversing ordinary fields. Apply the policy to
inputs and produced outputs without changing business arguments/results.
Validate the concrete schema selected by a known part's discriminator; a
malformed known type must not fall through to a permissive `GenericPart`.
Unknown extension types keep the inspected schema's explicit extension policy.

Check UTF-8 limits on the final serialized value of every content attribute,
including retrieval queries and embedded JSON. Per-leaf bounds alone do not
bound an aggregate; truncate structured content before serialization and
validate the result again. Add negative cases for quoted JSON scalars,
protected labelled text, nested/JSON-encoded reasoning parts, malformed known
parts and aggregate multibyte overflow. Assert protected-value absence and
useful safe-content retention on completed native records and actual exports,
not just a sanitizer's return. Audit specifies these acceptance cases;
instrument implements and executes them; verification tests or reports their
exact missing proof. Keep earlier failing receipts when a repair passes.

**Lifecycle and delivery evidence**

| Operation/scenario | Success/error/timeout/cancel terminal behavior | Parent/context and duplicate rule | Flush/close/terminate evidence | Captured proof or missing test |
|---|---|---|---|---|

Assess main and independent auxiliary calls separately, even when the main
turn or cloud UI says complete. Include explicit timeout, cancellation and
process-teardown rows; use source-backed N/A where an operation does not exist.
If a supplied auxiliary request timed out without an ended inference/error
span, report that exact missing lifecycle rather than passing ended main
spans. Assess context cleanup and exactly one node per actual operation.
Captured fixtures cannot prove application cleanup/SDK execution; absent
teardown/cancel evidence remains Not proven with a concrete test. Assess OTLP
partial-success rejection separately from HTTP200 or cloud completeness.
Preserve finish-reason positions for known expected generations. If a reason
was expected but absent after failure, cancellation or abnormal stream end,
record `error` for that known position while keeping unproduced output absent.
Do not invent generation slots when their count is unknown.
Assess creation-time sampling context separately from completed-span content.
When the inspected conventions recommend operation/provider/model/server or
other fields at creation, inspect the selected creator's arguments and the
actual sampler/`on_start` inputs. Later setters or exporter views cannot change
an earlier sampling decision. Record SDK limits and any affected configured
sampling behavior without inventing a new API or equating wire enrichment with
creation-time support; an always-on policy does not demonstrate attribute-based
sampling compatibility.
Before finalizing, reconcile all source operations/known fields against these
tables and correct missing rows. Do not claim full coverage from a score or
summary when any applicable requirement remains missing.

## Splunk Observability Studio GenAI Trace UI Contract

Splunk Observability Studio's GenAI trace view is span-first. If a value exists only in a metric
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
| Tokens summary | Current inference input/output usage counters with `gen_ai.token.modality`; retain any existing legacy token metric as a consumer contract. Also set available `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` on the owning GenAI span; a derived total uses an application/vendor-owned attribute |
| LLM/tool call counts | Service-owned per-workflow attributes or metrics such as `assistant.llm.calls` and `assistant.tool.calls`, plus child spans when possible |
| Error badges | Span status ERROR plus low-cardinality `error.type` |
| Streaming timeout explanation | First event/chunk latency, stream close reason family, timeout/cancel/disconnect events, and workflow ERROR with `error.type=first_event_timeout` or another stable class |

If an audit gap mentions a local trace summary, Splunk Observability Studio view, selected trace,
or demo trace, treat span-level selected-trace summary attributes as required
acceptance criteria in addition to detector metrics.

Do not put selected-trace aggregate GenAI usage on a generic HTTP root span or
generic server span. Attributes such as `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, an application/vendor-owned derived total,
`assistant.llm.calls`, and `assistant.tool.calls` belong on the workflow span or
the most specific owning GenAI span. A root HTTP span may wrap the whole request,
but it should not become a GenAI flow card unless it is explicitly the workflow
span with `gen_ai.operation.name=invoke_workflow`.

Check proposed attributes against the current official registry. Do not add
`gen_ai.usage.total_tokens` as an OTel semantic attribute when it is absent from
that registry. If a total is useful, use an application/vendor-owned field such
as `assistant.usage.total_tokens`, identify its calculation and distinguish
actual provider counts from estimates. Preserve and label a proven existing
legacy alias required by a consumer; do not require that alias on fresh spans.

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

The audit handoff must name the existing canonical owner for each discovered
logical-operation family: workflow, agent, model call, tool call, retrieval,
memory, and evaluation when present. Preserve that owner and name the supported
enrichment hook or exact uncovered boundary. If source evidence is insufficient
to establish ownership, classify it as a `manual decision` instead of authoring
a competing default producer.

If the framework/vendor bridge is the canonical source, keep it and add only
missing app-owned workflow/agent context, safe aggregate attributes, metrics,
or owner mappings. Do not add duplicate app-owned `chat` or `execute_tool`
spans for operations that the bridge already emits with correct semconv,
privacy, model/tool attributes, lifecycle, and parent context.

When existing app-owned spans are canonical, retain them and add only missing
operations or fields. Check the real bootstrap and startup environment for
framework spans before adding a new creator. Do not install overlapping
instrumentation and then disable an existing bridge to justify the new spans.
If the application already has competing owners, record the source-backed
conflict and exact affected operations as a manual decision. A gap-filling run
must preserve unrelated framework, HTTP, database, metrics and log coverage.
Changes to the real launch profile must be exercised through that profile;
module-local environment edits after bootstrap do not prove the intended state.

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
  `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`; any derived
  total follows the application/vendor namespace rule above. Aggregate to
  the owning agent/workflow span only as a
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
`dataclasses.replace`, `attrs.evolve`, pydantic `model_copy(update=...)` or
`copy(update=...)` as supported by the installed carrier API; Java records,
builders, or copy constructors; TypeScript
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

Apply the Required GenAI Coverage Profile and record both vendor sources and
the matching SDK example/API provenance. Classify each detected runtime using
GenAI Instrumentation Selection before choosing its canonical producer. An
SDK package, exporter success, complete trace flag, or span count is not proof
that required fields/content are emitted correctly.

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
- input and output token usage through current inference usage metrics when
  provider usage data is available, with explicit unknown-usage handling.

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
  per-workflow aggregated tokens and LLM calls. Use current inference usage
  metrics and provider/model attributes as the semconv source of usage. If the
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

Semconv publishes prompt, response, system instruction, retrieval document, and
tool definition/argument content as Opt-In attributes such as
`gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`,
`gen_ai.retrieval.documents`, `gen_ai.retrieval.query.text`,
`gen_ai.tool.definitions`, `gen_ai.tool.call.arguments`, and
`gen_ai.tool.call.result`. These fields are
sensitive.

For each model, retrieval, or tool surface that owns one of these values, audit
whether the corresponding attribute is emitted. Include missing applicable
attributes in that surface's existing `required_signals`, finding
`expected_telemetry`, and verification scenario; do not create a separate
finding for every attribute or hide them as governance-only context. Do not
propose attributes for content the application cannot observe.

When an existing GenAI finding containing these attributes is selected,
implement the exact listed attributes without a second content-capture
approval or runtime enablement step. Redact and truncate before recording,
follow the official structured schema, and prove trace/log correlation.

Audit content capture as `disabled`, `metadata-only`, `redacted`, or
`full-content`. This skill's required profile defaults to useful redacted
content capture, not disabled or metadata-only capture. Populate the real
capture configuration and redaction/truncation hook before SDK construction;
prove the SDK supports that mode. Require a storage destination,
retention/access owner, and trace/log correlation evidence. Redact credentials,
sensitive identity and hidden reasoning before any configured exporter sees
them; preserve ordered messages, typed parts, tool-call identity and valid JSON
under limits. A companion redacted field does not remove its original. If a
capture restriction or SDK limitation prevents useful safe content, report the
exact missing acceptance instead of substituting empty placeholders. Never
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
around the owned workflow boundaries of an existing producer and owner-map its
bridge/platform gaps. For a fresh agent, use the default Splunk AO creation
path from GenAI Instrumentation Selection instead of taking this existing-bridge
gap-filling clause as permission to build a new custom producer.
The source-proven per-operation compatibility exception above remains available
when both applicable SDK creation paths cannot meet the selected contract.

### Existing Vendor SDK Preservation

Treat an existing Galileo SDK integration, or another vendor GenAI bridge, as
working telemetry to preserve rather than an implicit migration request. First
identify whether the integration is only an OTel processor/exporter, creates
spans through wrappers or callbacks, or does both. A processor/exporter does not
by itself prove that workflow, model, tool, retrieval, streaming, memory, or
evaluation operations are instrumented.

Preserve the existing supported integration by default. Fill required GenAI
fields/content on its canonical spans through documented application hooks or
configuration. Close uncovered application-owned operations with compatible
OpenTelemetry spans, metrics, events, resource attributes, and lifecycle
handling at the owning application call sites. Keep those gaps as ordinary OTel findings even when the existing vendor
processor exports the resulting signals. Do not require a switch to another
vendor SDK merely because the target product can also consume that SDK.

Never edit an installed dependency, virtual environment, `site-packages`,
`node_modules`, generated client, or vendored cache to repair an SDK gap. Use a
documented application hook or configuration surface, add an app-owned OTel
closure, or record the exact external SDK prerequisite. Changing an
application-owned fork is a separate, explicitly selected scope.

For an existing Galileo path, keep its producer, provider and native exporter.
Assess and resolve its project/log-stream bindings through supported Galileo
APIs and the actual loaded vendor profile. Add missing non-overlapping OTel
signals without installing Splunk AO or adding a Studio route by default. For
other native OTel paths, use SDK-free resource APIs and supported trace headers.
An explicitly selected additional destination remains separate and must
preserve original Galileo selectors, authentication and export. If an API cannot
enrich a required field or route to the selected destination, name that exact
prerequisite rather than migrating the producer.
Verification must compare before/after operations, fields, metrics and logs,
prove one canonical span per logical operation and one export to each intended
destination, and separately prove project/stream routing when selected.

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

Resolve the current official GenAI metric contract at task time alongside the
span conventions. Inspect instrument types, units, required measurement
attributes and error/unknown-usage rules; familiar historical names do not
establish the current contract. Current inference conventions use:

- `gen_ai.client.inference.duration`, a duration histogram in seconds.
- `gen_ai.client.inference.usage.input_tokens` and
  `gen_ai.client.inference.usage.output_tokens`, token counters with
  `gen_ai.token.modality` plus the applicable operation/provider/model fields.
- Source-applicable cache/reasoning counters, per-operation token distributions
  and streaming timing metrics from the current inference/token tables.

The current contract excludes inference from `gen_ai.client.operation.duration`;
use that metric only for its applicable non-inference operations. Preserve
existing `gen_ai.client.token.usage`/`gen_ai.token.type` and older streaming
metrics as explicit compatibility contracts instead of silently renaming or
duplicating their producers. Record any selected transition and its consumer
impact separately from current-convention acceptance.

Use provider-reported usage and the current documented aggregation semantics.
Do not estimate tokens or substitute billing values for another defined count.
Where the current usage-counter contract specifies zero with modality `unknown`
for a missing/error response, prove that metric convention separately from
observed usage; it does not authorize fabricated span usage or successful
output. Keep unavailable source values explicit. Match every chosen metric to
the exact current table and observable source in the closure matrix.

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
| Slow or timing-out assistant/workflow | workflow p90/p99, applicable operation duration, `gen_ai.client.inference.duration` for inference, timeout rate by workflow/provider/model/environment |
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
- The required GenAI profile captures applicable content through configured
  redaction and limits; do not make it an optional completion criterion. Keep
  it out of metric dimensions. Treat `gen_ai.input.messages`,
  `gen_ai.output.messages`, `gen_ai.system_instructions`,
  `gen_ai.retrieval.documents`, `gen_ai.retrieval.query.text`,
  `gen_ai.tool.definitions`, `gen_ai.tool.call.arguments`,
  `gen_ai.tool.call.result`, and
  `gen_ai.evaluation.explanation` as sensitive.
- Span names and metric attributes must be stable. Replace IDs and path
  variables with templates such as `{id}` or `{resource}`.
- Conversation/session/task IDs may be useful as trace attributes for drilldown
  only when policy allows; never use them for metrics, detectors, or dashboard
  group-by dimensions.
