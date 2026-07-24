---
name: otel-audit
description: >-
  Scan a codebase for existing OpenTelemetry instrumentation and report
  on observability coverage gaps. Read-only for application code -- writes
  .observe/otel-audit.json and .observe/otel.html, but does not modify service code.
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
code: it writes `.observe/otel-audit.json` and `.observe/otel.html` but does not
modify service code, dependencies,
configuration, or tests.

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

Use the initial bounded file list as a size gate. When the service has at most
25 non-ignored files, exactly one dependency manifest, and no nested service
root, take the direct small-repo path: inspect that file list, the manifest,
the entrypoint, and cited source directly, and do not run the inventory helper.
For larger, multi-module, nested, or unclear repositories, run the shared
read-only inventory before broad manual searches:

```bash
python3 -I "<directory-containing-loaded-SKILL.md>/scripts/inspect_otel_project.py" \
  "<service-root>" \
  --output "<service-root>/.observe/tmp/otel-project-inventory.json"
```

Resolve the command directly from the directory containing the loaded
`otel-audit/SKILL.md`; do not probe a repository-root `references/` directory.
On the inventory path, run one successful invocation. Retry only to correct an
invocation or runtime failure. Its deterministic JSON
seeds language/manifests, entrypoint and route candidates, runtime candidates,
startup/test surfaces, and categorized OTel source/config hits. Treat every hit
as a candidate: the inventory does not prove target-process reachability,
runtime availability, or telemetry emission. First inspect `complete`,
`warnings`, `skipped`, and `section_counts`; then read only the JSON sections
needed for the task instead of dumping the full file into context. Reconcile
candidates with the actual entrypoint and source before making coverage claims.
For a section whose truncation is zero in a `complete: true` inventory, do not
repeat the same repository-wide `find` or broad `rg`; inspect cited files and
use focused source proof. In particular, do not follow a complete file/OTel
inventory with recursive `find`, `rg --files`, or a repository-wide OTel-pattern
`rg`. The helper creates the output parent; do not pre-create it. Search
manually for incomplete, skipped, unsupported, or truncated surfaces. If Python
or the shared helper is unavailable, perform the discovery manually and record
the exact inventory failure. Record which discovery path was selected.

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
  Record the decision in `meta.genai_ownership_detected` and as an exact
  `GenAI ownership` row in `evidence`. The two values must match.

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
saturation coverage in `current_instrumentation`, `findings`, or `verification`
with exact source paths and signal names.

**Incident readiness assessment** -- when the repository owns incident-relevant
surfaces or the user asks for faster detection/localization, use
`../references/incident-readiness.md` to assess API/workflow and customer
impact, dependencies, input complexity, freshness, backpressure,
synthetic/canary checks, auth/edge, capacity, and release/config context. For
incident evidence, classify each proposed signal as `MTTD-improving` only when
it can support a detector before or at first customer impact,
`localization-only` when it mainly narrows an already-detected fault,
`provider/platform-owned`, or `unknown owner`.

Record current readiness in `current_instrumentation.incident_readiness`.
Record only telemetry-scoped readiness surfaces there. A `partial` or
`missing` row is telemetry-scoped only when `required_signals` names an OTel
signal, OTel pipeline/configuration outcome, or telemetry-specific proof admitted
by the OTel finding boundary. Record every such owned surface in the single
canonical `findings` array. The matching finding and its mapped acceptance
scenarios form the closure contract for `$otel-instrument` and
`$splunk-configure`:

- Use only `covered`, `partial`, `missing`, or `owner-mapped` readiness
  statuses. Areas are unique. Every `partial`, `missing`, or Incident Readiness
  `owner-mapped` area must exactly match one finding with at least one
  verification scenario; Incident Readiness has no owner field, so its
  `owner-mapped` state remains unresolved. A GenAI `owner-mapped` row is
  complete only when its owner names a concrete external/provider/platform
  source with a category-prefixed value such as `Provider/platform-owned:
  billing API`. Generic categories or team labels are not exact owners. Only a
  `covered` Incident Readiness area is complete and must not have an unresolved
  finding; `covered` and valid `owner-mapped` GenAI areas must not have one.
  These invariants prevent a `Pass` audit from hiding missing readiness.

- `Area` is the stable human-readable gap identity used downstream.
- `Required fix` names every required signal or exact owner mapping; it must not
  use a vague label such as `add observability`.
- `Instrument mode` records whether safe app-owned work is `default`, broader
  safe work is `fix all`, or an external/unsafe choice is `manual decision`.
- The mapped scenario provides the code surface, expected telemetry, proof
  level, and acceptance criteria.

Split a telemetry gap when required signals have different owners, instrument
modes, or acceptance criteria. Never combine externally owned telemetry
follow-up with independently executable service-owned telemetry work: the
external finding must use `external follow-up`, while the service-owned OTel
work keeps its own `default` or `fix all` finding. Do not promote service code,
configuration, contract, documentation, policy, or general test work into its
own OTel finding. Do not mark a partial surface covered because one span or
metric exists, and do not imply that detector configuration can compensate for
an absent detector-critical metric.

**GenAI readiness assessment** -- when GenAI/LLM evidence exists, read both
`../references/genai-readiness.md` and `references/genai-audit.md` completely.
Follow the shared GenAI Semconv Source Contract, including live-or-snapshot
provenance and a semconv closure matrix, then apply the audit-specific contract
to every independently actionable surface. Keep the ownership decision,
`genai_readiness` rows, findings, and acceptance scenarios
consistent. Do not load the audit-specific reference for non-GenAI services.

**Deterministic findings contract** -- record GenAI detail in
`genai_readiness` and use matching human-readable finding areas.

Populate canonical `findings` directly. Use only `required`,
`recommended`, or `deferred` priorities and only `default`, `fix all`, `manual
decision`, or `external follow-up` instrument modes. Put baseline correctness,
trace continuity, error attribution, exporter/resource identity, cardinality
safety, and duplicate signal ownership in `required`. Put safe deeper
diagnostics, business metrics, and opt-in log export in `recommended` unless
the request already makes them mandatory. Use `deferred` only for a concrete
external owner, prerequisite, or decision. Every row must explain
user/operator impact, state a specific fix, and cite the verification scenario
IDs that can prove closure. Group related routes and call sites by remediation
theme instead of producing a row per edge.
When a default GenAI gap involves duplicate or overlapping instrumentation,
name the intended canonical owner per logical operation and the pre-bootstrap
suppression surface in `Required fix`. If source evidence cannot support that
choice, use `manual decision`; do not hand `$otel-instrument` an unresolved
"select one canonical source" instruction in a `default` row.

**Evidence contract** -- write compact structured source evidence. Do not author
`signal_flow` for new audits; findings and verification scenarios already carry
the downstream scope and proof handoff. Neither audit HTML nor scoped
instrumentation consumes a component map.

**Anti-patterns** -- flag any of these:

- Multiple SDK initializations in the same process
- Hardcoded OTLP endpoints instead of env vars
- Tracer/Meter created in hot paths instead of at startup
- High-cardinality attributes on metrics (user IDs, request IDs)
- Missing `recordException` in error handling paths
- Custom span names with variable segments (IDs, paths)
- Use of an unmaintained third-party wrapper outside official OpenTelemetry
  distributions when a supported official package exists. Official
  `go.opentelemetry.io/contrib`, `@opentelemetry/*`, and `opentelemetry-*`
  distributions are not evidence of this anti-pattern.

Do not repeat an anti-pattern when the same condition is already represented
by an actionable finding. The finding card owns its gap, impact, remediation,
selection, and proof path. Keep `anti_patterns` only for distinct OTel-scoped
compatibility or provenance context that does not create another action. The
canonical JSON preserves those authored notes; the
decision-focused HTML never renders a separate Anti-Patterns subsection.

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

In HTML, put selectable findings immediately after the concise decision
summary. Do not render a component map, connection lanes, component-coverage
groups, raw flow map, full current-state inventory, or a duplicate all-findings
decision table. Omit `signal_flow`; HTML and scoped instrumentation do not use
it. Reserve one collapsed technical appendix at the
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
select the finding, save the selection, and then run `$otel-instrument`; do not
present authored verification or dashboard work as
the reviewer's immediate action.
Keep that copy synchronized with selection state: selected work proceeds to
saving, an auto-added dependency explains why it is included, and
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

Keep the HTML complete and usable on its own. It may link to canonical JSON as
an alternate format, but must not require another audit report to understand or
select a finding.

Write the human summary as a decision brief, not a compressed defect list. In
HTML and chat summaries, use 3-7 plain-language bullets and state
the total finding count, what source or configuration currently shows, the
highest-priority app-owned work, and any exact owner decision or external
prerequisite that blocks executable work. Do not present canonical
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
preserving canonical order within the same priority. Priority controls order
only. Do not render priority sections, headings, labels, tags, colors, legends,
counts, action queues, or summary cards, and do not repeat finding links in the
executive summary. Put one concise current-baseline sentence and one
highest-priority-first explanation before the list, then show a compact
`Findings · N` heading immediately above the cards. Keep quick-win, effort,
severity, priority, and execution-state metadata machine-readable in canonical
JSON. Do not render Priority, Effort, or Status
filter facets.

Lead each finding card with the human title and expected monitoring outcome,
and show the stable `OTEL-###` ID only as a secondary reference. Do not replace
stable IDs with display-order labels such as `gap-1`; IDs must remain
deterministic across selection, instrumentation, verification, and
configuration handoffs. Keep `severity` in canonical JSON for machine
compatibility, but do not render it as a second human ranking system.

Do not render tag chips on finding cards. In particular, do not render
readiness, priority, severity, instrument mode, effort, or lifecycle tags such
as `Ready to select`, `optional`, `small effort`, `selected`, `included`,
`working`, or `done`. Priority is expressed only by list order; lifecycle is
reflected by the checkbox, next-step copy, and saved selection state, and
effort remains machine-readable only in canonical JSON. Do not render
`Required`, `Recommended`, `Deferred`, `Fix now`, `Consider next`, `Decide
now`, or `Decide first` as human categories.

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
classification, OTel concerns, verification-scenario references, ownership,
and requirements in canonical JSON. In HTML, keep
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
  "evidence": [
    {"check": "Manifest", "finding": "Go module", "source": "go.mod"},
    {"check": "Entry point", "finding": "HTTP service", "source": "main.go"},
    {"check": "Route source", "finding": "GET /health", "source": "main.go:42"},
    {"check": "Runtime/startup", "finding": "Go test runner", "source": "go.mod"},
    {"check": "GenAI ownership", "finding": "No", "source": "repository source scan"}
  ],
  "routes": [{"method": "GET", "path": "/health"}],
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
  work. Every `external follow-up` must
  include a known non-placeholder `external_owner` and an exact
  `external_requirement` naming an actual expected OTel signal, attribute,
  configuration scope, or telemetry proof that owner must supply. The exact
  external requirement must also be the finding's `required_fix`, so
  service-owned implementation cannot be hidden in an unselectable item. Those
  fields are invalid on other modes.
- In schema v2, every `manual decision` and `external follow-up` must be in the
  transitive dependency closure of at least one `default`/`fix all` finding.
  Reject orphan non-executable findings. A non-executable finding contains only
  its prerequisite decision or externally supplied telemetry requirement; put
  app-owned implementation in a separate executable finding that lists the
  prerequisite in `dependencies`.
- Classify effort as `small`, `medium`, `large`, or `decision` so owners can
  distinguish quick wins from longer or choice-dependent work.
- Every finding must include human impact, one concise `product_outcome`,
  required fix, evidence, acceptance criteria, expected telemetry with its
  Splunk/ObStudio `product_view`, and at least one follow-up action. The outcome
  states what the owner should see or gain after implementation and
  verification without claiming it is already proven. Include verification
  scenario IDs when runnable.
- Every mapped verification scenario must reference an ID in
  `verification.scenarios`.
- Do not use `$otel-verify` or generic `run
  verification` as an audit recommendation, finding follow-up, or chat next
  step; audit owns selection planning, while `$otel-instrument` invokes
  verification internally after implementation.
- Every finding dependency must reference another finding ID and point from the
  work toward its prerequisite. Every verification scenario reference must
  exist in `verification.scenarios`.
- Keep JSON values concise. Put bulky command output under `.observe/evidence/`
  and cite it from JSON.

After writing `.observe/otel-audit.json`, finalize it once. This command
validates the canonical source, renders HTML, and prints one compact digest:

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

Resolve the placeholder directly from the directory containing the loaded
`otel-audit/SKILL.md`; never use a service-root or repository-root script by
name. Treat the tool as opaque on the first attempt: do not inspect its source
or tests. If finalization fails, repair only the canonical field named
by the compact error and rerun `finalize-audit`; do not grep or dump generated
HTML or recheck JSON syntax separately.

The HTML is the human review and selection surface. Keep its empty fixed tray
`hidden` and `inert`. After a reviewer selects work or records a decision
answer, show only a compact summary -- `N in selection`, plus an auto-added
dependency count and decision-answer count only when nonzero -- and one primary
`Save selection` action plus a plain selectable terminal fallback command. Do
not require an intermediate review panel and do not render
clipboard-dependent `Copy command` or `Copy selection JSON` controls. The
fallback command must be regenerated from the current explicit `requested_ids`
and canonical `decision_answers` as
`$otel-instrument --ids OTEL-001,OTEL-002 --decision OTEL-003=option-id <absolute-service-root>`.
Use explicit requested IDs, not auto-added dependency closure, because
`$otel-instrument` recomputes and validates dependencies. If the reviewer has
recorded only decision answers and no executable selection, show that no
instrumentation command can be generated until an executable finding is
selected. The cards, summary, terminal fallback, and polite live region must
distinguish explicit selections from auto-added dependencies.

`Save selection` serializes the authoritative bound overlay with explicit
`requested_ids`, dependency-closed `approved_ids`, and canonical
`decision_answers` into the audit report's top-level `review_selection`, then
opens the browser's save-file flow with the suggested name
`otel-audit.selected.json`. Save this selected audit copy inside `.observe/`
when the browser permits choosing that directory; never overwrite the canonical
`.observe/otel-audit.json` from a browser tab. This prevents an older open tab
from rolling back a newer audit. `$otel-instrument` validates the saved copy's
audit ID and SHA-256 digest before extracting `review_selection`. If the browser
falls back to a download, `$otel-instrument` may adopt a matching saved audit
only when no trusted repository selection already exists; an explicit candidate
is required to replace existing repository intent. Do not tell the reviewer to
copy a downloaded selection into `.observe/`. The terminal fallback exists for
users who want to paste a deterministic command instead of relying on browser
save location; it must carry the same explicit IDs and decision answers that
the saved audit state would carry.

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
  `genai_readiness` only when it is true. Human HTML must visibly render
  authored GenAI readiness instead of leaving it only in embedded JSON.
- Put source inventory in `current_instrumentation` and actionable work in
  `findings`. Keep every span, metric, and log integration as an individual
  JSON row rather than grouping exact signals into prose.
- Omit `flow` and `signal_flow` from new audits. The workflow is fixed by the
  skills, and neither field is an HTML or downstream instrumentation input;
  findings and verification scenarios are authoritative.
- Every telemetry-scoped partial, missing, or owner-mapped
  `current_instrumentation.incident_readiness` row must have an unresolved
  (`proposed`, `approved`, or `in_progress`) finding with an identical `area`
  and mapped verification scenarios. A `covered` row conflicts only with an
  unresolved same-area finding. Validate incident `area` and
  `required_signals`, plus GenAI `surface`, `required_signals`, and
  `acceptance_criteria`, as OTel closure fields; evidence and operator-impact
  prose remain context. Do not put general operational observations in either
  canonical readiness array merely to force a finding. Render authored
  readiness tables visibly in HTML.
- Define reusable environments in `verification.environments`; every
  `verification.scenarios[*].environments` value must reference those IDs.
- Audit scenarios and signal inventory are source-derived plans, not runtime
  proof. Keep bulky evidence outside JSON and cite its path.

**Chat summary:** After writing the audit artifacts, present a brief summary in
chat that includes the total finding count, the most important findings first,
any decision or external prerequisite that blocks executable work, and the
recommendation line. Do not expose priority categories. Successful
`finalize-audit` output includes `links.review_report` and
`links.machine_report`; copy those Markdown link values verbatim into the final
response. End with clickable local-file links using absolute paths, never a
relative or bare path. `Review report: .observe/otel.html` is an invalid
handoff. The rendered form is
`Review report: [otel.html](/absolute/repo/.observe/otel.html)` and
`Machine report: [otel-audit.json](/absolute/repo/.observe/otel-audit.json)`.

### Step 4 -- Downstream Handoff

Do not perform telemetry execution inside the audit workflow. The report's
`Verification Plan` is a proof plan consumed downstream; it is not the
reviewer's immediate command.

- Recommend selecting executable findings, saving the audit state, and running
  `$otel-instrument` for source gaps. `$otel-instrument` owns the internal
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
