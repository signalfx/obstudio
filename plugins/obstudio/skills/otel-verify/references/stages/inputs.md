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

