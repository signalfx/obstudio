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

Before editing application code, read `../references/report-flow-contract.md`
and follow the Instrumentation Contract plus Reader-First Report Order.

Resolve every reference and script path from the directory containing the
loaded `otel-instrument/SKILL.md`. Here, `../references/<file>` means the shared
sibling under the parent skills directory, while `references/<file>`,
`./references/<file>`, and `scripts/<file>` are local to `otel-instrument`.
Never probe the service root or repository root for these paths.

## Workflow

### 1. Preflight

Before editing anything, ground the plan with repo evidence:

#### Canonical Audit And Selection Gate

When `.observe/otel-audit.json` exists, treat it as the canonical audit and
`.observe/otel-selection.json` as the only executable scope record. `.observe/otel.html`
is the audit and scope-planning surface; `.observe/otel.md` is a compatibility reader report,
not the implementation queue. Before any application-code, dependency,
runtime-config, or test edit, read and follow
`./references/json-approval-handoff.md`. Do not proceed without a validated,
bound selection whose `approved_ids` is nonempty. A valid answer-only handoff
may persist `decision_answers` with no executable IDs; it authorizes no code or
configuration edits. Implement exactly the dependency-closed selected IDs
(stored in `approved_ids` for schema compatibility).
Bind `.observe/otel-instrumentation.json` to the entire normalized selection
with `selection_sha256`, not only to its audit and executable IDs. This digest
includes `decision_answers`; changing an answer invalidates older
instrumentation even when `approved_ids` is unchanged.

When no canonical audit exists, a direct, concrete user request is the authorized
scope and the legacy no-audit workflow remains available. Do not fabricate
audit IDs or selection artifacts; record that a canonical audit is absent and
recommend `$otel-audit` before claiming audit-gap closure.

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
- **Go standard-HTTP bootstrap gate:** first read `go.mod`. Only when adding the
  standard `otelhttp` + trace/metric OTLP-HTTP bundle to a project with no
  existing `go.opentelemetry.io` requirements, run exactly once:
  `python3 -I "<directory-containing-loaded-SKILL.md>/scripts/resolve_go_otel_versions.py"
  --project "<service-root>"`. Follow the Go reference. Execute a complete plan
  with the sibling runner. When the result is incomplete but
  `bootstrap_probe.eligible` is true, run exactly one runner
  `--action probe-bootstrap`; only its `status: accepted` authorizes the runner
  `--action go-get`. A blocked probe is terminal for dependency edits. On this
  bootstrap branch, use `scripts/run_go_otel_command.py` for the dependency
  edit, follow-up Go commands, and cleanup. Never transcribe its env map, select
  a rejected candidate manually, probe `@latest`, inspect the home cache, or
  use the nonexistent official `otelchi` module. Keep the accepted-plan ledger
  through every source and report edit, final review, and required Go command;
  cleanup is the final project command. Skip the fixed-bundle workflow for
  existing OTel pins, non-HTTP services, or dependency-free edits; preserve
  their selected module family and use the project runtime.
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
  `full runtime` scenario to focused call-site proof.
- Only when canonical JSON is absent, use `.observe/otel.md` as the legacy
  source for `## Verification Plan` and the prioritized `## Gaps` table. If the
  legacy table is malformed or missing, stop and regenerate the audit rather
  than inferring an implementation queue.
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
the selected finding with the same `area`. On the legacy fallback, use
`### Incident Readiness` and its matching prioritized `## Gaps` row. Treat the
matched pair as one implementation contract. The
readiness row names the surface and detection/localization impact; the gap row
names the complete required fix and instrument mode; its acceptance scenarios
name the code path, expected telemetry, proof level, and acceptance criteria.
Do not create a second gap ledger or silently synthesize missing fields. If an
older audit lacks the current prioritized gaps or verification plan, regenerate
the audit before claiming one-to-one closure.

If the user broadly asks to improve incident readiness or MTTD, resolve every
safe app-owned incident gap allowed by the audit modes to exact IDs and create
the selection before editing. Do not choose one representative gap unless the
user explicitly narrows scope. `manual decision` and `external follow-up` rows
cannot enter the selection or either executable ID list. A recorded
`decision_answers` choice may unlock only the matching executable rows, which
still require explicit selection. Track the named external owner outside
instrumentation; never guess either boundary.

Use `../references/incident-readiness.md` to turn each owned gap into concrete,
low-cardinality signals. In particular, add or prove the applicable surfaces:

- API/workflow outcome, errors, latency, and detector-ready request/job counts;
- dependency timeout, retry, rate-limit, circuit-breaker, endpoint/target
  health, availability, and operation outcome;
- input complexity, freshness/age, queue depth/lag/oldest age, dropped or
  rejected work, worker/pool saturation, and scheduled-job last success;
- stream/long-lived connection open, auth, active count, duration, close reason,
  timeout, cancellation, and send/write failure;
- auth/identity/token/secret/certificate/edge failure reason, expiry/rotation,
  route/config mismatch, and synthetic/canary result when owned;
- CPU, memory, disk, inflight/concurrency, desired-vs-healthy,
  startup/readiness/healthcheck, target-health, and autoscaling saturation when
  observable by the app or its checked-in runtime configuration; and
- low-cardinality service/artifact/config/schema/feature-flag/rollout context,
  expected-vs-running state, compatibility failure, and rollout outcome.

Do not treat a bare time-since-last-update or time-since-last-success gauge as
detector-ready staleness when healthy idle periods are possible. Require a
source-backed expected cadence, pending/backlogged work, or accepted input that
should have produced the update. Without that evidence, classify the age gauge
as context or `localization-only` and use backlog, queue delay, or missed
schedule as the MTTD-improving detector input.

For repositories with both web/API and background-worker processes, apply the
Multi-Process Web And Worker Services contract in
`../references/incident-readiness.md`. Each process needs a distinct,
operator-overridable `service.name` default. Initialize its provider and
framework instrumentations only from that process's actual entrypoint or
startup hook; importing a worker/task module from the API must not configure
worker telemetry. Instrument enqueue and task success/failure at their owning
call sites, and explicitly record worker exception status before rethrowing.
Framework hooks or assumed auto-instrumentation are not a substitute for an
app-owned failure path when the readiness gap requires one.

Focused incident-readiness tests must execute the success and failure call
sites and assert emitted telemetry through an in-memory exporter or equivalent
app-code seam. AST, grep, source-string, or compile-only checks are not telemetry
proof. If dependencies cannot be restored or imported, keep the executable
tests, report the exact blocker, and mark dynamic verification `Blocked` or
`Not proven`; do not replace the tests with static assertions.

For Go changes involving goroutines, channels, queues, asynchronous persistence
or indexing, eviction, or observable callbacks, run `go test -race` for every
changed package. If that cannot run, record the exact toolchain/platform blocker;
a normal `go test` pass does not satisfy this concurrency gate.

For incident evidence, target the failure mechanism rather than its endpoint
symptom. Mark a signal `MTTD-improving` only when it can support a detector
before or at first customer impact; mark it `localization-only` when it mainly
narrows an already-detected fault. Endpoint RED metrics alone do not close an
auth handshake, secret expiry, stale output, rollout skew, dependency target
loss, stream lifecycle, or pool-saturation gap.

Extend the internal Audit-Driven Gap Closure matrix with the readiness surface,
required signals, MTTD/localization classification, implemented or proven
signals, tests, remaining signals, and owner. A row cannot be `Working` while
any required signal is absent, merely listed as a follow-up, or supported only
by an unexecuted test. If no app-owned candidate can be patched accurately and
safely, add no placeholder instrument; owner-map the exact prerequisite and
keep the row `Deferred`, `Not configured`, or `Not proven` as appropriate.

### Audit-Driven GenAI Readiness

When the canonical audit declares GenAI ownership or, on the legacy fallback,
`.observe/otel.md` contains `## GenAI Readiness`, read and follow
`./references/genai-instrumentation.md`. Treat its audit-driven closure,
implementation, verification, and finalization rules as part of this skill's
contract. Preserve the optional `## GenAI Readiness Closure` report interaction
below and the custom-instrumentation prompt trigger in Step 4.

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

- Implement exactly the selected IDs plus executable dependencies added by `select`; do
  not silently add another required, recommended, or nearby finding.
- A request to address all required gaps or fix all gaps must first be resolved
  to exact audit IDs and written to `.observe/otel-selection.json`.
- Reject a selection containing `manual decision` or `external follow-up` IDs,
  an unanswered manual dependency, an unknown answer, executable work outside
  the recorded option's `unlocks`, or work blocked by an external follow-up.
  `decision_answers` is separate from `requested_ids` and `approved_ids`; it
  remains decision state and never auto-selects work. Manual and external
  findings remain visible audit state; they are not implementation queue
  entries.
- Keep unselected findings visible as out of scope in the Markdown reader
  report, but never add them to `.observe/otel-instrumentation.json`.
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

### Implementation Report Contract

For every instrumentation run, create or update the reader report
`.observe/otel-instrumentation.md`. When a canonical audit and selection exist,
also write `.observe/otel-instrumentation.json` as the machine handoff and
render `.observe/otel-instrumentation.html` as the human change, impact, and
proof view. Do not update `.observe/otel.md` or `.observe/otel.html` as change
logs. Treat `.observe/otel.md` as a compatibility source only when canonical
JSON is absent; `.observe/otel.html` remains the audit scope-planning surface unless
the user explicitly asks for a fresh audit.

The instrumentation HTML must follow the feedback-oriented reader order:
one concise verification-state heading and one proof-and-delivery sentence,
followed immediately by every selected finding once with its issue title, all
recorded changes, how it improves observability, telemetry-item proof, neutral
coverage context, and remaining uncertainty. For `Partial` verification with no
executed failure, use **Verification incomplete — no observed failures** and
**X of Y telemetry changes are proven**. State separately whether local OTLP
delivery and Splunk Observability Cloud were checked. Do not present a raw
overall `Partial` result as though the implementation failed, and do not
truncate or replace the selected-finding list with an aggregate theme or
component summary.

Do not render aggregate statistic cards or global **Code → telemetry → product
result**, telemetry-item mapping, **Technical closure ledger**, **Verification
proof**, **Scenario proof**, or **Item-level proof** sections in the human HTML.
They repeat the selected cards and mix overlapping dimensions with different
units. Preserve the complete technical ledgers in
`.observe/otel-instrumentation.json`, `.observe/otel-instrumentation.md`,
`.observe/otel-verify.json`, and `.observe/otel-verify.md`; downstream workflows
consume those artifacts rather than the HTML. Those artifacts retain the full
selected-scope closure and code-to-product proof chain. A chart, detector, trace
waterfall, or filter result is expected value until verification records direct
evidence; zero product-visible items means **not checked** when no inspectable
collector or product query ran, not that telemetry was absent.

Never print raw trace IDs or span IDs in the instrumentation HTML, including
inside copied `observed_telemetry`. Say **the generated trace** and name the
relevant span or signal. Keep exact correlation identifiers only in canonical
verification fields, durable evidence, and Markdown `Technical Details` when
they are needed to reproduce the proof.

A direct successful unit, application, or runtime observation proves the
specific telemetry change it exercised. Author that `item_results` row as
`working` even when other route or lifecycle scenarios remain unexercised and
the finding stays `not_proven`. Do not create a second “stronger proof” state for
the same observed change. Require item-specific evidence: aggregate receiver
counts, a differently named signal, or a shared helper that never invokes the
exact item do not prove it. Keep such an item `not_proven`; render it as **Not
proven**, not **Observed**, and say that the exact item was not directly
observed. This rule does not make an incomplete finding fully
verified and does not turn source/config presence alone into emission proof.
Set the child verification row's required `direct_assertion_passed` boolean
before any finding/scenario rollup: `true` exactly for a passed assertion against
the exact item or call site, otherwise `false`. For a removed item, require a
bounded capture proving both absence of the removed signal and presence of its
intended replacement owner before setting it `true`.

After child verification, derive the instrumentation report's top-level result
from both authorities: verification finding/scenario/item state and the
instrumentation-owned `genai_closure`. A passing verification overlay does not
erase a partial or failed GenAI closure. `not_working` in either authority is
`Fail`. A verification blocker is `Blocked` only when no instrumentation or
GenAI proof succeeded; when any implementation-owned proof exists, the
aggregate is `Partial`. Otherwise unresolved proof or GenAI signals are
`Partial`, and `Pass` requires verified findings plus only `working`,
`deferred`, or `owner_mapped` GenAI closure rows.
Use that aggregate result on the first screen of the HTML report, and show one
concise GenAI closure table with every surface, current status, ready signals,
remaining signals, and owner. Do not hide unresolved GenAI scope behind a
passing finding-verification result.
Count implementation-owned proof only from a `working` finding with executed,
non-negative tests and durable evidence, or a `working`/`partial` GenAI row
with nonempty implemented/proven signals plus executed tests and durable
evidence. Source references, `not run`, blocked-test prose, owner mappings, and
the mere presence of a `tests` or `evidence` list do not turn a fully blocked
verification run into `Partial`.

On each selected-finding card, render one plain status such as **Verification
incomplete**, followed by a three-column **Telemetry
change / What was observed / Status** table. State local delivery and Splunk
Observability Cloud check scope once in the report-level status; do not repeat
it on every finding. Reserve **no observed failures** for the report-level
heading. Do not add generic per-finding lines such as **Target product: Not
checked** or **Executed checks: No executed check failed**. Keep
named audit triggers in one collapsed **Coverage details** disclosure, grouped
neutrally as confirmed in a running service, passed focused checks, focused
evidence obtained for an incomplete scenario, not exercised, blocked, failed,
or not configured. Only a `working` scenario may be called confirmed or passed;
a `not_proven` scenario with useful executed evidence stays explicitly
incomplete. Do not render a per-finding
completion checklist and do not repeat a successful focused check as required
running-service work. Keep stable scenario IDs, commands, acceptance criteria,
and exact counts in the canonical JSON and generated Markdown proof ledgers,
not in another aggregate HTML section.

For every blocked verification scenario, require the canonical row to carry a
concise `blocking_reason` and `unobserved_outcome`. The reason states the exact
unavailable prerequisite in past or present tense and is supported by the
scenario's command/evidence; it is not an instruction to the user. The outcome
states the specific runtime, OTLP-delivery, or product observation that could
not be captured. In HTML, replace a generic blocked count with **Runtime
verification unavailable** before **Coverage details**, then show **Why runtime
verification is unavailable**, **Already proven** from mapped working item
results, and **Still unobserved** from those structured scenario outcomes. Keep
affected audit triggers neutral inside the collapsed disclosure; do not present
them as though they were the user's next action.

When no audit report exists, still write `.observe/otel-instrumentation.md`
with service/runtime evidence, scoped implementation changes, validation gates,
verification results or handoff, and explicit remaining gaps. Do not fabricate
a full audit or machine flow JSON.

Use the exact machine schema and status rules in
`./references/json-approval-handoff.md`. Findings must exactly equal the
dependency-closed selected IDs (`approved_ids`) in audit order; keep unselected
findings out of the JSON.

Treat each `telemetry_changes` row as the durable code-to-product mapping. Give
it a stable item ID and record the concrete code/config change, exact source or
call site, added/modified/removed signal, newly added attributes/dimensions,
product view, audit scenarios, and item-specific follow-up actions. Do not rely
on the finding-level free-text `changes` list for coverage. Every new custom
attribute must preserve the audit promise exactly: key-only stays key-only and
an authored `key=value` keeps that exact bounded value. Every new custom
metric must name the chart/dashboard or detector action to take after proof;
every added low-cardinality attribute or dimension must name the product
filter, slice, group-by, or breakdown it enables. Never auto-publish a chart or
detector without the downstream review workflow.

The instrumentation report must be reader-first:

```markdown
# OTel Instrumentation Report: <service>

**Result:** Pass | Partial | Fail | Blocked
**Source audit:** `.observe/otel-audit.json` | `.observe/otel.md` legacy | not found
**Selected scope:** `.observe/otel-selection.json` | direct no-audit request
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

`Signals Changed` is the implementation-change inventory. Include a
signal-level table:

| Signal type | Added | Modified | Removed | Product result / next product action | Evidence | Verification status |
|---|---|---|---|---|---|---|
| Traces/spans | exact span names or `None` | exact changes or `None` | exact removals or `None` | waterfall/map/filter result and follow-up | source paths + tests/harnesses | verified/partial/not run/blocked |
| Metrics | exact metric names or `None` | exact changes or `None` | exact removals or `None` | chart/dashboard/detector action | source paths + tests/harnesses | verified/partial/not run/blocked |
| Logs/events | bridge/event names or `None` | exact changes or `None` | exact removals or `None` | query/correlation result and follow-up | source paths + tests/harnesses | verified/partial/not run/blocked |
| Runtime/config | service/exporter/env/startup settings or `None` | exact changes or `None` | exact removals or `None` | service/environment/export diagnostics | startup/config paths | verified/partial/not run/blocked |
| Dependencies | OTel packages or `None` | version/package changes or `None` | removed packages or `None` | enabled runtime behavior | manifest/lockfile paths | verified/partial/not run/blocked |

For incident-readiness work, add this nested table inside `## Signals Changed`
even when no source audit exists:

```markdown
### Incident Readiness Signal Roles

| Surface | Exact signal | Role | Detector use / reason | Proof | Remaining owner / prerequisite |
|---|---|---|---|---|---|
```

Use exactly `MTTD-improving`, `localization-only`,
`provider/platform-owned`, or `uncovered` in `Role`. Write one row per exact
added or proven signal; do not group multiple metric names. Use `None` for
`Exact signal` only when owner-mapping an unavailable prerequisite, and name
that owner or prerequisite in the final column. The table is a signal-role
inventory, not another gap ledger; reconcile audited surfaces through the
existing `Audit Gap Closure` rows.

Do not claim a removal unless the previous report or git diff proves the signal
or config existed and the current source proves it was removed. Use `None` for
empty cells. The final response must summarize `Signals Changed` by signal
type, distinguish added, modified, removed, and unchanged signals, and point to
`.observe/otel-instrumentation.md`.

`Audit Gap Closure` is the reader-facing compatibility reconciliation with the
source audit. Stable finding IDs and exact selected scope live in the machine
JSON:

| Priority | Gap | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|---|
| required | exact audit `Area` value | concrete code/config change or `No code change` | scenario IDs and test mode | Working / Not working / Not proven / Not configured / Deferred | direct evidence or exact blocker |

Use one row per prioritized audit gap in the compatibility report, marking
unselected rows `Deferred` with `Not in selected otel-selection.json scope`. The
machine JSON contains selected rows only. Keep `Not working` distinct from `Not
proven`: the former requires an executed failed check, while the latter means
the required scenario did not run or lacked a prerequisite. Use `Not
configured` when requested implementation is absent. Use `Deferred` only for
an explicit scope choice, owner, prerequisite, or `manual decision` row. When
there is no source audit, write `No source audit gap table was available.`
For every selected row, project `What changed`, `Tested`, and `Evidence / reason`
exactly from the instrumentation JSON `changes`, `tests`, and `evidence` arrays
in source order; after verification, only `Result` comes from the bound verify
row. Do not paraphrase these compatibility cells independently.

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
  .observe/otel.md .observe/otel-instrumentation.md \
  --audit-json .observe/otel-audit.json \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json
```

Resolve `scripts/validate_gap_closure.py` relative to this skill directory. If
the validator applies, run it before reading its implementation; use actionable
failures for repair rather than preloading validator source. If
validation fails, repair the report or expose the missing audit row before
finalizing.
After verification JSON exists, rerun the same validator with
`--verify-json .observe/otel-verify.json` instead of
`--instrumentation-json`. This prevents the Markdown compatibility report from
retaining stale pre-verification statuses or next-state results.

Also maintain `## Verification Handoff / Results` using the schema in
`./references/project-runtime-validation.md`. Record the selected runtime,
exact local-safe commands and outcomes, changed source-to-scenario mappings,
the `$otel-verify` result/report path when run, and any blocked prerequisites.
This section is not proof of emitted telemetry unless a test, harness, or
collector actually observed it.

Use the canonical audit, validated selection, and selected findings' referenced
verification scenarios as the handoff contract. Use Markdown sections only on
the legacy fallback. Do not copy unrelated report sections into the audit or
instrumentation report.

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

- Use only official OpenTelemetry packages (`go.opentelemetry.io/otel`, `go.opentelemetry.io/contrib`, `@opentelemetry/*`, `opentelemetry-*`). Do not use community or third-party OTel wrappers. The only exceptions are library-maintained integrations where no official package exists (e.g. `github.com/redis/go-redis/extra/redisotel/v9`, `XSAM/otelsql`).
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
- When a framework-specific auto-instrumentation package only provides spans
  (not HTTP server metrics), wrap the outermost handler with
  `otelhttp.NewHandler` (Go) or the language equivalent. Treat the exact metric
  set and names as version- and semantic-convention-mode-dependent; inspect the
  selected package source/config and require runtime evidence before naming an
  emitted metric. In particular, do not claim `http.server.active_requests`
  merely because `otelhttp.NewHandler` is present. Consult the Framework
  Selection Guide in the language reference for the correct wrapping pattern.
- HTTP server instrumentation must produce request-duration metrics as well as
  spans. Prefer the current stable metric `http.server.request.duration`. When
  the installed SDK requires a semantic-convention stability opt-in, set it in
  the launch environment before importing or constructing the instrumentor.
  Accept `http.server.duration` only when the installed SDK truly emits the
  alternate name and record that exact runtime evidence; never claim both names.
- For local, Docker, and eval-style runtime checks, configure metric export to flush quickly. When constructing a metric reader manually, use the language equivalent of `OTEL_METRIC_EXPORT_INTERVAL` with a safe local default of `1000` ms and `OTEL_METRIC_EXPORT_TIMEOUT` with a safe local default of `500` ms instead of relying on SDK defaults.
- Strictly adhere to OTel [semantic conventions](https://opentelemetry.io/docs/specs/semconv/) for span and metric naming and attributes for domains where such semantic conventions are defined.
- For domains where OTel semantic conventions exist, use semantic-convention
  names and attributes. Start with required spans, metrics, and attributes; add
  recommended optional signals only when an approved readiness or verification
  requirement depends on them, the service can observe the value accurately,
  and privacy/cardinality rules permit it. Do not invent custom spans, metrics,
  or attributes where a semantic-convention signal satisfies the requirement.
- Before adding any custom counter or histogram for an outcome that occurs
  inside a call already covered by an auto-instrumented RED metric, check
  whether that outcome can instead be recorded as an attribute on the existing
  metric via the language's per-call metric-attribute hook (see
  `#### Language-Specific Musts` below), rather than as a new standalone
  metric. Each convention below defines its own error/status attributes for
  exactly this purpose:
  - [HTTP server/client metrics](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/):
    `http.server.request.duration` / `http.client.request.duration` carry
    `error.type` and `http.response.status_code`.
  - [RPC server/client metrics](https://opentelemetry.io/docs/specs/semconv/rpc/rpc-metrics/):
    `rpc.server.call.duration` / `rpc.client.call.duration` carry `error.type`
    and `rpc.response.status_code`. Only fall back to the legacy
    `rpc.server.duration` / `rpc.client.duration` names when runtime evidence
    shows the installed SDK still emits those instead.
  - [Database client metrics](https://opentelemetry.io/docs/specs/semconv/database/database-metrics/):
    `db.client.operation.duration` carries `error.type` and
    `db.response.status_code`.
  - [Messaging metrics](https://opentelemetry.io/docs/specs/semconv/messaging/messaging-metrics/):
    `messaging.client.operation.duration` and `messaging.process.duration`
    carry `error.type` when the operation fails.

  Prefer the attribute over a dedicated custom metric whenever the outcome
  can be faithfully represented on the RED metric for that call *and* the
  language has a way to set it there: either auto-instrumentation already
  emits a relevant `error.type`/`*.response.status_code` attribute that
  actually distinguishes this outcome, or the language has a supported
  per-call metric-attribute hook that can set a standard *or custom*
  attribute on the metric (see `#### Language-Specific Musts` below -- for
  example Go's `otelhttp.Labeler`, which can attach a custom attribute like
  `outcome.reason` even when the outcome is not expressible via the standard
  status/error attributes alone). A dedicated custom metric is correct
  whenever that's not the case: a queue-depth gauge or a background job
  outcome with no inbound request has no call to attach to; or the outcome
  is not expressible via the standard status/error attributes alone (for
  example a business outcome that occurs once per request but is not
  distinguishable from the standard attributes -- a logical failure returned
  as HTTP 200, or two distinct failure causes sharing one HTTP status) and
  the language's auto-instrumentation also has no per-call metric-attribute
  hook to carry a custom attribute instead (Python's ASGI/WSGI hooks and
  Node's `@opentelemetry/instrumentation-http` only add span attributes, not
  metric attributes). In each of those cases, add the dedicated metric
  instead of suppressing the only detector-ready signal for the outcome.
- For incident-readiness work, follow
  `../references/incident-readiness.md`. Instrument only source-evidenced
  workflow, dependency, input-complexity, freshness, backpressure,
  synthetic/canary, auth/edge, capacity, health/readiness, and release/config
  surfaces. Prefer semantic-convention HTTP, RPC, database, messaging, process,
  and runtime signals; add custom outcome, lag, freshness, queue, retry,
  timeout, rate-limit, endpoint/target-health, drop/reject, circuit-breaker,
  saturation, desired-vs-healthy, startup/readiness/healthcheck, compatibility,
  and rollout signals only when the service owns and can observe them
  accurately.
- For GenAI/LLM code, follow both `../references/genai-readiness.md` and
  `./references/genai-instrumentation.md`; the latter defines the
  instrument-specific span ownership, context handoff, closure, and proof
  rules.
- Prove every custom metric's exact name, unit, instrument type, and complete
  emitted dimension sets. Lifecycle-specific counters must retain their
  specific error class; generic terminal errors must not overwrite earlier
  token-limit, truncation, timeout, provider, or tool classifications. Do not
  attach transient terminal outcome/error dimensions to intermediate gauges or
  size measurements unless the metric contract explicitly requires them.
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
- The ASGI/WSGI instrumentation underlying Flask/FastAPI already sets
  `http.response.status_code` on `http.server.request.duration` for every
  request, and `error.type` for a 5xx (or otherwise invalid) status, with no
  extra code -- a plain 4xx client-error response does not set `error.type`
  on a server span. `server_request_hook`/`response_hook` only set span
  attributes, not metric attributes; they are not a route to a new dimension
  on the duration metric itself. Do not add a standalone counter for a
  request outcome the duration metric already attributes correctly.

Node.js:
- Add `@opentelemetry/instrumentation-http` explicitly for HTTP server spans.
- Add the detected framework instrumentation explicitly, for example `@opentelemetry/instrumentation-express` for Express.
- Add `@opentelemetry/exporter-metrics-otlp-http` and `@opentelemetry/sdk-metrics` when wiring SDK-based metrics.
- Configure `PeriodicExportingMetricReader` with `exportIntervalMillis: Number(process.env.OTEL_METRIC_EXPORT_INTERVAL || 1000)` and `exportTimeoutMillis: Number(process.env.OTEL_METRIC_EXPORT_TIMEOUT || 500)` so HTTP duration metrics export during short runtime checks.
- Use the current `NodeSDK` metric reader option exactly as shown in the Node reference. Do not substitute `metricReaders` for `metricReader` unless the installed SDK version documents that option.
- Do not rely on `@opentelemetry/auto-instrumentations-node` alone when specific framework packages are expected.
- In the final response, name the updated preload command (`--require` or `--import`), the packages added, and that HTTP server spans plus request-duration metrics are expected.
- `@opentelemetry/instrumentation-http` already sets `http.response.status_code`
  on `http.server.request.duration` from the response for every request with no
  extra code. It does not set `error.type` from a failing status code:
  `error.type` there is reserved for a lower-level request/response transport
  error (for example a socket error before a status was ever sent), not an
  ordinary 4xx/5xx completion. Its hooks (`requestHook`, `responseHook`,
  `startIncomingSpanHook`) only add span attributes, not metric attributes.
  Do not add a standalone counter for a request outcome that `http.response.status_code`
  already distinguishes; `@opentelemetry/instrumentation-http` has no per-call
  metric-attribute hook, so a finer-grained reason dimension that the status
  code alone cannot express does need its own custom metric here.

Go:
- For HTTP services that need `otelhttp` request metrics, use
  `otelhttp.NewHandler` as the outermost and sole server-span producer.
- For chi, use `otelhttp.WithRouteTag` to put the low-cardinality route pattern
  in `http.route` on the existing server span and HTTP metrics. It does **not**
  rename the span. Prove the route attribute and prove one server span per
  request. If route-pattern span names are an explicit requirement, update the
  current outer span after route matching and test its name; do not add a
  second span-producing server middleware. Apply the same one-span rule to
  gin, mux, and other routers: use a non-span-producing route annotator with
  the outer `otelhttp.NewHandler`, or use the framework middleware alone and
  report that `otelhttp` server metrics were not added.
- Configure `sdkmetric.NewPeriodicReader` with an interval derived from `OTEL_METRIC_EXPORT_INTERVAL`, defaulting to `1000` ms, and a timeout derived from `OTEL_METRIC_EXPORT_TIMEOUT`, defaulting to `500` ms, for local runtime checks.
- In the final response, state the server handler wrapping, service-name setting, OTLP endpoint setting, and that HTTP server spans plus request-duration metrics are expected.
- `otelhttp.NewHandler` already sets `http.response.status_code` on
  `http.server.request.duration` from the response status with no extra code.
  It does not set `error.type` from that status: `otelhttp`'s metric
  attributes never include `error.type` for an ordinary 4xx/5xx completion.
  When a handler needs a dimension `otelhttp` cannot derive from the
  status code alone (a specific failure reason such as a downstream timeout
  vs. a validation error, both returning the same HTTP status), pull the
  `Labeler` that `otelhttp.NewHandler` already injects into the request
  context and add the attribute from inside the handler instead of creating
  a new counter:
  ```go
  labeler, _ := otelhttp.LabelerFromContext(r.Context())
  labeler.Add(attribute.String("outcome.reason", "gateway_timeout"))
  ```
  No extra `otelhttp.NewHandler` option is needed; the labeler is present in
  context for every request the handler already wraps. The older
  `otelhttp.WithMetricAttributesFn` middleware option is deprecated in favor
  of this per-request `Labeler`. A custom attribute like `outcome.reason` is
  detector-ready without a standalone counter: see
  `splunk-configure/references/detector-classification.md`'s "Evidenced
  Non-Standard Outcome Attribute" rule, which generates an attribute-filtered
  outcome detector directly from an evidenced non-standard histogram
  attribute.

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

Skip this prompt when the user already asked for incident-readiness or GenAI/LLM
workflow instrumentation or a specific custom signal on the legacy
no-canonical-audit path, when an Audit-Driven Readiness path applies, or when a
validated canonical selection already defines the scope. A direct request is
scope authority only on the legacy no-canonical-audit path; a canonical audit
requires its validated bound selection. Implement only the safe scoped signals
and clearly list any unpatched prerequisites.

- **If no**: proceed to the project-runtime validation gate (Step 5).
- **If yes**: for each candidate point below, first check whether it occurs
  inside a call an auto-instrumented RED metric already measures (HTTP, RPC,
  DB, or messaging — see `#### Implementation Rules`); if so, prefer adding
  an attribute to that existing metric via the language's per-call
  metric-attribute hook over defining a new counter/histogram. Analyze the
  codebase for high-value custom instrumentation points:
  - Error handling paths that catch and handle exceptions
  - Key business operations (payments, orders, user registration, etc.)
  - External calls not covered by auto-instrumentation libraries
  - Background workers and scheduled jobs
  - Cache interactions without auto-instrumentation support
  - Incident-readiness boundaries: customer-impact workflow outcome,
    dependency timeout/retry/rate-limit/error and endpoint/target health, input
    complexity, freshness, queue/backpressure, synthetic/canary result,
    auth/edge failure, capacity saturation, desired-vs-healthy,
    startup/readiness/healthcheck, traffic target health, and release/config
    context when code evidence exists
  - Incident-evidence boundaries: every supplied failure mechanism must map to
    an added or proven code-owned signal or an explicit external owner; generic
    endpoint metrics are insufficient when the mechanism is auth handshake,
    secret expiry, stale output, rollout skew, dependency target health, stream
    lifecycle, or pool saturation
  - GenAI/LLM workflow boundaries: workflow span, agent/workflow invocation,
    LLM inference, tool/function execution, MCP method dispatch when present,
    retrieval, fallback, token usage, model/config readiness, prompt/response
    parse outcome, safety/policy outcome, AI-derived data freshness, and
    AI-owned session/stream lifecycle when code evidence exists
  - Suggest specific spans and metrics with names, attributes, and rationale
  - Apply after the user selects it

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
   test. Parameterize tests when those call sites share setup. For
   detector-critical counters, histograms, and observable gauges, drive each
   incident state to a non-default value and assert its emitted datapoint and
   bounded dimensions; metric registration, name presence, or a zero-value
   observation alone is not incident-readiness proof.
   Map these executions back to every in-scope `Audit Gap Closure` row and its
   declared verification scenarios.
5. Confirm filtered tests actually ran by checking test output or generated
   reports; a no-match guard is reactor plumbing, not test evidence.
6. If a validation failure is caused by instrumentation changes, repair it and
   repeat the affected gate until it passes. Do not finalize with a compile,
   type, syntax, or import error on a modified line.

For Java, keep test-owned SDK/provider assertions in a no-agent JVM fork and
automatic instrumentation/runtime proof in a separate agent E2E fork, as
required by the Java and project-runtime references. When an app-owned metric
reporter reads environment variables, pass actual `OTEL_*` variables to its
fork; agent `-Dotel.*` properties alone are not equivalent.

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

#### Pre-finalization Repair Gate

Treat verification as a repair loop, not a terminal handoff. Before finalizing
any `Fail` result or run with a `not_working` finding, scenario, or telemetry
item, build a
failure-ownership table in working notes:

`failure -> failing source/config -> selected finding -> ownership -> evidence`

Classify a failure as **instrumentation-owned** when any of these is true:

- the current instrumentation diff introduced or modified the failing behavior;
- wiring, provider, dependency-injection, runtime configuration, or a test seam
  required by the current instrumentation change is missing or incorrect; or
- a pre-existing OTel code/config defect inside the dependency-closed selected
  scope prevents a selected telemetry outcome from working.

Do not classify an unrelated business-logic defect, an unselected feature, an
external service failure, unavailable credentials, or a live-platform outage as
instrumentation-owned merely because verification encountered it. Cite the
changed hunk, selected OTel source/config, or direct runtime evidence used for
every ownership decision. When Git or a saved pre-run snapshot exists, compare
the failing path with that baseline: an unchanged selected OTel wiring defect
is pre-existing but instrumentation-owned, not introduced by the current diff.
Uncertainty alone is not evidence that a repair is out of scope.

For every safe, in-scope instrumentation-owned failure, make a concrete
code/config repair and continue until the affected check passes or an evidenced
stop boundary is reached. One failed repair attempt is never a completion
condition. Add or strengthen the
smallest repo-native regression test that would have caught the failure when a
practical test seam exists, rerun the affected compile/focused-test gates, then
invoke verification again for the affected scenarios. Continue while an
iteration can make a safe in-scope change or gather evidence needed to choose
that change; never repeat an unchanged verification command and call it a
repair. Do not ask the user to invoke `$otel-instrument` a second time, relabel
an executed failure as `not_proven`, or finalize at the first failed check. A
failed verification artifact produced during this loop is an intermediate
artifact, not the instrumentation workflow's final handoff.
Do not finalize while any safe in-scope instrumentation-owned failure remains.

The final overlays are current-state artifacts, not an attempt log. After a
repair succeeds, replace superseded failure statuses, repair actions, trace IDs,
and run-level next steps with the latest verification result. Do not expose an
old failure or repair CTA on the first screen. If attempt history is useful,
keep it only as explicitly superseded technical evidence under
`.observe/evidence/<run>/`.

Stop only when the repair needs unselected work, a material behavior choice,
new authority, or a concrete external prerequisite; name that exact boundary
and its evidence for each remaining failure rather than describing verification
as pending. Exact scenario IDs are verifier-owned technical scope, not manual
steps for the user.

Keep repair and confirmation distinct in every handoff and report. The repair
action names the application code/config change that `$otel-instrument` must
make. The subsequent `$otel-verify` run only confirms the changed behavior; it
never performs the repair. Invoke that confirmation automatically inside this
workflow and do not render it as a second user action or as another bullet in a
failed finding's repair list.

Before invoking verification for a canonical flow, write the instrumentation
JSON, then follow `Validate And Render Instrumentation` in
`./references/json-approval-handoff.md`. Repair validation failures first. Pass
the same selection to `$otel-verify`; never broaden the handoff.
For every repair iteration, preserve this order: repair application code/config,
update the instrumentation overlay's exact change/source/test/evidence rows,
rerun compile and focused tests, invoke the affected verification scenarios,
then replace the current verification overlay. The verifier must bind
`instrumentation_sha256` to that updated normalized instrumentation overlay;
that digest transitively includes the exact selection through
`selection_sha256`. Never reuse proof from an earlier overlay that happens to
have the same finding or item IDs.

Before finalizing, reconcile delivery wording across the overlays. A telemetry
item whose `product_view` denies any OTLP pipeline or export path cannot be
paired with `otlp_accepted` or `explorer_visible`. Distinguish “no
application-owned exporter was added” from an evidenced agent- or
platform-owned export path.

Record the verification result and `.observe/otel-verify.md` path in
`.observe/otel-instrumentation.md`. If verification cannot run, record the exact
blocking prerequisite and do not describe the instrumentation as verified.
When `.observe/otel-verify.json` is produced, validate and render the complete
flow with the same reference, then refresh
`.observe/otel-instrumentation.html` with verification proof before finalizing.
Run the shared `instrumentation-final-gate` command after the final child
verification overlay. It must pass before the instrumentation workflow can
return a completed handoff; `Partial` proof may pass when no executed check
failed, but an intermediate or `not_working` child result cannot.
Do not render downstream state into `.observe/otel.html`.

When verified metric evidence exists and the user requested detectors,
alerting, monitors, Splunk configuration, or `$splunk-configure`, invoke or
apply that workflow and include the detector/configure verification result in
the instrumentation report.

When any claim depends on auto-instrumentation startup, framework route
resolution, automatic metrics, duplicate automatic-span prevention,
startup/exporter wiring, or runtime-installed OTLP logs, read
`../references/full-runtime-acceptance.md` and require its conditional full
runtime gate in the verification handoff. Apply its one-shot
`scripts/probe_loopback_bind.py` preflight before creating any receiver or
harness that requires a local listener. Attempt the gate without asking when
the repository provides a safe local profile or fixtures and the preflight
passes. Otherwise record the exact prerequisite and keep those rows `Partial`,
`Blocked`, or `Not proven`.
`Not run` or `no collector was run` alone is not an acceptable blocker. For
each required full-runtime row, record either the executed command and direct
result or the concrete unavailable runtime, listener, dependency, credential,
or fixture that prevented the attempt. Do not finalize while a safe local
profile exists and the required gate has not been attempted.

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
- Explain the operator/product result of each signal change and its next
  product action; do not report only files, packages, or signal names.
- State the selected project runtime, affected-module compile/type/import
  result, focused tests that actually ran, and the verification result or
  blocking prerequisite.
- Write `.observe/otel-instrumentation.md` and include a `Signals Changed`
  summary with added, modified, and removed traces/spans, metrics, logs/events,
  runtime/config, and dependencies. If no prior audit existed, state that the
  report establishes the implementation baseline.
- For a canonical audit flow, also write `.observe/otel-instrumentation.json`
  with exactly the dependency-closed selected finding IDs (`approved_ids`) in
  audit order, validate the complete
  available flow, render `.observe/otel-instrumentation.html`, and refresh that
  instrumentation HTML with verification proof when available. Leave
  `.observe/otel.html` as the audit and scope report.
- State the audit ID, selected finding IDs, machine-report path, and refreshed
  instrumentation HTML path. Do not describe unselected findings as implemented.
- Include `Audit Gap Closure` counts by `Working`, `Not working`, `Not proven`,
  `Not configured`, and `Deferred`. Keep every source-audit gap visible even
  when the user narrowed scope.
- For incident-readiness work, summarize each in-scope workflow, dependency,
  input-complexity, freshness, backpressure, synthetic/canary, auth/edge,
  capacity, health/readiness, and release/config surface as MTTD-improving,
  localization-only, provider/platform-owned, or uncovered. Name every
  remaining detector prerequisite and its owner; do not call the pass complete
  while an app-owned required signal is only a follow-up unless the user
  explicitly narrowed scope.
- For GenAI work, follow the finalization and remaining-signal rules in
  `./references/genai-instrumentation.md`.
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
- On the fixed Go bundle branch, finish and review all source and report edits,
  then run every required runner-backed Go validation before the final runner
  `--action cleanup`. Do not run cleanup after an initial pass while later
  edits or review remain. If final review causes an edit, repeat the affected
  runner-backed validation before cleanup. After cleanup, do not rerun the
  resolver, edit the project, or run another Go command. Never recover with a
  manual `GOCACHE`, `GOMODCACHE`, `go`, `rm`, or `find` branch.

## Credential Safety

Only enter this section when the repository already has an env-file workflow
or the user explicitly requests one. Standard OTel environment variables used
only by application code do not authorize adding `.env.example`, `.env`, or
`.gitignore`; document them in the implementation report or an existing
launcher instead.

When that env-file condition is met:

1. **Ensure `.env` is gitignored before writing secrets**: Check `.gitignore` for `.env`. If it is missing, add it. Never allow a `.env` with access tokens to be committed.
2. **Create or update `.env.example` with safe placeholders**: Do this only on the existing/requested env-file surface. `.env.example` must never contain real tokens.
3. **Verify no tokens in tracked files**: Search tracked config files for access tokens and confirm no real token values appear in files that would be committed.

## Scope

- **New apps**: Full scaffold matching the current runtime shape: instrumentation, SDK init, env var config
- **Existing apps**: Incremental -- detect what's already present, add only what's missing
