---
name: otel-verify
description: >-
  Run deterministic verification for existing OpenTelemetry instrumentation and
  produce a report. Use when the user types $otel-verify, asks to verify OTel
  instrumentation, prove spans/metrics/logs are emitted, run observability
  tests, validate .observe/otel-audit.json or .observe/otel.md, consume approved
  finding IDs from --ids or .observe/otel-selection.json, check GenAI trace
  correctness, prove modified/declared telemetry, derive per-code-path coverage,
  or emit local explorer-visible OTLP contract telemetry without starting the
  full app. Read-only for application code unless the user explicitly asks to
  add or repair tests; use $otel-instrument to change instrumentation.
---

# OTel Verify

Prove existing instrumentation with project-runtime and app-code execution,
optionally observe the same scenarios through local OTLP, and write
`.observe/otel-verify.md` plus `.observe/otel-verify.json` for canonical flow.

Do not load `../references/report-flow-contract.md` as an up-front
prerequisite. For canonical
JSON flow, read `./references/json-approval-handoff.md`; it owns deterministic
scope, schema, digest binding, status rollup, and HTML refresh. When no
canonical audit exists, read `./references/legacy-verification.md`; never mix
the two flows. Load `./references/verification-report.md` once at the artifact
boundary for the Markdown report, validation, and final handoff. Read the
shared report-flow contract only when a conditional downstream rule requires
it.

Resolve every reference and script path from the directory containing this loaded
`otel-verify/SKILL.md`. `../references/<file>` is the shared sibling under the
parent skills directory; `./references/<file>` and `scripts/<file>` are local.
Never probe the service root or repository root for these paths.

## Contract

- Outputs are `.observe/otel-verify.md` and, in canonical flow,
  `.observe/otel-verify.json` plus refreshed
  `.observe/otel-instrumentation.html`. Markdown is a reader projection or
  legacy fallback, never canonical state.
- Default to read-only application code. Do not add or repair instrumentation;
  route it to `$otel-instrument`. Temporary harnesses may live inline or under
  `.observe/tmp/`. Add or repair permanent tests only when the user explicitly
  requests that mode.
- Determine invocation ownership before checks. A standalone request produces
  the reader-facing result. An active `$otel-instrument` child stays read-only,
  writes proof, and returns control to the parent repair loop. It must not edit
  dependencies or permanent tests, present a terminal handoff for a repairable
  failure, or ask the user to restart either workflow.
- Canonical standalone overlays use `meta.workflow_mode: standalone` and
  `meta.lifecycle: final`. A failed instrumentation child is
  `instrumentation_child` / `intermediate`; a post-repair child is `final` only
  when no executed finding, scenario, or item is `not_working`.
- Keep failed finding `remaining` and top-level `next_steps` repair-only.
  Separately record an evidenced unselected-work, material-decision,
  new-authority, or external-prerequisite boundary in `stop_boundaries[]`.
- Bind canonical verification to the exact normalized instrumentation overlay
  with `instrumentation_sha256`. Require its `selection_sha256` to match the
  normalized selection first. Recompute after every instrumentation repair;
  matching IDs alone are not freshness proof.
- Derive the report title from a proven effective `service.name`; otherwise use
  the final segment of the owning module/package identifier or service
  directory. Strip a
  Go semantic-import suffix such as `/v2` and use the preceding module segment;
  never put a full module path in the title.
- Escape every literal vertical bar as `\|` inside Markdown table cells.
  Backticks do not make raw `|` safe. At the artifact boundary, the loaded
  report reference requires
  `scripts/validate_reader_report.py`, reruns it until it passes, and forbids
  finalizing an unvalidated report.
- Build a signal inventory, added/modified telemetry inventory, acceptance
  scenario inventory, runtime candidate inventory, and build/import impact
  inventory before claiming coverage. Keep them as working proof; publish only
  what supports the result or explains a gap.
- Verification is app-code-first. Generated SDK telemetry proves only an
  export/schema contract. One representative trace cannot prove multiple
  telemetry-distinct signals or paths.
- In canonical flow verify exactly approved findings, their expected telemetry,
  referenced scenarios/environments, and bound instrumentation items. Never let
  an unselected finding make the result partial.
- `Partial` means meaningful proof passed but in-scope work remains unproven or
  blocked with no executed failure. `Fail` requires an executed viability or
  telemetry failure. `Blocked` means a concrete prerequisite prevented all
  meaningful proof. `Not run` means no check executed.

Load conditional references only when triggered:

- `./references/project-runtime-resolution.md` before the first compile,
  import, test, harness, startup, or OTLP command.
- `./references/path-scenario-coverage.md` when an audit exists or scope has
  workflows, routes, jobs, startup, streaming, tools, retrieval, redaction, or
  error paths.
- `../references/full-runtime-acceptance.md` when a claim depends on
  auto-instrumentation startup, framework route names, automatic metrics,
  duplicate automatic-span prevention, startup wiring, or runtime-installed
  OTLP logs.
- `./references/explorer-witness.md` before claiming local OTLP/explorer
  visibility.
- `./references/app-code-test-authoring.md` only when the user explicitly asks
  to add, repair, persist, or write tests.

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
to `$otel-instrument`. When no canonical audit exists, read
`./references/legacy-verification.md` and use only its direct/Markdown scope.

Read canonical JSON first and Markdown only for reader detail; on the legacy
path read the Markdown audit then instrumentation report. Reconcile all saved
commands, runtimes, source paths, and expected signals with current source.
Inspect the target entrypoint, referenced/diffed instrumentation files, provider
and exporter wiring, startup/shutdown, and signal-affecting branches.

For every in-scope item record:

- stable item/finding/scenario identity and added, modified, removed, or
  existing state;
- exact source/call site and user/application path;
- span name, topology, attributes, status/events/links;
- metric name, unit, type, datapoint, and complete bounded dimensions;
- log body/category, severity, correlation, redaction, and bridge/export path;
- resource identity, exporter endpoint/protocol, startup, flush, and shutdown;
- required app-code, OTLP, runtime, and product proof.

Create one operation row for every telemetry-distinct route, create/batch/update
/delete, workflow, tool, job, and outcome. A shared helper does not prove each
exact emitted name. For GenAI scope include workflow/agent/inference/tool,
retrieval/memory/eval, token/model attributes, duplicate prevention, and
parent-child topology. Map each affected module to a viability gate and initial
failure ownership.

Before commands, be able to state the selected scope, target process/runtime,
inventoried items and scenarios, proof plan, and any concrete prerequisite.

### 2. Find Existing Verification Commands

Prefer focused existing OTel/telemetry tests, project scripts, in-memory
exporters, fake providers/clients, test HTTP/tool/MCP seams, and startup tests.
Map every command to exact inventory rows; a name appearing in an unrelated
test is not coverage.

Use this proof order:

1. Existing repo test or smoke that executes app code and asserts telemetry.
2. New/repaired repo-native test only in explicit test-authoring mode.
3. Temporary app-code harness with fakes and assertions.
4. The same app-code scenario with OTLP export.
5. Generated SDK contract only when app code cannot run; label contract-only.

Never require production credentials, VPN, live provider calls, or manual curl
when deterministic fakes can exercise the same signal.

### 3. Resolve The Project Test Runtime

Read `./references/project-runtime-resolution.md` before any verification
command and follow it exactly. It owns runtime discovery order, wrappers,
toolchains, locked restore behavior, Java-agent resolution and digest recheck,
language rules, container/CI fallback, and runtime reporting.

Use one selected project-configured runtime for viability, tests, harnesses,
startup, and OTLP. A global runtime failure is a rejected candidate when repo
configuration selects another. Do not install globally, edit dependency
manifests, refresh lockfiles, or add test dependencies without explicit user
authority.

### 4. Run The Build/Import Viability Gate

Before telemetry harnesses or startup:

- run `git diff --check` when Git exists and static integrity checks for
  changed scripts/config;
- compile, typecheck, syntax-check, or import every affected module under the
  selected project runtime using the narrowest project-native gate;
- confirm filtered tests actually ran when a no-match guard is necessary; and
- classify failures as `instrumentation-introduced`, `pre-existing`,
  `environment`, or `unknown` using changed lines, current config, and a Git or
  saved baseline when available. An unchanged selected OTel wiring defect is
  `pre-existing`, not `instrumentation-introduced`.

Verification never repairs application code. An instrumentation-introduced or
selected OTel source/config failure makes affected findings/items
`not_working` and the result `Fail`; return the exact repair to
`$otel-instrument`. Dependent scenarios may be blocked without changing that
failure into an environmental blocker. A concrete unavailable prerequisite
blocks only dependent rows and yields `Partial` when other meaningful proof
passes. Continue independent modules and scenarios.

### 5. Run Signal Verification

Run the smallest command set that proves the inventories; prefer offline
app-code execution before service/network/Docker paths. Use the selected runtime
for every harness.

When full runtime is triggered, read and execute
`../references/full-runtime-acceptance.md` after viability and focused tests.
Use the audit proof level and safe fixture to exercise the actual process and
complete scenario matrix. Keep exact unavailable prerequisites and unobserved
outcomes rather than weakening proof.

For Java, never mix a test-owned `SdkTracerProvider`/`OpenTelemetrySdk` with a
Java agent in one JVM. Use a no-agent provider-test fork and a separate agent
E2E fork. Pass real `OTEL_*` environment variables to app-owned reporters;
`-Dotel.*` agent properties configure only the agent-owned SDK.

Proof rules:

- app verification requires execution through a repo test, authored test,
  temporary app-code harness, or live smoke;
- spans require exact name/pattern, attributes, status/error, and relevant
  topology;
- metrics require observed/asserted datapoints, name, unit, type, and complete
  bounded dimensions, including absence of transient/unexpected dimensions;
- logs require observed/asserted body/category, severity, correlation when
  required, redaction, and the expected bridge/export path;
- topology requires asserted/observed parent-child edges, links, or depth;
- paths require the scenario trigger, expected telemetry, and local OTLP proof
  when available; and
- runtime-only claims require the actual process and its real agent, preload,
  middleware, or startup bootstrap. Synthetic roots cannot prove automatic
  span count/kind/route, metrics, log bridge, or duplicate suppression.

A successfully attached validated agent supersedes earlier missing-path
evidence. A later startup or assertion failure is not an agent blocker. Split
success, failure, interrupt, empty, unavailable, retry, fallback, timeout, and
other telemetry-distinct outcomes unless source proves identical telemetry.

Use working proof labels `Verified: unit`, `Verified: OTLP`, `Verified:
unit+OTLP`, `Verified: app test`, or `Verified: app test+OTLP`. Use `Source
only`, `Not emitted`, `Not run`, `Blocked`, `Not configured`, or `Not
applicable` only with their literal meanings. A missing declared dependency is
`Blocked`, not `Source only`; an absent requested implementation is `Not
configured`, not `Not proven`.

For every blocked canonical scenario, set `blocking_reason` to the evidenced
prerequisite failure in past/present tense and `unobserved_outcome` to the exact
runtime, delivery, or product behavior not captured. Keep remediation in
`remaining`/`next_steps`; never use it as the blocker explanation.

### 6. Prefer Unit+OTLP Contract Harnesses

When local OTLP or an explorer is available, read
`./references/explorer-witness.md`. Use the same focused app-code scenario for
assertions and export, preserve per-signal endpoint/protocol/resource proof,
and keep the exact emitting process alive through query/evidence capture. Use
`Verified: unit+OTLP` only when both assertions and delivery proof pass; use
`Verified: unit` when assertions pass without delivery evidence.

When topology is necessary and the real path cannot run, read the nested rules
in `./references/path-scenario-coverage.md`. Prefer real call sites; a generated
nested SDK fallback is contract-only.

### 7. Author App-Code Tests When Requested

Only when the user explicitly asks, read
`./references/app-code-test-authoring.md` before editing tests. It owns
repository-native placement, provider initialization order, app-code execution,
telemetry assertions, evidence mapping, and the missing-fixture boundary.

### 8. Produce Verification Artifacts

In canonical flow, write `.observe/otel-verify.json` using
`./references/json-approval-handoff.md`. Preserve exact finding/scenario/item
order, workflow mode/lifecycle, instrumentation digest, proof mode, visibility,
evidence, observed telemetry, product validation, blockers, and repair fields.

One successful direct unit/application/runtime assertion makes the exact item
`working`, even when broader finding/scenario coverage remains `not_proven`.
Set `direct_assertion_passed` before rollup. Aggregate receiver counts, a
differently named signal, source/config presence, or a helper that never invokes
the exact item are context only: leave it `not_proven`, never as `Observed`.
A removed item requires a bounded absence assertion plus presence of its
intended same-type replacement owner. A `not_proven` scenario with focused
evidence obtained remains incomplete, never passed.

In legacy flow, follow `./references/legacy-verification.md`. After either
canonical or legacy proof is classified, load
`./references/verification-report.md` exactly once. It owns the complete
Markdown reader shape, deterministic proof-column projection, zero-item case,
technical detail boundary, raw-ID redaction, reader validator, canonical HTML
refresh, and result/failure presentation.

### 9. Finalize Or Return Control

Follow the standalone or instrumentation-child branch in
`./references/verification-report.md`. A standalone run presents every exact
item and names `$otel-instrument` once for any application repair. A child run
writes and validates the artifacts, returns its repair packet without a
terminal user handoff, and never repairs application code or tells the user to
execute each scenario manually.

For canonical flow, state the audit ID and approved IDs and confirm unselected
findings were excluded. For demo-oriented runs, include:

`Obstudio can verify the instrumentation contract locally: it runs deterministic checks, can hold open a real OTLP contract process, and writes a report proving which OTel signals are emitted and visible.`
