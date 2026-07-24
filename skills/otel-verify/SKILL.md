---
name: otel-verify
description: >-
  Run deterministic verification for existing OpenTelemetry instrumentation and
  produce a report. Use when the user types $otel-verify, asks to verify OTel
  instrumentation, prove spans/metrics/logs are emitted, run observability
  tests, validate .observe/otel-audit.json, consume approved finding IDs from
  --ids or .observe/otel-selection.json, check GenAI trace correctness, prove
  modified/declared spans, metrics, and logs, derive per-code-path coverage from
  an audit report, produce an instrumentation verification report, or emit local
  explorer-visible OTLP contract telemetry without starting the full app. This
  skill is read-only for application code unless the user explicitly asks to
  add or repair tests; use $otel-instrument to add new instrumentation.
---

# OTel Verify

Run deterministic checks that prove existing OpenTelemetry instrumentation
works. Prefer app-code execution with fake inputs, optionally export the same
scenarios to a local OTLP collector or Obstudio, then write
`.observe/otel-verify.md`. In canonical flow also write
`.observe/otel-verify.json` and refresh `.observe/otel-instrumentation.html`.

Before writing verification artifacts, read
`../references/report-flow-contract.md` and follow the Verification Report
Contract plus Reader-First Report Order. When `.observe/otel-audit.json` exists,
also read `./references/json-approval-handoff.md`; it owns canonical scope,
schema, digest binding, status rollup, and the HTML refresh.

Resolve every reference and script path from the directory containing this
loaded `otel-verify/SKILL.md`. `../references/<file>` is the shared sibling
under the parent skills directory; `./references/<file>` and `scripts/<file>`
are local. Never probe the service root or repository root for these paths.

## Contract

- Default output: `.observe/otel-verify.md`; in canonical flow also write
  `.observe/otel-verify.json` and refresh `.observe/otel-instrumentation.html`.
- Canonical source of truth: `.observe/otel-audit.json`, the bound
  `.observe/otel-selection.json`, and `.observe/otel-instrumentation.json`.
  Read Markdown only for reader detail. Without canonical JSON, use the direct
  user request, current source, and `.observe/otel-instrumentation.md` when it
  exists; never fabricate canonical state.
- Default mode: read-only for application code. Verification never repairs
  application code. Use `$otel-instrument` for instrumentation changes.
- Determine invocation ownership before checks. A standalone request produces
  the final reader result. An active `$otel-instrument` child stays read-only,
  writes proof, returns its repair packet, and returns control to the parent
  repair loop.
- Canonical standalone overlays use `meta.workflow_mode: standalone` and
  `meta.lifecycle: final`. A failed instrumentation child uses
  `instrumentation_child` with `lifecycle: intermediate`; only a child with no
  executed finding, scenario, or item failure is final.
- Keep failed finding `remaining` and top-level `next_steps` repair-only.
  Record an evidenced boundary separately in `stop_boundaries[]`, using one of
  `unselected_work`, `material_decision`, `new_authority`, or
  `external_prerequisite`.
- In canonical flow, verify exactly dependency-closed `approved_ids`, their
  expected telemetry and referenced scenarios, plus every bound instrumentation
  item. Bind verification to the normalized instrumentation overlay with
  `instrumentation_sha256`; matching IDs alone are not freshness proof.
- Build inventories before running checks:
  - `Signal Inventory`: every declared span, metric, log/event, and
    runtime/exporter signal in scope
  - `Added Telemetry Inventory`: every added or modified trace/span/event,
    metric, log/event, and runtime/exporter signal from
    `.observe/otel-instrumentation.md`, with source/call site and
    user/application path
  - `Acceptance Scenario Inventory`: every audit-derived user/API/runtime path with
    distinct telemetry shape
- Run a project-runtime build/import viability gate before telemetry harnesses.
  A changed instrumented module that does not compile, typecheck, or import
  cannot have its telemetry verified.
- Default signal coverage target: every span, metric, and log signal declared
  in the audit or instrumentation report, especially `Signals Changed`,
  `Current Instrumentation`, `GenAI Readiness`, changed instrumentation source
  files, and user-provided scope.
- Default path coverage target: every signal-affecting path declared or implied
  by the audit: workflow success/failure, HTTP/API route, streaming, stream
  failure, tool/MCP call, retrieval/memory, redaction, startup, shutdown,
  background job, or dependency/runtime initialization.
- Do not treat one representative trace as full verification unless the
  inventories contain only that trace's signals and paths.
- Verification must be app-code-first. Generated SDK spans, metrics, and logs
  prove export/schema contract only; they do not prove the application code
  creates telemetry.
- The report must answer these questions before diagnostic detail:
  - What telemetry or runtime behavior was added or modified?
  - Was each change tested, and did application code execute?
  - Is each change working?
  - What direct proof supports that conclusion?
  - If anything is not working or not proven, why and what is needed next?
- Answer those questions per individual added or modified OTel item in one
  authoritative table. Use one row per exact route/server span, custom span
  call site, metric, log pipeline/category, and runtime/exporter behavior.
  Do not make the reader correlate separate change and test inventories.
- Keep the full signal, path, runtime, and build inventories as working
  verification data. Publish only the detail needed to support the result,
  reproduce a failure, or identify an uncovered path. Do not force the reader
  through separate inventories that repeat the same evidence.
- Report `Partial` when meaningful proof passes but any inventoried signal or
  path remains unverified. Report `Blocked` when no meaningful proof can run
  because a concrete prerequisite is missing.
- Do not require live provider credentials, production tokens, VPN, or manual
  curl commands when deterministic tests or fakes can exercise the same signal.
- Do not install missing app dependencies globally. Use the project-managed
  runtime, a temporary project-local cache, or mark import/startup rows
  `Blocked`.
- Before running compile, import, test, harness, startup, or OTLP commands,
  read `references/project-runtime-resolution.md`, derive the project runtime
  from repo config, and use that runtime for every verification command.
- Default generated harnesses are temporary: inline scripts, files under
  `.observe/tmp/`, or language-native temp runners. Do not create permanent
  repo tests unless the user explicitly asks to add, repair, persist, or write
  tests.
- When the user explicitly asks to add, repair, persist, or write tests, enter
  test-authoring mode and read `references/app-code-test-authoring.md`.
- When a canonical audit exists or direct scope includes routes, workflows,
  jobs, startup, streaming, tools, retrieval, redaction, or error paths, read
  `references/path-scenario-coverage.md` before designing harnesses or writing
  the report.
- Read `../references/full-runtime-acceptance.md` when any claim depends on
  auto-instrumentation startup, framework-resolved route names, automatic
  metrics, duplicate automatic-span prevention, startup wiring, or
  runtime-installed OTLP logs.
- Read `references/explorer-witness.md` before claiming local explorer
  visibility.

## Workflow

### 1. Discover The Verification Inputs

#### Canonical Scope Gate

When `.observe/otel-audit.json` exists, read and follow
`./references/json-approval-handoff.md` before choosing commands. Validate the
audit, bound selection, and instrumentation overlay, including its exact
`selection_sha256`, then verify exactly the approved findings in audit order
and their referenced scenarios. Never infer all-findings scope from prose.

If canonical audit/selection exists but instrumentation JSON is absent, do not
write verification JSON or infer IDs from instrumentation Markdown. Perform
only a clearly incomplete read-only check and route the missing bound handoff
to `$otel-instrument`. When no canonical audit exists, use only the direct user
request and current instrumentation Markdown/source as scope. Do not fabricate
canonical JSON.

- Use the initial bounded file list as a size gate. When the service has at
  most 25 non-ignored files, exactly one dependency manifest, and no nested
  service root, take the direct small-repo path: inspect that list, manifest,
  entrypoint, and cited source directly, and do not run the inventory helper.
- For larger, multi-module, nested, or unclear repositories, run one successful
  invocation of
  `python3 -I "<directory-containing-loaded-SKILL.md>/scripts/inspect_otel_project.py"
  "<service-root>" --output
  "<service-root>/.observe/tmp/otel-project-inventory.json"`. Retry only to
  correct an invocation/runtime failure. Resolve the helper from this skill;
  never probe a repository-root `references/` directory.
- Use its deterministic JSON to seed manifests/languages, entrypoint/route and
  runtime candidates, startup/test surfaces, and categorized OTel hits. Hits
  are candidates, not proof of process reachability, runtime availability,
  app execution, or emission. Inspect `complete`, `warnings`, `skipped`, and
  `section_counts`; read only needed sections instead of dumping the file.
- When a section has zero truncation in a `complete: true` inventory, do not
  repeat the same repository-wide `find` or broad `rg`. Do not follow complete
  file/OTel sections with recursive `find`, `rg --files`, or repository-wide
  OTel-pattern searches. Search manually only for incomplete, skipped,
  unsupported, or truncated surfaces. Record the chosen discovery path and any
  exact helper/runtime failure.

Read canonical JSON first and Markdown only for reader detail; on the direct
path read only the instrumentation report. Reconcile all saved
commands, runtimes, source paths, and expected signals with current source.
Inspect the target entrypoint, referenced/diffed instrumentation files, provider
and exporter wiring, startup/shutdown, and signal-affecting branches.

- In canonical flow, read `.observe/otel-audit.json`, the bound
  `.observe/otel-selection.json`, and `.observe/otel-instrumentation.json`
  first. Read Markdown only for reader detail. On the direct path, read
  `.observe/otel-instrumentation.md` if it exists.
- In canonical flow, seed runtime candidates and acceptance scenarios from the
  selected audit findings and their referenced verification scenarios. Then
  seed changed-signal scenarios and prior implementation checks from the bound
  instrumentation overlay. On the direct path, seed the same information from
  the instrumentation report and current source.
- Reconcile every saved command, runtime, source path, and expected signal with
  current source and configuration. Do not blindly trust a stale command,
  deleted runtime, or renamed module.
- Identify the top-level service/runtime surface under test.
- Inspect source files referenced by the audit and changed instrumentation
  files from git diff when applicable.
- Extract expected telemetry:
  - traces/spans: exact names or patterns, parentage, attributes, status/error
    behavior, events, links
  - metrics: exact names, units, dimensions, datapoints, recording/export
    behavior
  - logs/events: body/category, severity, correlation fields, redaction, log
    exporter or bridge
  - runtime/config: service name, environment, version, exporter endpoint,
    startup/shutdown wiring
- For every signal, record whether it is added, modified, removed, or existing;
  exact source/call site; user/application path(s) expected to emit it; and
  proof needed to show the app code works.
- Build an exact operation closure row for every distinct added or modified
  span name and metric call site. Shared helper execution does not prove that
  each route, create, batch, update, delete, workflow, or tool entrypoint emits
  its exact signal name.
- If GenAI readiness is in scope, include workflow, agent, LLM call, tool
  execution, retrieval/memory, eval when present, token usage, model/provider
  attributes, duplicate-span prevention, and correct parent/child topology.
- Map every affected source module to a compile, typecheck, syntax, or import
  gate. Use changed files and handoff evidence to classify failures as
  `instrumentation-introduced`, `pre-existing`, `environment`, or `unknown`.

Create these working inventories before choosing commands:

```markdown
## Signal Inventory

| Signal type | Name/pattern | Source | Required proof | Scenario | Status |
|---|---|---|---|---|---|

## Added Telemetry Inventory

| Signal type | Added signal | Source/call site | User/application path(s) | Required attributes/dimensions/body | Required code proof |
|---|---|---|---|---|---|

## Acceptance Scenario Inventory

| Scenario id | Audit/source evidence | Trigger | Expected topology/signals | Proof plan | Status |
|---|---|---|---|---|---|
```

Use these inventories to decide how many tests, traces, metrics, and log checks
are needed. One happy path is not enough when the inventory contains error
metrics, timeout metrics, empty retrieval, log redaction, alternate runtime
paths, or distinct user/application workflows.

### 2. Find Existing Verification Commands

Prefer focused existing checks over broad suites. Search for:

- tests mentioning OTel, telemetry, traces, spans, metrics, logs, GenAI,
  instrumentation, redaction, startup, or workflows
- Makefile/package scripts such as `test`, `verify`, `otel`, `telemetry`,
  `smoke`, or `integration`
- in-memory exporters, fake tracers/meters/loggers, test HTTP clients, fake
  model/provider clients, synthetic framework events, and MCP/tool tests
- startup code that installs tracer, meter, logger providers and OTLP exporters
- existing seams that can call telemetry helpers without live providers or full
  service startup

Map existing tests to inventory rows. Do not mark untested paths covered just
because the same span or metric name appears in another test.

Prefer this proof order for each signal and path:

1. Existing repo test or integration smoke that executes app code and asserts
   telemetry.
2. New or repaired repo-native unit/integration test, only in test-authoring
   mode.
3. Temporary app-code harness that executes the instrumented call site with
   fakes and asserts telemetry.
4. Temporary app-code harness with OTLP export from the same scenario.
5. Generated SDK contract trace, metric, or log only when app code cannot run;
   label it contract-only.

### 3. Resolve The Project Test Runtime

Do not assume the shell's default interpreter has the app dependencies.

Read `references/project-runtime-resolution.md` before selecting commands.
Create this working table and keep it updated as commands run:

```markdown
## Runtime Candidate Inventory

| Surface | Config evidence | Selected runner/env | Probe command | Outcome | Fallback/impact |
|---|---|---|---|---|---|
```

Rules:

- Prefer repository wrappers, lockfiles, toolchain files, devcontainer/CI
  commands, and language version config over global shell defaults.
- Validate the selected runtime with a version/probe command before running
  verification. For example, confirm the actual Java, Node, Python, Go, .NET,
  Rust, Ruby, or PHP version that will execute the tests.
- If a global/default runtime fails but project config indicates a different
  runtime, retry with the project runtime before marking app code failed.
  Record the default failure as a rejected runtime candidate, not as the
  application result.
- If a focused multi-module test filter fails because upstream modules have no
  matching tests, use the framework's no-match guard only for the reactor
  mechanics, then verify that the target test report exists and ran the
  expected tests.
- If restore/import is blocked by private registry credentials, network
  policy, missing toolchain, or platform mismatch, mark affected rows
  `Blocked` with the exact prerequisite. Do not call them `Source only`.
- Do not edit dependency manifests, refresh lockfiles, or add permanent test
  dependencies unless the user explicitly asks.

Runtime examples:

- Python: `.venv/bin/python`, `uv run --locked python`, `poetry run`,
  `pdm run`, `pipenv run`, `hatch run`, `tox`, or `nox`.
- Node/TypeScript: `pnpm exec`, `yarn`, `npm exec`, `bun`, with locked install
  only when needed for tests.
- Go: `go test` or `go run` in the relevant module.
- Java/Kotlin: `./mvnw` or `./gradlew` with focused filters.
- .NET/Rust/Ruby/PHP: `dotnet test`, `cargo test`, `bundle exec`, or
  `composer exec`.

The report's `Runtime Dependency Resolution` section must identify the config
evidence, selected runner, rejected runtime candidates, restore/import commands,
missing packages/modules, registry/toolchain prerequisites, and impacted rows.

### 4. Run The Build/Import Viability Gate

Before creating telemetry harnesses or starting services, prove that the
changed instrumentation can load under the selected project runtime.

Build an impact table:

```markdown
| Affected module/surface | Changed files | Gate command | Result | Failure ownership | Impacted scenarios |
|---|---|---|---|---|---|
```

Rules:

- Run static integrity checks for changed scripts/config and
  `git diff --check` when Git is available.
- Compile, typecheck, syntax-check, or import every module containing changed
  instrumentation. Use the narrowest project-native command that still loads
  the changed code and its generated sources/annotation processors.
- Use the selected runtime from Step 3 for every gate. A failure under a
  rejected global runtime is not an application failure.
- If `.observe/otel-instrumentation.md` records a passing gate, rerun it when
  practical; otherwise treat it as prior evidence, not current proof.
- Classify a failure on a changed line or changed API contract as
  `instrumentation-introduced` unless evidence proves otherwise. Classify
  missing configured runtimes, declared dependencies, private registries, or
  credentials as `environment`. Use `pre-existing` or `unknown` only with
  concrete evidence. An unchanged selected OTel wiring defect is
  `pre-existing`, not `instrumentation-introduced`.
- Verification remains read-only for application code. For an
  instrumentation-introduced failure, mark affected signal/path rows
  `Blocked`, set the overall result to `Fail`, name `$otel-instrument` as the
  repair path, and do not attempt expensive runtime/OTLP harnesses that depend
  on the broken module.
- An unavailable prerequisite produces `Blocked` rows and an overall `Partial`
  when meaningful proof passed. Use an overall `Blocked` result when no
  meaningful proof can run. Use `Fail` only when a scenario ran and its
  expected telemetry was absent or invalid.
- Continue with unaffected modules and scenarios when their runtime surface is
  independent.

### 5. Run Signal Verification

Run the smallest set of commands that proves the inventories. If a live app,
network, Docker, credentials, or long-running service is required, first look
for an offline unit/integration alternative.

#### Conditional Full Runtime Acceptance

When full runtime is triggered, read and execute
`../references/full-runtime-acceptance.md` after viability and focused tests.
Use the audit proof level and safe fixture to exercise the actual process and
complete scenario matrix. Before any listener-dependent receiver/harness, run
its one-shot `scripts/probe_loopback_bind.py` preflight. A blocked result stops
listener work; an available result only permits the real gate. Keep exact
unavailable prerequisites and unobserved outcomes rather than weakening proof.

When `../references/full-runtime-acceptance.md` is triggered, execute that gate
after build/import viability and focused tests. Do not defer it merely because
a synthetic-root or direct call-site harness exists. Use the audit's
`Proof Level` and local-safe fixture column to start the actual process and
exercise the complete runtime-required route/scenario matrix. If no safe local
profile exists, document the exact missing prerequisite and keep those rows
`Partial`, `Blocked`, or `Not proven`.

Use the same selected project runtime for temporary harnesses that you used for
compile/import checks. Do not compile a harness with a global classpath,
interpreter, package manager, or SDK when the project has a configured wrapper
or toolchain.

Coverage rules:

- A row is app-verified only when app code ran through an existing test, newly
  authored repo test, temporary app-code harness, or live smoke.
- Spans are verified only when name/pattern, required attributes, status/error
  behavior, and parent/child topology when relevant are asserted or observed.
- Metrics are verified only when a datapoint is observed or asserted for each
  expected metric name, unit, instrument type, and required complete dimension
  set. A source definition is not emission proof. Reject unexpected transient
  outcome/error dimensions as well as missing required dimensions.
- Logs are verified only when a log record is observed or asserted with
  expected body/category, severity, trace/span correlation when required, and
  redaction.
- Trace topology is verified only when expected parent -> child edges, links,
  or span depth are asserted or visible in collector/Obstudio evidence. Span
  presence alone is not DAG proof.
- Path coverage is verified only when the scenario trigger ran or was
  faithfully synthesized, expected topology/signals were asserted, and
  collector/Obstudio evidence was captured when OTLP is available.
- Runtime-only rows are verified only by the real process with its actual
  agent, preload, middleware, or startup bootstrap. A synthetic owning root or
  direct handler call cannot prove automatic server span count, kind, route
  name, automatic metric emission, or duplicate suppression.
- If the audit names multiple telemetry-distinct outcomes for one workflow,
  such as success, failure, interrupt, empty, unavailable, retry, fallback, or
  timeout, treat each as a separate path scenario unless source inspection
  proves identical telemetry.

Use this status vocabulary:

- `Verified: unit`: deterministic app-code assertion or in-memory exporter
  proof, not exported to a collector.
- `Verified: OTLP`: collector or Obstudio evidence from a real SDK exporter.
- `Verified: unit+OTLP`: deterministic assertions and collector/Obstudio
  evidence from the same focused scenario when possible.
- `Verified: app test`: committed or newly authored repo-native test executes
  app code and asserts telemetry. Use `Verified: app test+OTLP` when paired
  with local OTLP proof.
- `Source only`: source definition found but no emission was observed or
  asserted. Do not use this for declared dependencies that cannot be resolved.
- `Not emitted`: scenario ran but expected telemetry did not appear.
- `Not run`: scenario was not executed.
- `Blocked`: verification could not be attempted due to a concrete local
  prerequisite, including unresolved declared dependencies.
- `Not configured`: the requested signal has no implementation or runtime
  configuration, such as an absent OTLP log bridge/exporter.
- `Not applicable`: audit confirms no signal of that type was added or
  modified.

When a row is not fully verified, include one concrete reason: missing harness,
requires full app startup, live provider, credentials, unsafe side effect,
undriven error/timeout/stream/shutdown path, no log exporter, collector eviction,
source-only definition, missing metric datapoint, missing span attributes or
parentage, or missing log severity/body/correlation/redaction.

### 6. Prefer Unit+OTLP Contract Harnesses

When Obstudio, a local collector, or an explicit OTLP endpoint is available,
try to upgrade deterministic unit/integration proof to `Verified: unit+OTLP`
for every language and framework.

Follow `references/explorer-witness.md`: keep the source alive through exact
queries, save sanitized query responses before shutdown, and report live
visibility separately from post-exit persistence. Expected local eviction is
not an instrumentation failure.

- Configure real SDK tracer, meter, and logger providers before importing app
  modules that cache OTel globals.
- Export from the same focused fake-input scenario that performs assertions.
- Prefer one trace per path scenario. Use stable attributes such as
  `verification.scenario`, `verification.path`,
  `verification.audit_source`, and `verification.coverage_kind`.
- Use local/test-only endpoints such as HTTP `127.0.0.1:4318` or gRPC
  `127.0.0.1:4317`. Never export verification telemetry to production.
- Verify the effective endpoint, protocol, and path separately for traces,
  metrics, and logs. If one signal fails, test the configured exporter against
  the matching receiver: gRPC commonly uses `4317`; HTTP/protobuf commonly
  uses `4318/v1/<signal>`. Do not treat successful traces as evidence that the
  metrics exporter is valid.
- Assert effective resource attributes from collector data, including
  `service.name`, environment, and version. Source-level merge logic alone does
  not prove operator-provided values survive provider construction.
- For HTTP auto-instrumentation, assert the exact emitted request-duration
  metric and route dimensions. If stable semantic conventions were requested,
  require `http.server.request.duration`; an alternate metric in source or a unit
  fake does not satisfy that runtime row.
- Keep an Obstudio contract process alive until trace, metric, and log queries
  complete; some local explorers evict telemetry for short-lived sources.
- Mark `Verified: unit+OTLP` only when assertions and collector/Obstudio
  evidence both pass. If assertions pass but export is unavailable, use
  `Verified: unit`.

Run Obstudio validation when the user requests it, but classify each finding
before using it as an application result:

- `actionable`: emitted telemetry violates the selected convention or expected
  contract; repair or report it.
- `registry mismatch`: the validator's core Weaver registry marks GenAI/MCP
  fields as moved to a dedicated registry, rejects application-owned custom
  metrics/attributes, or rejects framework-owned attributes such as
  `asgi.event.type`. Record this separately and do not call the application
  failed solely from the raw red/violation count.
- `library-owned compatibility`: official auto-instrumentation emits a shape
  the validator interprets differently, such as omitting `server.port` for a
  default HTTPS port. Record the package/version and affected signal; do not
  rewrite unrelated app telemetry merely to silence the finding.
- `stale`: telemetry arrived during validation because a periodic exporter was
  still running. Save the run id and evidence snapshot; freshness churn is not
  signal failure.

Report the raw validator summary, the classification, and the count of
actionable application findings. Never hide findings, and never equate a large
unclassified advisory count with verification status.

Emit a nested temporary harness when topology is necessary and the real path
cannot run. Topology is necessary when the audit or user scope includes
workflow/agent/tool/retrieval/memory traces, GenAI flow graph, LangGraph,
Temporal, queues/jobs, async handoff, MCP tool execution, streaming lifecycle,
parent/child shape, duplicate-span prevention, or an explorer DAG.

Nested topology harness rules:

- Derive expected edges from the inventories, for example
  `workflow -> agent -> llm.call`, `agent -> tool`, `tool -> mcp`, or
  `stream -> send_failed event`.
- Prefer real instrumented call sites. If imports are blocked, use a generated
  temporary SDK contract with the same nesting and label it
  `generated temporary nested SDK contract`.
- Keep child spans active inside the parent span context. Do not create all
  spans as siblings under a synthetic root unless topology is out of scope.
- For async or queue boundaries, use parent/child when context propagates
  synchronously or span links when the architecture expects links.
- Assert topology after export by querying parent span ids, links, span depth,
  or Obstudio flow nodes/edges when available.

### 7. Author App-Code Tests When Requested

Enter this mode only when the user explicitly asks to add, repair, persist, or
write unit/integration tests. Follow
`references/app-code-test-authoring.md`.

Rules:

- Use the repo's existing test framework, fixtures, naming, and fake patterns.
- Add focused tests near the instrumented code's existing test area.
- Install OTel test providers before importing modules that cache tracers,
  meters, or loggers.
- Execute the real app function, route handler, middleware, workflow method,
  adapter, startup hook, job, or service runner with fake dependencies.
- Assert span names, parentage, required attributes, status/events, metric
  datapoints, log records, correlation, and redaction.
- Run the focused tests and include their paths and results in
  `.observe/otel-verify.md`.
- If dependency or fixture support is missing, report the smallest required
  seam instead of faking away the behavior in a misleading test.

### 8. Produce Verification Artifacts

In canonical flow, write `.observe/otel-verify.json` using
`./references/json-approval-handoff.md`. Preserve exact selected finding,
scenario, and instrumentation-item order; bind it to the exact normalized
instrumentation digest; validate the flow; and refresh
`.observe/otel-instrumentation.html`. Leave `.observe/otel.html` as the audit
and scope surface. In direct flow, write no canonical JSON.

## Reader Report

Write this order:

```markdown
# OTel Verification Report: <service>

**Result:** Pass | Fail | Partial | Blocked | Not run
**Bottom line:** <one plain-language sentence saying what works and what does not>
**Source audit:** `.observe/otel-audit.json` | direct user scope
**Approved selection:** `.observe/otel-selection.json` | direct scope
**Source instrumentation:** `.observe/otel-instrumentation.json` | `.observe/otel-instrumentation.md` direct | not found

## What Changed

| Area | Added or modified | Status |
|---|---|---|

## Tested And Working

**Individual result:** <working>/<total> working: <counts by signal type>.

Read this table left to right as: what was added, whether it works, how it was
tested, and the proof.

| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|

## Not Working Or Not Proven

| Item | State | Why | What is needed next |
|---|---|---|---|

Use `None` when every in-scope item is proven. Use `Not working` only when an
executed check failed. Use `Not proven` when a scenario was not run or a
prerequisite was unavailable.

## Proof

| Proof type | What it proves | Evidence |
|---|---|---|

## Technical Details

### Commands Run

| Command | Result | Evidence |
|---|---|---|

### Coverage And Diagnostics

<Include only the runtime, build, signal, path, topology, and explorer rows
needed to substantiate the result or explain gaps.>
```

Report requirements:

- Follow `../references/report-flow-contract.md`. The first screen must let a
  reader answer what changed, whether it was tested, whether it works, what
  proves it, and why anything remains unproven.
- Keep `Bottom line` to one sentence. Do not use coverage counts alone as the
  bottom line.
- In `What Changed`, group related signals by behavior or component instead of
  listing every span in prose.
- In `Tested And Working`, include every individual item from the reconciled
  Added Telemetry Inventory. Do not group independently instrumented or tested
  route spans, operation call sites, metrics, logs, or exporters into one row.
  When the same span name is emitted by multiple modified call sites, identify
  the call site in `OTel item` and give each call site its own row.
- Put `Individual result: <working>/<total> working` immediately above the
  table, followed by counts by signal type. Derive the counts from the table.
- Use only `Working`, `Not working`, `Not proven`, or `Not configured` in the
  `Working status` column. `Working` requires direct test or runtime evidence.
- State exactly how each item was tested: application test, actual full
  runtime, temporary app-code harness, OTLP query, or static configuration
  validation. Do not write only `tested`, `verified`, or a suite name.
- Put a direct file path, report, assertion, or saved collector response in
  every `Evidence` cell. Source code presence alone is not evidence that an
  OTel item works.
- Repeat non-working, unproven, and unconfigured rows under
  `Not Working Or Not Proven` with the reason and next action. Write `None`
  there only when every per-OTel row is `Working`.
- In `Proof`, explain the strength of evidence in plain language. Distinguish
  application tests, temporary app-code harnesses, OTLP collector acceptance,
  and source/config checks. Never present source presence as runtime proof.
- Put commands, runtime selection, trace IDs, full path matrices, signal
  inventories, and topology diagnostics under `Technical Details`. Omit
  diagnostic tables that merely repeat evidence already shown above.
- Use exact signal names and source/test paths.
- Do not claim a signal is verified unless command output, test assertion, or
  collector/Obstudio evidence proves it.
- If only fake/in-memory telemetry was used, say it is not explorer-visible.
- If any inventory row is unverified, set `Result: Partial`, `Blocked`, or
  `Fail`.
- Set `Result: Fail` when project-configured source viability fails because of
  instrumentation changes, or when an executed scenario omits or violates
  expected telemetry. Use `Partial` for environmental blockers or unexecuted
  rows when meaningful proof passed and no executed assertion failed. Use
  `Blocked` when no meaningful proof can run because a concrete prerequisite
  is unavailable.
- Include runtime dependency and build/import details under `Technical Details`
  when they affect the result. A failed gate must map to every blocked signal
  and path that depends on it.
- Use only `instrumentation-introduced`, `pre-existing`, `environment`,
  `unknown`, or `not applicable` in the failure-ownership column. Include
  compiler/import locations or prerequisite evidence for every non-passing row.
- Always summarize added or modified telemetry in `What Changed` when a source
  instrumentation artifact exists or the user asks what changed.
- Preserve per-path verification in the working inventory whenever workflows,
  routes, jobs, startup, streaming, tools, retrieval, redaction, GenAI, or
  runtime paths are in scope. Publish detailed rows only for gaps, failures, or
  materially different proof.
- Generated SDK contracts may appear in evidence but must not satisfy the
  `App code proof` column.
- The reconciled working inventories are the verification source of truth.
  The report's `What Changed`, `Tested And Working`, and
  `Not Working Or Not Proven` sections are the reader-facing projection of
  those inventories.
- Include summary counts, for example:

```markdown
**Added signal coverage:** Overall 37/42; spans 8/9; metrics 29/33; logs 0/0.
**Path coverage:** 8/12 verified; 2 source-only; 2 blocked.
**Unit export coverage:** unit+OTLP 12; unit-only 3; OTLP-only 2; blocked 1.
```

If no logs/events were added or modified, include one `Not applicable` row for
logs/events. If OTLP logs were requested but no log exporter or bridge exists,
mark them `Not configured` and state the implementation required. Do not use
`Not proven` for an absent implementation.

Never expose raw trace IDs or span IDs in generated HTML. Say **the generated
trace** and name the span or signal. Preserve exact identifiers only in
canonical `trace_ids`, durable evidence, and Markdown `Technical Details`.

## Reader Validation

Escape every literal `|` inside Markdown table cells as `\|`; backticks do not
make it safe. On the direct path, first write the exact `OTel item` labels from
the reconciled Added Telemetry Inventory to
`.observe/tmp/otel-verify-expected-items.txt`, one label per line. Then always
run:

```bash
python3 -I "<directory-containing-loaded-SKILL.md>/scripts/validate_reader_report.py" \
  "<service-root>/.observe/otel-verify.md"
```

In canonical mode add all four bindings:

```text
--instrumentation-json <service-root>/.observe/otel-instrumentation.json
--verify-json <service-root>/.observe/otel-verify.json
--audit-json <service-root>/.observe/otel-audit.json
--selection-json <service-root>/.observe/otel-selection.json
```

Only on the direct path add
`--expected-items-file .observe/tmp/otel-verify-expected-items.txt`. Repair
every structural, item-coverage, status, count, projection, or gap-mirroring
error and rerun until the validator passes. Do not finalize an unvalidated
report.

For canonical flow, then follow `Validate And Render` in
`json-approval-handoff.md`. Refresh `.observe/otel-instrumentation.html`; never
write verification state into `.observe/otel.html`. The instrumentation HTML
starts with one verification-state heading and one proof-and-delivery sentence,
then each selected finding exactly once. Keep technical ledgers in JSON and
Markdown, not duplicate HTML statistic cards or proof tables.

### 9. Final Response

Mirror the reader-first report in the command response. Use these exact headings
in this exact order; do not replace them with generic headings such as
`Outcome`, `Summary`, or `Validation`:

```markdown
**Result:** Pass | Fail | Partial | Blocked | Not run
**Report:** [otel-verify.md](<absolute path>)
**Machine report:** [otel-verify.json](<absolute path>) when canonical
**Instrumentation report:** [otel-instrumentation.html](<absolute path>) when canonical
**Audit report:** [otel.html](<absolute path>) when canonical

## What Changed
## Tested And Working
**Individual result:** <working>/<total> working: <counts by signal type>.
| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|
## Not Working Or Not Proven
## Proof
```

Keep technical diagnostics out of the command response, but do not shorten it
by omitting per-OTel rows. It is the user's primary result, not merely a pointer
to the file. Always include `Tested And Working`, even when verification fails
or is partial; the `Working status` column makes mixed results explicit.
Always include `Not Working Or Not Proven`; write `None` only when every
in-scope inventory row is proven.

Name `$otel-instrument` as the repair path for instrumentation-introduced
source failures; do not imply that rerunning verification will repair
application code. In canonical flow, state the audit ID and approved IDs and
confirm unselected findings were excluded.

For demo-oriented runs, include:

`Obstudio can verify the instrumentation contract locally: it runs deterministic checks, can hold open a real OTLP contract process, and writes a report proving which OTel signals are emitted and visible.`
