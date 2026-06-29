---
name: otel-audit
description: >-
  Scan a codebase for existing OpenTelemetry instrumentation and report
  on observability coverage gaps. Read-only -- does not modify code.
  Use when the user types $otel-audit, asks about observability gaps,
  wants to assess instrumentation coverage, says "what signals am I
  missing", "scan this service for observability", asks about
  "observability readiness", or asks whether GenAI/LLM workflows follow
  OpenTelemetry semantic conventions. Do NOT use for implementing code
  changes -- use $otel-instrument instead.
---

# Audit -- Observability Coverage Scan

## Overview

Scan a service repository to detect its language, framework, dependencies,
and existing OpenTelemetry instrumentation. Report what is instrumented,
what is missing, and any anti-patterns. This skill is read-only -- no code
is modified.

Before writing `.observe/otel.md`, read
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
4. Use the Auto-Instrumentation Library Map below to identify which packages should be present for each detected dependency.
5. Detect GenAI/LLM ownership: provider clients/model gateways, agents or
  workflows, tool/function dispatch, MCP when present, retrieval/RAG,
  model/deployment config, fallback/readiness checks, token accounting, call
  counts, prompt/response assembly, AI-derived data jobs, AI-path synthetic/canary checks, or usage logging. When any are present, load
  `../references/genai-readiness.md`.
  Follow its GenAI Semconv Source Contract before scoring GenAI coverage:
  reconcile detected AI surfaces with official semconv docs when available,
  record live-or-snapshot provenance, and build a semconv closure matrix.
  When GenAI incidents, postmortems, alerts, tickets, or failure examples are
  part of the request, use GenAI incident-evidence mode and map each failure
  mechanism to provider/model gateway, workflow, tool/function execution or
  AI-owned session/stream including MCP when present, retrieval/RAG, streaming,
  token/context, prompt/response parser, safety/policy, AI-derived data,
  model/config rollout, or AI-owned cache/session evidence.
6. Record exact evidence paths that should appear in the report:
  - Dependency manifest: `go.mod`, `package.json`, `pyproject.toml`, `pom.xml`, etc.
  - Process entry point: `main.go`, `cmd/.../main.go`, `app.py`, `app.js`, `TasksApplication.java`, etc.
  - Route source: router/controller files such as `TaskController.java`, `app.py`, `app.js`, or `kvstore/http.go`.
  - Traffic and readiness clients when they exercise a GenAI path: demo, load, eval, or replay scripts, plus AI-path synthetic or canary scripts such as `load_demo.py`,
    `smoke.py`, `scripts/check-*`, or `tests/e2e/*`.
  - Runtime/startup files when present: `Dockerfile`, `docker-compose.yml`, `Makefile`, `package.json` scripts, launch configs, worker files.
7. Inventory project runtime and verification evidence without installing or
   changing anything:
  - wrappers and task runners such as `mvnw`, `gradlew`, Make, package scripts,
    tox/nox, Cargo, or solution test projects
  - toolchain/version files and manifest runtime requirements
  - lockfiles, CI test commands, devcontainer config, and existing test layout
  - locally safe compile/type/import/test commands implied by project config
  Record configured requirements, not the shell's accidental default runtime.
8. Make one explicit GenAI ownership decision from the completed source scan:
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
`otelgrpc` emits `rpc.server.duration`, `rpc.server.request.size`,
`rpc.server.response.size`, `rpc.server.requests_per_rpc`, and
`rpc.server.responses_per_rpc` -- list each as its own row. Similarly,
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

**Audit document contract** -- the audit is a baseline source scan only. Do not
compute or show an instrumentation delta. If a prior `.observe/otel.md` exists,
use it only as historical context for stable service names, scenario IDs, or
known surfaces; do not compare old vs current signals and do not create added,
modified, or deleted signal tables. Implementation changes belong in
`.observe/otel-instrumentation.md`.

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

**Operational signal assessment** -- do not create a `RED Signals` section. If
rate, error, latency, or saturation gaps matter for the service, express them as
ordinary entries in `## Current Instrumentation`, `## Gaps`, or
`## Verification Plan` with exact source paths and signal names.

**GenAI readiness assessment** -- when GenAI/LLM evidence exists, use
`../references/genai-readiness.md` to check baseline trace continuity,
OpenTelemetry GenAI spans, semconv completeness, GenAI metrics, and
privacy/cardinality controls. Add or update `## GenAI Readiness` rows for
missing workflow, provider/model gateway, model/config rollout,
tool/function execution or AI-owned session/stream lifecycle including MCP when
present, token/context pressure, retrieval/RAG, streaming response lifecycle,
fallback/failover, prompt/response assembly, safety/policy outcome,
AI-derived data freshness, memory/context, evaluation quality, framework bridge
coverage, content governance, cost ownership, or AI-owned cache/session state
signals. For
code-owned GenAI pathway gaps, explicitly check for token/context pressure,
response parse failure, AI-derived data freshness, prompt/tool schema version,
LLM-call count, tool-call count, authentication/authorization result,
invalid-token or permission failure outcome, active AI-owned streams or
sessions, close reason family, stream duration/outcome, send/write failure,
memory hit/miss or stale/missing context, `gen_ai.evaluation.result` coverage,
evaluation score distribution, content capture mode/redaction/access owner, and
app-owned cost or owner-mapped billing source when those values are observable.
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

**GenAI readiness contract** -- the `## GenAI Readiness` table is the
instrumentation contract, not background context. Do not require a separate
GenAI gap-contract section and do not require opaque IDs such as `GR8` or `G1`.
For every GenAI readiness gap, create or update a structured surface row with:
`surface`, `evidence`, `current_status`, `required_signals`,
`owner/source_files`, and `acceptance_criteria`. If an existing audit already
has an ID column, treat it only as an optional source-row reference; use the
surface name in human-facing summaries and closure handoffs. Split a surface
when required signals have different owners or acceptance criteria. Required
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
exists. The GenAI Readiness surface row is the source of truth for
`$otel-instrument` and `$splunk-configure`.

Compute each GenAI surface independently. Generic HTTP/database/runtime or
infrastructure metrics do not make `Metrics and detectors` partial unless they
satisfy one of that row's required GenAI workflow, model, tool, token, memory,
evaluation, or AI-path signals. Use `missing` when none of the required GenAI
signals exists, even if unrelated OTel metrics are source-active.

**Deterministic gap section contract** -- the audit report must contain at most
one top-level gap section, named exactly `## Gaps`. Do not emit `## Gap
Register`, `## Gaps and Recommendations`, `Gaps:`, or any GenAI-local gap
subsection. For GenAI issues, record the contract in `## GenAI Readiness` table
rows and add only concise references in `## Gaps` that point back to the
human-readable readiness surface name.

Write `## Gaps` as the prioritized table defined in
`../references/report-flow-contract.md`. Use only `required`, `recommended`, or
`deferred` priorities and only `default`, `fix all`, or `manual decision`
instrument modes. Put baseline correctness, trace continuity, error
attribution, exporter/resource identity, cardinality safety, and duplicate
signal ownership in `required`. Put safe deeper diagnostics, business metrics,
and opt-in log export in `recommended` unless the request already makes them
mandatory. Use `deferred` only for a concrete external owner, prerequisite, or
decision. Every row must explain user/operator impact, state a specific fix,
and cite the verification scenario IDs that can prove closure. Group related
routes and call sites by remediation theme instead of producing a row per edge.
When a default GenAI gap involves duplicate or overlapping instrumentation,
name the intended canonical owner per logical operation and the pre-bootstrap
suppression surface in `Required fix`. If source evidence cannot support that
choice, use `manual decision`; do not hand `$otel-instrument` an unresolved
"select one canonical source" instruction in a `default` row.

**Evidence and flow contract** -- write source evidence as a compact
`## Audit Evidence` table and create one `## Signal Flow` / `### Component Flow
Map` using the exact marker semantics in `report-flow-contract.md`. The map is
a reader aid, not runtime proof. Show only major process, dependency, and
telemetry edges; keep independent roots separate and point human-readable gap
markers to the prioritized gap table. Do not add a step-by-step signal coverage
matrix, `Shows Today` column, or unqualified `[COVERED]` marker.

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

Write the report to `.observe/otel.md` inside the scanned service root (create
the `.observe/` directory if it does not exist). Also present a concise summary
in chat that references the file path.

Use this template for `.observe/otel.md`:

````markdown
# Observability Report: {service-name}

**Language:** {language} | **Framework:** {framework} | **Date:** {YYYY-MM-DD}
**Status:** Pass | Partial | Blocked
**GenAI ownership detected:** Yes | No

## Executive Summary
- {most important finding}
- {top missing signal or "No critical gaps detected"}
- {verification handoff summary}
- {recommended next action}

## Flow
`audit -> instrument -> verify -> configure -> configure-verify`

## Audit Evidence

| Check | Finding | Source |
|---|---|---|
| Manifest | {language, framework, dependency finding} | {path} |
| Entry point | {target process finding} | {path} |
| Route source | {route ownership finding} | {path(s)} |
| Runtime/startup | {configured runtime finding} | {path(s) or "none detected"} |
| GenAI ownership | {Yes or No, matching the report declaration} | {owned source paths or repository scan evidence} |

## Routes

| Method | Path |
|--------|------|
| GET | /health |
| GET | /tasks |
| POST | /tasks |
| GET | /tasks/{id} |
| ... | ... |

## Signal Flow

### Component Flow Map

```text
{process entry point} [SOURCE-COVERED]
  -> {framework routes or worker dispatch} [SOURCE-COVERED]
     -> {business operation} [GAP: human-readable area]
     -> {dependency} [SOURCE-COVERED]
  -> {OTLP/export path} [GAP: human-readable area]
```

`[SOURCE-COVERED]` means source/config evidence exists; it is not runtime
emission proof. Each `[GAP: ...]` marker maps to one row below.

## Current Instrumentation

### Spans

List every individual span name -- one row per span. Never group auto-
instrumented spans with vague labels like "HTTP server spans" or
"gRPC server spans (all N RPCs)".

| Name | Source | Type |
|------|--------|------|
| GET /tasks | otelhttp | auto |
| POST /tasks | otelhttp | auto |
| GET /tasks/{id} | otelhttp | auto |
| orders.process | orders/service.go:42 | custom |

If no span sources are found, write: "No spans detected."

### Metrics

List every individual metric name -- one row per metric. Never group auto-
instrumented metrics with vague labels like "(+ related)" or parenthetical
summaries.

| Name | Source | Type |
|------|--------|------|
| http.server.request.duration | otelhttp | auto |
| http.server.active_requests | otelhttp | auto |
| http.server.request.size | otelhttp | auto |
| http.server.response.size | otelhttp | auto |
| orders.processed.count | orders/metrics.go:15 | custom |

If no metric sources are found, write: "No metrics detected."

### Logs

| Integration | Source | Detail |
|-------------|--------|--------|
| trace-context injection | opentelemetry-instrumentation-logging | Injects trace_id/span_id into log records |
| span events | orders/service.go:55 | span.AddEvent("order.validated") |

If no OTel log integrations are found, write: "No OTel log instrumentation detected."

If no OTel packages or setup are found across all three signal types, include
the phrase: "OpenTelemetry instrumentation is missing."

## GenAI Readiness

Include only when GenAI/LLM ownership evidence exists.

| Surface | Status | Evidence | Required Signals | Owner / Source Files | Acceptance Criteria | Detection/Localization Impact |
|---------|--------|----------|------------------|----------------------|---------------------|-------------------------------|
| Trace and semconv | {covered / partial / missing} | {workflow, agent, tool, chat, retrieval spans and gen_ai attrs; model-call lifecycle hook evidence} | {missing parent/child span, propagation, request model, provider, tool name, chat/model lifecycle span, or error type} | {owner and file/path evidence} | {code + tests, proof path + signal name, or exact external owner/source} | {model/provider/tool issues remain slow to localize} |
| Metrics and detectors | {covered / partial / missing} | {gen_ai metrics or service-owned counters/histograms} | {missing latency/token/fanout/readiness/fallback metric} | {owner and file/path evidence} | {code + tests, proof path + signal name, or exact external owner/source} | {alert cannot fire before manual trace search} |
| AI pathway surfaces | {covered / partial / missing} | {provider/model gateway, workflow, tool/function execution or AI-owned session/stream lifecycle including MCP when present, retrieval/RAG, streaming, token/context, prompt/response parser, safety/policy, AI-derived data, model/config rollout, or AI-owned cache/session signals} | {missing outcome, latency, error class, duration, count, freshness, fallback, rejection, version, parse, prompt/tool schema, or model/config compatibility signal} | {owner and file/path evidence} | {code + tests, proof path + signal name, or exact external owner/source} | {AI pathway incidents cannot be detected or routed by failure mechanism} |
| Memory/context | {covered / partial / missing} | {memory/context spans, hit/miss, stale/missing context, source/version, auth failure} | {missing memory operation span or detector-ready stale/miss signal} | {owner and file/path evidence} | {code + tests, proof path + signal name, or exact external owner/source} | {bad context may look like model quality failure} |
| Evaluation quality | {covered / partial / missing} | {`gen_ai.evaluation.result`, score value/label, evaluator errors, sample/freshness metrics} | {missing quality event, score distribution, failure count, or no-data signal} | {owner and file/path evidence} | {code + tests, proof path + signal name, or exact external owner/source} | {hallucination, toxicity, factuality, or instruction-following regressions need manual review} |
| Framework bridge/content/cost | {covered / partial / missing / owner-mapped} | {framework OTel bridge evidence, content capture mode/redaction/access owner, token-to-cost or billing source} | {unproven bridge, unsafe content capture, missing cost source, or provider/platform owner missing} | {owner and file/path evidence} | {code + tests, proof path + signal name, or exact external owner/source} | {duplicate/missing spans, unsafe telemetry, or cost incidents remain hard to explain} |
| Privacy/cardinality | {covered / partial / missing} | {content capture and attribute policy evidence} | {raw content or high-cardinality dimension risk} | {owner and file/path evidence} | {code + tests, proof path + signal name, or exact external owner/source} | {telemetry may be unsafe or unusable for alert grouping} |

## Gaps

| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | {human-readable area} | {source-derived gap} | {user/operator impact} | {specific result} | default | {scenario IDs or N/A} |

If no gaps remain, keep the header and separator, omit example rows, and write:
`No gaps found.`

## Verification Plan

This section is a source-derived contract for downstream instrumentation,
verification, and detector configuration; it does not claim runtime execution.

### Test Environments

| Environment ID | Surface | Config Evidence | Runner / Toolchain | Scope | Shared Prerequisites |
|----------------|---------|-----------------|--------------------|-------|----------------------|
| {stable-environment-id} | {service/module} | {wrapper, toolchain file, manifest, CI path} | {runner and configured version} | {compile/type/import/test scope} | {local-safe fixture, available requirement, or exact missing prerequisite} |

### Acceptance Scenarios

These rows are the executable handoff to `$otel-instrument` and
`$otel-verify`: each row says which user/application action must be run and
what telemetry must appear. They are source-derived test plans, not claims that
the paths already work. The `Environment` cell contains only IDs defined in
`Test Environments`; use comma-separated IDs when a scenario needs more than
one environment.

| Scenario ID | Trigger / Path | Source Entrypoint | Expected Signals | Proof Level | Acceptance Criteria | Environment |
|-------------|----------------|-------------------|------------------|-------------|---------------------|-------------|
| {stable.id} | {route, workflow, worker, startup, error path} | {file:line or symbol} | {exact spans, metrics, logs, runtime signal} | {focused call-site / full runtime / either} | {observable status, attrs, datapoint, log, topology, or exporter proof} | {stable-environment-id} |

## Anti-Patterns
- {any issues found, or "None detected"}

## Recommendation
- {actionable next step: "Run $otel-instrument to add auto-instrumentation
  for X, Y, Z" or "Instrumentation looks complete -- consider
  $otel-instrument for custom business metrics"}

---
*Generated by otel-audit on {YYYY-MM-DD HH:MM UTC}*
````

After writing the report, run the dependency-free validator bundled with this
skill:

```bash
python3 scripts/validate_audit_report.py .observe/otel.md
```

Resolve `scripts/validate_audit_report.py` relative to this skill directory.
If validation fails, repair the report and rerun it before presenting results.

Report requirements:

- Follow `../references/report-flow-contract.md`: put `Status`, `Executive
  Summary`, `Flow`, `Audit Evidence`, routes, the compact signal-flow map,
  current instrumentation, optional GenAI readiness, and prioritized gaps in
  that order.
- Never include top-level `## Instrumentation Delta` or `## RED Signals` in
  `.observe/otel.md`.
- Never include `## Step-by-Step Signal Coverage`, a `Shows Today` table, or an
  unqualified `[COVERED]` flow marker.
- Always include top-level `## Verification Plan` after `## Gaps`. Populate both
  `Test Environments` and `Acceptance Scenarios`; write
  `No runnable surface detected` only when source evidence supports that
  conclusion.
- Give every test environment a unique stable ID. Every acceptance scenario
  must reference only IDs defined in `Test Environments`; do not repeat fixture
  or prerequisite prose in scenario rows.
- Treat runtime and scenario rows as source-derived inputs, not executed proof.
  Never write `verified` in this section unless a cited existing test report or
  artifact already proves the claim.
- If GenAI/LLM code is detected, include `## GenAI Readiness` after
  `## Current Instrumentation`; omit it otherwise.
- Always emit `**GenAI ownership detected:** Yes` or `No` and one matching
  `GenAI ownership` row in `## Audit Evidence`. `Yes` requires the readiness
  table; `No` forbids it. Never leave the decision implicit in framework names,
  gaps, or scenarios.
- Put `## Gaps` after `## Current Instrumentation` and optional
  `## GenAI Readiness`, so the reader sees the source-derived baseline before
  the prioritized remediation queue.
- The report must have at most one top-level gap section, named exactly
  `## Gaps`. Do not emit `## Gap Register`, `## Gaps and Recommendations`,
  `Gaps:`, or a GenAI-local gap subsection.
- Use the exact prioritized gap-table columns and allowed priority/instrument
  mode values from `report-flow-contract.md`. Every gap row must name user
  impact, required fix, and applicable verification scenario IDs.
- If GenAI readiness gaps exist, put the required signals, owner/source files,
  and acceptance criteria directly in the `## GenAI Readiness` surface rows.
  Every GenAI-related `## Gaps` bullet must refer back to the human-readable
  surface name, not an opaque ID such as `GR8`.
- Keep GenAI readiness generic: no organization-specific service names,
  incident IDs, customer names, realms, or provider account names.
- Prefer OTel GenAI semantic conventions. Treat missing
  `gen_ai.request.model` as a gap when the requested model is available.
- For GenAI incident-evidence requests, include the generic coverage mapping
  `incident class -> failure mechanism -> repo/service owner -> code surface ->
  signal -> MTTD impact -> remaining owner`. Mark each gap as
  `MTTD-improving`, `localization-only`, `provider/platform-owned`, or
  `unknown owner`.
- Treat missing provider/model gateway health, workflow outcome,
  tool/function execution or AI-owned session/stream lifecycle including MCP
  when present, retrieval/RAG freshness or quality, streaming lifecycle,
  token/context pressure, prompt/response build or parse outcome,
  safety/policy outcome, AI-derived data freshness, model/config rollout, and
  AI-owned cache/session state as GenAI gaps only when code or runtime evidence
  shows the service owns that AI pathway surface.
- When those GenAI surfaces are owned, name concrete detector-ready signals such
  as token/context budget percent, truncation rate, token-limit errors,
  prompt/tool schema size, LLM call count, tool call count, response parse
  failure, AI-derived data freshness, prompt/tool schema version,
  model/config readiness, and expected-vs-running model/config state instead
  of reporting a vague GenAI gap. Put missed, flapping, auto-resolved, or
  no-data alert evidence into the `$splunk-configure` detector reliability
  handoff.
- IDs for users, accounts, tenants, sessions, tasks, conversations, requests,
  and traces may help trace drilldown, but must not be metric dimensions or
  detector group-by keys.
- If instrumentation is incomplete, always include the exact token `$otel-instrument` in the recommendation.
- If OpenTelemetry is absent, include both words `OpenTelemetry` and `missing`.
- Name the concrete files that support findings; do not only refer to "the service" or "./service".
- For Node.js, mention `package.json` and the app entry point such as `app.js`.
- For Python, mention `pyproject.toml` or `requirements.txt`, the app file such as `app.py`, and runtime files such as `Dockerfile` or `docker-compose.yml` when present.
- For FastAPI/Celery services, mention the web app, worker file, Dockerfile, compose commands, FastAPI/ASGI coverage, Celery instrumentation, Redis instrumentation if Redis is present, and HTTP client instrumentation only when an HTTP client dependency is detected.
- For Java/Spring Boot, mention the Spring Boot entry point such as `TasksApplication.java`, controller files such as `TaskController.java`, and the Java agent recommendation.
- For Java/Kafka services, mention the main entry point, runtime configuration,
  producer/consumer classes that wrap `KafkaProducer` or `KafkaConsumer`, batch
  poll loops that handle `ConsumerRecords`, listener-container classes or
  methods such as `@KafkaListener`, and Kafka Streams lifecycle/topology code
  that constructs `KafkaStreams`, `Topology`, `StreamsBuilder`, `KStream`, or
  `KTable`.
- For Java/Kafka services, name topics, consumer groups, poll/send/listener or
  topology behavior, offset commit behavior, uncaught exception handling, Java
  agent coverage for Kafka clients, and missing business signals such as
  processed records, failed parses, high-risk alerts, processing errors,
  consumer lag/offset visibility, and record-processing latency.
- For Go multi-package services, name the process entry point such as `cmd/kvstore-server/main.go` and relevant library files. If filesystem persistence, background indexing, or LRU eviction exists, call those out explicitly.

**Chat summary:** After writing `.observe/otel.md`, present a brief summary in
chat that includes: audit status, the most important findings first, gap counts
by `required`, `recommended`, and `deferred`, and the recommendation line. End with:
`Full report: .observe/otel.md`.

### Step 4 -- Verification Handoff

Do not perform telemetry execution inside the audit workflow. The report's
`Verification Plan` is the handoff to `$otel-instrument` and
`$otel-verify`.

- Recommend `$otel-instrument` when source gaps require implementation.
- Recommend `$otel-verify` when instrumentation exists and the user wants
  compile, app-code, signal-emission, topology, or OTLP proof.
- If the same user request explicitly asks for both audit and verification,
  finish the audit report first, then apply `$otel-verify` so runtime selection,
  app-code execution, and collector evidence follow its stricter contract.

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
