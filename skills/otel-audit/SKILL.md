---
name: otel-audit
description: >-
  Scan a codebase for existing OpenTelemetry instrumentation and report
  on observability coverage gaps. Read-only for application code -- writes
  audit artifacts under .observe/ including .observe/otel-audit.json
  and .observe/otel.html, but does not modify service code.
  Use when the user types $otel-audit, asks about observability gaps,
  wants to assess instrumentation coverage, says "what signals am I
  missing", "scan this service for observability", asks about
  "observability readiness", asks whether instrumentation can make incidents
  faster to detect or localize, or asks whether GenAI/LLM workflows follow
  OpenTelemetry semantic conventions. Do NOT use for implementing code changes
  -- use $otel-instrument instead.
---

# Audit -- Observability Coverage Scan

## Overview

Scan a service repository to detect its language, framework, dependencies,
and existing OpenTelemetry instrumentation. Report what is instrumented,
what is missing, and any anti-patterns. This skill is read-only for application
code: it writes `.observe/otel-audit.json` and `.observe/otel.html` but does
not modify service code, dependencies, configuration, or tests.

Resolve every reference and script path from the directory containing the
loaded `otel-audit/SKILL.md`. Here, `../references/<file>` means the shared
sibling under the parent skills directory, while `references/<file>` and
`scripts/<file>` are local to `otel-audit`. Never probe the service root or
repository root for these paths.

Before writing the report artifacts, read
`../references/report-flow-contract.md` and follow the Audit Contract plus the
Reader-First Report Order.

## Process

### Step 1 -- Repository Discovery

Scan the repository to determine language, framework, and existing instrumentation.

1. Detect primary language and framework:
   - Go: `go.mod`
   - Python: `requirements.txt`, `pyproject.toml`, `setup.py`
   - Node.js: `package.json`
   - Java: `pom.xml`, `build.gradle`
   - Rust: `Cargo.toml`
   - .NET: `*.csproj`, `*.sln`
2. Identify entry points (`main`, `cmd/`, `app.py`, `index.ts`, etc.)
3. Enumerate all HTTP routes with method and path pattern (e.g. `GET /tasks`, `POST /tasks`, `GET /tasks/{id}`). List them explicitly in the report.
4. Use the Auto-Instrumentation Library Map below to identify which packages
  should be present for each detected dependency.
5. Detect incident-readiness ownership: user-visible workflows, dependency
  calls, background processing, queues/streams, data freshness, auth/edge
  paths, capacity limits, and release/config context. When any are present or
  when the user asks for faster incident detection/localization, load
  `../references/incident-readiness.md`. When incidents, postmortems, tickets,
  alerts, or failure examples are supplied, use its Incident-Evidence Mode and
  map each failure mechanism to its owning code or platform surface before
  scoring coverage.
6. Detect GenAI/LLM ownership: provider clients/model gateways, agents or
  workflows, tool/function dispatch, MCP when present, retrieval/RAG,
  model/deployment config, model/config compatibility,
  expected-vs-running model/config state, fallback/readiness checks, token
  accounting, call counts, prompt/response assembly, AI-derived data jobs,
  AI-path synthetic/canary checks, or usage logging. When any are present, load
  `../references/genai-readiness.md`.
  Follow its GenAI Semconv Source Contract before scoring GenAI coverage:
  reconcile detected AI surfaces with official semconv docs when available,
  record live-or-snapshot provenance, and build a semconv closure matrix.
  When GenAI incidents, postmortems, alerts, tickets, or failure examples are
  part of the request, use GenAI incident-evidence mode and map each failure
  as `incident class -> failure mechanism -> repo/service owner -> code surface ->`
  required signal before scoring whether instrumentation is MTTD-improving or
  localization-only. Map each failure
  mechanism to provider/model gateway, workflow, tool/function execution or
  AI-owned session/stream including MCP when present, retrieval/RAG, streaming,
  token/context, prompt/response parser, safety/policy, AI-derived data,
  model/config rollout, or AI-owned cache/session evidence.
7. Record exact evidence paths that should appear in the report:
  - Dependency manifest: `go.mod`, `package.json`, `pyproject.toml`, `pom.xml`, etc.
  - Process entry point: `main.go`, `cmd/.../main.go`, `app.py`, `app.js`, `TasksApplication.java`, etc.
  - Route source: router/controller files such as `TaskController.java`, `app.py`, `app.js`, or `kvstore/http.go`.
  - Traffic and readiness clients when they exercise a GenAI path: demo, load, eval, or replay scripts, plus AI-path synthetic or canary scripts such as `load_demo.py`,
    `smoke.py`, `scripts/check-*`, or `tests/e2e/*`.
  - Runtime/startup files when present: `Dockerfile`, `docker-compose.yml`, `Makefile`, `package.json` scripts, launch configs, worker files.
  Use complete repository-relative paths with an optional `:line`,
  `:start-end`, or comma-separated line selector. The HTML renderer links only
  exact existing in-repository files; do not shorten citations to basenames,
  use globs, or guess paths when the owning file can be named precisely.
8. Inventory project runtime and verification evidence without installing or
   changing anything:
  - wrappers and task runners such as `mvnw`, `gradlew`, Make, package scripts,
    tox/nox, Cargo, or solution test projects
  - toolchain/version files and manifest runtime requirements
  - lockfiles, CI test commands, devcontainer config, and existing test layout
  - locally safe compile/type/import/test commands implied by project config
  Record configured requirements, not the shell's accidental default runtime.
9. Make one explicit GenAI ownership decision from the completed source scan:
  - `Yes` when any provider/model, agent/workflow, tool/MCP, retrieval/RAG,
    memory/context, evaluation, prompt/response, model/config, token usage, or
    other AI-path surface is owned by the repository.
  - `No` only when the dependency and source scan finds none of those surfaces.
  Record the decision both as `**GenAI ownership detected:** Yes|No` near the
  report status and as an exact `GenAI ownership` row in `## Audit Evidence`.
  The two values must match.

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

- OTel log bridge or SDK log packages (`opentelemetry-instrumentation-logging`
for Python, `@opentelemetry/instrumentation-winston` /
`@opentelemetry/instrumentation-pino` for Node.js).
- Trace-context injection into log records (`trace_id`, `span_id` fields).
- `span.AddEvent()` / `span.add_event()` calls used as structured log events.
- Logging formatters, filters, adapters, MDC/context variables, access-log
  formatters, and exception helpers that can add request, user, tenant,
  session, trace, raw URL, exception text, or traceback data. Check the final
  formatting path, not only application logger call arguments.
- Classify logs as `otlp`, `correlation-only`, or `not configured`. Trace/MDC
  fields in stdout are not an OTLP log pipeline.

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
- For every exact custom span name or operation entrypoint, create an explicit
  scenario row. Shared helper implementation is not proof that each operation
  emits its expected name and topology.
- Before writing a scenario, confirm every cited source path and symbol exists
  with `rg -n` or a language-aware index. Never hand off a guessed or stale
  symbol name.
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

**Deterministic gap section contract** -- the canonical audit has exactly one
actionable gap source: `findings`. Record GenAI detail in canonical
`genai_readiness` rows, promote only service-owned OTel telemetry closure rows
into `findings`, and keep the HTML decision view focused on those findings.

Populate canonical `findings` so the shared renderer can project the single
priority-ordered finding list; do not hand-author its layout. Use only `required`,
`recommended`, or `deferred` priorities and only `default`, `fix all`, `manual
decision`, or `external follow-up` instrument modes. Put baseline correctness,
trace continuity, error attribution, exporter/resource identity, cardinality
safety, and duplicate signal ownership in `required`. Put safe deeper
diagnostics, business metrics, and opt-in log export in `recommended` unless
the request already makes them mandatory. Keep product behavior decisions,
readiness contract choices, content governance, safety policy, cost/billing
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
name the intended canonical owner per logical operation and the pre-bootstrap
suppression surface in `Required fix`. If source evidence cannot support that
choice, use `manual decision`; do not hand `$otel-instrument` an unresolved
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
- Hardcoded OTLP endpoints instead of env vars
- Tracer/Meter created in hot paths instead of at startup
- High-cardinality attributes on metrics (user IDs, request IDs)
- Missing `recordException` in error handling paths
- Custom span names with variable segments (IDs, paths)
- Use of community or third-party OTel wrappers when an official OpenTelemetry package exists (e.g. `go.opentelemetry.io/contrib`, `@opentelemetry/`*, `opentelemetry-*`)

For partially instrumented Go services, explicitly check and report:

- hardcoded OTLP endpoints such as `collector.example.com`
- `otel.Tracer(...)` or `otel.Meter(...)` calls inside request handlers or loops
- high-cardinality span names such as `GetTask-{id}`
- missing `otel.SetTextMapPropagator(...)`
- missing `MeterProvider`, missing `service.name`, and missing provider shutdown/flush

### Step 3 -- Report

Write two audit artifacts inside the scanned service root (create the
`.observe/` directory if it does not exist):

- `.observe/otel-audit.json` -- canonical machine-readable audit source.
- `.observe/otel.html` -- self-contained human review report generated from the
  JSON. This is the normal human interaction surface for expanding and
  selecting finding IDs. Keep it audit-only; never render instrumentation
  or verification overlays into this file.
Use `.observe/otel-audit.json` as the source of truth for stable finding IDs,
selection, and downstream tool handoff. Do not require humans to read or edit
the JSON directly; generate `.observe/otel.html` from it.
The reviewer uses `.observe/otel.html` to understand findings, answer any
manual decision controls, choose executable instrumentation scope, and save or
copy the exact `$otel-instrument` command. It is not a proof report. After
instrumentation, change-impact and proof status move to
`.observe/otel-instrumentation.html`; scope changes should return to
`.observe/otel.html`, not edit generated HTML or JSON by hand.

In HTML, put selectable findings immediately after the concise decision
summary. Do not render the component map, connection lanes, component-coverage
groups, raw flow map, full current-state inventory, or a duplicate all-findings
decision table. Keep `signal_flow` in canonical JSON for machine use. Reserve
one collapsed technical appendix at the
report level after the findings for cross-finding source-visible
instrumentation evidence, the shared verification plan, audit evidence, and
recommendations; keep finding-specific proof and implementation detail on its
card.

After the card header and selection or decision control, keep the expanded
narrative decision-sized. Its four first-level fields are
`Gap`, `Why it matters`, a mode-aware required action, and `Next step`. Label
the action `Instrumentation change` for executable work, `Decision needed` for
a manual prerequisite, and `External requirement` for an external
prerequisite. For a currently selectable executable finding, `Next step` is to
select the finding, copy the generated command, and run `$otel-instrument`; do not
present authored verification or dashboard work as
the reviewer's immediate action.
Keep that copy synchronized with selection state: selected work proceeds to
the generated command, an auto-added dependency explains why it is included, and
blocked work names the blocking `OTEL-###` IDs and directs the reviewer to
resolve them first. Show a compact telemetry shape on the card from exact
`expected_telemetry[*].type` counts, including configuration and resource
items. When a finding has dependencies, show their stable IDs as a selection effect.
Do not infer a material-safety badge from free-text constraints, severity, or
priority; the schema does not author that judgment.

Put exact expected telemetry, evidence, acceptance criteria, and authored
constraints behind one collapsed `Technical details`
disclosure. Label constraints `Implementation guardrails`, and summarize the
disclosure with acceptance-check, guardrail, and source-reference counts. Do
not render raw verification-scenario IDs, repeated full scope classification,
canonical `follow_up_actions`, resolution metadata, or
a second dependency list in finding HTML. Those fields remain in canonical
JSON for `$otel-instrument` and `$otel-verify`. Put post-instrumentation product actions in
`.observe/otel-instrumentation.html`, not in the audit finding card. Keep a
manual decision's owner and question in its decision control and `Next step`;
keep an external prerequisite's owner and required telemetry in its primary
action and `Next step`.

Keep the HTML complete and usable on its own. It may link to the canonical JSON
as an optional alternate format, but must not require the reviewer to open
Markdown to understand or select a finding.

Write the HTML summary as a decision brief, not a compressed defect list. Use
3-7 plain-language bullets and state the total finding count, what source or
configuration currently shows, the highest-priority app-owned work, and any
exact owner decision or external prerequisite that blocks executable work.
Keep this detail in the HTML report; the chat handoff is intentionally limited
to the single report link defined below. Do not present canonical
`meta.status` as a human outcome in HTML: it classifies the machine report and
does not claim runtime proof. Do not repeat a generic runtime-unproven warning
in the decision summary. Put finding-specific missing proof in that finding's
nested `Technical details`; reserve the report-level technical appendix for
cross-finding current-state evidence, the shared verification plan, and audit
notes. Give every finding one concise
`product_outcome` sentence answering what the owner should see or gain after
implementation and verification. Lead with monitoring and product outcomes such as a reliable trace
waterfall, route or dependency filtering, a chart, detector, or readiness view. Move
class names, provider topology, exporter details, and other implementation
jargon into finding evidence or technical highlights unless they are the
decision itself.

In the HTML decision view, render exactly one findings list ordered by
machine-readable priority: `required`, then `recommended`, then `deferred`,
preserving canonical order within the same priority. Priority defines ordering
only. Put one concise current-baseline sentence and one
highest-priority-first explanation before the list, then show a compact
`Findings · N` heading immediately above the cards. Keep quick-win, effort,
severity, priority, and execution-state metadata machine-readable in canonical
JSON.

Each card has one title, one expected monitoring outcome, one neutral selection
control when executable, and the stable `OTEL-###` ID as a secondary
cross-report reference. IDs must remain deterministic across selection,
instrumentation, verification, and configuration handoffs. Priority is expressed
only by list order; lifecycle is reflected by the checkbox, next-step copy, and
saved selection state, and effort remains machine-readable only in canonical
JSON.

Use the instrument modes consistently in the human view:

- `default` is safe app-owned work that can enter the instrumentation handoff
  after the reviewer selects it.
- `fix all` is safe broader work that remains opt-in; render the same neutral
  `Select` checkbox as `default`, without an `optional` tag.
- `manual decision` renders as `decision needed`: a named telemetry-specific
  prerequisite offers two or three explicit answers and blocks separate
  executable findings until one answer is selected. The manual finding remains
  visible but its ID cannot enter instrumentation scope.
- `external follow-up` renders as `external follow-up`: a known owner outside
  the service must supply an exact prerequisite needed by a separate executable
  finding. It remains visible as `External follow-up` but cannot enter
  instrumentation scope.

Render the neutral `Select` checkbox only for executable `default` and
`fix all` findings. For `manual decision`, render its two or three
`decision_options` as an accessible one-of answer control, never as a `Select`
checkbox. Keep `external follow-up` non-interactive and never emit a
checkbox for it; never emit a checkbox for either non-executable finding mode.
Persist the chosen option under `decision_answers` in the saved selection. The
answer unlocks only executable findings listed in that
option's `unlocks`; every other branch remains blocked. Answering does not
select or auto-add unlocked work. If the answer changes, remove any now-invalid
requested or dependency-closed work before export. Keep the full mode
classification, verification-scenario references, ownership, and requirements
in canonical JSON. In HTML, keep
manual decision ownership and the question in the answer control and `Next
step`; keep external ownership and its requirement in the primary action and
`Next step`. Render explicit lifecycle state as `selected` and an auto-added
dependency as `included`, never `approved` or `decision requested`. A checked
checkbox records explicit reviewer intent; dependency inclusion is derived
separately and must not make an auto-added executable dependency look explicitly
chosen.

Use this shape for `.observe/otel-audit.json`:

```json
{
  "schema_version": 2,
  "kind": "otel-audit",
  "meta": {
    "audit_id": "example-service-20260717",
    "service_name": "example-service",
    "commit": "abc1234",
    "language": "go",
    "framework": "chi",
    "date": "2026-07-17",
    "status": "Partial",
    "genai_ownership_detected": false
  },
  "summary": ["highest impact finding first"],
  "flow": "audit -> select -> instrument -> verify -> configure/dashboard -> publish",
  "evidence": [
    {"check": "Manifest", "finding": "Go module", "source": "go.mod"},
    {"check": "Entry point", "finding": "HTTP service", "source": "main.go"},
    {"check": "Route source", "finding": "GET /health", "source": "main.go:42"},
    {"check": "Runtime/startup", "finding": "Go test runner", "source": "go.mod"},
    {"check": "GenAI ownership", "finding": "No", "source": "repository source scan"}
  ],
  "routes": [{"method": "GET", "path": "/health"}],
  "signal_flow": {
    "component_flow_map": "main.go [SOURCE-COVERED] -> handler [GAP: HTTP latency]"
  },
  "current_instrumentation": {
    "spans": [{"name": "GET /health", "source": "otelhttp", "type": "auto"}],
    "metrics": [],
    "logs": [],
    "incident_readiness": []
  },
  "genai_readiness": [],
  "findings": [
    {
      "id": "OTEL-001",
      "title": "HTTP latency lacks route-level proof",
      "severity": "high",
      "priority": "required",
      "effort": "small",
      "status": "proposed",
      "area": "HTTP latency",
      "gap": "Source shows no route latency metric or span timing.",
      "impact": "Operators cannot isolate slow routes in Splunk Observability.",
      "product_outcome": "Operators should see one route-named trace plus route latency, request-rate, and error views.",
      "required_fix": "Add HTTP server instrumentation and route attributes.",
      "instrument_mode": "default",
      "verification_scenarios": ["http.health.success"],
      "dependencies": [],
      "evidence": ["main.go:42"],
      "acceptance_criteria": ["One server span has http.route=/health."],
      "constraints": ["Keep route values low cardinality."],
      "expected_telemetry": [
        {
          "type": "span",
          "name": "GET /health",
          "attributes": ["http.route"],
          "product_view": "Trace waterfall and route filtering"
        }
      ],
      "follow_up_actions": ["After instrumentation proof exists, filter the span in ObStudio before merge."]
    }
  ],
  "verification": {
    "environments": [
      {
        "id": "go.local",
        "surface": "example service",
        "config_evidence": "go.mod",
        "runner": "go test ./...",
        "scope": "module",
        "prerequisites": "none"
      }
    ],
    "scenarios": [
      {
        "id": "http.health.success",
        "trigger": "GET /health",
        "entrypoint": "main.go:42",
        "expected_signals": "GET /health span",
        "proof_level": "full runtime",
        "acceptance_criteria": "span is emitted with stable route attributes",
        "environments": ["go.local"]
      }
    ]
  },
  "anti_patterns": [],
  "recommendation": ["Run $otel-instrument with selected executable finding IDs."]
}
```

JSON requirements:

- Write new audits as schema v2. Every saved selection and downstream overlay binds
  the exact normalized audit by its digest.
- Use stable finding IDs such as `OTEL-001`, `OTEL-002`, in priority order.
- Use finding `status: proposed` for newly audited gaps. Selection, implementation,
  and verification overlays update later artifacts; the audit baseline remains
  source-derived.
- Use only `critical`, `high`, `medium`, `low`, or `info` severity values.
- Use only `required`, `recommended`, or `deferred` priorities and only
  `default`, `fix all`, `manual decision`, or `external follow-up` instrument
  modes.
- Every `manual decision` must include a non-placeholder `decision_owner` and
  an exact telemetry-specific `decision_question` that names an actual expected
  signal, attribute, or configuration scope, plus two or three explicit
  `decision_options`. Each option has a stable `id`, concise `label`, concrete
  `outcome`, and an `unlocks` list containing only executable finding IDs that
  depend on the manual finding. Option IDs are unique within the decision, and
  option unlock sets are pairwise disjoint. An option may use an empty
  `unlocks` list when that answer intentionally produces no instrumentation
  work. Do not create a `manual decision` finding for a product/runtime choice
  unless it gates a concrete service-owned OTel finding. Every
  `external follow-up` must
  include a known non-placeholder `external_owner` and an exact
  `external_requirement` naming an actual expected OTel signal, attribute,
  configuration scope, or telemetry proof that owner must supply. The exact
  external requirement must also be the finding's `required_fix`, so
  service-owned implementation cannot be hidden in an unselectable item. Do not
  create an `external follow-up` finding only to record business, billing,
  product, governance, or platform context; keep that context in readiness rows
  unless it blocks an in-scope service-owned OTel finding. Those fields are
  invalid on other modes.
- In schema v2, every `manual decision` and `external follow-up` must be in the
  transitive dependency closure of at least one `default`/`fix all` finding.
  Reject orphan non-executable findings. A non-executable finding contains only
  its prerequisite decision or externally supplied telemetry requirement; put
  app-owned implementation in a separate executable finding that lists the
  prerequisite in `dependencies`. For real OTel branches, create one
  option-locked executable finding per option and put each ID only in the
  matching option's `unlocks`; do not pre-create branch findings as visible,
  simultaneous independent gaps that inflate the audit count before the user
  answers.
- Classify effort as `small`, `medium`, `large`, or `decision` so owners can
  distinguish quick wins from longer or choice-dependent work.
- Every finding must include human impact, one concise `product_outcome`,
  required fix, evidence, acceptance criteria, expected telemetry with its
  Splunk/ObStudio `product_view`, and at least one follow-up action. The outcome
  states what the owner should see or gain after implementation and
  verification without claiming it is already proven. Include verification
  scenario IDs when runnable.
- When a finding would modify an existing emitted metric, span, resource, log,
  exporter, or dashboard/detector contract, call out telemetry consumer
  compatibility in the finding's gap, required fix, constraints, or acceptance
  criteria. Distinguish additive semantic-convention fields from breaking
  removals or renames. Require safe existing aliases to be preserved by default;
  if an unsafe high-cardinality field such as raw URL `path` must be removed,
  name the bounded replacement such as `http.route` and state that dashboards or
  detectors using the old field need migration.
- Every mapped verification scenario must reference an ID in
  `verification.scenarios`.
- Do not use `$otel-verify` or generic `run
  verification` as an audit recommendation, finding follow-up, or chat next
  step; audit owns selection planning, while `$otel-instrument` invokes
  verification internally after implementation.
- Every finding dependency must reference another finding ID and point from the
  work toward its prerequisite. Every verification scenario reference must
  exist in `verification.scenarios`.
- Put bulky command output under `.observe/evidence/` and cite it from JSON.

After writing `.observe/otel-audit.json`, run `finalize-audit`. This command
validates the canonical source, renders the interactive HTML view, and prints
one compact digest:

```bash
python3 -I "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" finalize-audit \
  .observe/otel-audit.json \
  --html .observe/otel.html
```

`render-html` infers the source repository root when the audit is under
`.observe/` and turns exact existing repository-relative citations into local
file links. When rendering an audit from another directory, pass
`--repo-root <service-root>` explicitly; never embed an absolute host path in
the canonical JSON.

Resolve both placeholders directly from the directory containing the loaded
`otel-audit/SKILL.md`; never use a service-root or repository-root script by
name. If finalization fails, repair the reported canonical input or renderer
problem and rerun `finalize-audit`; never patch generated HTML.

`finalize-audit` starts or reuses a detached report server bound only to
`127.0.0.1` on an available port and returns the HTTP Markdown link in
`links.review_report`. The server exposes only `otel.html`,
`otel-audit.json`, and its private health check; it never serves the repository.
It requires an unguessable token in the URL path, rejects symlinked report
files, disables caching and content sniffing, and stores versioned reuse state
with user-only permissions where the platform supports them. Do not open the
browser automatically. A loopback link works directly in desktop IDEs; remote
workspaces may require their normal localhost port forwarding.

The HTML is the human review and selection surface. Keep its empty fixed tray
`hidden` and `inert`. After a reviewer selects work or records a decision
answer, show only the plain selectable terminal command section. Do not render
a selection-count summary, save guidance, or a `Save selection` button. The
command must be regenerated from the current explicit `requested_ids`
and canonical `decision_answers` as
`$otel-instrument --ids OTEL-001,OTEL-002 --decision OTEL-003=option-id <absolute-service-root>`.
Embed the validated absolute service root supplied to `finalize-audit` in the
HTML payload and use it in the generated command, including when the report is
served over loopback HTTP. Keep `file://` path inference only as a compatibility
fallback; a normally finalized report must never show the literal
`<service-root>` placeholder.
Use explicit requested IDs, not auto-added dependency closure, because
`$otel-instrument` recomputes and validates dependencies. If the reviewer has
recorded only decision answers and no executable selection, show that no
instrumentation command can be generated until an executable finding is
selected. The cards, terminal command, and polite live region must
distinguish explicit selections from auto-added dependencies.

The terminal command is the only visible selection handoff. It must carry the
explicit requested IDs and decision answers needed for `$otel-instrument` to
recompute and validate dependency closure. Keep selected-audit and
`.observe/otel-selection.json` compatibility in the machine workflow, but do
not expose browser save or download controls in audit HTML.

The expanded finding's collapsed `Technical details` must retain every expected
telemetry item, acceptance criteria, authored constraint labelled
`Implementation guardrails`, and source evidence. Canonical JSON retains
verification-scenario references, full mode ownership and requirements,
follow-up actions, dependencies, and resolution metadata for downstream
skills.

The saved audit report may carry `review_selection`; `$otel-instrument` must
extract and validate it before instrumentation. For compatibility, the
instrumentation preflight may materialize the same validated selection as
`.observe/otel-selection.json`, but that is an internal handoff artifact, not a
manual user copy step. It records explicit requests, executable dependency
closure, and `decision_answers`.
`decision_answers` is separate from `requested_ids` and `approved_ids`: it is
a canonical-audit-order list of `finding_id`/`option_id` entries and never
contains executable scope; a selection carrying `decision_answers` is schema v2.
Preserve the machine schema names `requested_ids` and
`approved_ids` for compatibility, but do not present `approved_ids` as human
approval: it is the dependency-closed executable selection. A manual
decision ID and an external follow-up ID can never appear in either executable
ID list. Reject unanswered decision dependencies, answers not authored by the
audit, and requested or approved executable work not listed in the chosen
option's `unlocks`. A valid answer only unlocks matching executable work; it
never selects that work automatically. Persist an answer even when its option
unlocks no work, without inventing requested or approved IDs. Announce
automatic dependency changes and save/adoption feedback through an
`aria-live="polite"`, `aria-atomic="true"` status region. Never hand-edit
generated HTML. When the user provides
IDs in the same request, create and validate the bound selection with:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" select \
  .observe/otel-audit.json \
  --ids OTEL-001,OTEL-004 \
  -o .observe/otel-selection.json
```

The tool validates IDs, binds the selection to the audit ID and SHA-256 digest,
and auto-includes dependencies in audit order. Do not edit code until the owner
has selected executable IDs.

Keep these essential input semantics in the canonical JSON:

- `meta.genai_ownership_detected` is the explicit ownership switch. Populate
  `genai_readiness` only when it is true. Human HTML must not render full
  Incident or GenAI readiness ledgers as separate primary sections; preserve
  authored readiness rows in canonical JSON for downstream skills.
- Put source inventory in `current_instrumentation` and actionable work in
  `findings`. Keep every span, metric, and log integration as an individual
  JSON row rather than grouping exact signals into prose.
- In `signal_flow.component_flow_map`, use only `[SOURCE-COVERED]` and
  `[GAP: <area>]`. Every gap marker must use the exact `area` of a finding, and
  every finding area must appear in at least one marker. Repeat an area only
  when the same finding explicitly spans multiple components; do not create a
  duplicate finding for the repeated association.
- Every telemetry-scoped partial, missing, or owner-mapped
  `current_instrumentation.incident_readiness` row must have an unresolved
  (`proposed`, `approved`, or `in_progress`) finding with an identical `area`
  and mapped verification scenarios. A `covered` row conflicts only with an
  unresolved same-area finding. Validate incident `area` and
  `required_signals`, plus GenAI `surface`, `required_signals`, and
  `acceptance_criteria`, as OTel closure fields; evidence and operator-impact
  prose remain context. A row is telemetry-scoped only when its required
  signals name service-owned OTel telemetry or configuration, not merely a
  product contract, cost owner, safety policy, content-governance rule, or
  external business prerequisite. Do not put general operational observations
  in either canonical readiness array merely to force a finding. Do not render
  authored readiness tables as visible peer sections in audit HTML; finding
  cards carry the user-facing action context.
- Define reusable environments in `verification.environments`; every
  `verification.scenarios[*].environments` value must reference those IDs.
- Audit scenarios and signal inventory are source-derived plans, not runtime
  proof. Keep bulky evidence outside JSON and cite its path.

`finalize-audit` runs the dependency-free validator bundled with the shared
renderer. Resolve the helper from the loaded skill directory, never the audited
repository.

**Chat handoff:** After writing and finalizing the audit artifacts, the final
response must contain exactly this one line and nothing else:

```text
Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)
```

Copy `links.review_report` from successful `finalize-audit` output verbatim
after the `Review report: ` label. Do not include summary bullets, finding
counts, recommendations, a machine-report link, artifact-write narration, or
any other text in the final response. Keep the canonical JSON as an internal
downstream artifact even though it is not linked in chat.

### Step 4 -- Downstream Handoff

Do not perform telemetry execution inside the audit workflow. The report's
`Verification Plan` is a proof plan consumed downstream; it is not the
reviewer's immediate command.

- Recommend selecting executable findings, copying the generated command, and
  running `$otel-instrument` for source gaps. `$otel-instrument` owns the internal
  verification child after implementation.
- Do not present `$otel-verify` or generic `run verification` as the audit
  prompt's next step, recommendation line, or finding follow-up. If proof is
  requested without code changes, state that standalone verification is a
  separate explicit `$otel-verify` request after the audit is complete.
- If the same user request explicitly asks for both audit and standalone
  verification, finish and validate the audit report first, then start
  `$otel-verify` as a separate workflow only after handing off the audit links.

## Warning Signs

- Fewer than expected auto-instrumentation packages for the detected dependencies
- SDK initialized but no auto-instrumentation packages installed
- OTel packages in dependencies but no SDK init file found
- Error handling code without span error status or recordException

## Auto-Instrumentation Library Map

Use these tables to check whether each detected dependency has a matching
auto-instrumentation package installed. Only flag gaps for dependencies that
appear in the project.

### Go

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `net/http` (stdlib) | `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp` | spans + metrics |
| `gorilla/mux` | `go.opentelemetry.io/contrib/instrumentation/github.com/gorilla/mux/otelmux` | spans only |
| `go-chi/chi` | `go.opentelemetry.io/contrib/instrumentation/github.com/go-chi/chi/otelchi` | spans only |
| `gin-gonic/gin` | `go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin` | spans only |
| `google.golang.org/grpc` | `go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc` | spans + metrics |
| `database/sql` | `github.com/XSAM/otelsql` | spans only |
| `go-redis/redis` | `github.com/redis/go-redis/extra/redisotel` | spans only |
| `runtime` | `go.opentelemetry.io/contrib/instrumentation/runtime` | metrics only |
| `host` | `go.opentelemetry.io/contrib/instrumentation/host` | metrics only |
| `segmentio/kafka-go` | `go.opentelemetry.io/contrib/instrumentation/github.com/segmentio/kafka-go/otelsegmentio` | spans only |
| `aws-sdk-go-v2` | `go.opentelemetry.io/contrib/instrumentation/github.com/aws/aws-sdk-go-v2/otelaws` | spans only |

### Python

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `flask` | `opentelemetry-instrumentation-flask` | spans |
| `django` | `opentelemetry-instrumentation-django` | spans |
| `fastapi` / `starlette` | `opentelemetry-instrumentation-fastapi` | spans |
| `requests` | `opentelemetry-instrumentation-requests` | spans |
| `httpx` | `opentelemetry-instrumentation-httpx` | spans |
| `urllib3` | `opentelemetry-instrumentation-urllib3` | spans |
| `aiohttp` | `opentelemetry-instrumentation-aiohttp-client` | spans |
| `psycopg2` | `opentelemetry-instrumentation-psycopg2` | spans |
| `sqlalchemy` | `opentelemetry-instrumentation-sqlalchemy` | spans |
| `pymongo` | `opentelemetry-instrumentation-pymongo` | spans |
| `redis` | `opentelemetry-instrumentation-redis` | spans |
| `celery` | `opentelemetry-instrumentation-celery` | spans |
| `grpcio` | `opentelemetry-instrumentation-grpc` | spans |
| `kafka-python` / `confluent-kafka` | `opentelemetry-instrumentation-kafka-python` / `opentelemetry-instrumentation-confluent-kafka` | spans |
| `boto3` / `botocore` | `opentelemetry-instrumentation-botocore` | spans |
| `logging` (stdlib) | `opentelemetry-instrumentation-logging` | logs |

### Node.js

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `express` | `@opentelemetry/instrumentation-express` | spans |
| `fastify` | `@opentelemetry/instrumentation-fastify` | spans |
| `koa` | `@opentelemetry/instrumentation-koa` | spans |
| `@nestjs/core` | `@opentelemetry/instrumentation-nestjs-core` | spans |
| `http` / `https` (stdlib) | `@opentelemetry/instrumentation-http` | spans |
| `pg` | `@opentelemetry/instrumentation-pg` | spans |
| `mysql2` | `@opentelemetry/instrumentation-mysql2` | spans |
| `mongodb` | `@opentelemetry/instrumentation-mongodb` | spans |
| `ioredis` | `@opentelemetry/instrumentation-ioredis` | spans |
| `redis` (node-redis v4+) | `@opentelemetry/instrumentation-redis-4` | spans |
| `@grpc/grpc-js` | `@opentelemetry/instrumentation-grpc` | spans |
| `kafkajs` | `@opentelemetry/instrumentation-kafkajs` | spans |
| `graphql` | `@opentelemetry/instrumentation-graphql` | spans |
| `aws-sdk` / `@aws-sdk/*` | `@opentelemetry/instrumentation-aws-sdk` | spans |

### Java

The OpenTelemetry Java agent auto-instruments without code changes:

- Spring MVC (REST controllers), Spring WebFlux, Spring Data (JPA, JDBC)
- RestTemplate and WebClient (outbound HTTP)
- Kafka producers/consumers (including clients used internally by Kafka Streams)
- RabbitMQ, gRPC
- Servlet containers (Tomcat, Jetty, Undertow)
- JDBC drivers

## Troubleshooting

**No dependency manifest found:** Ask the user which subdirectory contains the service, then re-scan from that root.

**Multiple languages detected:** Ask which service to audit, or audit each independently.
