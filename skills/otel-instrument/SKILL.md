---
name: otel-instrument
description: >-
  Add OpenTelemetry observability to applications using auto-instrumentation
  and optional custom spans/metrics, write separate instrumentation Markdown
  and HTML reports,
  and run verification unless explicitly skipped or blocked. Use when the user
  types $otel-instrument, asks to "add OTel", "add tracing", "add metrics",
  "implement observability", "wire up telemetry", "instrument this service",
  passes selected executable audit finding IDs with --ids, supplies
  .observe/otel-selection.json,
  asks to add a specific custom signal like "add a metric to track queue
  depth", "add a span for payment processing", "track error rate for X", or
  asks to add signals that make incidents faster to detect or localize, or asks
  to instrument GenAI/LLM workflows with OpenTelemetry semantic conventions.
---

# Instrument

Add OpenTelemetry observability to applications using auto-instrumentation and optional custom spans/metrics.

Prefer the application's current runtime shape. If the project already uses Docker/Compose or Kubernetes, fit instrumentation into that path. If the user does not have Docker or does not want Docker, do not introduce containers just for observability; use the host/native runtime patterns.

Do not load `../references/report-flow-contract.md` as an up-front
prerequisite. For a canonical JSON flow, read
`./references/json-approval-handoff.md`; it is the scoped instrumentation and
reader-report contract. For a direct no-audit flow, load
`./references/instrumentation-report.md` only when producing the report.
Load `./references/finalization.md` once at the finalization boundary. Read the
shared report-flow contract only when a conditional downstream workflow
explicitly requires one of its additional field or rollup rules.

Resolve every reference and script path from the directory containing the
loaded `otel-instrument/SKILL.md`. Here, `../references/<file>` means the shared
sibling under the parent skills directory, while `references/<file>`,
`./references/<file>`, and `scripts/<file>` are local to `otel-instrument`.
Never probe the service root or repository root for these paths.

When this workflow invokes its `$otel-verify` child, resolve that skill exactly
once as
`<directory-containing-loaded-SKILL.md>/../otel-verify/SKILL.md`. Treat that
sibling as the only authoritative verifier because it belongs to the same
installed skill bundle as this workflow. Never search `$CODEX_HOME`, a home
directory, the service root, or the repository root for another verifier, and
never compare alternate installed copies. If the exact sibling is absent,
record that the installed Obstudio skill bundle is incomplete; do not silently
substitute a global or stale verifier.

## Workflow

### 1. Preflight

Before editing anything, ground the plan with repo evidence:

#### Canonical Audit And Selection Gate

When `.observe/otel-audit.json` exists, treat it as the canonical audit.
Executable scope may come from the audit report's embedded `review_selection`,
from a materialized `.observe/otel-selection.json`, or from exact IDs supplied
in the current request; when none are present and the user asks for bare or
broad instrumentation, use deterministic `select --all`. `.observe/otel.html`
is the audit and scope-planning surface. Never open or read an audit Markdown
report. Before any application-code,
dependency, runtime-config, or test edit, read and follow
`./references/json-approval-handoff.md`. Do not proceed without a validated,
nonempty executable selection. A valid answer-only handoff persists
`decision_answers` but authorizes no code edits.
Selection precedence is current-request exact `--ids`, then an existing or
adopted bound selection, then bare/broad `select --all`. Unless current-request
`--ids` already wrote a fresh selection, run the shared `adopt-selection` helper
as an idempotent preflight step before reporting a missing selection. If the
helper prints `PASS:` or `wrote`, immediately run `validate-flow` and continue
the same `$otel-instrument` run; do not ask the user to move a download, save
again, or rerun instrumentation. If no saved selection exists and the request is
bare/broad, run `select --all`; if it prints manual-decision options, stop
before edits and present those exact `--decision OTEL-###=option-id` choices.
Never choose between mutually exclusive telemetry owners or paths. Stop before
edits only when the audit is invalid, stale, not broad enough to imply all
eligible work, or the bound/created selection has empty `approved_ids`.
Implement exactly the dependency-closed selected IDs.
Bind `.observe/otel-instrumentation.json` to the entire normalized selection
with `selection_sha256`, not only to its audit and executable IDs. This digest
includes `decision_answers`; changing an answer invalidates older
instrumentation even when `approved_ids` is unchanged.
When no canonical audit exists, a direct, concrete user request is the
authorized scope and the direct no-audit workflow remains available. Do not
fabricate audit IDs or selection artifacts; recommend `$otel-audit` before
claiming audit-gap closure.

- Use the initial bounded file list as a size gate. When the service has at
  most 25 non-ignored files, exactly one dependency manifest, and no nested
  service root, take the direct small-repo path: inspect that file list, the
  manifest, entrypoint, and cited source directly, and do not run the inventory
  helper. For larger, multi-module, nested, or unclear repositories, run
  `python3 -I "<directory-containing-loaded-SKILL.md>/scripts/inspect_otel_project.py"
  "<service-root>" --output
  "<service-root>/.observe/tmp/otel-project-inventory.json"` before broad
  manual searches. Resolve the command
  directly from the directory containing the loaded `otel-instrument/SKILL.md`;
  do not probe a repository-root `references/` directory. On the inventory
  path, run one successful invocation; retry only to correct an invocation or runtime failure.
  Use its deterministic JSON to seed manifests/languages,
  entrypoint and route candidates, runtime candidates, startup/test surfaces,
  and categorized OTel source/config hits. Treat all hits as candidates, not
  proof of target-process reachability, runtime availability, or emission.
  Inspect `complete`, `warnings`, `skipped`, and `section_counts`, then read only
  needed JSON sections rather than dumping the full file. Reconcile cited files
  with the selected process. For a section whose truncation is zero in a
  `complete: true` inventory, do not repeat the same repository-wide `find` or
  broad `rg`; use focused source proof. Do not follow complete file/OTel
  sections with recursive `find`, `rg --files`, or a repository-wide
  OTel-pattern `rg`. The helper creates the output parent; do not pre-create it.
  Search manually for incomplete, skipped, unsupported, or truncated surfaces.
  If Python or the shared helper is unavailable, perform the preflight manually
  and record the exact failure. Record which discovery path was selected.

- Confirm the language and framework from actual dependency or source files.
  Immediately load exactly one matching language reference:
  `./references/languages/{python,node,java,go}.md`. Do not postpone this until
  after dependency commands and do not load unrelated language references.
- **Go standard-HTTP bootstrap gate:** first read `go.mod`, then follow the
  loaded Go reference's `Dependencies` section exactly. It owns the conditional
  fixed-bundle resolver, digest-bound plan, sibling-runner actions, serial
  validation, and terminal cleanup rules. Do not apply that branch to existing
  OTel pins, non-HTTP services, or dependency-free edits, and never reconstruct
  its commands from memory or an alternate skill copy.
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
  reachability from the selected process. For Python, reconcile the shared
  inventory's provider/exporter candidates with source. The older audit-owned
  Python topology scanner is a compatibility fallback only; do not run both
  scanners unless the shared inventory is incomplete.
  Existing ownership of any one signal makes this an incremental integration;
  it does not prove that the other signals are configured.
- When `.observe/otel-audit.json` exists, use only the validated selected
  findings and their referenced `verification.scenarios` and environments as
  the implementation and validation plan. Preserve every stable finding,
  scenario, and environment ID. Keep each `proof_level`; do not downgrade a
  `full runtime` scenario to focused call-site proof. Ignore `signal_flow`; it
  does not authorize or shape scoped instrumentation.
- When canonical JSON is absent, use only an explicit current user request and
  current source as direct scope. Do not fabricate audit IDs, selection state,
  or audit-derived gap closure.
- Detect incident-readiness surfaces. Search source and configuration for
  user-visible workflows, dependency clients, background jobs, queues/streams,
  data freshness, input complexity, synthetic/canary checks, auth/edge paths,
  capacity limits, and release/config context. When any are present or when the
  user asks for faster incident detection/localization, load
  `../references/incident-readiness.md`.
- When incidents, postmortems, tickets, alerts, or failure examples are supplied,
  use Incident-Evidence Mode from `../references/incident-readiness.md`: map
  each failure mechanism to the owning code or platform surface and classify
  the proposed signal as MTTD-improving, localization-only, or still uncovered
  before editing.
- Detect GenAI/LLM ownership. Search dependencies, config, and source for
  provider clients, model gateways, agent/workflow orchestration, tool/function
  dispatch, MCP when present, retrieval/RAG, model/deployment config, fallback,
  token usage, prompt/response assembly, AI-derived data jobs, AI-path
  synthetic/canary checks, and usage logging. When present, load both
  `../references/genai-readiness.md` and
  `./references/genai-instrumentation.md` before planning or editing.
  Do not load the instrument-specific GenAI reference for non-GenAI services.
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
- Confirm the planned `service.name`, `service.version`, and environment source.
  Also record available low-cardinality region, platform, image/artifact,
  config, and rollout sources. Prefer existing OTel semantic-convention or
  platform resource attribute names, including `deployment.environment.name`,
  `cloud.region`, `cloud.platform`, `container.image.name`, and
  `container.image.tags`. Treat `deployment.environment`,
  `deployment.region`, `deployment.platform`, and `container.image.tag` as
  legacy or custom input aliases only, not names to newly emit or reasons to
  duplicate the standard attributes.
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
- canonical audit ID and SHA-256, dependency-closed selected finding IDs
  (`approved_ids`) in audit order, and the
  validated selection path when `.observe/otel-audit.json` exists
- for Java, trace source of truth (see `./references/languages/java.md` Preflight section)
- incident-readiness surfaces and the workflow, dependency, input complexity,
  freshness, backpressure, synthetic/canary, auth/edge, capacity, and
  release/config signals to add or prove when the repo owns those surfaces
- incident-evidence coverage when failure examples are supplied: failure
  mechanism, owner, code surface, signal to add or prove, expected MTTD or
  localization impact, and remaining external owner
- GenAI workflow surfaces and the GenAI semantic-convention plus service-owned
  readiness signals to add, when the repo owns LLM, agent, tool/function, MCP,
  retrieval, streaming, model/config, token/context, prompt/response,
  safety/policy, AI-derived data, memory/context, evaluation quality, content
  capture, framework bridge, app-computed cost, or AI-owned state code
- GenAI incident coverage when GenAI incidents or AI pathway failures are
  supplied: failure mechanism, provider/model/tool/retrieval/config/prompt/
  AI-derived-data owner, signal to add or prove, expected MTTD/localization
  impact, and remaining non-code or dependency owner

State these preflight values together in one explicit progress note before the
first file edit. Do not defer `service.name` or environment ownership to the
final report.

### Fast Path: Targeted Custom Signal

If the user is asking for a specific signal ("add a metric for queue depth",
"track error rate on payments", "add a span for the indexing job") AND the
preflight scan finds OTel SDK already initialized:

1. Skip Steps 2-3 (dependencies and auto-instrumentation are already present).
2. Go directly to Step 4 (Custom Instrumentation) with the user's request as context.
3. Add only the requested signal — do not re-scaffold or re-wire existing setup.
4. Proceed to Step 5 (project-runtime validation gate).

When a canonical selection exists, this fast path still covers every selected
ID, including executable dependencies added by `select`; never reduce it to one requested
signal.

If the preflight scan finds no OTel SDK, tell the user auto-instrumentation
needs to be set up first and continue with the full workflow (Steps 2-3).

### Audit-Driven Incident Readiness

When the canonical audit contains partial or missing
`current_instrumentation.incident_readiness` rows, reconcile each row through
the selected finding with the same `area`. Treat the matched pair as one
implementation contract. The
readiness row names the surface and detection/localization impact; the gap row
names the complete required fix and instrument mode; its acceptance scenarios
name the code path, expected telemetry, proof level, and acceptance criteria.
Do not create a second gap ledger or silently synthesize missing fields. In a
direct no-audit request, derive readiness only from explicit scope and current
source.

If the user broadly asks to improve incident readiness or MTTD, resolve every
safe app-owned incident gap allowed by the audit modes to exact IDs and create
the selection before editing. Do not choose one representative gap unless the
user explicitly narrows scope. `manual decision` and `external follow-up` rows
cannot enter the selection or either executable ID list. A recorded
`decision_answers` choice may unlock only the matching executable rows, which
still require explicit selection. Track the named external owner outside
instrumentation; never guess either boundary.

Load `../references/incident-readiness.md` once for selected readiness work;
do not duplicate its signal catalog here. It owns concrete low-cardinality
workflow, dependency, input/freshness, queue/stream, auth/edge, capacity,
release/config, multi-process, Go-concurrency, focused-test, healthy-idle age,
and incident-evidence rules. Apply every source-evidenced surface it requires,
including `go test -race` when triggered, and preserve its
`MTTD-improving`, `localization-only`, external-owner, and no-placeholder
classifications.

Extend the internal Audit-Driven Gap Closure matrix with the readiness surface,
required signals, MTTD/localization classification, implemented or proven
signals, tests, remaining signals, and owner. A row cannot be `Working` while
any required signal is absent, merely listed as a follow-up, or supported only
by an unexecuted test. If no app-owned candidate can be patched accurately and
safely, add no placeholder instrument; owner-map the exact prerequisite and
keep the row `Deferred`, `Not configured`, or `Not proven` as appropriate.

### Audit-Driven GenAI Readiness

When the canonical audit declares GenAI ownership or direct source inspection
finds GenAI/LLM ownership in a no-audit request, read and follow
`./references/genai-instrumentation.md`. Treat its audit-driven closure,
implementation, verification, and finalization rules as part of this skill's
contract. Preserve the optional `## GenAI Readiness Closure` interaction owned
by the instrumentation-report reference and the custom-instrumentation prompt
trigger in Step 4.

When GenAI ownership is declared, write the authoritative top-level
`genai_closure` inventory in `.observe/otel-instrumentation.json` before
rendering its Markdown projection. Preserve audit surface order and the exact
`surface`, `required_signals`, and `owner`; record `implemented_proven`,
executed `tests`, durable `evidence`, `remaining_signals`, and a lowercase
closure `status`. Follow the field and rollup rules in
`../references/report-flow-contract.md`; never leave GenAI closure only in
mutable Markdown outside the instrumentation digest.

### Audit-Driven Gap Closure

Treat the validated dependency-closed selected finding set as the implementation queue, not
report background:

- Implement exactly the selected IDs plus executable dependencies added by
  `select`; never add unselected work. Priority orders the audit only and never
  authorizes instrumentation scope.
- Resolve broad instrumentation to exact audit IDs in `.observe/otel-selection.json` before editing.
- Reject a selection containing `manual decision` or `external follow-up` IDs,
  an unanswered manual dependency, an unknown answer, executable work outside
  the recorded option's `unlocks`, or work blocked by an external follow-up.
  `decision_answers` is separate from `requested_ids` and `approved_ids`; it
  remains decision state and never auto-selects work. Manual and external
  findings remain visible audit state; they are not implementation queue
  entries.
- Keep unselected findings visible in the immutable audit and audit HTML. Omit
  them from instrumentation JSON, Markdown, and HTML.
- A row may require only verification rather than code. Run the mapped
  scenarios and do not invent a source change.
- Reconcile GenAI gap rows with `## GenAI Readiness`; the readiness row remains
  the detailed required-signal contract and the prioritized gap remains the
  user-facing work item.

Build an internal closure matrix before editing:
`finding ID -> area -> priority -> required fix -> instrument mode -> planned action ->
verification scenarios`. Update it after validation and verification. Do not
mark a row `Working` merely because code changed or a shared helper test
passed. Closure requires the source change or proven existing implementation,
the applicable project-runtime validation gate, and `$otel-verify` proof at the
audit scenario's proof level. In particular, execute every named route, span
call site, metric path, log pipeline, and duplicate-prevention scenario the row
references.

### Implementation Report And Handoff

Always write `.observe/otel-instrumentation.md`. Load
`./references/instrumentation-report.md` once, only when producing
that technical report; it owns its reader order, signal inventory, gap
closure, validation, and no-audit rules.

When a canonical audit and selection exist, reuse the already loaded
`./references/json-approval-handoff.md`; it is the sole machine-schema and
instrumentation-HTML authority. Write and validate
`.observe/otel-instrumentation.json`, render
`.observe/otel-instrumentation.html`, keep every selected finding exactly once,
and leave `.observe/otel.html` as the audit surface. Keep
selected-scope closure in the canonical artifacts; the separately bound verify
overlay owns verification results. When canonical JSON is absent, write only
the direct-scope technical Markdown and never fabricate canonical JSON.

For GenAI scope, the loaded GenAI reference additionally owns the
`genai_closure` rollup and finalization rules. Do not load the shared report-flow
contract unless a conditional downstream workflow explicitly needs a field not
owned by these routed references.
### 2. Dependencies

Reuse the exactly one language reference loaded during preflight; do not reload
it. Add only its detected official OTel SDK, agent, exporter, and framework
packages through the repository's dependency manager. Preserve compatible
existing pins and ownership. The Go reference exclusively owns the conditional
fixed-bundle dependency path.

### 3. Instrument

Apply auto-instrumentation first, then selected custom spans/metrics at real
diagnostic boundaries. Preserve the existing startup surface and runtime shape.

Core rules:

- Use official OTel packages, except a library-maintained integration where no
  official package exists.
- Find and extend existing explicit or lazy OTel setup. Keep one provider per
  signal and one resource identity per process; never race app and automatic
  provider installation.
- Merge application resource defaults only for absent keys. Preserve operator
  `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`, service version, and standard
  deployment environment values. Prove the effective resource after merging.
- Resolve exporter endpoint, protocol, and signal path per signal. A successful
  trace export never proves metrics or logs.
- Keep initialization in an observability-owned file, minimize unrelated code
  movement, and preserve idiomatic dependency/config/lifecycle patterns.
- Create tracers, meters, and metric instruments once during startup. Give every
  instrument an appropriate unit and description; never create it in a hot path.
- Use only stable semantic-convention signals where defined. Do not invent a
  custom signal when an approved standard signal faithfully satisfies scope.
  Start with signals needed for selected closure; add broader signals only when
  an approved requirement needs them and accuracy, privacy, and cardinality
  permit them.
- Set custom-span failure status to ERROR and record the exception. Preserve
  HTTP semantic status ownership: ordinary handled 4xx server responses remain
  unset; actual exceptions, transport failures, and 5xx failures are errors.
- HTTP server coverage must include request-duration metrics as well as spans.
  Treat exact metric names as installed-version and stability-mode dependent;
  prove them at runtime and never claim both old and current names.
- Use bounded span names and dimensions. Never put IDs, raw paths/URLs,
  payloads, request/user/tenant/session values, exception text, or tracebacks in
  metric attributes or an approved application-log surface.
- Preserve environment-variable configuration; do not hardcode endpoints. For
  host/native local use, default to loopback unless checked-in platform config
  owns another collector address.
- A library exposes opt-in setup and never initializes an SDK merely on import.

For HTTP outcome work, never broaden canonical scope. Make one bounded pass over
non-success call sites grouped by stable `(method, route, status code)`. When
standard HTTP/RPC/database/messaging RED attributes distinguish the outcome, do
not add a duplicate instrument. When operator-distinct outcomes collide, prefer
the loaded language reference's supported per-call metric-attribute hook and
assert every bounded reason. Add a custom metric only when no covered call or
supported metric-attribute hook can faithfully carry it. Never derive a
dimension from response bodies or unbounded payloads. In canonical flow, the
selected expected telemetry must author the exact bounded attribute first;
otherwise require a corrected audit/selection. Legacy direct work may close a
source-evidenced collision.

Classify logs during preflight as `correlation-only`, `otlp`, or `not requested`.
MDC/trace fields in stdout are not OTLP export. Add an official log bridge only
when selected scope requires explorer-visible logs, then prove category/body,
severity, correlation, redaction, resource identity, and OTLP delivery. An
absent requested bridge is `Not configured`, not `Not proven`.

The loaded language reference owns detected framework dependencies, SDK/agent
startup, provider reconciliation, route handling, request metric behavior,
per-call metric-attribute capabilities, export timing, error recording, and
language-specific final-response requirements. For incident-readiness or GenAI
scope, follow the already loaded domain reference as an additional contract.

### 4. Custom Instrumentation

When no canonical audit exists, no incident/GenAI readiness path applies, and
the user did not already request a specific signal, ask once after baseline
auto-instrumentation whether they want business spans or metrics, then wait.
Skip the prompt in canonical, readiness, GenAI, or explicit-signal scope.
A direct request is scope authority only on the direct no-canonical-audit path.
A validated canonical selection already defines the scope.

For approved custom work, prefer attributes on covered standard RED metrics
when the loaded language supports them. Otherwise instrument only evidenced
error paths, business operations, uncovered dependencies, jobs, cache paths,
and selected readiness/GenAI boundaries. Suggest exact low-cardinality names,
attributes, and rationale; apply only the authorized choice.

### 5. Validate And Verify

Reuse `./references/project-runtime-validation.md`, loaded during preflight; do
not reload it or substitute a shell-default runtime. Before child verification:

1. Record the selected runtime version.
2. Run `git diff --check` when Git exists plus parser/config checks.
3. Compile, typecheck, or import every affected module.
4. Run the smallest focused repo tests. For custom telemetry, add/update a
   practical repo-native in-memory test and execute every changed call site,
   exact signal name, incident state, and bounded dimension set.
5. Confirm filtered tests actually ran.
6. Repair instrumentation-caused failures and rerun affected gates. A modified
   syntax/type/import failure cannot be finalized.

Use separate Java no-agent provider-test and agent E2E forks, and pass actual
`OTEL_*` variables to app-owned reporters that read environment variables.
Skip commands only when the user forbids verification or explicitly assigns
all checks to an external eval; record `Not run` and never claim completion.
Record a concrete unavailable project runtime/dependency as `Blocked`; never
fall back to an incompatible global runtime.

For canonical flow, write and validate the instrumentation overlay with
`json-approval-handoff.md`, then invoke the exact bundle-local `$otel-verify`
child with the same selection unless explicitly skipped or concretely blocked.
Load that sibling once and reuse it. Do not present `$otel-verify` as the user's
next command after instrumentation: name the concrete repair, runtime prerequisite,
or product evidence gap instead.
After in-scope repair, verification checks run automatically inside `$otel-instrument`.

If viability or child verification records an executed failure, read
`./references/repair-loop.md` before classification or repair. Continue every
safe in-scope instrumentation-owned repair and automatic confirmation until it
passes or reaches an evidenced stop boundary. Never finalize an intermediate or
repairable failure.

When verified metric evidence exists and the user requested detectors,
alerting, monitors, Splunk configuration, or `$splunk-configure`, invoke that
workflow and include its result. When automatic startup, route resolution,
automatic metrics, duplicate suppression, startup/export wiring, or
runtime-installed OTLP logs are claimed, apply the conditional full-runtime
contract and its listener preflight; a safe local profile must be attempted.

### 6. Finalize

After implementation, child verification, requested downstream work,
conditional full-runtime work, and final review are complete, read
`./references/finalization.md` exactly once. It owns VS Code debug setup,
credential safety, final reports/response, canonical and direct terminal
branches, fixed-Go cleanup, and the no-command-after-terminal boundary.
