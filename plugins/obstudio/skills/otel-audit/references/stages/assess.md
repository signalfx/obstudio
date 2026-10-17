### Step 2 -- Instrumentation Assessment

Check for existing OTel instrumentation and identify gaps. Inventory every
signal by type so the report can list them explicitly.

**SDK and configuration** -- search for:

- OTel SDK initialization files (`otel_setup.py`, `instrumentation.ts`, `otel.go`, etc.)
- OTel imports/dependencies (`opentelemetry`, `otel`, `otlp`, `go.opentelemetry.io`)
- Auto-instrumentation packages matching detected frameworks/clients
- `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT` in env files or configs
- Per-signal OTLP endpoint and protocol variables. Record the effective pair
  (`grpc` with the gRPC receiver, or `http/protobuf` with `/v1/<signal>`), not
  just a host or port. A configured endpoint with an incompatible protocol is
  a required exporter gap.
- Resolve the effective local receiver with the shared local-receiver
  precedence. Record the source of the resolved endpoint and preserve every
  configured non-default port. Treat `4317` and `4318` only as conventional
  fallbacks when no endpoint is configured or discoverable; flag startup code
  that calls Obstudio, MCP, or its REST API to discover the endpoint at
  application runtime.
- Resolve whether the logs endpoint is the local Splunk Observability Studio receiver or a direct
  cloud ingest endpoint. An unset signal-specific logs endpoint must not inherit
  a generic direct-cloud endpoint: local application logs default to Splunk Observability Studio,
  while direct-cloud or Splunk Observability Studio cloud forwarding is traces and metrics only.
  An explicit local Splunk Observability Studio logs endpoint may participate in the default
  pipeline. An explicit non-local endpoint paired with an absent or `otlp`
  exporter is instead an operator-owned boundary conflict. Represent it as an
  `external follow-up` that requires the named operator to remove the non-local
  endpoint or replace it with the exact detected local Splunk Observability Studio endpoint, plus
  a dependent `required`/`default` local-log finding. The
  dependency keeps the executable finding locked until the operator resolves
  the conflict; do not classify the conflict as a scan blocker or authorize
  the provider/bridge early. Preserve `none` and other
  non-OTLP exporter branches without validating their endpoint. Flag any cloud
  log endpoint, credential/header, exporter, or forwarding flag introduced by
  Splunk Observability Studio instrumentation as a required boundary violation.
- Treat any nonempty generic `OTEL_EXPORTER_OTLP_HEADERS` as unsafe for an
  Splunk Observability Studio-owned local log path, even when
  `OTEL_EXPORTER_OTLP_LOGS_HEADERS` is also set. SDKs may merge generic and
  signal-specific headers. Require the generic value to be moved to
  trace/metric signal variables and removed before local log export is enabled.
- Semantic-convention stability opt-ins and when they are set relative to SDK
  and framework imports. Treat a late opt-in as inactive for already-created
  instruments.

**Provider/exporter topology** -- build this per target process and per signal;
do not infer it only from the launch command or installed packages.

- Find explicit and lazy `TracerProvider`, `MeterProvider`, and
  `LoggerProvider` construction, global `set_*_provider` calls, no-op provider
  branches, exporter construction, resource creation, flush/shutdown, and
  helpers that initialize providers on first instrument access.
- Trace each provider helper from the selected process entrypoint and real
  startup environment to its recording call sites. Classify each signal as
  `source-active`, `externally bootstrapped`, `source-defined but inactive`, or
  `no provider`; none of these classifications is runtime emission proof.
- Keep provider ownership separate by signal. A process can own a real metrics
  provider while tracing and logs remain disabled. Never describe all OTel as
  no-op because one startup wrapper lacks `opentelemetry-instrument`.
- For Python repositories, run the bundled
  `scripts/scan_python_otel_topology.py <service-root>` before reporting. The
  scanner finds candidates; reconcile every hit with target-process
  reachability before using it as evidence.
- Reconcile resource precedence. Identify operator-provided
  `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES`, app defaults, detector
  output, and any merge that overwrites `service.name`, environment, or
  version. Preserve operator values and classify hard-coded overwrite as a
  required resource-identity gap.
- For framework instrumentation, record whether the app is instrumented before
  serving begins. In frameworks that install middleware, instrumentation first
  invoked inside lifespan/startup can be too late; classify it as partial until
  source or runtime proof shows middleware was installed before the first
  request.

**Spans inventory** -- build a list of every span source:

- Auto-instrumentation packages that emit spans (check the "Signals" column in
the language reference). Enumerate every individual span name the package
produces -- one row per span. Never group spans with vague labels like
"HTTP server spans" or "gRPC server spans (all N RPCs)". For example,
`otelgrpc` on a server with methods `GetUser` and `ListUsers` produces spans
`/UserService/GetUser` and `/UserService/ListUsers` -- list each as its own
row.
- Custom span creation calls: `tracer.Start` / `span.End` (Go),
`tracer.start_as_current_span` / `tracer.start_span` (Python),
`tracer.startActiveSpan` / `tracer.startSpan` (Node.js),
`@WithSpan` / `Span.current()` (Java).
Record the span name and source file with line number.

**Metrics inventory** -- build a list of every metric source:

- Auto-instrumentation packages that emit metrics (check the "Signals" column).
Enumerate every individual metric name the package produces -- one row per
metric. Never group metrics with vague labels like "(+ related)" or
parenthetical summaries like "(goroutines, memory, GC)". For example,
`otelgrpc` emits `rpc.server.call.duration` (or the legacy `rpc.server.duration`
on older SDK versions), `rpc.server.request.size`, `rpc.server.response.size`,
`rpc.server.requests_per_rpc`, and `rpc.server.responses_per_rpc` -- list each
as its own row. Similarly,
`runtime.Start()` emits `process.runtime.go.goroutines`,
`process.runtime.go.mem.heap_alloc`, `process.runtime.go.gc.count`, etc. --
list each individually.
- Custom metric registrations: `meter.Int64Counter`, `meter.Float64Histogram`,
`meter.Int64ObservableGauge`, `meter.Int64UpDownCounter` (Go);
`meter.create_counter`, `meter.create_histogram`,
`meter.create_observable_gauge` (Python);
`meter.createCounter`, `meter.createHistogram`,
`meter.createObservableGauge` (Node.js).
Record the metric name and source file with line number.

**Logs inventory** -- build a list of OTel log integrations:

- OTel log bridge or SDK log packages
  (`opentelemetry-instrumentation-logging` for current Python releases, with
  the SDK `LoggingHandler` only when the installed bridge/API capability
  requires that compatibility path;
  `@opentelemetry/instrumentation-console`,
  `@opentelemetry/instrumentation-winston`, or
  `@opentelemetry/instrumentation-pino` for Node.js; the Java agent's detected
  Logback/Log4j appender; and the matching
  `go.opentelemetry.io/contrib/bridges` package for Go).
- `LoggerProvider`, batch log record processor, OTLP log exporter,
  signal-specific logs endpoint, global registration, and shutdown/flush.
- Existing stdout, stderr, file, platform, appender, handler, transport, hook,
  and worker-thread sinks. Identify which stay active and whether two bridges
  would export the same application record twice.
- Trace-context injection into log records (`trace_id`, `span_id` fields).
- `span.AddEvent()` / `span.add_event()` calls used as structured log events.
- Logging formatters, filters, adapters, MDC/context variables, access-log
  formatters, and exception helpers that can add request, user, tenant,
  session, trace, raw URL, exception text, or traceback data. Check the final
  formatting path, not only application logger call arguments.
- Classify logs as `local-otlp-default`, `explicitly-disabled`,
  `operator-owned`, `correlation-only`, `unsupported-stack`, or `not
  configured`. Trace/MDC fields in stdout are not an OTLP log pipeline.
  `OTEL_LOGS_EXPORTER=none` is an explicit opt-out, while an absent exporter on
  a supported Python, Node.js, Java, or Go application logging stack requires a
  default local Splunk Observability Studio OTLP pipeline only when the logs endpoint is absent or
  matches the detected local Splunk Observability Studio receiver. Preserve any other explicit
  exporter as operator-owned without validating or supplementing its endpoint.
  For an absent/`otlp` exporter with an explicit non-local endpoint, record an
  external operator prerequisite and a dependent default local-log finding;
  do not classify it as working or select that implementation until the
  dependency is resolved. If `none` is set
  while an existing bridge still exports application records, report the
  ineffective opt-out as a required ownership gap.

**Audit document contract** -- the audit is a current-state baseline source
scan. Describe the instrumentation and gaps established by current repository
evidence. Implementation changes belong in `.observe/otel-instrumentation.md`.

**Verification plan** -- derive deterministic inputs for later
instrumentation and verification. This is source-derived planning, not runtime
proof.

- Define reusable test environments for each runnable surface. Give every
  environment a stable ID and record its configured runtime/toolchain,
  evidence file, expected project runner, affected module scope, and shared
  prerequisites once.
- Create one scenario per telemetry-distinct user, API, worker, startup,
  shutdown, error, timeout, streaming, tool, retrieval, or dependency path.
- Use stable scenario IDs such as `http.search.success`,
  `http.search.failure`, `runtime.startup`, or `worker.batch.failure`.
- Map each scenario to its source entrypoint, expected exact signals, and
  acceptance criteria: span status/attributes/parentage, metric datapoints and
  dimensions, log body/severity/correlation/redaction, or runtime/exporter
  behavior.
- Classify each scenario's required proof as `focused call-site`,
  `full runtime`, or `either`. Use `full runtime` when proof depends on agent or
  preload startup, framework-resolved route names, automatic metrics,
  runtime-installed log export, or absence of duplicate automatic spans.
- For a default local application-log pipeline, include scenarios that prove
  body/category, severity, the same service resource identity as traces and
  metrics, trace/span correlation inside an active span, final-pipeline
  redaction, preservation of the existing stdout/file sink, exactly one OTLP
  record per log call, provider shutdown/flush, and
  `OTEL_LOGS_EXPORTER=none` producing no OTLP record. When cloud trace/metric
  export or forwarding exists, also prove the application record remains
  visible in local Splunk Observability Studio without any cloud log path.
- Require the normal generated launch profile to set
  `OTEL_LOGS_EXPORTER=otlp`, the resolved local Studio logs endpoint and its
  matching protocol alongside trace and metric settings. An absent logs bridge
  or an unrequested generated `none` setting is a log coverage gap, even when
  traces and metrics work. Keep a real explicit user/operator logs opt-out as
  separate scope; do not recommend `none` as the normal launch default. SDK
  `@log` spans and stdout correlation are not received OTLP LogRecords.
- For local OTLP export, include at least one scenario using a discovered or
  fixture-provided non-default receiver port. Its acceptance criteria must
  prove the exact endpoint/protocol/path tuple and that application startup
  does not query Obstudio for routing or endpoint registration.
- For every exact custom span name or operation entrypoint, create an explicit
  scenario row. Shared helper implementation is not proof that each operation
  emits its expected name and topology.
- Before writing a scenario, confirm every cited source path and symbol exists
  with `rg -n` or a language-aware index. Never hand off a guessed or stale
  symbol name. Never invoke `rg` with `--pre` or `--pre-glob`; those flags run
  an arbitrary external command against matched files rather than only
  searching them. Use plain search flags only (for example `-n`, `-l`, `-i`).
- Reference one or more exact test-environment IDs from every acceptance
  scenario. Put local-safe fixture strategy and missing prerequisites in the
  environment profile, not repeated prose in each scenario row.
- Keep prerequisites explicit. Do not require live credentials when fakes or
  an existing test seam can exercise the same app code.
- Avoid path explosion: combine branches only when they emit identical
  telemetry; split success/failure or alternate paths when telemetry differs.

**Dependencies without instrumentation** -- for each dependency detected in Step 1:

- Check if a matching auto-instrumentation package is installed
- Use the Auto-Instrumentation Library Map below as the checklist
- Flag any dependency that has an available auto-instrumentation package but is not instrumented

**Operational signal assessment** -- express rate, error, latency, and
saturation coverage as ordinary entries in `## Current Instrumentation`,
`## Gaps`, or `## Verification Plan` with exact source paths and signal names.

**Incident readiness assessment** -- when the repository owns incident-relevant
surfaces or the user asks for faster detection/localization, use
`../references/incident-readiness.md` to assess API/workflow and customer
impact, dependencies, input complexity, freshness, backpressure,
synthetic/canary checks, auth/edge, capacity, and release/config context. For
incident evidence, classify each proposed signal as `MTTD-improving` only when
it can support a detector before or at first customer impact,
`localization-only` when it mainly narrows an already-detected fault,
`provider/platform-owned`, or `unknown owner`.

Record current readiness as `### Incident Readiness` under
`## Current Instrumentation`; do not add another top-level report section.
Readiness rows are audit context first. Promote a missing or partial readiness
surface into the single prioritized `## Gaps` table only when the repository
owns a concrete OTel closure gap: a span, metric, log, provider/exporter,
resource, semantic attribute, correlation, cardinality, or runtime lifecycle
change that can be implemented without changing the product/runtime contract.
The prioritized gap row and its mapped acceptance scenarios form the closure
contract for `$otel-instrument` and `$splunk-configure`:

- `Area` is the stable human-readable gap identity used downstream.
- `Required fix` names every required signal or exact owner mapping; it must not
  use a vague label such as `add observability`.
- `Instrument mode` records whether safe app-owned work is `default`, broader
  safe work is `fix all`, or an external/unsafe choice is `manual decision`.
- The mapped scenario provides the code surface, expected telemetry, proof
  level, and acceptance criteria.

Split a gap when required signals have different owners, instrument modes, or
acceptance criteria. Do not promote service behavior choices, health endpoint
semantics, readiness/liveness contracts, capacity policy, release policy, or
general operational observations into findings unless the user explicitly asks
for that domain and the row names concrete service-owned OTel telemetry to add
or repair. When an external owner must supply telemetry, record the owner and
requirement in the readiness row and summary by default; create an
`external follow-up` finding only when it blocks an in-scope service-owned OTel
finding. Do not mark a partial surface covered because one span or metric
exists, and do not imply that detector configuration can compensate for an
absent detector-critical metric.

**GenAI readiness assessment** -- when GenAI/LLM evidence exists, use
`../references/genai-readiness.md` to check baseline trace continuity,
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
  explicitly asks for that audit domain. Redaction/retention/access ownership,
  safety/refusal policy, evaluation explanation policy, model rollout policy,
  and cost/billing ownership are not default service instrumentation findings.
  Missing source-backed GenAI content attributes are telemetry gaps, not
  governance-only rows. Add each applicable attribute named in the shared
  Content Capture Governance Contract to the owning model, retrieval, or tool
  readiness row and existing selectable finding's `expected_telemetry`; give
  that finding a redacted-content verification scenario. Do not create one
  finding per attribute or omit an applicable attribute solely because its
  value is sensitive. Do not require a second content-capture approval after
  the finding is selected. Do not propose fields the application cannot observe.
  Before `finalize-audit`, reconcile every app-owned model, retrieval, and tool
  boundary with all eight attributes in that contract: `gen_ai.input.messages`,
  `gen_ai.output.messages`, `gen_ai.system_instructions`,
  `gen_ai.retrieval.documents`, `gen_ai.retrieval.query.text`,
  `gen_ai.tool.definitions`, `gen_ai.tool.call.arguments`, and
  `gen_ai.tool.call.result`. Inspect the actual provider-bound input and
  returned output, observable instructions and tool definitions, retrieval
  query and documents, and tool-call arguments and result. Put each applicable
  missing attribute literally in the owning finding's `expected_telemetry`
  and require an assertion on its completed model, retrieval, or tool span in
  the verification scenario. Metadata-only spans or prose about privacy and
  capture mode do not close source-backed content coverage. If safe emission
  is not feasible, retain the unresolved finding and name the blocker instead
  of marking it covered.
  Assess successful null results separately from calls that produced no result.
  When the verified tool schema cannot represent null in
  `gen_ai.tool.call.result`, recognize a truthful captured OpenInference
  `output.value="null"` as the supported alternative. Require removal of a
  schema-invalid native result and retain the remaining same-tool-span content
  requirements. A failed call with no result must not gain successful output.
  Supplied helper captures establish that case's capability, not live app or
  exporter coverage; bind unproved application behavior to a local scenario.
  Require evidence of the actual value crossing its owning boundary before
  classifying a content attribute as applicable: a tool name or handler source
  is not a model-bound `gen_ai.tool.definitions` payload. A prompt passed to
  a search-like tool is not `gen_ai.retrieval.query.text` unless the tool
  consumes that value as its search or lookup input; a prompt used only to
  simulate an error is not a retrieval query. Counts or scores without
  returned document objects are not `gen_ai.retrieval.documents`. Keep
  observable tool-call arguments and results in the tool finding rather than
  promoting an unused parameter to retrieval content.
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
Apply **Retrieval detection inside tools** independently of tool-call coverage.
Inspect each code-owned tool body and its reachable helpers for semantic,
vector, corpus, document, index, knowledge-base, or embedding search whose
results become model context. A name such as `search_docs` is useful evidence
but is not sufficient by itself; corroborate it with the implementation,
dependency calls, returned matches/documents/scores, or the caller's use of the
results. Match counts or scores may justify a retrieval-like operation but do
not prove query text or document bodies. Follow dataflow through the tool:
require a value actually consumed by its search/lookup path before adding
`gen_ai.retrieval.query.text`, and returned document objects before adding
`gen_ai.retrieval.documents`. An unused prompt parameter, including one read
only for a simulated error, is not query evidence. When a tool performs such a
retrieval-like operation, a generic tool span is not complete retrieval
coverage. Before finalizing the audit, compare
each confirmed retrieval call site against its tool span and check the JSON for
two distinct items: a retrieval-specific readiness row and a selectable
retrieval finding with its own ID. A combined "tool and retrieval" row or
finding does not satisfy this check. Preserve the `execute_tool` operation,
then require the nested retrieval span with
`gen_ai.operation.name=retrieval` and a stable low-cardinality data-source
identifier. Add an explicit retrieval verification scenario that proves its
parentage under the tool span, proves any selected source-backed content fields
only after redaction and truncation, and never records raw documents, query
text, embeddings, or other sensitive/high-cardinality values.
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
Classify each orchestration boundary from source before choosing its operation.
Do not require both `invoke_workflow` and `invoke_agent` for one standalone
agent invocation merely because it calls models or tools. A separate workflow
requires evidence of an application-defined coordinated process at its own
boundary; HTTP/SSE wrappers and internal runner details do not establish one.
Bind each proposed orchestration node to that distinct source operation.
For Python with Splunk AO, make that inventory explicit. Search for
`from splunk_ao import log`, `@log`, `span_type="tool"`,
`span_type="retriever"`, `SplunkAOLogger`, `SplunkAOCallback`, supported model
or framework wrappers, `add_splunk_ao_span_processor`,
`configure_distributed_tracing`, and `instrument_distributed_tracing`. Classify
each path using the shared Splunk AO compatibility guidance as span creation,
export-only, transport-only, combined setup, or resource management. Record
the actual provider/export lifecycle and content-capture mode. Never infer workflow, model, tool, or
retrieval coverage from an export-only processor, and never infer generic HTTP,
metric, or log coverage merely from `@log`. When decorators, handlers, or
wrappers overlap app-owned OTel spans, mark coverage partial until one canonical
producer, safe content behavior, lifecycle, parentage, and duplicate absence are
proven.
For each span-producing Splunk AO callback, inspect its registration and the
owning workflow for a second callback, `@log` decorator, framework auto hook,
or app-owned OTel span on the same logical operation. Record source-backed
negative evidence when each overlap is absent, including the searched call
sites; do not infer absence from one file or from a clean example trace.
Where overlap exists, name the canonical producer and the duplicate-prevention
change. A local scenario must verify one correctly parented span per logical
workflow, model, and tool operation and no duplicate counts.
Audit teardown for every detected Splunk AO span source as an independent
outcome. Record a distinct current-state lifecycle assessment even when
teardown is present: cite the source of logger or provider creation and its
matching teardown, classify the path as source-covered when proven, and keep
this assessment separate from trace-capture inventory and any future
verification scenario. A separate Audit Evidence row or covered GenAI Readiness
surface can carry that result; source coverage alone is not runtime flush
proof. When an SDK-owned logger or sink lacks source proof of
`logger.terminate()` or another supported process teardown, create a separate
selectable lifecycle finding; do not hide it inside privacy, span-coverage, or
export findings and do not omit it merely because the process is short-lived.
For a caller-owned provider, require source proof of `provider.shutdown()` in
the same way. Keep each lifecycle row unresolved until the matching teardown is
proved by source and a focused local scenario.
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
Keep duplicate-span remediation in `remaining_signals` until the audit names
the existing canonical producer and proves no duplicate operation. Preserve
existing framework/vendor or app-owned coverage; a newly proposed app span is
not permission to disable the original bridge. An existing ownership conflict
or unsupported safe enrichment requires a precise manual decision.
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
`dataclasses.replace`, `attrs.evolve`, pydantic `model_copy(update=...)` or
`copy(update=...)` as supported by the installed carrier API; Java records,
builders, or copy constructors; TypeScript
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
an application/vendor-owned derived total, `assistant.llm.calls`, or
`assistant.tool.calls`
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

**GenAI metric applicability inventory** -- assess every metric in the reviewed
current official tables relevant to the detected operations, including metrics
not chosen for implementation. Put one row per metric in canonical Audit
Evidence (`evidence[]`): `check` names the instrument; `finding` records its
official level, type/unit, actual source boundary and value availability,
applicability, disposition and reason; `source` cites the table/revision/date
and application source. Distinguish `applicable`, `N/A` and `source unknown`
from `required`, `recommended`, `optional` and `deferred` decisions. Assess
token distributions separately from usage totals, and non-inference duration
scopes separately from inference exclusions. An applicable optional metric may
remain recommended or deferred with a reason and its remaining capability
explicit; do not force every optional metric to emit or label it covered by an
instrument with different semantics. Required missing metrics must remain in
their owning executable findings' `required_fix`, `expected_telemetry`,
acceptance and verification scenarios; an official optional level cannot
downgrade a required skill/vendor or selected contract. A supplemental matrix
does not replace this canonical inventory, and a short list of chosen metrics
does not assess the rest. Preserve existing metric producers and consumer
contracts when proposing any transition.

Before handoff, apply the per-tool vendor content contract in
`../references/genai-readiness.md` to every actual tool boundary. For the GenAI
path, list `gen_ai.tool.call.arguments` plus `gen_ai.input.messages` for its
arguments, and `gen_ai.tool.call.result` plus `gen_ai.output.messages` for any
produced result, on that tool's canonical `expected_telemetry`. Bind missing
mappings in `required_fix`, acceptance and its verification scenario; preserve
an explicitly supported OpenInference alternative when that producer uses it.
Parent/model messages and an arguments/results-only tool span do not cover
these fields. Correct a canonical omission before rendering or handoff rather
than leaving the requirement only in supplemental prose.

Make each selected GenAI contract concrete and consistent across readiness
`required_signals`, finding `required_fix`, `expected_telemetry`, acceptance and
verification scenarios. Name the actual existing producer or the proposed SDK
creation API and matching official example path/revision/version, not only
'logger/schema helpers'. Enumerate applicable input/output message fields,
instructions/tool definitions, arguments/results, known parameters/response/
usage/stream fields and opaque correlation. Include the vendor-required agent
provider and tool input/output message mappings separately from their official
OTel levels. Require current typed-parts schema/value/redaction proof and actual
success/error/cancel parentage with no duplicate nodes; a generic 'GenAI
semconv' requirement cannot stand in for missing field acceptance.

For each producer path, place the concrete capture policy in the canonical
finding and acceptance scenario: preserve a known stricter policy, otherwise
propose redacted capture with 16 messages, 64 parts per message and 8192 UTF-8
bytes per content attribute. Name the actual or proposed file/function hook
that sanitizes before SDK capture and every export sink. Unknown existing
settings stay unproven; a proposed policy must still specify those limits,
valid typed-parts truncation and native-record/OTLP sentinel-absence tests.
Do not let a supplemental statement of 'bounded/redacted' replace this
selected finding contract.

Compute each GenAI surface independently. Generic HTTP/database/runtime or
infrastructure metrics do not improve a GenAI surface status unless they
satisfy that row's required workflow, model, tool, token, memory, evaluation,
or AI-path signals. Use `missing` when none of the required GenAI signals
exists, even if unrelated OTel metrics are source-active.

**Splunk AO Runtime Coverage Contract** -- when AO is detected, requested, or
selected as the default producer for a fresh agent,
assess every in-scope GenAI runtime independently before writing findings.
Enumerate interactive/API, worker, and evaluation/test entry points from the
source scan. For each, record runtime-specific canonical `genai_readiness`
surfaces and an Audit Evidence row naming the entry point and reachable AO setup (or
the searched registration/configuration call sites when no setup is reachable).
Assess project binding, dedicated Agent Stream binding, configured runtime routing,
span producer, content behavior, and matching teardown for that runtime.

A logger, callback, project, Agent Stream, or `terminate()` path reachable only
from an evaluation, test, experiment, or demo runner does not cover a separate
interactive runtime. Likewise, a repository dependency, dormant helper,
generic OTLP endpoint, or collector receipt is not runtime routing evidence.
Preserve source-covered evaluation integration without inventing duplicate
resource or lifecycle work, but never let it close or replace the live-runtime
assessment. Search the actual live callback registration and startup/shutdown
paths, not merely the files containing AO imports.

For an in-scope live agent runtime without source-configured product bindings,
record its missing project binding, dedicated runtime Agent Stream binding,
and runtime route as separate readiness surfaces with distinct `surface` names.
Promote source-backed application/deployment configuration gaps to distinct
selectable `finding_group: splunk-agent-observability` findings, with the
project -> Agent Stream ->
routing prerequisite chain described below. Existing evaluation
resources may be reused only when source proves their intended live binding;
do not claim they are absent globally or force duplicate resources. When
adoption has no explicitly selected product target, use `fix all` and describe
it as opt-in live AO configuration, not a broken existing route.
When the user explicitly requests Agent Observability coverage, deployment,
or routing, use `instrument_mode: default` for safe, source-backed AO project,
Agent Stream, and live-routing gaps in that requested scope. Do not leave
those requested gaps in `fix all` merely because no cloud credentials are
present during a read-only audit. Keep incidental AO adoption, including a fresh
default SDK choice without an explicit product-target request, in `fix all`.
Still author its source-backed project, Agent Stream and runtime-routing
findings; a missing SDK import does not exclude that assessment.
Missing secret
values alone are not code defects or external blockers. Do not impose AO
adoption on repositories with neither existing/intended AO instrumentation nor
a user AO request. A fresh default Splunk AO producer is intended instrumentation,
not evidence that any cloud resource already exists or is globally absent.
Keep missing ordinary workflow/model/tool OTel signals untagged and separate;
content capture and lifecycle findings require their own source-backed gaps.

An AO routing finding's transitive dependency closure must support its own
acceptance criteria. If those criteria require canonical workflow, agent,
model, tool, or nested retrieval spans, include every unresolved producer and
semantic-continuity finding needed for those operations, not only exporter and
workflow setup. Cross-check each required live GenAI readiness surface and
its verification scenario against the routing finding's dependency closure:
when a tool such as `search_docs` performs a distinct retrieval operation,
its retrieval finding must be included separately from the tool finding.
Alternatively, explicitly narrow routing proof to the already covered
operations; do not silently promise unselected instrumentation work.

For a new live AO sink, include any unresolved ordinary provider-lifecycle
finding needed by that route. Author a local proof scenario for the exact
live entry point and attach it to the AO routing finding or its selected
provider-lifecycle prerequisite. Use fake or in-memory application and AO
sinks without cloud credentials: reuse the existing provider and compatible
exporter with routed trace headers (or the already selected SDK sink), emit one
canonical workflow/model/tool span per logical
operation, inspect every active sink, and prove at most one export to the same
AO destination. Exercise `force_flush` and `shutdown` on owned providers or
supported AO logger termination; assert completed pending spans drain and
owned resources close. Keep fresh cloud receipt as a separate scenario. An
evaluation logger's teardown does not prove a new live sink's lifecycle.
Keep ordinary producer/lifecycle findings untagged rather than duplicating
them as AO findings.

Before `finalize-audit`, apply this AO acceptance gate to each live-routing
finding, not only to a generic provider finding:

1. Name the selected destination. Preserve any configured supported AO API
   and direct-cloud endpoint. When AO destination settings are absent, prefer
   an available Splunk Observability Studio cloud-compatible gateway as the
   default local route. Its availability is a delivery prerequisite for that
   route; source instrumentation, imports, and local tests do not depend on
   the gateway. Cite the actual endpoint and
   availability evidence only when discovered. If no gateway or live target
   was inspected, say `unverified` and do not invent a host or port.
   For an existing non-AO path, inspect its actual resource API origin,
   selectors, resolved trace-header configuration and supported existing
   exporter. Do not require SDK variables or a new AO SDK dependency.
   For an SDK-owned Python Studio gateway path, inspect populated `SPLUNK_AO_API_URL`,
   `SPLUNK_AO_CONSOLE_URL`, and the public `SPLUNK_AO_API_KEY=local-gateway`
   marker in the actual loaded profile and any generated env, not only key
   allowlists or examples. Missing values require a selected configuration
   fix and a profile-to-process acceptance scenario; audit does not write the
   env file. Missing application cloud credentials do not establish that this
   gateway path is unavailable.
2. State the selected resource client's project/Agent Stream API endpoint,
   authentication and existing exporter's per-request trace-route compatibility
   (or the installed AO SDK's contracts for an SDK-owned path) as separate
   `supported`, `unsupported` with the exact missing contract, or `unverified`
   with the exact unavailable package/runtime evidence decisions in canonical
   evidence and AO runtime rows; do not defer them to the acceptance scenario.
   Generic "cloud-compatible" wording is not a compatibility assessment.
3. Attach a dedicated credential-free scenario to the AO routing finding or
   its selected lifecycle prerequisite. It must invoke the live entry point
   with fake or in-memory application and AO sinks, call the actual
   `force_flush`/`shutdown` or supported logger termination path, inspect
   both outputs, prove pending completed spans drained and resources closed,
   assert one canonical workflow/model/tool operation tree, and rule out
   duplicate export to the same AO destination. A separate generic provider
   shutdown scenario or a vague "no duplicates" sentence is insufficient.
   Keep fresh cloud receipt as a distinct optional proof.

Before `finalize-audit`, reconcile every enumerated runtime with its readiness
row and source evidence. Every missing or partial app-owned AO configuration
row must map to an unresolved AO-group finding with the same `area`; a covered
row must cite reachable setup for that exact runtime. If any runtime was
omitted, repair the canonical JSON before rendering. Never patch HTML or add
empty AO cards just to make the subsection appear.

**Deterministic gap section contract** -- the canonical audit has exactly one
actionable gap source: `findings`. Record GenAI detail in canonical
`genai_readiness` rows, promote service-owned OTel telemetry closure rows into
`findings`, and keep the HTML decision view focused on those findings. When
Splunk Agent Observability is in scope, follow
`../references/splunk-agent-observability.md` and put source-backed actionable
product or routing gaps in the same `findings` array with
`finding_group: splunk-agent-observability`. Never add a top-level
`splunk_agent_observability` object or a peer report section.
Treat a source-proven Splunk AO SDK content-capture boundary as AO-specific
work too: if `SplunkAOCallback` captures raw caller content contrary to the
application's documented metadata-only behavior, create a distinct selectable
finding for the app-owned guard before callback construction and set
`finding_group: splunk-agent-observability`. Keep general content policy and
governance questions as context; ordinary missing GenAI content attributes
belong in their owning selectable OTel findings without an AO finding group.
For a source-backed project/Agent Stream/routing gap that can be closed by
application or deployment configuration, author selectable project configuration
and selectable Agent Stream configuration findings with executable modes and
their dependency edges. Set `ao_target_scope: resource-routing` on these
resource and runtime-routing configuration findings; do not mark AO callback
content boundaries or unrelated configuration as resource-target eligible.
Preserve the shared reference's unmarked legacy resource/routing findings.
A target ID or credential may be supplied at the
selected instrumentation/deployment step; missing audit-time credentials alone do not make an AO finding external.
When all three gaps exist, create separate selectable AO findings for project, Agent Stream, and runtime routing
rather than collapsing them into one card. The Agent Stream depends on project;
runtime routing depends on project, Agent Stream, and OTel export. Keep a
project finding scoped to resolving or creating the product resource, a stream
finding scoped to its own resource, and a routing finding scoped to durable
application/deployment configuration. A user can then select a downstream
finding and see its distinct prerequisites auto-included. Do not split a
single already-working resource just to increase the finding count.
Apply the shared AO reference's Project And Agent Stream Inputs and Idempotent
Resource Provisioning contracts to these findings. State explicitly that
instrumentation resolves existing resources and creates missing selected,
named resources, rather than weakening the fix to "configure existing names."
Offer optional resource-name inputs and reuse-only behavior in the audit
selection view, with existing configured IDs/names or clearly labeled stable
service-derived suggestions. Keep these values in the bound selection's
`ao_target`, not in an unvalidated report note. Bind the shared provisioning
contract to canonical resource acceptance and mapped scenarios: reuse both
existing resources without creates; create conclusively missing selected names
in project-before-stream order; handle mixed state and repeated-run reuse;
recover duplicate conflicts and uncertain create outcomes with bounded exact
relookup; treat supplied IDs as lookup-only with no create on an unresolved ID;
validate ownership and stream/project association; and never treat auth,
transport, or 5xx failures as absence. Failure must not suppress ordinary OTel.
The routing scenario must prove the named launch profile is loaded before
exporter initialization (and SDK import on an SDK-owned path), not just that
an env file contains the right keys. Existing non-AO apps use supported
resource APIs and trace-specific headers on the existing exporter without a
new SDK dependency.
A read-only audit
does not create resources or claim that an unqueried resource is absent.
For the resource plan, inventory the actual application launch profile and
its supported loader. Record native selector aliases and whether that exact
runtime consumes the standard SDK selectors `SPLUNK_AO_PROJECT` /
`SPLUNK_AO_PROJECT_ID` and `SPLUNK_AO_AGENT_STREAM` /
`SPLUNK_AO_AGENT_STREAM_ID`; evaluation-only selectors do not establish a live
application binding. Explain blank-input fallback in the canonical report:
preserve each existing configured selector independently, and disclose a
stable service-derived name for each missing resource. Name the profile and
runner that instrumentation should update/load, with user-supplied selection
values taking precedence. Record missing or unsupported profile wiring as a
gap. Audit remains read-only for env files and cloud resources.
Distinguish ordinary local OTLP receipt from AO resource and delivery evidence.
When AO destination settings are absent, an available cloud-compatible Studio
gateway is the default local destination. Its absence must not block source
instrumentation or credential-free tests. An existing direct-cloud route
remains valid. Assess normal SDK resource calls, supported per-request
project/stream binding, gateway compatibility, and cloud
receipt separately. Preserve explicit operator/direct-cloud destinations.
Do not propose a Studio-specific application adapter or global route
registration. If the SDK or gateway cannot implement the standard API/ingest
contract, record that exact compatibility gap rather than claiming that a
connection alone provisions resources or proves delivery. Local OTel receiver
configuration remains ordinary OTel work; AO project/stream/routing remains
distinct configuration work under the same findings ledger.
Do not claim a product resource or routed trace is Working until it is
resolved and verified. In contrast, reserve `external follow-up` for a source-proven outside owner
who must perform a prerequisite action outside the selected application's
configuration or supported product API path. Do not make an executable Agent
Stream or routing finding depend on a non-executable external item merely
because the read-only audit cannot call Lab0.

Populate canonical `findings` so the shared renderer can project the single
priority-ordered finding list; do not hand-author its layout. Use only `required`,
`recommended`, or `deferred` priorities and only `default`, `fix all`, `manual
decision`, or `external follow-up` instrument modes. Put baseline correctness,
trace continuity, error attribution, exporter/resource identity, cardinality
safety, and duplicate signal ownership in `required`. Put safe deeper
diagnostics and business metrics in `recommended` unless the request already
makes them mandatory. For a detected supported application logging stack, put
a missing local Splunk Observability Studio provider/exporter/bridge in `required` with
`instrument_mode: default`; this makes it part of implicit broad/default
Splunk Observability Studio instrumentation. Do not create that finding when logs are explicitly
disabled or a non-OTLP operator-owned exporter is already configured. When an
absent/`otlp` exporter is paired with an explicit non-local logs endpoint,
create an `external follow-up` whose exact `required_fix` and
`external_requirement` name the operator-owned configuration change, then
create the local-log `required`/`default` finding with that external ID in
`dependencies`. This valid dependency closure keeps the executable finding
locked; never put this configuration conflict in `scan_blockers`.
Keep product
behavior decisions,
readiness contract choices, content-policy ownership, safety policy, cost/billing
ownership, and external telemetry prerequisites out of canonical `findings` by
default; record them in readiness/context rows instead. Use `deferred` only for
a concrete prerequisite or decision that gates an in-scope service-owned OTel
finding. Every row must explain user/operator impact, state a specific OTel fix,
and cite the verification scenario IDs that can prove closure. Group related
routes and call sites by remediation theme instead of producing a row per edge.
Do not create manual or external findings just to record product/runtime
choices, billing, cost, safety policy, content-governance, or external business
context.
When a default GenAI gap involves duplicate or overlapping instrumentation,
name the existing canonical owner per logical operation and its supported
enrichment hook or proven uncovered boundary in `Required fix`. Do not propose
a replacement producer plus blanket suppression. If source evidence cannot
support ownership or safe enrichment, use `manual decision`; do not hand `$otel-instrument` an unresolved
"select one canonical source" instruction in a `default` row.

For mutually exclusive choices, first decide whether the branches are in scope.
If the decision only changes product/runtime behavior, such as liveness versus
dependency-aware health, keep it in readiness context unless that domain was
explicitly requested. If multiple options each produce real service-owned OTel
instrumentation work, create one option-locked executable finding per real
branch, put each branch ID in only that option's `unlocks`, and keep those
unlock sets pairwise disjoint. Do not use one shared executable finding for
multiple exclusive options, and do not make two branch implementations appear
as simultaneous independent audit gaps before the user answers.

**Evidence and flow contract** -- write source evidence as a compact
`## Audit Evidence` table and create one `## Signal Flow` / `### Component Flow
Map` using the exact marker semantics defined in this skill. The map is
a reader aid, not runtime proof. Show only major process, dependency, and
telemetry edges; keep independent roots separate and point human-readable gap
markers to the prioritized gap table. Use only `[SOURCE-COVERED]` and
`[GAP: <area>]` markers.

**Anti-patterns** -- flag any of these:

- Multiple SDK initializations in the same process
- Hardcoded OTLP endpoints instead of resolved standard OTel configuration.
  The conventional local `4317`/`4318` values are fallbacks only after the
  configured or advertised receiver endpoint has not been found; never replace
  a discovered non-default port with them.
- Tracer/Meter created in hot paths instead of at startup
- High-cardinality attributes on metrics (user IDs, request IDs)
- Missing `recordException` in error handling paths
- Custom span names with variable segments (IDs, paths)
- Use of community or third-party OTel wrappers when an official OpenTelemetry package exists (e.g. `go.opentelemetry.io/contrib`, `@opentelemetry/`*, `opentelemetry-*`)
- A generic direct-cloud OTLP endpoint implicitly receiving application logs,
  or a Splunk Observability Studio-added Splunk cloud log endpoint/header/token/exporter/
  forwarding flag
- Two log providers, appenders, handlers, transports, hooks, or bridges that
  export the same application record twice
- Replacing an existing stdout/file sink when adding local OTLP logs

For partially instrumented Go services, explicitly check and report:

- hardcoded OTLP endpoints such as `collector.example.com`
- `otel.Tracer(...)` or `otel.Meter(...)` calls inside request handlers or loops
- high-cardinality span names such as `GetTask-{id}`
- missing `otel.SetTextMapPropagator(...)`
- missing `MeterProvider`, missing `service.name`, and missing provider shutdown/flush

