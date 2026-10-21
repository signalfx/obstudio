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
scenarios to a local OTLP collector or Splunk Observability Studio, then write
`.observe/otel-verify.md`. In canonical flow also write
`.observe/otel-verify.json` and refresh `.observe/otel-instrumentation.html`.

Before writing verification artifacts, read
`../references/report-flow-contract.md` and follow the Verification Report
Contract plus Reader-First Report Order. When `.observe/otel-audit.json` exists,
also read `./references/json-approval-handoff.md`; it owns canonical scope,
schema, digest binding, status rollup, and the HTML refresh.
Independently reconcile each selected GenAI orchestration role with the source
control flow before accepting the audit or test expectations. A custom
model-directed tool/result feedback loop is an agent invocation; an existing
`invoke_workflow` label or a passing test asserting that label cannot prove
correct agent coverage. For no-tool, tool-feedback and failure turns, compare
the received canonical span's operation, actual agent identity, parentage,
call counts, status and selected agent-duration measurement with executed app
code. Require one agent node at that boundary, without an extra workflow for
the same turn. Distinguish genuine staged workflows and single inference
facades. When source behavior contradicts a bound audit contract, report the
role defect and its affected proof as incomplete/failed; do not rewrite source,
rebind old proof or mark the agent covered from schema validation alone.
Always read `../references/local-otlp-receiver.md` before choosing a local
export target. When selected or bound findings use
`finding_group: splunk-agent-observability`, or the repository contains a
`splunk_ao` dependency/import, also read
`../references/splunk-agent-observability.md`.
For every source-owned agent, independently assess project, dedicated stream
and runtime routing using the Agent Resource And Producer Decision matrix in
`../references/splunk-agent-observability.md`, including native OTel fallback,
existing native OTel, existing AO and Galileo plus native OTel. An old audit
omitting these requirements is an audit coverage gap, not proof of completeness.
Keep canonical selected checks bound to their selection; report omitted or
unselected resource/delivery gaps separately without rebinding evidence or
modifying source/configuration. Standalone verification assesses all three.
When the selected scope or application owns GenAI operations, also read
`../references/genai-readiness.md` and apply its GenAI Instrumentation Selection
and Required GenAI Coverage Profile. Verify the chosen producer's span creation
separately from export-only setup; preserve and verify the canonical existing
OTel/Galileo producer when present. Applicable content/vendor fields are
required acceptance even when OTel publishes them as Opt-In.
For fixture-only GenAI reviews, report unknown capture configuration as
`Not proven`. For each producer and exporter, name a pre-SDK redaction/schema
hook and give concrete proposed UTF-8 byte/message/part limits, or an acceptance
test against documented configured limits. Require useful schema-valid content,
truthful truncation/gap handling and credential/token/email sentinel absence from
native records, attributes/events and wire as applicable. Keep proposed settings
and unrun acceptance tests separate from observed configuration or emission.
Classify preservation before checking creator choice: any existing runtime
OTel/Galileo/AO producer, provider or exporter for traces, metrics or logs makes
this incremental. Compare its before/after identity, operations, safe fields,
metrics/log records and destinations; a missing GenAI span does not authorize
SDK adoption or framework suppression. Run the real startup and configured
export path, and exercise repeated callbacks and teardown for duplicates or
unfinished spans. Missing original evidence is Not proven, not permission to
replace it.
For a runtime with no existing telemetry instrumentation using the Splunk AO
default, or an existing Splunk AO creator, also read
`../references/splunk-agent-observability.md` and its Decorator Selection plus
Fresh Agent SDK Instrumentation mapping, even with no `splunk_ao` import or selected
AO resource finding. Select a supported Splunk AO creator for that path where
it meets the contract; assess the reference's per-operation public OTel
compatibility exception for source-proven incompatible SDK boundaries. An
explicit user choice of another supported producer overrides the default;
verify that chosen canonical producer and its required coverage. Record
creator symbols, actual boundary,
installed or proposed source-verified version and exact example/revision;
separate that prospective choice from actual emitted-span proof. A fixture
without an installed SDK does not justify silently changing the fresh default.
Distinguish that missing installation from a language/runtime with no compatible
supported Splunk AO SDK. For the latter, verify its native OTel implementation
against the same applicable GenAI/vendor field profile, complete trace graph,
privacy/schema, lifecycle and signal/export preservation. Require current
support evidence and public language-native APIs; do not fail the native path
merely because AO SDK packages or Python `@log` are absent. Keep real missing
fields or unsupported native capabilities explicit and scoped.
Apply its mandatory per-function producer decision gate to every fresh or
newly uncovered Python GenAI source function, including model/tool/retrieval
functions and async-generator agents. Reconcile the named function/type and
each applicable control-flow branch before assigning kind or usage rules:
networked inference requires CLIENT, actual in-process inference uses its
appropriate kind, and a deterministic demo/rule-engine branch is N/A for real
model inference usage and remote CLIENT acceptance. Keep these conditions in
the per-function evidence; a function name does not establish inference.
Reconcile the
native public source/probe assessment with the actual SDK `@log` or justified
application-owned function decorator. A missing decision or newly added manual
function scope without a proven exception is Fail/Partial even with correct
span attributes; `@contextmanager` on a scope factory is not that function
decorator or SDK `@log`. An incompatible capture, generator protocol, lifecycle,
creation-time or sink contract requires exact evidence and a supported fallback.
Verify actual business values, stream behavior and one node per operation, not merely
the presence of an annotation. Preserve framework/provider-owned operations
without a duplicate decorator span and keep all remaining field gaps visible.


For a supplemental SDK/connection source review, close the supplied API facts:
exact helper signature, effective creation kind, initial attributes/sampling
inputs, and exit-time updates. Read the reference's local span creation and function
producer gates even when a full semantic audit is excluded. Name the justified
app-owned function decorator and supported creator for uncovered boundaries.
Use a public OTel exception only for a source-proven incompatible contract;
keep unknown transport Conditional and preserve existing producers. Record
unexecuted runtime proof separately from established source behavior.


## Contract

- Default output: `.observe/otel-verify.md`; in canonical flow also write
  `.observe/otel-verify.json` and refresh `.observe/otel-instrumentation.html`.
- Canonical source of truth: `.observe/otel-audit.json`, the bound
  `.observe/otel-selection.json`, and `.observe/otel-instrumentation.json`.
  Read Markdown only for reader detail. Without canonical JSON, stop and ask
  the user to run `$otel-audit`; never fabricate canonical state.
- Default mode: read-only for application code.
- Do not add instrumentation. Use `$otel-instrument` for instrumentation
  changes.
- In canonical flow, verify exactly dependency-closed `approved_ids`, their
  expected telemetry and referenced scenarios, plus every bound instrumentation
  item. Bind verification to the normalized instrumentation overlay with
  `instrumentation_sha256`; matching IDs alone are not freshness proof.
- Build inventories before running checks:
  - `Signal Inventory`: every declared span, metric, log/event, and
    runtime/exporter signal in scope
  - `Changed Telemetry Inventory`: every added, modified, or removed
    trace/span/event, metric, log/event, and runtime/exporter signal from
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
  - What telemetry or runtime behavior was added, modified, or removed?
  - Was each change tested, and did application code execute?
  - Is each change working?
  - What direct proof supports that conclusion?
  - If anything is not working or not proven, why and what is needed next?
- Answer those questions per individual added, modified, or removed OTel item
  in one authoritative table. Use one row per exact route/server span, custom span
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
- Treat local Studio OTLP acceptance as receiver evidence only, not cloud Agent
  Observability visibility. Verify the selected destination mode: normal SDK
  project/stream calls, per-request routing through the configured gateway or
  explicit direct-cloud endpoint, and a fresh trace in the intended cloud
  stream. Prove no Studio-specific application adapter, global route
  registration, or runtime endpoint discovery is required.
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
- When the canonical audit or selected verification scenarios include routes,
  workflows, jobs, startup, streaming, tools, retrieval, redaction, or error
  paths, read `references/path-scenario-coverage.md` before designing harnesses
  or writing the report.
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
to `$otel-instrument`. When no canonical audit exists, stop and ask the user to
run `$otel-audit`; do not infer scope from generated Markdown reports or
fabricate canonical JSON.

Inspect the repo before running anything:

- In canonical flow, read `.observe/otel-audit.json`, the bound
  `.observe/otel-selection.json`, and `.observe/otel-instrumentation.json`
  first. Read Markdown only for reader detail.
- In canonical flow, seed runtime candidates and acceptance scenarios from the
  selected audit findings and their referenced verification scenarios. Then
  seed changed-signal scenarios and prior implementation checks from the bound
  instrumentation overlay.
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
- For every instrumentation item with `consumer_compatibility`, verify the
  declared consumer contract as part of item proof. `compatible` requires proof
  that the safe existing name/dimension/attribute still emits beside the new
  semantic field. `breaking` requires proof that the old contract was removed
  or changed as declared and that the replacement/migration field emits when
  applicable. `requires_review` remains not proven until the downstream
  consumer impact is classified or explicitly accepted.
- Build an exact operation closure row for every changed signal that should
  still emit, plus an explicit removal-proof row for every removed signal.
  Shared helper execution does not prove that each route, create, batch,
  update, delete, workflow, or tool entrypoint emits its exact signal name.
- If GenAI readiness is in scope, include workflow, agent, LLM call, tool
  execution, retrieval/memory, eval when present, token usage, model/provider
  attributes, duplicate-span prevention, and correct parent/child topology.
  For supplied source/probe cases, start a ledger before drafting the report:
  each case's actual operation, chosen creator/type and sink, safe source
  values/bounds, known capture/lifecycle/field support or failure, and exact
  source/probe receipt. Decide support from the available evidence now; keep
  unexecuted app/export acceptance separate. Group cases only when their
  distinct constraints and decisions remain explicit.
- Map every affected source module to a compile, typecheck, syntax, or import
  gate. Use changed files and handoff evidence to classify failures as
  `instrumentation-introduced`, `pre-existing`, `environment`, or `unknown`.

Create these working inventories before choosing commands:

```markdown
## Signal Inventory

| Signal type | Name/pattern | Source | Required proof | Scenario | Status |
|---|---|---|---|---|---|

## Changed Telemetry Inventory

| Signal type | Changed signal | Source/call site | User/application path(s) | Required attributes/dimensions/body | Required code/removal proof |
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
  concrete evidence.
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
  or span depth are asserted or visible in collector or Splunk Observability Studio evidence. Span
  presence alone is not DAG proof.
- Path coverage is verified only when the scenario trigger ran or was
  faithfully synthesized, expected topology/signals were asserted, and
  collector or Splunk Observability Studio evidence was captured when OTLP is available.
- Runtime-only rows are verified only by the real process with its actual
  agent, preload, middleware, or startup bootstrap. A synthetic owning root or
  direct handler call cannot prove automatic server span count, kind, route
  name, automatic metric emission, or duplicate suppression.
- If the audit names multiple telemetry-distinct outcomes for one workflow,
  such as success, failure, interrupt, empty, unavailable, retry, fallback, or
  timeout, treat each as a separate path scenario unless source inspection
  proves identical telemetry.

Bind each runtime claim to its own capture path, process/mode, destination,
scenario and observed trace/span IDs. Resolve cited IDs against that exact
capture and its decoded request metadata before finalizing; IDs copied from a
Studio case cannot prove a public or rejected-export case. Add a negative
association test when generating report evidence from several captures.
When the receiver is unavailable, business success and an export error prove
neither native emission nor delivery. Independently capture completed native
spans, metric points and LogRecords through supported SDK test seams, or keep
that emission claim Not proven. Preserve N/A applicability in every downstream
state row; a non-agent N/A cannot become required/Blocked AO setup in a template.
Interpret applicability with its explicit scope: a whole section marked N/A
can retain a conditional catalog of checks without making them current work.
Flag an active required/Blocked child outcome that contradicts that scope,
not the mere presence of a key named `required` inside an N/A section.

Use this status vocabulary:

- `Verified: unit`: deterministic app-code assertion or in-memory exporter
  proof, not exported to a collector.
- `Verified: OTLP`: collector or Splunk Observability Studio evidence from a real SDK exporter.
- `Verified: unit+OTLP`: deterministic assertions and collector or Splunk Observability Studio
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

When Splunk Observability Studio, a local collector, or an explicit OTLP endpoint is available,
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
- Resolve the current local endpoint with the shared receiver precedence and
  preserve its exact port. HTTP `127.0.0.1:4318` and gRPC `127.0.0.1:4317` are
  conventional fallbacks only. Never export verification telemetry to production.
- Run at least one deterministic OTLP check on a non-default local port, or use
  existing evidence that did so, so hardcoded `4317`/`4318` behavior cannot
  pass. Do not probe the conventional ports after a configured or advertised
  endpoint has been resolved.
- Verify the effective endpoint, protocol, and path separately for traces,
  metrics, and logs. If one signal fails, test the configured exporter against
  the matching receiver: gRPC commonly uses `4317`; HTTP/protobuf commonly
  uses `4318/v1/<signal>`. Do not treat successful traces as evidence that the
  metrics exporter is valid.
- For the default Studio pipeline, verify the consumed launch profile has
  `OTEL_LOGS_EXPORTER=otlp` and that application LogRecords arrive in Studio
  alongside the actual trace spans and metric datapoints. A generated `none`
  setting without an explicit user/operator opt-out does not satisfy default
  log acceptance. SDK `@log` GenAI spans and stdout correlation do not prove
  log export. Keep intentional opt-out tests separate from the normal launch.
- Verify dependency compatibility using the actual installed/locked packages
  and current official metadata/APIs; record exact resolved versions and
  source dates in run evidence. Skills contain no fixed library release
  recipes. Do not upgrade the application during read-only verification or
  claim a newer proposed compatible set was installed or executed.
- Assert effective resource attributes from collector data, including
  `service.name`, environment, and version. Source-level merge logic alone does
  not prove operator-provided values survive provider construction.
- For HTTP auto-instrumentation, assert the exact emitted request-duration
  metric and route dimensions. If stable semantic conventions were requested,
  require `http.server.request.duration`; an alternate metric in source or a unit
  fake does not satisfy that runtime row.
- Keep a Splunk Observability Studio contract process alive until trace, metric, and log queries
  complete; some local explorers evict telemetry for short-lived sources.
- Mark `Verified: unit+OTLP` only when assertions and collector or Splunk Observability Studio
  evidence both pass. If assertions pass but export is unavailable, use
  `Verified: unit`.
- Keep application startup independent of receiver discovery. It may consume
  persisted standard `OTEL_EXPORTER_OTLP_*` and supported AO SDK endpoint/auth
  settings, but it must not query `observer_status`, MCP, or Studio-specific
  discovery/route-registration APIs. Normal SDK authentication and resource
  calls to the configured cloud-compatible endpoint are allowed.

For each assessed agent, report four outcomes separately, marking unselected
work or unavailable remote proof explicitly rather than claiming full readiness:

- the project is resolved or created through a supported product path;
- the dedicated Agent Stream is resolved or created;
- the selected application routing mode is configured and exercised; and
- a fresh application trace is observed in the intended project and stream.

For existing native OTel, apply the shared reference's Native trace binding
and recovery contract. Capture actual headers and completed span Resources:
`projectid` must equal `splunk_ao.project.id`, and `logstreamid` must equal
`splunk_ao.logstream.id`, using the selected resolved UUIDs. A header-only test
does not prove payload binding. Require a real-launcher test starting with only
selected names and already-existing resources, an initially unavailable API,
then recovery in the same app PID with zero creates and no manual setup.
Separately test resolved bindings through an outage without erasing them.
Preseeding IDs or restarting between states cannot prove names-only recovery.
Include finite per-request timeouts, a capped retry rate/backoff, business and
local-telemetry progress during a prolonged outage, and cancellation of pending
retries on shutdown in that acceptance. Bounded retry work does not require
permanently stopping retries before Studio connects. Record actual configured
bounds when source or captures supply them; otherwise name the missing bounds
and their future assertion as Not proven. An automatic-recovery sentence alone
does not assess these constraints, and source-only verification must not invent
numeric runtime settings.
Only exact fresh cloud trace readback proves end-to-end AO visibility.

For Galileo, verify its native project/log-stream client and actual consumed
vendor configuration, then its installed native processor/logger/export path.
Preserve nondefault selectors, API/console/auth and legitimate native OTel
sinks; do not require Splunk AO variables or Studio trace headers for that path.
Local fakes must exercise the real installed Galileo SDK and application
startup/exporter, not a fake vendor module. Apply the same resource lookup,
creation, repeat, association, ID, race and failure checks through supported
Galileo APIs. Missing live credentials/API permission may block exact remote
trace readback; report that outcome separately from local runtime proof.

For selected resource provisioning, inspect the configured `ao_target` and
exercise the application's actual provisioning step with credential-free API
fakes. Existing non-AO paths must work without importing or installing the AO
SDK: use its configured standard resource HTTP client and existing exporter.
Prove both-existing causes zero creates, both-missing and mixed resources are
resolved or created in the intended project, and a repeated run reuses the
same IDs. Exercise duplicate/conflict recovery by exact scoped relookup,
ambiguous and wrong-project resources, unresolved explicit IDs, and lookup or
creation permission/server failures. Failures must leave ordinary OTel active
and must not trigger alternate names or blind repeat creates. Lookup-only code
does not prove the missing-resource branch. Record reused/created resources
separately from attempted or blocked provisioning and fresh cloud receipt;
verify mode must not provision live resources merely to produce evidence.

For each selected resource, inventory lookup and creation as separate paths.
Exercise 401, 403, timeout, and 5xx failures for project lookup, Agent Stream
lookup, project creation, and Agent Stream creation wherever the actual
runtime supports that operation; an unsupported creation branch must be
reported as missing rather than tested through a replacement implementation.
Inspect call counts and sink initialization to prove failure isolation. Reconcile
the actual loaded profile and runtime-native selectors with standard
`SPLUNK_AO_PROJECT(_ID)` and `SPLUNK_AO_AGENT_STREAM(_ID)` settings, then test
non-default and conflicting values to establish which selectors the source
consumes and their precedence. Do not assume standard SDK variables control a
runtime that passes its own resource names explicitly. Prove explicit-ID
plumbing when supported, or state the source-backed name-only limitation;
passing an ID string to a name lookup does not prove ID support.

For a native OTel application without Galileo, verify the actual launch consumes the resolved IDs
through the existing exporter's supported trace-header hook: current Studio
uses `projectid`/`logstreamid`, public standalone AO docs use
`projectid`/`agentstreamid`. Verify the exact target contract and authentication,
preserved endpoint/protocol/non-default port and harmless existing headers,
no AO header leakage to metrics/logs, no second provider/SDK creator, one AO
delivery per operation and unchanged unrelated sinks. Test resource failure
before binding headers and normal resource resolution through the same gateway
connection. A sample env file or fake lookup alone does not prove this path.
Local Studio visibility proves receiver delivery only. For Python SDK gateway
mode, verify its actual profile loader and env generator deliver populated
`SPLUNK_AO_API_URL`, `SPLUNK_AO_CONSOLE_URL`, and
`SPLUNK_AO_API_KEY=local-gateway` to the provisioning process through a
credential-free SDK boundary. Compare with the discovered API base, including
non-default ports; an unused sample, pass-through allowlist, or blank generated
assignment is `Not configured`. Keep verify read-only for application/env
files and report the missing fields instead of repairing them. Preserve
explicit direct-cloud mode and do not require this trio for an unselected or
direct-cloud AO path. For other languages, verify the runtime's actual supported
gateway endpoint, authentication, resource selectors and consumed profile;
absence of Python SDK variables alone is not `Not configured`. Keep source
configuration, runtime receipt and fresh cloud visibility separate. Separately
prove that Studio uses its active
connection/realm, supplies upstream auth,
preserves per-request resource bindings without cross-application leakage, and
handles unavailable or changed connections honestly. Application cloud
credentials are not a prerequisite for this mode. A missing Studio connection
or required resource permission may block live product proof without blocking
credential-free configuration, provider-reuse, lifecycle, content-safety, and
duplicate-span tests.

Apply the per-tool vendor content contract in
`../references/genai-readiness.md` per actual tool span ID. Arguments/results
alone or messages on its parent/model do not satisfy the tool's message fields.
For the GenAI path, check arguments against both `gen_ai.tool.call.arguments`
and schema-valid `gen_ai.input.messages`, and produced results against both
`gen_ai.tool.call.result` and `gen_ai.output.messages`. A supported
OpenInference `input.value`/`output.value` path is an explicit alternative,
not a reason to silently pass missing content. Compare the same sanitized
source values, correlation and configured limits; missing, malformed or
mismatched mappings are individual failures. For error/cancel/timeout without
a produced result, require error/lifecycle evidence and an exact absent-output
reason, never a fabricated successful output. A fixture-only pass remains
structural proof; SDK-created spans still need actual runtime capture.

For selected GenAI spans, reconcile current OTel docs/schemas and both vendor
integration guides before scoring. Inventory every operation and field with
official level, vendor requirement, skill acceptance, applicability, actual
source value, original/AO/exported value and proof. Check span kind/name,
provider/model, parameters, response/finish reasons, usage, streaming,
conversation/tool-call IDs, input/output messages, effective instructions/tool
definitions, actual arguments/results and retrieval content when applicable.
SDK-created spans are not automatic proof; empty placeholders, omitted
applicable content and wrong schema/value mappings fail required coverage.
For a compatibility exception, verify the actual public OTel function creator,
initial kind/request fields, active context, retained provider and configured
or selected export paths;
never count its processor as SDK span creation. After a repair, reconcile all
normal report sections with current creator/kind/output evidence. A stale SDK
label or repaired failure left in an older section is a report inconsistency.
Before finalizing, reconcile every requested case and source-known request
control with its report evidence. Inventory controls at their actual request
call sites, then compare each attribute's expected safe source value with the
captured value or absence. Record applicability, result and proof. Naming a
missing control without its known source value does not complete this
comparison; a similarly named tool-result field is not a request control.
Use supplied SDK source and probe facts to decide that captured package's
capability or failure concretely now for each function. Reconcile its ledger
decision with the report: SDK decorator/type, exact justified application-owned
decorator fallback, or preserved producer. Separate dispatch, captured fields,
lifecycle/protocol and normal versus custom sink support from unexecuted
application/wire proof. A conditional "when supported" or hypothetical future
compatibility does not decide a source/probe case with available facts.
For supplied native signal examples, compare each signal's endpoint/protocol/path
and available record values with its contract. Assess log body, severity,
resource, logger scope and trace/span ID presence separately from an actual
match to an owning span. Record supported fields and missing evidence even
when runtime delivery is unproven; a synthetic record is not receiver or cloud
receipt. Generic policy does not assess a supplied parameter, dependency
selection or signal record.
Include exact source URLs and provided
revision/date/hash receipts rather than only naming an input artifact.
Supplemental source or captured cases may use accurate Markdown, JSON or linked
equivalent evidence; preserve canonical JSON contracts separately and never
invent live findings for fixtures. State an omitted or unavailable check
explicitly instead of silently dropping the case or field.
An explicit restricted-content scenario can pass its safety assertion while
remaining partial for the full profile. Never fabricate successful output for
failed operations or duplicate system-role content in separate instructions.
Execute success plus stream-error/timeout/cancel cases at actual SDK/application
boundaries; auxiliary suggestions/title/subagent calls are operations too.
Prove one canonical producer, correct parent context and no unfinished spans.
Check existing SDK partial-rejection/export-health diagnostics and distinguish
receiver receipt, accepted batch, source/cloud inventory and product visibility.
No trace complete flag substitutes for per-field or per-source-span proof.
When verifying producer-selection scenarios, publish a separate row for each
runtime: current canonical creator/provider/exporter, intended preserved or
fresh SDK path, named supported API and matching official example/version
evidence or exact unavailable prerequisite. Do not leave a generic 'SDK or
another producer' statement. Publish real conversation/tool-call correlation
as per-field results too: a known missing call ID is a gap, an unavailable
session ID is unproven/N/A according to current applicability, and neither is
silently invented. Keep prospective configuration distinct from observed
app-code span creation and fixture-only structural evidence.

Run Splunk Observability Studio validation when the user requests it, but classify each finding
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
  or Splunk Observability Studio flow nodes/edges when available.

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
and scope surface.

## Reader Report

Write this order:

```markdown
# OTel Verification Report: <service>

**Result:** Pass | Fail | Partial | Blocked | Not run
**Bottom line:** <one plain-language sentence saying what works and what does not>
**Source audit:** `.observe/otel-audit.json`
**Approved selection:** `.observe/otel-selection.json`
**Source instrumentation:** `.observe/otel-instrumentation.json` | not found

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

- For GenAI, include all three **Required GenAI Report Evidence** tables from
  `../references/genai-readiness.md` in the requested review/report. Even a
  captured-fixture review must map fresh-agent boundaries to exact actual or
  proposed creators: supported SDK methods or the justified per-operation
  public OTel exception. Record chosen package/public API source and applicable
  example revision, preserve existing creators, assess ordinary
  helpers as GenAI N/A, and include explicit cancellation/teardown evidence
  rows. Missing runtime evidence is Not proven; generic SDK recommendations
  cannot substitute for the producer receipt or lifecycle assessment.
- Follow `../references/report-flow-contract.md`. The first screen must let a
  reader answer what changed, whether it was tested, whether it works, what
  proves it, and why anything remains unproven.
- Keep `Bottom line` to one sentence. Do not use coverage counts alone as the
  bottom line.
- In `What Changed`, group related signals by behavior or component instead of
  listing every span in prose.
- In `Tested And Working`, include every individual item from the reconciled
  Changed Telemetry Inventory. Do not group independently instrumented or tested
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
  collector or Splunk Observability Studio evidence proves it.
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
- Always summarize added, modified, or removed telemetry in `What Changed` when
  a source instrumentation artifact exists or the user asks what changed.
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
**Changed signal coverage:** Overall 37/42; spans 8/9; metrics 29/33; logs 0/0.
**Path coverage:** 8/12 verified; 2 source-only; 2 blocked.
**Unit export coverage:** unit+OTLP 12; unit-only 3; OTLP-only 2; blocked 1.
```

If no logs/events were changed, include one `Not applicable` row for
logs/events. If OTLP logs were requested but no log exporter or bridge exists,
mark them `Not configured` and state the implementation required. Do not use
`Not proven` for an absent implementation.

Never expose raw trace IDs or span IDs in generated HTML. Say **the generated
trace** and name the span or signal. Preserve exact identifiers only in
canonical `trace_ids`, durable evidence, and Markdown `Technical Details`.

## Reader Validation

Escape every literal `|` inside Markdown table cells as `\|`; backticks do not
make it safe. Always run:

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

Repair every structural, item-coverage, status, count, projection, or
gap-mirroring error and rerun until the validator passes. Do not finalize an
unvalidated report.

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
**Instrumentation report:** [otel-instrumentation.html](http://127.0.0.1:<port>/<token>/otel-instrumentation.html) when canonical
**Audit report:** [otel.html](http://127.0.0.1:<port>/<token>/otel.html) when canonical

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

Use the loopback links returned by `render-instrumentation-html` for both HTML
reports. Do not open either report automatically. Keep the Markdown and JSON
report links as absolute local-file paths.

Name `$otel-instrument` as the repair path for instrumentation-introduced
source failures; do not imply that rerunning verification will repair
application code. In canonical flow, state the audit ID and approved IDs and
confirm unselected findings were excluded.

For demo-oriented runs, include:

`Splunk Observability Studio can verify the instrumentation contract locally: it runs deterministic checks, can hold open a real OTLP contract process, and writes a report proving which OTel signals are emitted and visible.`
