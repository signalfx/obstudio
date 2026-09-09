# Direct Verification Workflow

Read this reference only when `$otel-verify` must execute new compile, import,
test, harness, startup, or OTLP checks. Do not load it merely to validate and
render an already-complete, bound `.observe/otel-verify.json` proof packet.

## Build The Verification Inventories

Start from the dependency-closed `approved_ids` and their referenced scenarios,
then reconcile them with current source and the bound instrumentation overlay.
Inspect changed instrumentation files and record every declared or changed
signal, including removals and runtime/exporter behavior.

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

Inventory every exact route/server span, custom span call site, metric,
log/event pipeline or category, and runtime/exporter behavior. Shared helper
execution does not prove each route, create, batch, update, delete, workflow,
or tool entrypoint. Record each signal's change kind, source/call site,
application paths, expected shape, and required proof. A removed item needs
direct absence proof and proof of the intended replacement.

For `consumer_compatibility`, prove the declared contract. `compatible`
requires the safe prior name, dimension, or attribute beside the new semantic
field. `breaking` requires the declared old contract to be removed or changed
and the replacement/migration field to emit where applicable.
`requires_review` remains unproven until impact is classified or explicitly
accepted.

For GenAI scope, inventory workflow, agent, LLM, tool, retrieval/memory, eval
when present, token usage, model/provider attributes, duplicate-span
prevention, and parent/child topology.

When routes, workflows, jobs, startup, streaming, tools, retrieval, redaction,
or error paths are in scope, read `path-scenario-coverage.md`. It owns scenario
derivation, per-path inventory shape, execution rules, and path reporting.

## Select Existing Proof Before New Harnesses

Prefer the smallest proof that executes the real instrumented call site:

1. Existing focused repo test or integration smoke.
2. A repo-native test only when the user requested test authoring.
3. A temporary app-code harness using fakes.
4. The same app-code scenario exported through local OTLP.
5. A generated SDK contract only when app code cannot run; label it
   `contract-only`.

Search focused tests, project scripts, in-memory exporters, fake
tracers/meters/loggers, test clients, fake providers, startup wiring, and seams
that avoid live providers or full service startup. Map each command to exact
inventory rows; a matching name in an unrelated test does not prove a path.

Generated SDK spans, metrics, or logs prove only export/schema behavior. They
do not prove application instrumentation. Generated harnesses are temporary:
use inline scripts, language-native temp runners, or `.observe/tmp/`. Never add
permanent tests unless the user explicitly asks; then read
`app-code-test-authoring.md`.

## Resolve Runtime And Prove Source Viability

Before any verification command, read `project-runtime-resolution.md`. It owns
runtime discovery, the runtime-candidate inventory, language rules, retry
behavior, and reporting. Use the selected project runtime for every compile,
import, test, harness, startup, and OTLP command. Do not use a global fallback
to declare the application broken, install dependencies globally, edit
manifests, or refresh lockfiles.

Before telemetry harnesses or service startup:

- Run static integrity checks for changed scripts/config and `git diff
  --check` when Git is available.
- Compile, typecheck, syntax-check, or import every module containing changed
  instrumentation with the narrowest project-native command that loads the
  changed code and generated sources.
- Rerun recorded passing instrumentation gates when practical; otherwise label
  them prior evidence.
- Classify failures as `instrumentation-introduced`, `pre-existing`,
  `environment`, `unknown`, or `not applicable`, with concrete evidence.
- An instrumentation-introduced source failure blocks dependent rows, makes
  the overall result `Fail`, and routes repair to `$otel-instrument`. Do not run
  expensive dependent harnesses through broken code.
- An unavailable prerequisite makes affected rows `Blocked`; use overall
  `Partial` when other meaningful proof passed and `Blocked` only when none
  could run. Continue independent surfaces.

## Execute Signal And Path Proof

Run enough focused commands to prove every inventory row. Prefer offline fakes
and deterministic tests over live credentials, production tokens, VPN, unsafe
side effects, or manual curl steps.

- App proof requires an existing test, requested authored test, temporary
  app-code harness, or live smoke that executes the real call site.
- Span proof requires the expected name/pattern, required attributes,
  status/error behavior, and relevant parentage, events, or links.
- Metric proof requires an observed/asserted datapoint for every expected name,
  unit, instrument type, and complete bounded dimension set. Reject missing
  required dimensions and unexpected transient outcome/error dimensions.
- Log proof requires an observed/asserted record with expected body/category,
  severity, required trace/span correlation, redaction, and exporter/bridge.
- Topology proof requires expected parent-child edges, links, or depth; span
  presence is not DAG proof.
- Path proof requires the scenario trigger, expected signals/topology, and
  collector/Obstudio evidence when OTLP is available.
- Runtime-only proof requires the real process with its agent, preload,
  middleware, or startup bootstrap. A direct handler or synthetic root cannot
  prove automatic span count/kind/route, automatic metrics, duplicate
  suppression, or startup-installed logging.
- Treat telemetry-distinct success, failure, interrupt, empty, unavailable,
  retry, fallback, timeout, stream, and shutdown outcomes as separate scenarios
  unless source proves an identical shape.

Use these detailed row statuses:

- `Verified: unit`, `Verified: OTLP`, `Verified: unit+OTLP`,
  `Verified: app test`, or `Verified: app test+OTLP` only for the named direct
  evidence.
- `Source only` when implementation exists but emission was not observed; do
  not use it for unresolved dependencies.
- `Not emitted` when an executed scenario omitted expected telemetry.
- `Not run` when the scenario was not executed.
- `Blocked` for a concrete unavailable local prerequisite.
- `Not configured` when no requested implementation/runtime pipeline exists.
- `Not applicable` when the audit confirms that signal type was unchanged.

Give every incomplete row one concrete reason. Any unverified inventoried
signal or path prevents a `Pass`.

## Full Runtime Acceptance

Read `../../references/full-runtime-acceptance.md` and execute its gate when a
claim depends on auto-instrumentation startup, framework-resolved route names,
automatic metrics, duplicate automatic-span prevention, startup/resource/
exporter wiring, automatic dependency topology, or runtime-installed OTLP
logs. Do not substitute a call-site harness or generated contract. Use the
audit's proof level and safe fixture profile. If no safe local profile exists,
record the exact prerequisite and leave the rows incomplete.

## Local OTLP And Explorer Proof

When a local OTLP endpoint or Obstudio is available, try to pair deterministic
app-code assertions with export from the same scenario. Before claiming
explorer visibility, read `explorer-witness.md`; it owns source lifetime,
bounded queries, durable sanitized evidence, visibility wording, and shutdown.

- Configure providers before importing modules that cache OTel globals.
- Use only local/test endpoints and verify endpoint, protocol, and path
  separately for traces, metrics, and logs. A trace export does not prove the
  metric or log exporter.
- Assert effective `service.name`, environment, and version from collector
  data, not only source merge logic.
- For HTTP auto-instrumentation, assert the emitted request-duration metric
  and bounded route dimensions; when stable conventions were requested,
  require `http.server.request.duration`.
- Use stable verification attributes; never export verification telemetry to
  production or use trace, request, user, or session IDs as metric dimensions.
- Mark `Verified: unit+OTLP` only when both direct assertions and saved local
  delivery evidence pass.

Preserve raw Obstudio validator results, then classify each finding as
`actionable`, `registry mismatch`, `library-owned compatibility`, or `stale`.
Moved registries, application-owned custom fields absent from a core registry,
framework-owned fields, or expected exporter freshness do not alone prove the
application failed.

When topology is required and the real path cannot run, a temporary nested SDK
contract may show schema/export shape but remains contract-only. Derive edges
from the inventories, keep children active under parents, use links only where
the architecture expects them, and assert exported parent IDs, links, depth,
or explorer edges. Do not flatten unrelated paths under one synthetic root.

## Hand Off Artifacts

After execution, write the bound `.observe/otel-verify.json` through
`json-approval-handoff.md`, then write the reader report through
`verification-report.md`. Preserve canonical finding, scenario, and item order
and every incomplete row. Do not turn source presence, a successful exporter,
or a representative trace into broader application/path proof.
