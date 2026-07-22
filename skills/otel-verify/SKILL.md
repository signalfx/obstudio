---
name: otel-verify
description: >-
  Run deterministic verification for existing OpenTelemetry instrumentation and
  produce a report. Use when the user types $otel-verify, asks to verify OTel
  instrumentation, prove spans/metrics/logs are emitted, run observability
  tests, validate .observe/otel-audit.json or .observe/otel.md, consume approved
  finding IDs from --ids or .observe/otel-selection.json, check GenAI trace correctness, prove all
  modified/declared spans, metrics, and logs, derive per-code-path coverage
  from an audit report, produce an instrumentation verification report, or emit
  local explorer-visible OTLP contract telemetry without starting the full app.
  This skill is read-only for application code unless the user explicitly asks
  to add or repair tests; use $otel-instrument to add new instrumentation.
---

# OTel Verify

Run deterministic checks that prove existing OpenTelemetry instrumentation
works. Prefer app-code execution with fake inputs, optionally export the same
scenarios to a local OTLP collector or Obstudio, then write
`.observe/otel-verify.md` and, for a canonical audit flow,
`.observe/otel-verify.json`.

Before writing verification artifacts, read
`../references/report-flow-contract.md` and follow the Verification Report
Contract plus Reader-First Report Order.

## Contract

- Default outputs: `.observe/otel-verify.md` and, when canonical audit approval
  exists, `.observe/otel-verify.json`, plus a refreshed
  `.observe/otel-instrumentation.html` concise selected-finding proof view.
- Default source of truth: `.observe/otel-audit.json` plus the bound
  `.observe/otel-selection.json`, and `.observe/otel-instrumentation.json` when
  present. Markdown reports are reader projections and legacy fallbacks only.
- Default mode: read-only for application code
- Do not add instrumentation. Use `$otel-instrument` for instrumentation
  changes.
- Determine invocation ownership before running checks. A standalone
  `$otel-verify` request writes the verification artifacts and returns a
  reader-facing result. When an active `$otel-instrument` workflow invokes
  verification, `$otel-verify` remains read-only but returns control to that
  workflow after writing the artifacts; it does not turn a repairable failure
  into a terminal user handoff. In that child mode, do not enter the optional
  permanent-test-authoring or dependency-edit paths; return the required test
  or dependency repair to the parent instrumentation workflow.
- Record that ownership in canonical JSON: standalone runs use
  `meta.workflow_mode: standalone` and `meta.lifecycle: final`; child runs use
  `meta.workflow_mode: instrumentation_child`. A failed child result is
  `meta.lifecycle: intermediate`, never `final`. A post-repair child overlay is
  `final` only after no executed finding, scenario, or item is `not_working`.
- Bind canonical verification to the exact normalized instrumentation overlay
  with `instrumentation_sha256`. Recompute it after every instrumentation
  repair; matching audit and item IDs alone are not freshness proof.
- Derive the report title service identity from an existing effective
  `service.name` when proven. Otherwise use the final segment of the owning
  module/package identifier or the service directory basename. For a Go
  semantic-import suffix such as `/v2`, strip that suffix and use the preceding
  module segment; never put a full module path such as
  `example.com/org/service` in the title.
- In every Markdown table cell, escape a literal vertical bar as `\|`,
  including bars inside inline-code commands and regexes. Backticks do not make
  raw `|` safe inside a Markdown table.
- After writing the report, always run
  `python3 -I "<directory-containing-loaded-SKILL.md>/scripts/validate_reader_report.py"
  "<service-root>/.observe/otel-verify.md"`. In canonical mode add
  `--instrumentation-json <service-root>/.observe/otel-instrumentation.json`
  and `--verify-json <service-root>/.observe/otel-verify.json` so item identity,
  status, observed proof, product result, and evidence are projected from the
  authoritative overlays.
  Use `--expected-items-file` only for the legacy no-JSON fallback. Repair every
  structural, row-coverage, status, count, or gap-mirroring error and rerun until
  it passes. Do not finalize an unvalidated report.
- Build inventories before running checks:
  - `Signal Inventory`: every declared span, metric, log/event, and
    runtime/exporter signal in scope
  - `Added Telemetry Inventory`: every added or modified trace/span/event,
    metric, log/event, and runtime/exporter signal from
    `.observe/otel-instrumentation.json`, or the Markdown legacy fallback, with
    stable item ID, source/call site, product view/action, and user/application
    path
  - `Acceptance Scenario Inventory`: every audit-derived user/API/runtime path with
    distinct telemetry shape
- Run a project-runtime build/import viability gate before telemetry harnesses.
  A changed instrumented module that does not compile, typecheck, or import
  cannot have its telemetry verified.
- For a canonical flow, the signal and path coverage target is exactly the
  approved findings, their expected telemetry, and their referenced scenarios,
  plus instrumentation changes mapped to those IDs. Do not let unselected audit
  findings make the result partial. On the legacy fallback, cover every signal
  and signal-affecting path declared in the Markdown audit or instrumentation
  report.
- Do not treat one representative trace as full verification unless the
  inventories contain only that trace's signals and paths.
- Verification must be app-code-first. Generated SDK spans, metrics, and logs
  prove export/schema contract only; they do not prove the application code
  creates telemetry.
- The report must answer these questions before diagnostic detail:
  - What telemetry or runtime behavior was added or modified?
  - Was each change tested, and did application code execute?
  - Is each change working?
  - If anything is not working or not proven, why and what is needed next?
  - What direct proof supports the current conclusion?
- Answer those questions per individual added or modified OTel item in one
  authoritative table. Use one row per exact route/server span, custom span
  call site, metric, log pipeline/category, and runtime/exporter behavior.
  Do not make the reader correlate separate change and test inventories.
- In canonical mode, the stable instrumentation telemetry item IDs are the
  expected inventory. Write exactly one verification `item_results` row for
  each ID in instrumentation order and carry that ID into the reader table.
  Never let a separately authored expected-items file omit a canonical item.
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
- When `.observe/otel-audit.json` or legacy `.observe/otel.md` exists, read
  `references/path-scenario-coverage.md` before designing harnesses or writing
  the report.
- Read `../references/full-runtime-acceptance.md` when any claim depends on
  auto-instrumentation startup, framework-resolved route names, automatic
  metrics, duplicate automatic-span prevention, startup wiring, or
  runtime-installed OTLP logs.
- Read `references/explorer-witness.md` before claiming local explorer
  visibility.

Resolve every reference and script path from the directory containing the
loaded `otel-verify/SKILL.md`. Here, `../references/<file>` means the shared
sibling under the parent skills directory, while `references/<file>` and
`scripts/<file>` are local to `otel-verify`. Never probe the service root or
repository root for these paths.

## Workflow

### 1. Discover The Verification Inputs

Inspect the repo before running anything:

#### Canonical Scope Gate

When `.observe/otel-audit.json` exists, verification scope must come from the
same explicit approval used for instrumentation. Read and follow
`./references/json-approval-handoff.md` before choosing commands. Validate the
audit, selection, and instrumentation handoff; then verify exactly the approved
findings and referenced scenarios. Never infer an all-findings scope.

If a canonical instrumentation Markdown report exists without its JSON
handoff, do not infer selected finding IDs from prose. Treat it as legacy
context, clearly mark the missing machine handoff, and verify only the
audit-selected scope that can be reconciled to source. When no canonical audit
exists, retain the existing legacy Markdown and direct-user-scope workflow; do
not fabricate audit IDs or flow JSON.

- Use the initial bounded file list as a size gate. When the service has at
  most 25 non-ignored files, exactly one dependency manifest, and no nested
  service root, take the direct small-repo path: inspect that file list, the
  manifest, entrypoint, and cited source directly, and do not run the inventory
  helper. For larger, multi-module, nested, or unclear repositories, run
  `python3 -I "<directory-containing-loaded-SKILL.md>/scripts/inspect_otel_project.py"
  "<service-root>" --output
  "<service-root>/.observe/tmp/otel-project-inventory.json"` before broad
  manual searches. Resolve the command
  directly from the directory containing the loaded `otel-verify/SKILL.md`;
  do not probe a repository-root `references/` directory. On the inventory
  path, run one successful invocation; retry only to correct an invocation or runtime failure.
  Use its deterministic JSON to seed manifests/languages,
  entrypoint and route candidates, configured runtime candidates, startup/test
  surfaces, and categorized OTel source/config hits. Treat these as candidates,
  not proof of target-process reachability, runtime availability, application
  execution, or telemetry emission. Inspect `complete`, `warnings`, `skipped`,
  and `section_counts`, then read only needed JSON sections instead of dumping
  the full file. For a section whose truncation is zero in a `complete: true`
  inventory, do not repeat the same repository-wide `find` or broad `rg`; use
  focused source proof. Do not follow complete file/OTel sections with recursive
  `find`, `rg --files`, or a repository-wide OTel-pattern `rg`. The helper
  creates the output parent; do not pre-create it. Search manually for
  incomplete, skipped, unsupported, or truncated surfaces. If Python or the
  shared helper is unavailable, perform the discovery manually and record the
  exact failure. Record which discovery path was selected.

- Read canonical `.observe/otel-audit.json`, `.observe/otel-selection.json`, and
  `.observe/otel-instrumentation.json` first. Read their Markdown projections
  only for reader detail or when canonical JSON is absent.
- In the canonical flow, seed runtime candidates and scenarios from the
  approved findings' `verification_scenarios`, resolving every environment ID
  before execution. Seed changed-signal scenarios and prior checks from the
  matching instrumentation JSON finding rows. Reconcile all rows with current
  source and config; do not blindly trust a stale command, deleted runtime, or
  renamed module.
- On the legacy fallback only, seed runtime candidates and acceptance scenarios
  from `.observe/otel.md`, then seed changed-signal scenarios and prior checks
  from `.observe/otel-instrumentation.md`.
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
- For every signal, record whether it is added, modified, or existing; exact
  source/call site; user/application path(s) expected to emit it; and proof
  needed to show the app code works.
- Build an exact operation closure row for every distinct added or modified
  span name and metric call site. Shared helper execution does not prove that
  each route, create, batch, update, delete, workflow, or tool entrypoint emits
  its exact signal name.
- If `## GenAI Readiness` exists, include workflow, agent, LLM call, tool
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
- Put required auto-instrumentation artifacts in the runtime candidate
  inventory. For a Java-agent scenario, use
  `scripts/resolve_java_agent.py` as required by the project-runtime reference;
  do not turn one missing host/container path into a blocker. When it resolves,
  use its absolute path/version/hash and keep production parity separate.
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
  concrete evidence. When Git or a saved pre-instrumentation snapshot exists,
  compare the failing path with that baseline before assigning ownership; an
  unchanged selected OTel wiring defect is `pre-existing`, not
  `instrumentation-introduced`.
- Verification remains read-only for application code. For an
  instrumentation-introduced failure, mark the affected finding and telemetry
  items `not_working`, set the overall result to `Fail`, and return the exact
  repair to `$otel-instrument`. Scenarios that could not execute because the
  module failed its viability gate may remain `Blocked`; they do not turn the
  application failure into an environmental blocker. Do not attempt expensive
  runtime/OTLP harnesses that depend on the broken module.
- An unavailable prerequisite produces `Blocked` rows and an overall `Partial`
  when meaningful proof passed. Use an overall `Blocked` result when no
  meaningful proof can run. Use `Fail` when project-configured source viability
  fails because of instrumentation changes, or when a scenario ran and its
  expected telemetry was absent or invalid.
- Continue with unaffected modules and scenarios when their runtime surface is
  independent.

### 5. Run Signal Verification

Run the smallest set of commands that proves the inventories. If a live app,
network, Docker, credentials, or long-running service is required, first look
for an offline unit/integration alternative.

#### Conditional Full Runtime Acceptance

When `../references/full-runtime-acceptance.md` is triggered, execute that gate
after build/import viability and focused tests. Do not defer it merely because
a synthetic-root or direct call-site harness exists. Use the audit's
`Proof Level` and local-safe fixture column to start the actual process and
exercise the complete runtime-required route/scenario matrix. If no safe local
profile exists, document the exact missing prerequisite and keep those rows
`Partial`, `Blocked`, or `Not proven`. Before authoring a receiver or temporary
harness that needs a local listener, run the shared contract's one-shot
`scripts/probe_loopback_bind.py` preflight. A blocked result is concrete proof
to stop listener-dependent attempts; an available result is only permission to
continue with the real gate.

Use the same selected project runtime for temporary harnesses that you used for
compile/import checks. Do not compile a harness with a global classpath,
interpreter, package manager, or SDK when the project has a configured wrapper
or toolchain.

For Java, never combine a test-owned `SdkTracerProvider`/`OpenTelemetrySdk`
with the Java agent in one test JVM. Use a no-agent unit-test fork for provider
assertions and a separate agent E2E fork for automatic/runtime behavior. Pass
actual `OTEL_*` environment variables to any app-owned metric reporter that
reads `System.getenv`; `-Dotel.*` agent properties do not configure that code.

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
- Here, the actual agent is the validated artifact attached to the real
  verification process; the exact deployed-production version need not be
  known to run the check. Once attachment succeeds, remove superseded
  agent-unavailable blockers and provisioning language from `remaining` and
  `next_steps`. A later app startup/assertion failure is not an agent blocker.
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

For every scenario with `status: blocked`, record two reader-facing canonical
fields: `blocking_reason` and `unobserved_outcome`. `blocking_reason` states the
exact prerequisite failure in past or present tense and must be backed by the
scenario's command/evidence; do not write an imperative such as “provide” or
“run.” `unobserved_outcome` states the exact runtime, OTLP-delivery, or product
behavior that the blocked scenario would have proved. Omit both fields for
non-blocked scenarios. Keep remediation, when one exists, in finding
`remaining` or run-level `next_steps`; never use it as the blocker explanation.

### 6. Prefer Unit+OTLP Contract Harnesses

When Obstudio, a local collector, or an explicit OTLP endpoint is available,
read and follow `references/explorer-witness.md` before configuring the
contract harness or claiming `Verified: unit+OTLP`, explorer visibility,
resource preservation, or validation success. Use the same focused app-code
scenario for deterministic assertions and OTLP export. If assertions pass but
export or explorer evidence is unavailable, use `Verified: unit`.

For local Obstudio, hold the exact emitting process or test JVM alive through
the query and evidence save. Do not wait for Maven, Gradle, Surefire, or a test
worker to exit and then infer non-emission from an empty query; source-PID
eviction makes that a missing live witness.

Emit a nested harness when topology is necessary and the real path
cannot run. Topology is necessary when the audit or user scope includes
workflow/agent/tool/retrieval/memory traces, GenAI flow graph, LangGraph,
Temporal, queues/jobs, async handoff, MCP tool execution, streaming lifecycle,
parent/child shape, duplicate-span prevention, or an explorer DAG.
When this condition applies, read and follow the nested-topology rules in
`references/path-scenario-coverage.md`. Prefer real instrumented call sites;
label any unavoidable SDK-only fallback as contract-only rather than app-code
proof.

### 7. Author App-Code Tests When Requested

Enter this mode only when the user explicitly asks to add, repair, persist, or
write unit/integration tests. Before editing tests, read and follow
`references/app-code-test-authoring.md` for repository-native placement,
provider initialization order, app-code execution, telemetry assertions, and
report mapping. If the required dependency or fixture seam is unavailable,
report that exact prerequisite instead of weakening the proof.

### 8. Produce Verification Artifacts

For a canonical audit flow, write `.observe/otel-verify.json` first, using the
exact schema, ID coverage, scenario coverage, and status rules in
`./references/json-approval-handoff.md`.

Derive `item_results` directly from the stable instrumentation
`telemetry_changes[].id` inventory and preserve instrumentation order. Record
proof mode and visibility for both scenarios and items. `Working` requires the
mapped scenario IDs, direct evidence, observed telemetry, product validation,
an executed proof mode, and a known visibility state. Unit proof can be working
while explicitly not explorer-visible; an explorer-visible claim requires
saved Observer/query evidence.

When one unit, application, or runtime check directly and successfully observes
a telemetry change, mark that item `working`. Do not leave the item
`not_proven` merely because additional routes or lifecycle scenarios were not
exercised. Scenario and finding coverage remain independent: an item can be
working inside a `not_proven` finding. Source/config presence, a contract-only
check, or an unbounded/ambiguous absence does not satisfy this rule. The evidence
must name or assert the exact telemetry item and call site. Aggregate receiver
counts, a differently named signal, or a shared helper that never invokes the
item are context only; keep that item `not_proven` and describe it as the exact
item not directly observed, never as `Observed` or as needing “stronger proof.”

Record that judgment in the required `item_results[].direct_assertion_passed`
boolean before computing scenario or finding rollups. Set it `true` only for a
passed assertion against the exact item or call site, and then set item
`status: working`. Set it `false` for contextual, aggregate, ambiguous,
not-run, or failed evidence. For a removed telemetry item, an expected-absence
assertion is a passed direct assertion only when a bounded executed capture
shows the removed signal is absent and the intended replacement owner is
present. A working removed item must also record `removal_proof` with the exact
removed signal name, a distinct replacement signal/owner, and true
`absence_assertion_passed` and `replacement_assertion_passed` booleans. The
canonical validator rejects a `not_proven` item with
`direct_assertion_passed: true` and a `working` item with it set to `false`.

Also create or update `.observe/otel-verify.md` with this reader-first report
shape:

```markdown
# OTel Verification Report: <service>

**Result:** Pass | Fail | Partial | Blocked | Not run
**Bottom line:** <one plain-language sentence saying what works and what does not>
**Source audit:** `.observe/otel-audit.json` | `.observe/otel.md` legacy | not found
**Approved selection:** `.observe/otel-selection.json` | direct legacy scope
**Source instrumentation:** `.observe/otel-instrumentation.json` | `.observe/otel-instrumentation.md` legacy | not found

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
- Use the stable service identity rule from the top-level contract for the
  title. Escape every literal `|` inside table-cell evidence or command text as
  `\|` before running the reader-report validator.
- Keep `Bottom line` to one sentence. Do not use coverage counts alone as the
  bottom line.
- Preserve evidence provenance without turning it into a second reader-facing
  proof ladder. A scenario that ran with `app_test`, `unit`, `static`, or
  `contract_only` retains that exact `proof_mode`; never collapse it into
  `proof_mode: not_run`. Keep its positive `observed_telemetry`. The
  instrumentation HTML shows its human audit `trigger` under neutral **Coverage
  details** and marks each directly observed telemetry item **Proven**. It does
  not call a `not_proven` scenario passed merely because it contains useful
  executed evidence; render that trigger under **Focused evidence obtained**
  while keeping the scenario explicitly incomplete. It does not render
  “stronger proof required” or a per-finding checklist. State local
  delivery and target-product check scope once in the report-level status; do
  not repeat it per finding or add generic “Target product: Not checked” or
  “Executed checks: No executed check failed” lines. Use “Verification
  incomplete” on an incomplete finding and reserve “no observed failures” for
  the report-level heading. Its body
  starts with one concise verification status and then the selected-finding
  cards; do not add aggregate statistic cards, code-to-telemetry mapping
  ledgers, closure ledgers, scenario-proof tables, or item-proof tables there.
  Per-finding ratios, exact counts, commands, scenario IDs, and raw evidence
  remain in `.observe/otel-verify.json` and `.observe/otel-verify.md`.
  A blocked finding renders **Runtime verification unavailable** before
  **Coverage details**, with the exact `blocking_reason`, mapped working item
  evidence under **Already proven**, and the exact `unobserved_outcome` under
  **Still unobserved**. Do not render only a generic blocked count or raw
  trigger list.
- In `What Changed`, group related signals by behavior or component instead of
  listing every span in prose.
- In `Tested And Working`, include every individual item from the reconciled
  Added Telemetry Inventory. Do not group independently instrumented or tested
  route spans, operation call sites, metrics, logs, or exporters into one row.
  When the same span name is emitted by multiple modified call sites, identify
  the call site in `OTel item` and give each call site its own row.
- Put `Individual result: <working>/<total> working` immediately above the
  table, followed by counts by signal type. Derive the counts from the table.
- Use the stable canonical telemetry item ID in `Item ID`. Its order must match
  `.observe/otel-instrumentation.json`; use `OTel item` for the readable signal
  and call-site label.
- Use only `Working`, `Not working`, `Not proven`, or `Not configured` in the
  `Working status` column. `Working` requires direct test or runtime evidence.
- State exactly how each item was tested: application test, actual full
  runtime, temporary app-code harness, OTLP query, or static configuration
  validation. Do not write only `tested`, `verified`, or a suite name.
- In `Product result / visibility`, name the monitoring/product outcome and the
  explicit visibility state. Distinguish unit-only `not_explorer_visible`,
  local `otlp_accepted`, and saved-query `explorer_visible` evidence. Include
  the chart/dashboard or detector follow-up for a metric and the
  filter/slice/group-by follow-up for a newly added attribute or dimension.
- Reconcile that visibility with the instrumentation item's `product_view`.
  Never claim `otlp_accepted` or `explorer_visible` when it says no OTLP
  pipeline or export path exists. “No application-owned exporter was added” is
  compatible only when durable evidence proves an agent- or platform-owned
  path.
- Put a direct file path, report, assertion, or saved collector response in
  every `Evidence` cell. Source code presence alone is not evidence that an
  OTel item works.
- Repeat non-working, unproven, and unconfigured rows under
  `Not Working Or Not Proven` with the reason and next action. Write `None`
  there only when every per-OTel row is `Working`.
- For a `not_working` finding, write `remaining` as a repair-only list of the
  concrete in-scope application code/config changes `$otel-instrument` must
  make. Do not append “rerun verification,” scenario execution, proof capture,
  or product inspection as another repair action. Put the observed failure in
  failed scenario `observed_telemetry`; keep the affected confirmation scope in
  the scenario mappings and exact IDs/counts in `Technical Details`. In
  reader-facing text, state that `$otel-verify` never repairs application code:
  after `$otel-instrument` applies the change, its workflow invokes verification
  automatically only to confirm whether the repair worked. Do not tell the
  user to execute each scenario manually.
- In `Proof`, explain the strength of evidence in plain language. Distinguish
  application tests, temporary app-code harnesses, OTLP collector acceptance,
  and source/config checks. Never present source presence as runtime proof.
- Put commands, runtime selection, trace IDs, full path matrices, signal
  inventories, and topology diagnostics under `Technical Details`. Omit
  diagnostic tables that merely repeat evidence already shown above.
- Never expose raw trace IDs or span IDs in generated human-facing HTML,
  including narrative `observed_telemetry`. Say **the generated trace** and
  name the relevant span or signal; retain exact identifiers in canonical
  `trace_ids`, durable evidence, and Markdown `Technical Details` only.
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
- Always summarize added or modified telemetry in `What Changed` when
  `.observe/otel-instrumentation.md` exists or the user asks what changed.
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
- Before finishing in canonical mode, run the bundled validator against the
  instrumentation JSON so report coverage cannot be reduced by a hand-authored
  inventory:

```bash
python3 -I <otel-verify-skill-dir>/scripts/validate_reader_report.py \
  .observe/otel-verify.md \
  --instrumentation-json .observe/otel-instrumentation.json \
  --verify-json .observe/otel-verify.json
```

  Only on the legacy no-JSON fallback, write exact `OTel item` labels to
  `.observe/tmp/otel-verify-expected-items.txt` and use
  `--expected-items-file`.

  Treat a validator failure as an incomplete report. Fix missing, grouped,
  duplicate, vague, or unsupported rows before returning the result.
- For a canonical flow, follow `Validate And Render` in
  `./references/json-approval-handoff.md` after both verification artifacts
  pass their own report checks. Repair every flow error before finalizing.
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

### 9. Standalone Final Response

Use this section only when `$otel-verify` is the user-invoked workflow. When an
active `$otel-instrument` workflow invoked verification, skip this terminal
response and return the repair packet defined below to the parent workflow.

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

<1-5 concise bullets covering the added or modified telemetry/runtime behavior>

## Tested And Working

**Individual result:** <working>/<total> working: <counts by signal type>.

| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|
<one row for every individual added or modified OTel item; do not group or omit
rows merely to shorten the response>

## Not Working Or Not Proven

<`None` or concise bullets with state, reason, and next required action>

## Proof

<1-5 links or concise bullets naming the strongest direct evidence>
```

Keep technical diagnostics out of the command response, but do not shorten it
by omitting per-OTel rows. It is the user's primary result, not merely a pointer
to the file. Always include `Tested And Working`, even when verification fails
or is partial; the `Working status` column makes mixed results explicit.
Always include `Not Working Or Not Proven`; write `None` only when every
in-scope inventory row is proven.

Name `$otel-instrument` as the repair path for instrumentation-owned source or
configuration failures; do not imply that rerunning verification will repair
application code. Instrumentation-owned includes a regression introduced by
the current instrumentation diff, missing wiring required by that change, and
a pre-existing OTel defect inside selected scope that prevents the selected
telemetry from working. It excludes unrelated business logic and external or
unselected dependencies.

When this verification was invoked by an active `$otel-instrument` workflow,
write `meta.workflow_mode: instrumentation_child` and return a repair packet to
that workflow using the existing canonical fields:
failed finding/item/scenario IDs, direct evidence, and repair-only `remaining`
actions. Set `meta.lifecycle: intermediate` for this failed artifact. Do not
emit the terminal reader-facing handoff yet and do not ask the user to start
`$otel-instrument` again. The parent instrumentation workflow
classifies ownership, applies every safe in-scope repair, and invokes the
affected checks again after updating the instrumentation overlay; the next
verification must carry its new `instrumentation_sha256`. The parent's shared
`instrumentation-final-gate` rejects this intermediate artifact as a final
handoff. For a standalone verification request, name
`$otel-instrument` once as the next workflow and explain that verification is
read-only. For `Fail`, keep top-level `next_steps` to the repair that must
happen now; the automatic verification recheck is workflow behavior, not a
second user action.

For a canonical flow, state the audit ID and approved finding IDs, and confirm
that unselected findings were excluded from this verification result.

For demo-oriented runs, include:

`Obstudio can verify the instrumentation contract locally: it runs deterministic checks, can hold open a real OTLP contract process, and writes a report proving which OTel signals are emitted and visible.`
