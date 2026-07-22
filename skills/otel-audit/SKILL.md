---
name: otel-audit
description: >-
  Scan a codebase for existing OpenTelemetry instrumentation and report
  on observability coverage gaps. Read-only for application code -- writes
  audit artifacts under .observe/ including .observe/otel.md,
  .observe/otel-audit.json, and .observe/otel.html, but does not modify service code.
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
code: it writes `.observe/otel.md`, `.observe/otel-audit.json`, and
`.observe/otel.html` but does not modify service code, dependencies,
configuration, or tests.

Resolve every reference and script path from the directory containing the
loaded `otel-audit/SKILL.md`. Here, `../references/<file>` means the shared
sibling under the parent skills directory, while `references/<file>` and
`scripts/<file>` are local to `otel-audit`. Never probe the service root or
repository root for these paths.

Do not load `../references/report-flow-contract.md` as an up-front
prerequisite. This `SKILL.md` contains the audit finding, canonical JSON,
reader-report, selection-handoff, and finalization contract. Read the shared
report-flow contract only when a conditional downstream workflow explicitly
requires an additional field or rollup rule that is not defined here.

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
4. Load only the detected language's dependency map from
  `references/languages/{go,python,node,java}.md`. For Rust or .NET, use
  current official dependency evidence and record the source; do not load or
  restate unrelated language guidance.
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
- For Python repositories, use the shared inventory's provider/exporter
  candidates and reconcile every hit with target-process reachability before
  using it as evidence. The older `scripts/scan_python_otel_topology.py` remains
  available as a focused compatibility fallback; do not run both scanners
  unless the shared inventory is incomplete.
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
- Record `span.AddEvent()` / `span.add_event()` calls as trace span events under
  their owning span. A span event is trace data and never establishes log
  integration or an OTLP log pipeline.

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
- Use only the detected language reference as the checklist
- Flag any dependency that has an available auto-instrumentation package but is not instrumented
- In that finding's `required_fix` or follow-up action, name the exact supported
  package and any framework-specific adapter or route-tag API from the loaded
  reference. Do not reduce a proven package-level gap to generic "add
  instrumentation" wording.

**Operational signal assessment** -- express rate, error, latency, and
saturation coverage as ordinary entries in `## Current Instrumentation`,
`## Gaps`, or `## Verification Plan` with exact source paths and signal names.

When multiple bounded source-defined reasons share one status or outcome and
remain operator-distinct, preserve that distinction with a bounded reason
attribute or metric dimension when it changes diagnosis or response. Derive
the allowed values from source branches, not payload text, identifiers,
exception messages, or other unbounded values. One status code by itself is not
complete outcome coverage when the repository already proves several
materially different causes.

Treat source-computed bounded business aggregates such as accepted/rejected
counts, critical/noncritical counts, or another finite classification as
recommended custom-signal candidates when they materially improve diagnosis or
a product decision. They must not become required solely because the source
computes them; use `required` only when the user request or a detector-critical
correctness requirement explicitly makes that signal mandatory. Do not propose
an aggregate merely because it can be computed; cite the owning source branch
and the chart, detector, filter, or group-by it would enable.

**OTel finding boundary** -- a canonical finding is eligible only when closing
it necessarily changes or proves at least one OpenTelemetry concern: span,
metric, or log emission; trace/log correlation or context propagation;
semantic attributes or cardinality safety; SDK, auto-instrumentation, provider,
exporter, resource, propagation, or OTLP log-pipeline configuration; or an
executable telemetry-specific proof gap. Project every candidate onto telemetry
only: `title`, `area`, `gap`, `product_outcome`, `required_fix`,
`acceptance_criteria`, `expected_telemetry`, mapped verification scenarios, and
`follow_up_actions` must describe one coherent OTel deficiency, change, product
use, and proof path. Remove every general operational clause and confirm that an
independently useful OTel closure still remains. If no OTel-specific closure
remains, omit the finding. Keep non-telemetry facts only in `evidence`,
`constraints`, or operator-impact prose under the narrow exception below.

API/OpenAPI contract accuracy, documentation, runbook or ownership links,
product limits and rejection policy, retry/timeout/cache/fallback behavior,
liveness/readiness semantics, deployment policy, and general CI or test hygiene
must not become OTel findings merely because telemetry could observe them. Do
not relabel those outputs as `configuration` expected telemetry. When a concern
mixes telemetry with behavior, policy, documentation, contract, or
general test work, split it: keep only the OTel change and telemetry proof in the
finding. Retain a non-telemetry fact only inside evidence or constraints for a
kept OTel finding when it directly proves the current behavior being observed
or prevents instrumentation from changing that behavior. Omit unrelated
contract, documentation, link, policy, security, or product debt from every
audit section, including summary, top-level evidence, readiness, anti-patterns,
recommendations, findings, and scenarios. Use `manual decision` only when a
telemetry-specific prerequisite blocks an otherwise valid OTel finding; it is
not an escape hatch for general operational work.

Resolve source evidence before assigning that mode. When the repository and
its configuration prove one safe, reversible, app-owned OTel implementation,
the work is executable and must not become a `manual decision`: use `default`
for required work or `fix all` for broader optional work. The reviewer's choice
not to select safe work is already represented by leaving its checkbox
unchecked; do not manufacture an approve/decline decision around it. A genuine
`manual decision` exists only when two or three materially distinct,
telemetry-specific choices remain after the source scan. Record those choices
as explicit selectable `decision_options`, each with a stable `id`, concise
`label`, concrete `outcome`, and the executable finding IDs it `unlocks`.
Because the choices are mutually exclusive, their `unlocks` sets must be
pairwise disjoint; one executable finding cannot encode two different answers.

After applying the OTel boundary, validate finding relevance from the
dependency graph. Dependency direction is executable finding -> prerequisite.
Keep every coherent `default`/`fix all` OTel finding. Keep a `manual decision`
or `external follow-up` only when it is transitively required by at least one
executable finding. A decision/follow-up that merely depends on executable
work, but that no executable finding depends on, is downstream governance
rather than an instrumentation prerequisite; omit it from findings, readiness,
flow markers, scenarios, summaries, and recommendations. If a telemetry choice
genuinely blocks future app-owned work, split the choice from the
implementation: make the decision/follow-up a pure non-executable prerequisite
and make the separate executable OTel finding reference it. Never combine
"decide, then implement" in one non-executable finding. Every executable ID in
an option's `unlocks` must list that manual finding as a dependency. An option
may unlock no work, but selecting an answer never selects executable work; it
only makes the matching work eligible for an independent `Select` choice.

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
Record only telemetry-scoped readiness surfaces in this table. A `partial` or
`missing` row is telemetry-scoped only when `required_signals` names an OTel
signal, OTel pipeline/configuration outcome, or telemetry-specific proof admitted
by the OTel finding boundary. Record every such owned surface in the single
prioritized `## Gaps` table. The prioritized gap row and its mapped acceptance
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
- `Gap` is one concise, plain-language sentence that states only the missing or
  incorrect condition. It must be understandable without reading evidence. Do
  not use it to inventory competing classes, providers, exporters, or source
  candidates; keep topology and implementation detail in evidence, consequences
  in `Why it matters`, and the solution or owner choice in `Required fix`.
- `Required fix` names every required signal or exact owner mapping; it must not
  use a vague label such as `add observability`.
- `Instrument mode` records whether safe app-owned work is `default`, broader
  safe work is `fix all`, an unresolved telemetry-specific choice is `manual
  decision`, or externally owned telemetry work is `external follow-up`.
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
`## GenAI Readiness` rows, prioritized gaps, and acceptance scenarios
consistent. Do not load the audit-specific reference for non-GenAI services.

**Deterministic gap section contract** -- the audit report has exactly one
top-level gap section, named `## Gaps`. Record GenAI detail in
`## GenAI Readiness` table rows and add concise `## Gaps` references that point
back to the human-readable readiness surface name.

Populate canonical `findings` so `render-markdown` can project the single
prioritized `## Gaps` table; do not hand-author its layout. Use only `required`,
`recommended`, or `deferred` priorities and only `default`, `fix all`, `manual
decision`, or `external follow-up` instrument modes. Put baseline correctness, trace continuity, error
attribution, exporter/resource identity, cardinality safety, and duplicate
signal ownership in `required`. Put safe deeper diagnostics, business metrics,
and opt-in log export in `recommended` unless the request already makes them
mandatory. Use `deferred` only for a concrete external telemetry owner,
telemetry-specific prerequisite, or OTel decision. Use `manual decision` only
for an exact OTel signal, SDK/provider/exporter/resource/propagation, sampling,
cardinality, or telemetry-privacy choice with two or three source-supported
options. When source evidence leaves one safe, reversible implementation, use
`default` or `fix all` instead. Use `external follow-up` only when a
known external owner must supply an exact OTel signal, pipeline configuration,
or telemetry proof required by an executable finding. Owner discovery or an
independent downstream platform decision is evidence, not a finding. Apply these classifications
only after the OTel finding boundary; ownership and safety do not make general
operational work eligible. Every row must explain user/operator impact, state a specific fix,
and cite the verification scenario IDs that can prove closure. Group related
routes and call sites by remediation theme instead of producing a row per edge.
When a default GenAI gap involves duplicate or overlapping instrumentation,
name the intended canonical owner per logical operation and the pre-bootstrap
suppression surface in `Required fix`. If source evidence cannot support that
choice, use `manual decision`; do not hand `$otel-instrument` an unresolved
"select one canonical source" instruction in a `default` row.

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
- Use of an unmaintained third-party wrapper outside official OpenTelemetry
  distributions when a supported official package exists. Official
  `go.opentelemetry.io/contrib`, `@opentelemetry/*`, and `opentelemetry-*`
  distributions are not evidence of this anti-pattern.

Do not repeat an anti-pattern when the same condition is already represented
by an actionable finding. The finding card owns its gap, impact, remediation,
selection, and proof path. Keep `anti_patterns` only for distinct OTel-scoped
compatibility or provenance context that does not create another action. The
canonical JSON and compatibility Markdown preserve those authored notes; the
decision-focused HTML never renders a separate Anti-Patterns subsection.

For partially instrumented Go services, explicitly check and report:

- hardcoded OTLP endpoints such as `collector.example.com`
- `otel.Tracer(...)` or `otel.Meter(...)` calls inside request handlers or loops
- high-cardinality span names such as `GetTask-{id}`
- missing `otel.SetTextMapPropagator(...)`
- missing `MeterProvider`, missing `service.name`, and missing provider shutdown/flush

### Source-to-Report Reconciliation Gate

This terminal pre-report gate runs immediately before writing the canonical
audit. Reconcile the final inventory, findings, readiness rows, and verification
scenarios against the inspected source. This is the last source-analysis step,
not a runtime check. Confirm all of the following:

- Reconcile the process entrypoint and runtime configuration when one exists. A
  cited file without its role is not a reconciled process inventory.
- Reconcile messaging direction, topic, group, and commit-or-ack behavior,
  including produced versus consumed, queue identity, send results, and errors.
- Reconcile silent branches and bounded source-defined outcomes that change
  operator diagnosis, including distinct reasons that share one status/outcome
  and source-computed bounded aggregates under the priority rules above.
- Reconcile dependency instrumentation coverage against the loaded language map
  and manifest: name the supported instrumentation that is present, or cite
  manifest evidence that matching instrumentation is absent. Do not report a
  generic dependency gap without this package-level proof.
- Every final finding can be traced back to inspected source evidence and every
  inspected source fact used to justify a finding survives into the canonical
  JSON. Remove stale candidates, guessed symbols, and report claims that the
  final evidence ledger no longer supports.

Do not proceed to Step 3 until this gate is complete. If reconciliation exposes
missing source evidence, inspect only the cited files needed to resolve it and
rerun the gate; do not restart broad repository discovery.

### Step 3 -- Report

Write three audit artifacts inside the scanned service root (create the
`.observe/` directory if it does not exist):

- `.observe/otel-audit.json` -- canonical machine-readable audit source.
- `.observe/otel.html` -- self-contained human review report generated from the
  JSON. This is the normal human interaction surface for expanding and
  selecting finding IDs. Keep it audit-only; never render instrumentation
  or verification overlays into this file.
- `.observe/otel.md` -- backward-compatible reader summary and handoff report
  generated from the same JSON for legacy readers.

Use `.observe/otel-audit.json` as the source of truth for stable finding IDs,
selection, and downstream tool handoff. Do not require humans to read or edit
the JSON directly; generate `.observe/otel.html` from it.

In HTML, put selectable findings immediately after the concise decision
summary. Do not render the component map, connection lanes, component-coverage
groups, raw flow map, full current-state inventory, or a duplicate all-findings
decision table. Keep `signal_flow` in canonical JSON and generated Markdown for
machine and compatibility use. Reserve one collapsed technical appendix at the
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

Put exact expected telemetry with configuration scope, evidence, acceptance
criteria, and authored constraints behind one collapsed `Technical details`
disclosure. Label constraints `Implementation guardrails`, and summarize the
disclosure with acceptance-check, guardrail, and source-reference counts. Do
not render raw verification-scenario IDs, OTel concern taxonomy, repeated full
scope classification, canonical `follow_up_actions`, resolution metadata, or
a second dependency list in finding HTML. Those fields remain in canonical
JSON for `$otel-instrument` and `$otel-verify`; Markdown remains the complete
compatibility view. Put post-instrumentation product actions in
`.observe/otel-instrumentation.html`, not in the audit finding card. Keep a
manual decision's owner and question in its decision control and `Next step`;
keep an external prerequisite's owner and required telemetry in its primary
action and `Next step`.

Keep the HTML complete and usable on its own. It may link to the sibling
`.observe/otel.md` compatibility view and canonical JSON as optional alternate
formats, but must not require the reviewer to open Markdown to understand or
select a finding.

Write the human summary as a decision brief, not a compressed defect list. In
generated Markdown and chat summaries, use 3-7 plain-language bullets and state counts by
`required`/`recommended`/`deferred`, what source or configuration currently
shows, the safe app-owned work that can be selected now, the owner decisions
that must be answered, and what can wait. Do not present canonical
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

In the HTML decision view, do not render standalone priority or quick-win
summary cards. Group actions by priority in this order: `required`,
`recommended`, then `deferred`. Within each priority group, show the applicable
action tag that actually applies: `Fix now`, `Decide now`, `Consider next`,
`Decide first`, `Resolve prerequisite first`, `Consider later`, or `Track external
follow-up` -- with its finding count. Show executable progress separately from
open decisions, blocked work, and external follow-ups in the priority heading.
Reserve `Decide now`, `Decide first`, and `Track external follow-up` for
validated prerequisites that block at least one executable finding; orphan
non-executable findings are invalid canonical input and must never reach HTML.
Keep quick-win information as the finding's effort tag
because it overlaps priority rather than forming another executive total. Do
not render Priority, Effort, or Status filter facets: they repeat information
already visible in the priority-first action groups and finding tags. Show a
compact `Findings · N` heading immediately above the cards instead.

In HTML queues, lead with the human title or area, show its one-sentence
expected monitoring outcome, and show
the stable `OTEL-###` ID only as a secondary reference. Do not replace stable
IDs with display-order labels such as `gap-1`; IDs must remain deterministic
across selection, instrumentation, verification, and configuration handoffs.
Keep `severity` in canonical JSON for machine compatibility, but do not render
it as a second human ranking system. Use priority/action, effort, and the impact
narrative for owner decisions.

On each finding card, render exactly one highlighted action tag derived from
priority, instrument mode, and unresolved prerequisites: `Fix now`, `Decide
now`, `Consider next`, `Decide first`, `Resolve prerequisite first`, `Consider
later`, or `Track external follow-up`. Do not repeat priority or instrument mode as separate
tags. Render concrete effort only as `small effort`, `medium effort`, or `large
effort`; omit the schema's `decision` effort because the action tag already
communicates that state. Omit the baseline `proposed` lifecycle tag and show
lifecycle only after it changes, such as `selected`, `included`, `working`, or
`done`.

Use the instrument modes consistently in the human view:

- `default` renders as `ready to implement`: safe app-owned work that can
  enter the instrumentation handoff after the reviewer selects it.
- `fix all` renders as `optional`: safe broader work that remains opt-in.
- `manual decision` renders as `decision needed`: a named telemetry-specific
  prerequisite offers two or three explicit answers and blocks separate
  executable findings until one answer is selected. The manual finding remains
  visible but its ID cannot enter instrumentation scope.
- `external follow-up` renders as `external follow-up`: a known owner outside
  the service must supply an exact prerequisite needed by a separate executable
  finding. It remains visible as `Track external follow-up` but cannot enter
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
and requirements in canonical JSON and compatibility Markdown. In HTML, keep
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
      "otel_concerns": ["signal-emission", "semantic-attributes"],
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
      "follow_up_actions": ["Verify the span in ObStudio before merge."]
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

Set schema-v2 canonical `meta.status` deterministically from the source audit:
`Pass` only when the scan completed with zero findings, `Partial` when a completed
scan produced one or more findings, and `Blocked` only when one or more
structured `scan_blockers` prevented a complete scan. Each blocker must have a
stable ID, a supported check (`manifest`, `entry-point`, `route-source`,
`runtime-startup`, `dependency-scan`, `genai-ownership`, or `source-scan`),
nonempty blocked scope, prerequisite, evidence, and required action. Blockers
are invalid on `Pass` or `Partial`. `Pass` means no source-visible gaps and no
unresolved partial/missing readiness rows; it does not claim runtime
verification. Never use `Fail` for an audit.
Frozen schema-v1 inputs may retain legacy `Blocked` status without structured
blockers. Preserve their normalization and digest; regenerate as v2 before
depending on blocker detail or gate policy.

JSON requirements:

- Write new audits as schema v2. Schema v1 remains a frozen read-only legacy
  input so existing selection digests stay valid. Do not infer v2 concerns,
  ownership fields, or scan blockers into v1. Preserve optional concerns and
  decision/external ownership already authored by a transitional v1 producer,
  including concern order. Upgrading a v1 audit requires authored concern
  classifications, human review, and regeneration of downstream overlays.
  A selection without answers remains schema v1; a selection carrying
  `decision_answers` is schema v2. Instrumentation, verification, scope, and
  gate overlays remain schema v1. Every overlay binds either audit version by
  its version-specific digest.
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
- Classify every finding with one or more `otel_concerns`: `signal-emission`,
  `context-propagation`, `trace-log-correlation`, `semantic-attributes`,
  `cardinality-safety`, `otel-configuration`, or `telemetry-proof`. The
  validator cross-checks configuration, signal type, attributes, and proof
  structure against this declaration and normalizes the list in that canonical
  order; it is not a label for general work. The validator also rejects
  action/object clauses for API contracts, documentation/runbooks, general
  CI/tests, product behavior/policy, ownership administration, and non-OTel
  service configuration in closure-driving fields. Put a directly relevant
  non-telemetry fact only in `evidence`, `constraints`, or operator-impact
  prose; never add a decoy signal to admit general work.
- Every finding must include human impact, one concise `product_outcome`,
  required fix, evidence, acceptance criteria, expected telemetry with its
  Splunk/ObStudio `product_view`, and at least one follow-up action. The outcome
  states what the owner should see or gain after implementation and
  verification without claiming it is already proven. Include verification
  scenario IDs when runnable.
- Every finding must name at least one actual OTel signal or OTel pipeline
  behavior in `expected_telemetry`. A `configuration` item may describe only
  OTel SDK, auto-instrumentation, provider, exporter, resource, propagation, or
  OTLP log-pipeline configuration. Every `configuration` item must include
  `configuration_scope` with exactly one of `otel-sdk`, `otel-resource`,
  `otel-exporter`, `otel-sampling`, `otel-propagation`,
  `otel-instrumentation`, or `otel-collector`. Configuration is insufficient by
  itself; also name the span, metric, log, or resource outcome it enables.
  Never use `configuration` for API contracts, documentation or ownership
  links, product limits, operational policy, deployment behavior, or general
  CI checks.
- Every mapped verification scenario must prove telemetry. Its
  `expected_signals` must name an OTel signal, OTel pipeline/configuration
  outcome, or telemetry-specific negative assertion. Contract lint, link
  validation, behavior-only tests, and policy approval without telemetry proof
  are not audit verification scenarios.
- Make follow-up actions telemetry-operational. They may contain only OTel
  implementation, configuration, verification, or downstream telemetry-product
  work. Every new custom metric must name the
  chart/dashboard or detector decision it enables after verification. Every
  new low-cardinality attribute or metric dimension must name the
  filter/slice/group-by it enables. Every `manual decision` finding must name
  the responsible owner and exact telemetry-specific question. Every `external
  follow-up` finding must name a known external owner and the exact OTel signal,
  pipeline configuration, or telemetry proof they must supply; owner discovery
  alone is not a finding. It must not contain independently executable service
  work. App-owned changes must
  include a deterministic local proof step before merge; use ObStudio only when
  a local explorer witness is available, and distinguish unit proof from
  explorer visibility.
- Every finding dependency must reference another finding ID and point from the
  work toward its prerequisite. Every verification scenario reference must
  exist in `verification.scenarios`.
- Keep JSON values concise. Put bulky command output under `.observe/evidence/`
  and cite it from JSON; `.observe/otel.md` is generated and must not diverge.

After writing `.observe/otel-audit.json`, validate it and generate both human
views from that single source:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate \
  .observe/otel-audit.json

python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" render-html \
  .observe/otel-audit.json \
  -o .observe/otel.html

python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" render-markdown \
  .observe/otel-audit.json \
  -o .observe/otel.md
```

`render-html` infers the source repository root when the audit is under
`.observe/` and turns exact existing repository-relative citations into local
file links. When rendering an audit from another directory, pass
`--repo-root <service-root>` explicitly; never embed an absolute host path in
the canonical JSON.

Resolve the placeholder directly from the directory containing the loaded
`otel-audit/SKILL.md`; never use a service-root or repository-root script by
name. If validation fails, repair `.observe/otel-audit.json` and rerun all
commands before presenting results.

The HTML is the human review and selection surface. Keep its empty fixed tray
`hidden` and `inert`. After a reviewer selects work or records a decision
answer, show only a compact summary -- `N in selection · R of T required
fixes`, plus an auto-added dependency count only when nonzero -- and one
primary `Save selection` action. Do not require an intermediate review panel
and do not render `Copy command` or `Copy selection JSON` controls. The cards,
summary, and polite live region must distinguish explicit selections from
auto-added dependencies.

`Save selection` serializes the authoritative bound overlay with explicit
`requested_ids`, dependency-closed `approved_ids`, and canonical
`decision_answers`, then requests a browser download named
`otel-selection.json`. A self-contained `file://` report cannot silently write
or overwrite a sibling repository file or confirm the browser's download
destination. State this limitation in the tray and tell the reviewer to place
the downloaded file at `.observe/otel-selection.json` before running
`$otel-instrument`.

The expanded finding's collapsed `Technical details` must retain every
configuration scope beside its expected telemetry item, acceptance criteria,
authored constraints labelled `Implementation guardrails`, and source
evidence. Canonical JSON retains OTel concern classifications,
verification-scenario references, full mode ownership and requirements,
follow-up actions, dependencies, and resolution metadata for downstream
skills. The Markdown fallback exposes those enforcement fields in `### OTel
Closure Details`. For frozen schema-v1 reports, render `Legacy v1 —
unclassified` in Markdown without inventing concerns in normalized JSON.

The downloaded JSON must be saved as `.observe/otel-selection.json` before
instrumentation. It records explicit requests, executable dependency closure,
and `decision_answers`.
`decision_answers` is separate from `requested_ids` and `approved_ids`: it is
a canonical-audit-order list of `finding_id`/`option_id` entries and never
contains executable scope. Preserve the machine schema names `requested_ids` and
`approved_ids` for compatibility, but do not present `approved_ids` as human
approval: it is the dependency-closed executable selection. A manual
decision ID and an external follow-up ID can never appear in either executable
ID list. Reject unanswered decision dependencies, answers not authored by the
audit, and requested or approved executable work not listed in the chosen
option's `unlocks`. A valid answer only unlocks matching executable work; it
never selects that work automatically. Persist an answer even when its option
unlocks no work, without inventing requested or approved IDs. Announce
automatic dependency changes and save/download feedback through an
`aria-live="polite"`, `aria-atomic="true"` status region. Never hand-edit
generated HTML. When the user provides
IDs in the same request, create and validate the bound selection with:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" select \
  .observe/otel-audit.json \
  --ids OTEL-001,OTEL-004 \
  -o .observe/otel-selection.json \
  --scoped-out .observe/tmp/otel-selected-findings.json
```

The tool validates IDs, binds the selection to the audit ID and SHA-256 digest,
auto-includes dependencies in audit order, and produces the compact scope that
`$otel-instrument` consumes. Do not edit code until the owner has selected executable IDs.

For CI/MR use, generate the audit first and then apply an explicit policy:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" gate \
  .observe/otel-audit.json \
  --fail-on required \
  --output .observe/tmp/otel-audit-gate.json
```

Schema or reference errors exit `1`; unresolved findings matching the selected
policy exit `2`; a structurally valid schema-v2 `Blocked` audit also exits `2`
for `required`, `recommended`, or `any` because its policy cannot be evaluated.
`--fail-on none` remains validation-only and reports the incomplete scan without
calling it a pass. A passing policy exits `0`. `required` blocks only unresolved
required findings, `recommended` also blocks recommended findings, `any` blocks
all unresolved priorities, and `none` validates without blocking. CI must choose
the threshold deliberately; this headless gate does not itself invoke an agent.

The `render-markdown` command owns the complete `.observe/otel.md`
compatibility schema, including headings, tables, empty states, and ordering.
Do not embed a second Markdown template in this skill. Do not hand-author or
independently update `.observe/otel.md`; render it only from validated
`.observe/otel-audit.json`.

Keep these essential input semantics in the canonical JSON:

- `meta.genai_ownership_detected` is the explicit ownership switch. Populate
  `genai_readiness` only when it is true. Human HTML and Markdown must visibly
  render authored GenAI readiness instead of leaving it only in embedded JSON.
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
  prose remain context. Do not put general operational observations in either
  canonical readiness array merely to force a finding. Render authored
  readiness tables visibly in HTML and Markdown.
- Define reusable environments in `verification.environments`; every
  `verification.scenarios[*].environments` value must reference those IDs.
- Audit scenarios and signal inventory are source-derived plans, not runtime
  proof. Keep bulky evidence outside JSON and cite its path.

`render-markdown` owns all compatibility layout. Change Markdown structure in
the shared renderer and its tests, never by embedding another template in this
skill.

After writing the report, run the dependency-free validator bundled with this
skill:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/validate_audit_report.py" \
  .observe/otel.md
```

Resolve the placeholder from the loaded skill directory, never the audited
repository.
Do not read the validator implementation before the first run; execute it and
use its actionable failures if repair is needed.
If validation fails, repair the report and rerun it before presenting results.

Treat a compatibility-validator failure as either invalid canonical input or a
renderer defect. Repair `.observe/otel-audit.json` or the shared renderer as
appropriate, rerender both human views, and never patch generated Markdown.

**Chat summary:** After writing the audit artifacts, present a brief summary in
chat that includes: the most important findings first, gap counts
by `required`, `recommended`, and `deferred`, and the recommendation line. End with:
`Review report: .observe/otel.html` and `Machine report: .observe/otel-audit.json`.

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

## Troubleshooting

**No dependency manifest found:** Ask the user which subdirectory contains the service, then re-scan from that root.

**Multiple languages detected:** Ask which service to audit, or audit each independently.
