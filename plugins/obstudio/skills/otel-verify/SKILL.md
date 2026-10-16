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
Always read `../references/local-otlp-receiver.md` before choosing a local
export target. When selected or bound findings use
`finding_group: splunk-agent-observability`, or the repository contains a
`splunk_ao` dependency/import, also read
`../references/splunk-agent-observability.md`.
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

## Stage workflow

Read `../references/skill-workflow-observability.md` before starting. Follow the
stages below in order, loading each linked reference before its affected work.
These references retain the complete workflow requirements; they are not optional
summaries. Resolve all paths in stage references from this skill directory,
including existing `./references/` and sibling `../references/` paths.

- [inputs](references/stages/inputs.md): Read before selecting inputs, commands, and a runtime; record `inputs` with `canonical`, `missing`, or `stale`.
- [build](references/stages/build.md): Read before the build/import viability gate; record `build` with `passed` or `blocked`.
- [signals](references/stages/signals.md): Read before signal checks; record `signals` with `focused`, `full_runtime`, `contract_only`, or `blocked`.
- [report](references/stages/report.md): Read before producing verification artifacts or the final response; record `report` after artifact validation.

Record only stages actually reached. If blocked, record the reason and finish
`partial` or `failed`; leave unreached stages unobserved. A recorder failure must
not interrupt the primary workflow. Preserve the existing final response contract.
