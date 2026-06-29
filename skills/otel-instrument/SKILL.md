---
name: otel-instrument
description: >-
  Add OpenTelemetry observability to applications using auto-instrumentation
  and optional custom spans/metrics, write a separate instrumentation report,
  and run verification unless explicitly skipped or blocked. Use when the user
  types $otel-instrument, asks to "add OTel", "add tracing", "add metrics",
  "implement observability", "wire up telemetry", "instrument this service",
  asks to add a specific custom signal like "add a metric to track queue
  depth", "add a span for payment processing", "track error rate for X", or
  asks to instrument GenAI/LLM workflows with OpenTelemetry semantic
  conventions.
---

# Instrument

Add OpenTelemetry observability to applications using auto-instrumentation and optional custom spans/metrics.

Prefer the application's current runtime shape. If the project already uses Docker/Compose or Kubernetes, fit instrumentation into that path. If the user does not have Docker or does not want Docker, do not introduce containers just for observability; use the host/native runtime patterns.

Before editing application code, read `../references/report-flow-contract.md`
and follow the Instrumentation Contract plus Reader-First Report Order.

## Workflow

### 1. Preflight

Before editing anything, ground the plan with repo evidence:

- Confirm the language and framework from actual dependency or source files
- Read `./references/project-runtime-validation.md`, inventory the repository's
  configured runtime and build/test commands, and select the locally available
  project runtime before editing. Do not use the shell's default runtime when
  wrappers, toolchain files, manifests, CI, or existing project environments
  select another one.
- Confirm the target process from the repo's real start surface: `docker-compose.yml`, Kubernetes manifests, `package.json` scripts, `Makefile`, `Procfile`, PM2 configs, Supervisor configs, systemd units, launchd plists, PowerShell scripts, or a plain shell command
- Confirm existing telemetry indicators or record `none found`
- Build a provider/exporter topology per signal before choosing SDK or preload
  wiring. Find explicit and lazy provider construction, global registration,
  exporters, resources, no-op branches, and shutdown paths, then prove
  reachability from the selected process. For Python, run
  `../otel-audit/scripts/scan_python_otel_topology.py <service-root>` when that
  bundled scanner is available and reconcile its candidates with source.
  Existing ownership of any one signal makes this an incremental integration;
  it does not prove that the other signals are configured.
- If `.observe/otel.md` contains `## Verification Plan`, use its
  `Test Environments` and `Acceptance Scenarios` rows as the initial
  implementation and validation plan. Resolve each scenario's `Environment`
  IDs to the reusable runtime and prerequisite rows before running it.
  Reconcile them with current config/source; preserve stable IDs and update
  stale paths or prerequisites. Keep each `Proof Level`; do not downgrade a
  `full runtime` row to focused call-site proof. For older audits, normalize
  `Verification Contract / Project Runtime / Path Scenarios` into this model.
- If `.observe/otel.md` contains the prioritized `## Gaps` table, parse every
  row by `Priority`, `Area`, `Required fix`, `Instrument mode`, and
  `Verification scenarios`. Reconcile each row with current source and the
  verification contract before editing. For legacy bullet-only `## Gaps`,
  normalize each actionable bullet into the same fields and record inferred
  priority/mode in the instrumentation report; do not silently drop it.
- Detect GenAI/LLM ownership. Search dependencies, config, and source for
  provider clients, model gateways, agent/workflow orchestration, tool/function
  dispatch, MCP when present, retrieval/RAG, model/deployment config, fallback,
  token usage, prompt/response assembly, AI-derived data jobs, AI-path
  synthetic/canary checks, and usage logging. When present, load
  `../references/genai-readiness.md`.
  Follow its GenAI Semconv Source Contract before editing: reconcile detected
  AI surfaces with official semconv docs when available, record
  live-or-snapshot provenance, and build a semconv closure matrix.
- When GenAI incidents, postmortems, tickets, alerts, or failure examples are
  part of the request, use GenAI incident-evidence mode from
  `../references/genai-readiness.md`: map each AI pathway failure mechanism to
  the owning provider/model gateway, workflow, tool/function execution or
  AI-owned session/stream including MCP when present, retrieval/RAG, streaming,
  token/context, prompt/response parser, safety/policy, AI-derived data,
  model/config rollout, or AI-owned state surface before editing.
- For Java projects, build a trace wiring inventory per `./references/languages/java.md` (Preflight section) and classify as `auto-only`, `custom-with-provider`, `custom-provider-external`, or `missing` before editing.
- Confirm the planned `service.name` source and `deployment.environment` source
- Distinguish between application repos and tooling repos such as CLIs, MCP servers, workers, libraries, installers, and build tools. Instrument the executable path users or operators actually run today. Do not invent a web app, Docker path, or entrypoint that is not present.
- If the repo has multiple runnable surfaces, instrument the one the user actually cares about; otherwise ask which one matters
- If the repo is primarily tooling or library code and no runnable surface is obvious, stop and ask instead of inventing an app shell
- Ask one focused clarifying question only if the target process or runtime shape is still ambiguous after checking the repo

Do not proceed until you can state all of these clearly:

- target process
- runtime shape
- `service.name`
- environment dimension
- incremental addition vs new scaffold
- selected project runtime, probe command, and affected-module validation
  command, or the exact prerequisite that makes validation unavailable
- audit gap closure plan: rows in scope now, rows deferred by mode or explicit
  user scope, and the scenario IDs that will prove each in-scope row
- for Java, trace source of truth (see `./references/languages/java.md` Preflight section)
- GenAI workflow surfaces and the GenAI semantic-convention plus service-owned
  readiness signals to add, when the repo owns LLM, agent, tool/function, MCP,
  retrieval, streaming, model/config, token/context, prompt/response,
  safety/policy, AI-derived data, memory/context, evaluation quality, content
  capture, framework bridge, app-computed cost, or AI-owned state code
- GenAI incident coverage when GenAI incidents or AI pathway failures are
  supplied: failure mechanism, provider/model/tool/retrieval/config/prompt/
  AI-derived-data owner, signal to add or prove, expected MTTD/localization
  impact, and remaining non-code or dependency owner

### Fast Path: Targeted Custom Signal

If the user is asking for a specific signal ("add a metric for queue depth",
"track error rate on payments", "add a span for the indexing job") AND the
preflight scan finds OTel SDK already initialized:

1. Skip Steps 2-3 (dependencies and auto-instrumentation are already present).
2. Go directly to Step 4 (Custom Instrumentation) with the user's request as context.
3. Add only the requested signal — do not re-scaffold or re-wire existing setup.
4. Proceed to Step 5 (project-runtime validation gate).

If the preflight scan finds no OTel SDK, tell the user auto-instrumentation
needs to be set up first and continue with the full workflow (Steps 2-3).

### Audit-Driven GenAI Readiness

#### GenAI Readiness Contract

If `.observe/otel.md` contains `## GenAI Readiness`, use that table as the
source of truth. The audit output is a contract, not background context.
Parse each row by human-readable `surface` plus `required_signals`,
`owner/source_files`, and `acceptance_criteria`. Do not require opaque row IDs such as `GR8`
or `G1`; if an older audit has an ID column, keep it only as an optional
source-row reference and use the surface name in human-facing summaries. If an
older audit contains a separate GenAI gap-contract section, treat it as legacy
input and normalize it into surface rows before editing code.

Reconcile every GenAI audit gap to a required instrumentation result:

| Audit Gap | Required Instrumentation Result |
|---|---|
| App-owned + patchable | Code added + tests |
| App-owned but unsafe/too large | Explicitly split into named follow-up batch |
| Provider/platform-owned | Owner mapped with exact missing source |
| Already covered | Proven with source path and signal name |

For each surface row, produce and maintain a closure matrix:
`surface -> required_signals -> implemented_signals -> tests ->
remaining_signals -> status`. The final gate is strict: the instrumentation
pass cannot say `covered`, `fixed`, `closed`, or `complete` unless every
required GenAI signal is either implemented with tests, proven existing with
source path and signal name, or explicitly owner-mapped with the exact missing
source. Optimize for honesty over broad progress. Partial closure is acceptable;
silent partial closure is the bug.

For every GenAI instrumentation run, include a concise closure summary in the
final response. It must name remaining GenAI signals, or say `Remaining signals: none`
only when the closure matrix has no partial rows. Do not use unqualified
phrases such as `expected coverage`, `covered`, or `complete` for a GenAI surface
unless the related row is fully closed by the matrix.

When the source audit declares `**GenAI ownership detected:** Yes`, or a legacy
source audit contains `## GenAI Readiness`, write
`## GenAI Readiness Closure` in `.observe/otel-instrumentation.md` after
`## Audit Gap Closure`. Copy every `Surface` and its complete `Required Signals`
cell from the audit readiness table, then record `Implemented / proven`,
`Tests`, `Remaining signals`, and `Result`. Use one row per audit surface and
do not merge or omit partial, deferred, or owner-mapped surfaces. Use `Working`,
`Partial`, `Not working`, `Not proven`, `Not configured`, `Deferred`, or
`Owner-mapped`. `Working` requires `Remaining signals` to be exactly `None`;
all other results must name the remaining signal, blocker, or external owner.
Omit the section only when the source audit explicitly declares `No`. Treat a
legacy `GenAI` row in `## Audit Evidence` without a readiness table as an
invalid source audit that must be regenerated, not as permission to omit the
closure.

If `.observe/otel.md` contains `## GenAI Readiness` rows with `partial` or
`missing` status and the user asked to instrument, treat those rows as an
approved request for custom GenAI readiness instrumentation. Do not stop after
auto-instrumentation and do not ask the Step 4 custom-instrumentation question
for GenAI gaps that the repo clearly owns.

### Audit-Driven Gap Closure

Treat the prioritized `## Gaps` table as the implementation queue, not report
background:

- A normal `$otel-instrument` run addresses every safe app-owned `required`
  row whose instrument mode is `default`.
- A request to fix all gaps also addresses safe app-owned `recommended` rows
  whose instrument mode is `fix all`.
- `manual decision` rows are never silently implemented. Record the owner,
  prerequisite, or explicit choice needed.
- An explicit narrower user scope takes precedence. Keep all untouched rows in
  `Audit Gap Closure` and `Remaining Gaps` so scope reduction is visible.
- A row may require only verification rather than code. Run the mapped
  scenarios and do not invent a source change.
- Reconcile GenAI gap rows with `## GenAI Readiness`; the readiness row remains
  the detailed required-signal contract and the prioritized gap remains the
  user-facing work item.

Build an internal closure matrix before editing:
`area -> priority -> required fix -> instrument mode -> planned action ->
verification scenarios`. Update it after validation and verification. Do not
mark a row `Working` merely because code changed or a shared helper test
passed. Closure requires the source change or proven existing implementation,
the applicable project-runtime validation gate, and `$otel-verify` proof at the
audit scenario's proof level. In particular, execute every named route, span
call site, metric path, log pipeline, and duplicate-prevention scenario the row
references.

### Implementation Report Contract

For every instrumentation run, create or update
`.observe/otel-instrumentation.md`. Do not update `.observe/otel.md` as a
change log. Treat `.observe/otel.md` as the source audit input only unless the
user explicitly asks for a fresh audit.

When no audit report exists, still write `.observe/otel-instrumentation.md`
with service/runtime evidence, scoped implementation changes, validation gates,
verification results or handoff, and explicit remaining gaps. Do not fabricate
a full audit.

The instrumentation report must be reader-first:

```markdown
# OTel Instrumentation Report: <service>

**Result:** Pass | Partial | Fail | Blocked
**Source audit:** `.observe/otel.md` | not found
**Verification report:** `.observe/otel-verify.md` | not run | blocked
**Detector report:** `.observe/detectors.md` | not requested | blocked

## Executive Summary
## Flow
## Files Changed
## Signals Changed
## Audit Gap Closure
<!-- Include the next section only for a GenAI source audit. -->
## GenAI Readiness Closure
## Validation Gates
## Verification Handoff / Results
## Detector Handoff / Results
## Remaining Gaps
## Next Steps
```

`Signals Changed` replaces the old audit delta. Include a signal-level table:

| Signal type | Added | Modified | Removed | Evidence | Verification status |
|---|---|---|---|---|---|
| Traces/spans | exact span names or `None` | exact changes or `None` | exact removals or `None` | source paths + tests/harnesses | verified/partial/not run/blocked |
| Metrics | exact metric names or `None` | exact changes or `None` | exact removals or `None` | source paths + tests/harnesses | verified/partial/not run/blocked |
| Logs/events | bridge/event names or `None` | exact changes or `None` | exact removals or `None` | source paths + tests/harnesses | verified/partial/not run/blocked |
| Runtime/config | service/exporter/env/startup settings or `None` | exact changes or `None` | exact removals or `None` | startup/config paths | verified/partial/not run/blocked |
| Dependencies | OTel packages or `None` | version/package changes or `None` | removed packages or `None` | manifest/lockfile paths | verified/partial/not run/blocked |

Do not claim a removal unless the previous report or git diff proves the signal
or config existed and the current source proves it was removed. Use `None` for
empty cells. The final response must summarize `Signals Changed` by signal
type, distinguish added, modified, removed, and unchanged signals, and point to
`.observe/otel-instrumentation.md`.

`Audit Gap Closure` is the reader-facing reconciliation with the source audit:

| Priority | Gap | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|---|
| required | exact audit `Area` value | concrete code/config change or `No code change` | scenario IDs and test mode | Working / Not working / Not proven / Not configured / Deferred | direct evidence or exact blocker |

Use one row per prioritized audit gap. Keep `Not working` distinct from `Not
proven`: the former requires an executed failed check, while the latter means
the required scenario did not run or lacked a prerequisite. Use `Not
configured` when requested implementation is absent. Use `Deferred` only for
an explicit scope choice, owner, prerequisite, or `manual decision` row. When
there is no source audit, write `No source audit gap table was available.`

For a GenAI audit, `GenAI Readiness Closure` is the detailed signal-level
reconciliation and `Audit Gap Closure` remains the prioritized user-facing work
queue. Do not treat one as a substitute for the other.

Derive the report-level `**Result:**` from both closure tables. Do not use
`Pass` when any audit-gap row is `Not working`, `Not proven`, or
`Not configured`, or when any GenAI readiness row is `Partial`, `Not working`,
`Not proven`, or `Not configured`. Use `Partial` when meaningful proof passed
but any such row remains. `Deferred` and `Owner-mapped` may coexist with Pass
only when the exact external owner or explicit scope decision is recorded.

When a source audit exists, run the dependency-free closure validator bundled
with this skill after writing the instrumentation report:

```bash
python3 scripts/validate_gap_closure.py \
  .observe/otel.md .observe/otel-instrumentation.md
```

Resolve `scripts/validate_gap_closure.py` relative to this skill directory. If
validation fails, repair the report or expose the missing audit row before
finalizing.

Also maintain `## Verification Handoff / Results` using the schema in
`./references/project-runtime-validation.md`. Record the selected runtime,
exact local-safe commands and outcomes, changed source-to-scenario mappings,
the `$otel-verify` result/report path when run, and any blocked prerequisites.
This section is not proof of emitted telemetry unless a test, harness, or
collector actually observed it.

Older `.observe/otel.md` reports may contain `## Instrumentation Delta` or
`## Instrumentation Verification Handoff`; treat those sections as legacy input
only. Do not preserve or rewrite them into the audit report.

When the user asks broadly to apply GenAI readiness skills, improve GenAI MTTD,
or fix found GenAI gaps, treat the scope as **all discovered app-owned GenAI
gaps**. Do not select one representative or highest-value gap unless the user
explicitly narrows the scope to that gap.

Close code-evidenced AI pathway surfaces from `../references/genai-readiness.md`:
provider/model gateway, agent/workflow orchestration, tool/function execution
or AI-owned session/stream lifecycle including MCP when present, retrieval/RAG,
streaming response lifecycle, token/context pressure, safety/policy outcome,
prompt/response assembly, AI-derived data freshness, memory/context operations,
evaluation quality, content governance, framework bridge configuration,
app-computed cost, model/config rollout, and AI-owned cache/session state.

For evaluation quality surfaces, code evidence such as evaluator classes,
scoring functions, LLM-as-judge calls, feedback processors, `EvalScore` models,
faithfulness/similarity/expectation metrics, pass/fail labels, or quality
report exporters is enough to require eval instrumentation.
Metrics-only coverage does not satisfy selected-trace eval visibility. Add or prove
`gen_ai.evaluation.result` on the relevant workflow/evaluation span with
`gen_ai.evaluation.name`, `gen_ai.evaluation.score.value` when numeric scores
exist, `gen_ai.evaluation.score.label` when labels/verdicts exist, and safe
parent linkage. Also add or prove detector-ready score distribution, pass/fail
or violation count, sample count/rate, evaluator duration/error/no-data, and
freshness by low-cardinality workflow/model/evaluation name. If the service
only emits eval counters, histograms, logs, or report files, keep the evaluation quality surface partial
and name the missing span-level eval event and remaining detector metrics.

For MCP, JSON-RPC, and tool dispatch, normalize request metadata before adding
attributes or metric dimensions. Never record JSON-RPC request IDs, raw request
IDs, session IDs, trace IDs, user/account/tenant IDs, raw tool arguments, raw
payloads, prompts, completions, or retrieved content as metric dimensions.
Use stable method names only from an allowlist or from known route/tool registration; otherwise record a low-cardinality method family such as
`known_tool`, `unknown_method`, `invalid_request`, or `unsupported_method`.

Prefer detector-ready metrics and span attributes for outcome, duration,
timeout, retry, rate-limit, fallback, active AI-owned sessions/streams, close
reason family, send/write failure, freshness, empty/low-confidence retrieval,
token budget, prompt build failure, response parse failure, AI-derived data
freshness, prompt/tool schema version, model/config readiness,
model/config compatibility, expected-vs-running model/config state, truncation,
rejection, LLM-call fanout, tool-call fanout, evaluation score/outcome,
memory hit/miss or staleness, content capture mode/redaction, app-owned cost
source, and version dimensions when the service can observe them accurately.
Use OTel GenAI semconv names when possible: `gen_ai.evaluation.result`,
`gen_ai.evaluation.name`, `gen_ai.evaluation.score.value`,
`gen_ai.evaluation.score.label`, safe `gen_ai.evaluation.explanation`, memory
operation names such as `search_memory`, `create_memory`, `update_memory`,
`upsert_memory`, and `delete_memory`, and opt-in content attributes such as
`gen_ai.input.messages`, `gen_ai.output.messages`,
`gen_ai.system_instructions`, `gen_ai.retrieval.documents`,
`gen_ai.retrieval.query.text`, `gen_ai.tool.definitions`, and
`gen_ai.tool.call.arguments`. Treat framework bridges as covered only when
OTel-compatible GenAI semconv output and privacy settings are proven. Treat cost
as custom app-owned instrumentation only when the app owns an accurate pricing map; otherwise owner-map the billing or provider source. Generic non-AI runtime,
platform, or job surfaces are out of scope for this GenAI section unless source
evidence shows they carry or block the AI pathway.
If GenAI incident evidence depends on missed, flapping, auto-resolved, or no-data alerts, record detector reliability evidence as a `$splunk-configure`
handoff instead of adding app metrics for alert lifecycle behavior.

For AI-owned streaming generators, WebSocket/SSE handlers, callback bridges,
or protocol send loops, do not call stream lifecycle coverage complete without
a send/write failure signal. Add a counter, span event, or low-cardinality
outcome attribute for send/write failure when app code can observe it; otherwise
owner-map the missing source explicitly to the framework/server/platform.

For token/context pressure gaps, `gen_ai.client.token.usage` plus a
context-window usage gauge does not close a broader token-pressure gap unless
the audit contract only requires those two signals. If `required_signals`
include context budget percent, truncation rate, token-limit errors,
prompt/tool schema size, LLM call count per turn, or tool call count per turn,
mark the row partial until each signal is implemented, proven, or owner-mapped.
When the user broadly asks for GenAI readiness without a preexisting audit
contract, treat token/context pressure as requiring the same concrete signal
check: token usage, context budget percent, truncation, token-limit errors,
prompt/tool schema size or safe proxy, LLM-call count, and tool-call count when
the app can observe them.
Use this exact style when only token and context-window usage were added:
`Partial: token usage and context window added; truncation, token-limit error, prompt/tool schema size, and LLM-call fanout remain missing.`

If prompt/tool schema size cannot be measured safely, add a low-cardinality
detector-ready proxy metric such as schema JSON length bucket, schema field count,
prompt template length bucket, or tool count when the app can observe it.
Span attributes like prompt template version, schema version, or one-off schema
metadata help traces but do not close prompt/tool schema size pressure by themselves. If no safe metric or detector-ready existing signal exists, the
closure matrix and final response must keep prompt/tool schema size in
`remaining_signals` with the owner and missing source. Do the same for LLM-call
and tool-call fanout: implement per-workflow counts when observable, prove an
existing signal, or keep them explicitly partial.

Final summaries, PR descriptions, and audit updates must not omit residual
truncation, token-limit, prompt/tool schema size, LLM-call fanout, or
tool-call fanout gaps when they were in the audit contract or when broad GenAI
readiness instrumentation discovered the token/context surface.

For tool/function execution, GenAI spans alone do not satisfy detector-ready
tool coverage. When app code observes tool execution, add or prove a
tool-specific duration histogram and tool error/timeout counter using a stable
tool name and low-cardinality failure class. If only spans are safe, keep tool
latency/error metrics in `remaining_signals` and do not claim detector-ready
tool coverage.

Do not call GenAI instrumentation complete when an app-owned provider/model,
workflow, tool/function execution or AI-owned session/stream including MCP when
present, retrieval, streaming, token/context, safety/policy, prompt/response,
AI-derived data, memory/context, evaluation quality, content governance,
framework bridge, app-computed cost, model/config rollout, or AI-owned
cache/session surface remains only listed as a follow-up, unless the user
explicitly narrowed scope.

### 2. Dependencies

Add the OpenTelemetry SDK and auto-instrumentation packages for the detected language. Load the appropriate reference file:

| Language | Reference | Key packages |
|----------|-----------|-------------|
| Python   | `./references/languages/python.md` | `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, framework instrumentation packages |
| Node.js  | `./references/languages/node.md` | `@opentelemetry/sdk-node`, `@opentelemetry/instrumentation-http`, `@opentelemetry/exporter-metrics-otlp-http`, `@opentelemetry/sdk-metrics`, detected framework instrumentation packages |
| Java     | `./references/languages/java.md` | OTel Java agent (javaagent JAR) |
| Go       | `./references/languages/go.md` | `go.opentelemetry.io/otel`, `go.opentelemetry.io/contrib` |

### 3. Instrument

Apply auto-instrumentation first, then add manual spans for key business operations. Read the language-specific reference for exact patterns.

**Critical for APM error tracking:**
- Set `otel.status_code` to `ERROR` on failures -- this is how APM backends identify errors
- For HTTP server spans, 5xx responses set ERROR automatically per OTel semantic conventions
- For custom spans wrapping business logic, explicitly set error status on exceptions
- Reuse the app's current startup entrypoint instead of replacing it with a new Docker-only path
- For Python, Node.js, and Java, prefer preload or agent wrappers plus env vars over large code refactors when auto-instrumentation already covers the framework
- For host/native runtimes, default OTLP endpoints to loopback (`http://localhost:4318`) unless the existing platform already provides a collector address
- For Python web services, do not satisfy implementation by only changing a Makefile, Docker command, or shell wrapper. Add an explicit setup module such as `otel_setup.py` and wire the app entry point to call it before framework instrumentation is activated.
- For Java/Spring Boot, prefer the OpenTelemetry Java agent. The final response must state the service-name setting (`OTEL_SERVICE_NAME` or `otel.service.name`), OTLP endpoint setting (`OTEL_EXPORTER_OTLP_ENDPOINT` or `otel.exporter.otlp.endpoint`), and that the agent provides HTTP server spans plus request duration metrics.

#### Implementation Rules

- Use only official OpenTelemetry packages (`go.opentelemetry.io/otel`, `go.opentelemetry.io/contrib`, `@opentelemetry/*`, `opentelemetry-*`). Do not use community or third-party OTel wrappers. The only exceptions are library-maintained integrations where no official package exists (e.g. `go-redis/redisotel`, `XSAM/otelsql`).
- Do not initialize the SDK more than once per process.
- Find any existing OTel setup before adding new code. Extend it. Treat lazy
  provider helpers and providers initialized on first instrument creation as
  existing setup even when the startup wrapper itself contains no OTel call.
- Keep one global provider per signal. When adding traces/logs around an
  existing custom metrics provider, consolidate resource/exporter ownership or
  adapt the helper to the shared provider; never let auto-instrumentation and
  app code race to call `set_meter_provider`.
- Preserve operator resource values. Merge app defaults only for absent keys;
  do not overwrite `OTEL_SERVICE_NAME`, `deployment.environment`,
  `deployment.environment.name`, or `service.version` from
  `OTEL_RESOURCE_ATTRIBUTES`. Add a focused resource-merge test and assert the
  effective resource in live OTLP evidence.
- Resolve the exporter per signal as an endpoint/protocol/path tuple. Pair gRPC
  with the gRPC receiver (commonly `4317`) and `http/protobuf` with an HTTP
  signal path such as `4318/v1/metrics`. Do not assume one generic endpoint
  configures every exporter. A successful trace export does not prove metrics
  or logs; exercise each configured signal and repair protocol errors before
  reporting it as working.
- For Java trace wiring, DI binding, and provider rules, follow `./references/languages/java.md` (Implementation Rules section).
- Place OTel initialization code in a separate file.
- Minimize changes to existing code. Do not move functions between files.
- Do not create spans for trivial helpers. Only span real diagnostic boundaries.
- Set span status to ERROR and call recordException on failed operations.
- When a framework-specific auto-instrumentation package only provides spans (not HTTP server metrics), wrap the outermost handler with `otelhttp.NewHandler` (Go) or equivalent to ensure `http.server.request.duration` and `http.server.active_requests` are emitted. Consult the Framework Selection Guide in the language reference for the correct wrapping pattern.
- HTTP server instrumentation must produce request-duration metrics as well as
  spans. Prefer the current stable metric `http.server.request.duration`. When
  the installed SDK requires a semantic-convention stability opt-in, set it in
  the launch environment before importing or constructing the instrumentor.
  Accept `http.server.duration` only when the installed SDK truly emits the
  legacy name and record that exact runtime evidence; never claim both names.
- For local, Docker, and eval-style runtime checks, configure metric export to flush quickly. When constructing a metric reader manually, use the language equivalent of `OTEL_METRIC_EXPORT_INTERVAL` with a safe local default of `1000` ms and `OTEL_METRIC_EXPORT_TIMEOUT` with a safe local default of `500` ms instead of relying on SDK defaults.
- Strictly adhere to OTel [semantic conventions](https://opentelemetry.io/docs/specs/semconv/) for span and metric naming and attributes for domains where such semantic conventions are defined.
- For domains where OTel semantic conventions exist, emit required spans and metrics only, with required attributes only. Do not emit spans or metrics that are marked optional, do not include attributes that are marked optional. Do not invent custom spans, metrics or attributes in domains where OTel semantic conventions exist.
- For GenAI/LLM code, follow `../references/genai-readiness.md`: create
  baseline distributed tracing plus OTel GenAI spans for inference,
  `invoke_agent`, `invoke_workflow`, `plan`, `execute_tool`, `retrieval`, and
  memory operations where code evidence exists; emit
  `gen_ai.client.operation.duration` and
  `gen_ai.client.token.usage` when the data is available; use stable tool names;
  add low-cardinality `error.type`; and avoid raw prompt, completion, retrieved
  content, memory record, tool argument, evaluation explanation, user, tenant,
  session, task, request, trace, or raw URL values in metric dimensions.
- Prove every custom metric's exact name, unit, instrument type, and complete
  emitted dimension sets. Lifecycle-specific counters must retain their
  specific error class; generic terminal errors must not overwrite earlier
  token-limit, truncation, timeout, provider, or tool classifications. Do not
  attach transient terminal outcome/error dimensions to intermediate gauges or
  size measurements unless the metric contract explicitly requires them.
- For GenAI/LLM code, apply the `Single-Source GenAI Span Contract` before
  adding manual spans. Inventory framework/vendor bridges, provider SDK hooks,
  callbacks, middleware, auto-instrumentors, and existing app spans that can
  emit GenAI telemetry. Choose one canonical GenAI span source per logical
  operation: workflow, agent, model call, tool call, retrieval, memory operation, or
  evaluation result. If a framework/vendor bridge already emits correct GenAI
  semconv spans with lifecycle, privacy, model/tool attributes, and parent
  context, keep that bridge and add only missing workflow/agent context,
  aggregates, metrics, or owner mappings; do not create duplicate app-owned
  `chat` or `execute_tool` spans for those same operations. If app-owned spans
  are the canonical source, emit the complete app-owned span set and disable,
  opt out of, or suppress overlapping framework/vendor GenAI instrumentation
  using the discovered runtime mechanism, such as instrumentor names, bridge
  settings, callback configuration, or provider-hook opt-out flags. Do not
  hard-code this decision to one framework. Keep HTTP/database/runtime
  auto-instrumentation when it does not create duplicate GenAI nodes.
  When the process uses preload, agent, `opentelemetry-instrument`,
  `NODE_OPTIONS --require`, or another auto-instrumentation bootstrap, apply
  the suppression in the launch environment before the bootstrap runs. Update
  the actual startup surfaces the repo uses, such as Makefile targets, service
  runner scripts, Docker or Helm env, VS Code launch configs, procfiles,
  systemd units, shell env generators, or generated env scripts. App module
  code that mutates environment variables after import is only defense in depth
  and is not sufficient proof because framework hooks may already be
  registered.
  Verification or static proof must show one GenAI node per logical operation,
  no wrapper-only spans counted as tools, expected LLM/tool counts, stable
  model/tool names, and workflow/agent parent shape such as
  `invoke_workflow -> invoke_agent -> chat/execute_tool`. Required proof should
  name stable model/tool names explicitly.
- Preserve existing application stable business workflow identity when setting
  `gen_ai.workflow.name` and workflow span names. Prefer constants, function or
  handler names, workflow registrations, telemetry event names, docs, or prior
  trace names. Do not derive GenAI workflow names from HTTP routes, request
  resources, session/storage tables, or transport labels. If source evidence
  shows a workflow is named `assistant_v3_turn`, keep `assistant_v3_turn`;
  never rename it to `assistant_v3_session_turn`, `POST /v2/assistant/sessions`,
  or another route/session-derived value. If the app has no stable workflow
  identity, keep the HTTP route as the HTTP span and mark GenAI workflow
  coverage partial instead of inventing a low-cardinality workflow name.
  Do not invent names from HTTP routes or session-derived labels.
- Preserve existing application stable agent identity when setting
  `gen_ai.agent.name` and agent span names. Prefer framework agent names, agent
  factory names, class names, registration names, callback owner names, docs, or
  prior trace names. If source evidence shows a DeepAgents-backed agent, use the
  discovered stable agent identity such as `deepagents`; never rename it to
  `assistant_v3_agent`, `assistant`, `agent`, or another generic service-derived
  wrapper name. If the app has no stable agent identity, keep agent coverage
  partial instead of inventing one.
- For app-owned LLM/model calls, apply the `LLM Inference Lifecycle Contract`.
  Do not satisfy inference coverage with workflow-level token accounting,
  final usage events, token usage, or model names only on the workflow span.
  Add or prove a real model-call lifecycle span at the provider request
  boundary: start before the call or stream starts, end after the
  response/terminal stream event, and end with error status for exceptions,
  cancellations, provider timeouts, or stream-close failures. In LangChain,
  LangGraph, DeepAgents, callback, or event-stream based systems, hook
  `on_chat_model_start`, `on_chat_model_end`, and `on_chat_model_error` or the
  equivalent lifecycle callbacks. In direct SDK/model-gateway code, wrap the
  provider call or streaming generator. The span must carry
  `gen_ai.operation.name` such as `chat`, `generate_content`, or
  `text_completion`, `gen_ai.provider.name`, `gen_ai.request.model` when known,
  `gen_ai.response.model` when known, and token usage on that inference span
  when provider usage is available.
- Preserve the owning workflow/agent context for event-derived GenAI spans. In
  callback, stream, LangChain, LangGraph, or DeepAgents integrations, capture
  the workflow/agent context and use it when starting chat/model and tool
  spans. Do not let callback-created `chat` or `execute_tool` spans attach to a
  generic HTTP root span as siblings of the workflow. A representative trace
  should prove a shape such as `workflow -> chat`, `workflow -> execute_tool`,
  and follow-up `workflow -> chat` or `agent -> chat` edges.
- Capture that workflow/agent context before opening long-lived helper/setup
  spans such as memory store, checkpointer, database session, stream-writer,
  resource setup, or lifecycle wrappers. These helper spans must not become the
  parent for model/tool lifecycle spans. Event-derived `chat` and `execute_tool`
  spans must use the captured workflow/agent context, not whichever helper span
  happens to be current when a callback is translated. Store the workflow/agent
  span object or context explicitly so stream cleanup writes aggregates to that
  owner even if the current span has changed.
  Use this rule for memory store, checkpointer, database session, stream-writer,
  or resource setup paths: helper spans must not become the parent; capture the
  workflow/agent context before opening helper spans, start event-derived `chat`
  and `execute_tool` spans with that captured context, and write aggregate
  counters to the workflow span, not to whichever current span is active.
- In async generator, SSE, WebSocket, ping-loop, timeout-wrapper, or task handoff
  paths that advance a stream with `create_task`, `wait`, `anext`, or equivalent
  scheduling, do not keep an OpenTelemetry current-span context manager open
  across yield/task boundaries. Start the workflow/agent span with an explicit
  parent context, store a workflow span/context handle, pass that handle into the
  callback/event translator, and end the workflow span manually after stream
  cleanup.
- When the captured workflow/agent context must travel through a request, turn
  input, event payload, callback state, or config object that may be
  immutable/frozen or owned by a framework, do not mutate that carrier in place.
  Treat a carrier as immutable/frozen when source evidence shows frozen or
  readonly declarations, record/value types, no mutation API, framework request
  immutability patterns, or existing code constructs new copies instead of
  mutating.
  Use the app's idiomatic copy/replacement API: Python `dataclasses.replace`,
  `attrs.evolve`, pydantic `model_copy(update=...)` or v1 `copy(update=...)`;
  Java records, builders, or copy constructors; TypeScript object spread,
  explicit `Readonly<T>` replacements, or `structuredClone` only for plain-data
  carriers and never for live OTel `Context` or `Span` handles; Go value copies
  with explicit field replacement; or the framework's request clone/with-context
  API. If no safe copy path exists, use a separate invocation-scoped sidecar
  context: a local object, context variable, request-scoped map, or callback
  state keyed to the invocation lifecycle and cleared after cleanup. Do not key
  sidecar context by raw user, tenant, session, request, or trace IDs. Add a
  focused test, or explicit static proof when the repo has no test harness, that
  proves the parent context is passed downstream and the original immutable
  input remains unchanged; for Python, guard against `FrozenInstanceError`
  regressions when a frozen dataclass or model is present.
- Put aggregate selected-trace GenAI attributes on the workflow span or
  most specific owning GenAI span, not on a generic HTTP root span or generic server span.
  This includes `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`, `gen_ai.usage.total_tokens`,
  `assistant.llm.calls`, and `assistant.tool.calls`. The HTTP root can remain
  the server entrypoint, but it should not become the evidence for a GenAI flow
  card unless it is explicitly instrumented as the workflow span.
- If runtime telemetry verification is unavailable, perform a static
  instrumentation proof before claiming GenAI trace coverage: identify the
  model-call source file, the lifecycle hook or client wrapper, the created
  inference span name, required `gen_ai.*` attributes, parent-context handoff,
  aggregate-attribute placement, end/error path, and a focused test or compile
  check. If the proof shows only workflow-level usage attributes and no
  inference span, or chat/tool spans that are siblings of the workflow under a
  generic HTTP root span, keep the surface partial in `remaining_signals`.
- For local span-first trace explorers such as Obstudio, metrics alone are not enough
  for a selected-trace summary. When provider usage, model, tool,
  memory, evaluation, or fanout data is available, also set safe span attributes
  on the most specific GenAI span and aggregate to the workflow span when
  useful: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
  `gen_ai.usage.total_tokens`, `gen_ai.request.model`,
  `gen_ai.response.model`, service-owned LLM/tool call counts, stable
  `gen_ai.tool.name`, memory operation names, evaluation names/labels, and
  low-cardinality `error.type`.
- For assistant, agent, or streaming workflows, instrument first non-ping event
  or first chunk latency, timeout, cancellation, disconnect, close reason
  family, and send/write failure. Normalize timeout classes such as
  `first_event_timeout` instead of relying only on framework exception class
  names, while still recording the exception on the span.
- For custom attribute names use `{domain}.{noun}.{adjective}` format.
- Span names must be low-cardinality (no IDs, no variable path segments).
- Metric attributes must avoid high cardinality.
- Preserve existing env-var patterns for telemetry config instead of hardcoding endpoints.
- If the app is a library, provide an opt-in setup path rather than forcing SDK initialization on import.
- Keep the codebase idiomatic. Match the repo's dependency manager, config style, and lifecycle patterns.
- Obtain OTel Tracer, Meter once during startup and reuse it. Do not call `getTracer` or `getMeter` in hot paths.
- Create metric instruments once during startup and reuse them. Do not create instruments in hot paths.
- Metric instruments must be created with appropriate unit and description parameters.

#### Log Export Scope

- Classify application logs as `correlation-only`, `otlp`, or `not requested`
  during preflight.
- Do not treat MDC/trace-context fields in stdout as OTLP log export.
- Do not silently add an OTLP log bridge when the user or audit contract does
  not require explorer-visible logs; log export can affect cost, privacy, and
  duplicate ingestion.
- When OTLP logs are required, configure the official bridge/exporter for the
  detected logging stack and add proof for body/category, severity,
  trace/span correlation, redaction, resource identity, and OTLP visibility.
- Report absent requested export as `Not configured`, not `Not proven`.
- Apply privacy checks to the final logging pipeline: formatter fields,
  adapters, MDC/context variables, framework access logs, and exception
  rendering. Removing IDs from one `logger.*` call is insufficient when a
  formatter or access logger adds them back. Keep raw request/user/tenant/
  session IDs, raw dynamic URLs, exception text, and tracebacks out of the
  approved application-log surface unless the policy explicitly permits them.

#### Language-Specific Musts

Python:
- Add explicit dependency entries for `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, and each detected framework/client instrumentation package.
- Create a separate setup file such as `otel_setup.py`, `telemetry.py`, or `instrumentation.py`.
- Configure a shared `Resource.create({"service.name": ...})`, trace provider,
  meter provider, and requested log provider/exporters in that setup file only
  for signals the process does not already own. If a source-owned provider
  exists, move or adapt its construction into the shared setup while preserving
  existing wrappers, views, file-export modes, and tests; do not create a
  second provider.
- Import and call the setup function from the app entry point before creating or instrumenting the app.
- For Flask, call `FlaskInstrumentor().instrument_app(app)`.
- For FastAPI, call `FastAPIInstrumentor.instrument_app(app)` immediately
  after app construction and before lifespan/startup begins. Do not first call
  it inside lifespan: Starlette/FastAPI middleware installation is too late
  after the application has started serving.
- For Celery, call `CeleryInstrumentor().instrument()` in the worker path.
- Keep existing Docker/Compose/Makefile commands, but update them only as the startup surface for the explicit setup, not as a replacement for app wiring.

Node.js:
- Add `@opentelemetry/instrumentation-http` explicitly for HTTP server spans.
- Add the detected framework instrumentation explicitly, for example `@opentelemetry/instrumentation-express` for Express.
- Add `@opentelemetry/exporter-metrics-otlp-http` and `@opentelemetry/sdk-metrics` when wiring SDK-based metrics.
- Configure `PeriodicExportingMetricReader` with `exportIntervalMillis: Number(process.env.OTEL_METRIC_EXPORT_INTERVAL || 1000)` and `exportTimeoutMillis: Number(process.env.OTEL_METRIC_EXPORT_TIMEOUT || 500)` so HTTP duration metrics export during short runtime checks.
- Use the current `NodeSDK` metric reader option exactly as shown in the Node reference. Do not substitute `metricReaders` for `metricReader` unless the installed SDK version documents that option.
- Do not rely on `@opentelemetry/auto-instrumentations-node` alone when specific framework packages are expected.
- In the final response, name the updated preload command (`--require` or `--import`), the packages added, and that HTTP server spans plus request-duration metrics are expected.

Go:
- For HTTP services, use `otelhttp.NewHandler` as the outermost server handler so request-duration metrics are emitted, even when router-specific middleware is also used for route-aware spans.
- Configure `sdkmetric.NewPeriodicReader` with an interval derived from `OTEL_METRIC_EXPORT_INTERVAL`, defaulting to `1000` ms, and a timeout derived from `OTEL_METRIC_EXPORT_TIMEOUT`, defaulting to `500` ms, for local runtime checks.
- In the final response, state the server handler wrapping, service-name setting, OTLP endpoint setting, and that HTTP server spans plus request-duration metrics are expected.

Java:
- Use the Java agent for Spring Boot unless custom business spans are explicitly requested.
- Avoid adding SDK dependencies to `pom.xml` for basic Spring Boot coverage.
- Follow `./references/languages/java.md` Implementation Rules for DI binding, provider reuse, and dependency checks.
- Wire the agent through the existing startup surface, `JAVA_TOOL_OPTIONS`, or a documented run command.
- In the final response, explicitly mention the agent setup or path,
  `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, HTTP server spans, and
  `http.server.request.duration`.

### 4. Custom Instrumentation

After auto-instrumentation is wired up, prompt the user:

> Auto-instrumentation is configured. Would you like me to add custom spans or metrics for your business logic?

Then wait for the user's answer.

Skip this prompt when the user already asked for GenAI/LLM workflow
instrumentation, a specific GenAI custom signal, when the Audit-Driven GenAI
Readiness path applies, or when prioritized audit rows are already in scope by
the Audit-Driven Gap Closure rules. In those cases, the user's request and
audit gaps are the approval context; implement the safe scoped signals and
clearly list any unpatched prerequisites.

- **If no**: proceed to the project-runtime validation gate (Step 5).
- **If yes**: analyze the codebase for high-value custom instrumentation points:
  - Error handling paths that catch and handle exceptions
  - Key business operations (payments, orders, user registration, etc.)
  - External calls not covered by auto-instrumentation libraries
  - Background workers and scheduled jobs
  - Cache interactions without auto-instrumentation support
  - GenAI/LLM workflow boundaries: workflow span, agent/workflow invocation,
    LLM inference, tool/function execution, MCP method dispatch when present,
    retrieval, fallback, token usage, model/config readiness, prompt/response
    parse outcome, safety/policy outcome, AI-derived data freshness, and
    AI-owned session/stream lifecycle when code evidence exists
  - Suggest specific spans and metrics with names, attributes, and rationale
  - Apply after user approval

### 5. Validate The Implementation

Read and follow `./references/project-runtime-validation.md`. Local,
deterministic validation is the default completion gate; do not ask for
permission to run a project-configured syntax, compile, typecheck, import, or
focused test command. Do not require full app startup, Docker, credentials,
live providers, or an OTLP collector for this gate.

At minimum:

1. Probe the selected project runtime and record the version actually used.
2. Run static/config checks for changed scripts and manifests, including
   `git diff --check` when Git is available.
3. Compile, typecheck, or import every affected application module with the
   selected project runtime.
4. Run the smallest existing focused tests that exercise changed code. For
   custom spans, metrics, or logs, add or update a focused repo-native test
   when the existing test framework provides a practical in-memory OTel seam.
   Build an exact signal closure matrix and execute every added or modified
   span name and metric call site. Do not infer coverage for create, batch,
   update, delete, route, tool, or workflow names solely from a shared helper's
   test. Parameterize tests when those call sites share setup.
   Map these executions back to every in-scope `Audit Gap Closure` row and its
   declared verification scenarios.
5. Confirm filtered tests actually ran by checking test output or generated
   reports; a no-match guard is reactor plumbing, not test evidence.
6. If a validation failure is caused by instrumentation changes, repair it and
   repeat the affected gate until it passes. Do not finalize with a compile,
   type, syntax, or import error on a modified line.

Skip command execution only when the user explicitly forbids verification or
states that an external eval owns all checks. In that case, still perform
source-level review, record `Not run` in the handoff, and do not describe the
instrumentation as verified or complete. If the configured runtime or declared
dependencies are unavailable, record `Blocked` with the exact prerequisite;
do not fall back to an incompatible global runtime.

After the implementation gate, invoke or apply the `$otel-verify` workflow
unless the user explicitly opts out or a concrete prerequisite blocks it. The
instrumentation goal is not done until code viability is known and verification
has run, been explicitly skipped by the user, or is documented as blocked.

Record the verification result and `.observe/otel-verify.md` path in
`.observe/otel-instrumentation.md`. If verification cannot run, record the exact
blocking prerequisite and do not describe the instrumentation as verified.

When verified metric evidence exists and the user requested detectors,
alerting, monitors, Splunk configuration, or `$splunk-configure`, invoke or
apply that workflow and include the detector/configure verification result in
the instrumentation report.

When any claim depends on auto-instrumentation startup, framework route
resolution, automatic metrics, duplicate automatic-span prevention,
startup/exporter wiring, or runtime-installed OTLP logs, read
`../references/full-runtime-acceptance.md` and require its conditional full
runtime gate in the verification handoff. Attempt the gate without asking when
the repository provides a safe local profile or fixtures. Otherwise record the
exact prerequisite and keep those rows `Partial`, `Blocked`, or `Not proven`.

### 6. Enable Debugging in VS Code

This step is REQUIRED whenever `.vscode/launch.json` exists.

1. Check whether `.vscode/launch.json` exists.
2. If it exists, update at least one debug configuration for this service to include:
   - `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`
   - `OTEL_METRIC_EXPORT_INTERVAL=1000`
   - `OTEL_BSP_SCHEDULE_DELAY=100`
3. After editing, report which configuration was updated, the file path, and whether the env vars were added or already present.
4. If `.vscode/launch.json` exists and you do not update it, stop and explain why.
5. If `.vscode/launch.json` does not exist, explicitly report: `No .vscode/launch.json found; Step 6 skipped.`

### 7. Finalize

- In the final response, separate file changes from verified outcomes
- State the selected project runtime, affected-module compile/type/import
  result, focused tests that actually ran, and the verification result or
  blocking prerequisite.
- Write `.observe/otel-instrumentation.md` and include a `Signals Changed`
  summary with added, modified, and removed traces/spans, metrics, logs/events,
  runtime/config, and dependencies. If no prior audit existed, state that the
  report establishes the implementation baseline.
- Include `Audit Gap Closure` counts by `Working`, `Not working`, `Not proven`,
  `Not configured`, and `Deferred`. Keep every source-audit gap visible even
  when the user narrowed scope.
- When the source audit declares GenAI ownership, include the complete
  `GenAI Readiness Closure` matrix and list every non-`Working` remaining signal
  in the final response.
- Include `$otel-verify` results and `.observe/otel-verify.md` path when run.
  If detectors/configuration were requested, include `$splunk-configure`
  outputs and `.observe/splunk-configure-verify.md` status when run.
- If verification is partial, say exactly what is working and what is still missing instead of reporting full success
- Never say `complete`, `working`, or `verified` when the mandatory
  compile/type/import gate failed, was blocked, or was not run. Use
  `implemented; verification blocked/not run` and name the prerequisite.
- Always include the service-name configuration, OTLP endpoint configuration, and which automatic spans/metrics are expected from the instrumentation.
- State the selected log scope and the full-runtime acceptance result whenever
  either is applicable.
- For GenAI work, state which OTel GenAI operations were instrumented, which
  GenAI metrics are expected, whether trace continuity should produce a nested
  workflow/agent/tool/chat/retrieval shape, and which privacy/cardinality limits
  were enforced.
- For GenAI incident-evidence work, include a concise coverage summary by
  incident class or repo surface: MTTD-improving, localization-only, or
  uncovered. Name any remaining provider/model, workflow, tool/function
  execution or AI-owned session/stream including MCP when present, retrieval,
  streaming, token/context, prompt/response, safety/policy, AI-derived data,
  model/config rollout, or AI-owned cache/session owner that still blocks
  detector-ready coverage.

## Credential Safety

When the project uses or introduces env files:

1. **Ensure `.env` is gitignored before writing secrets**: Check `.gitignore` for `.env`. If it is missing, add it. Never allow a `.env` with access tokens to be committed.
2. **Create or update `.env.example` with safe placeholders**: Do this whenever the instrumentation introduces env vars. `.env.example` must never contain real tokens.
3. **Verify no tokens in tracked files**: Search tracked config files for access tokens and confirm no real token values appear in files that would be committed.

## Scope

- **New apps**: Full scaffold matching the current runtime shape: instrumentation, SDK init, env var config
- **Existing apps**: Incremental -- detect what's already present, add only what's missing
