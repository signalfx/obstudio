### Fast Path: Targeted Custom Signal

If the user is asking for a specific signal ("add a metric for queue depth",
"track error rate on payments", "add a span for the indexing job") AND the
preflight scan finds OTel SDK already initialized:

1. Skip Steps 2-3 (dependencies and auto-instrumentation are already present).
2. Go directly to Step 4 (Custom Instrumentation) with the user's request as context.
3. Add only the requested signal — do not re-scaffold or re-wire existing setup.
4. Proceed to Step 5 (project-runtime validation gate).

When a canonical selection exists, this fast path still covers every selected
ID, including executable dependencies added by `select`; never reduce it to one
requested signal.

If the preflight scan finds no OTel SDK, tell the user auto-instrumentation
needs to be set up first and continue with the full workflow (Steps 2-3).

### Audit-Driven Incident Readiness

When the canonical audit contains partial or missing
`current_instrumentation.incident_readiness` rows, reconcile each row through
its selected finding with the same `area`. Treat the matched pair as one
implementation contract. The
readiness row names the surface and detection/localization impact; the gap row
names the complete required fix and instrument mode; its acceptance scenarios
name the code path, expected telemetry, proof level, and acceptance criteria.
Do not create a second gap ledger or silently synthesize missing fields. If an
older audit lacks the current prioritized gaps or verification plan, regenerate
the audit before claiming one-to-one closure.

If the user broadly asks to improve incident readiness or MTTD, resolve every
safe app-owned incident gap to exact IDs and create the selection before
editing. Do not choose one representative gap unless the user explicitly
narrows scope. `manual decision` and `external follow-up` rows cannot enter
the executable selection. A recorded `decision_answers` choice may unlock only
the matching executable rows, which still require explicit selection. Track
the named external owner outside instrumentation; never guess either boundary.

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

#### GenAI Readiness Contract

If the canonical audit contains top-level `genai_readiness`, use those rows as
the source of truth. The audit output is a contract, not background context.
Parse each row by human-readable `surface` plus `required_signals`,
`owner/source_files`, and `acceptance_criteria`. Use the surface name as the
human-facing identifier throughout implementation and reporting.

Reconcile the selected finding's complete `required_fix`, acceptance,
`expected_telemetry`, and readiness `required_signals` with the Required GenAI
Coverage Profile before implementing or planning. A historical subset cannot
erase requested workflow/agent operations or applicable content/vendor fields.
If those authored contracts disagree, report the exact stale fields and
refresh/rebind the audit selection through the normal flow before code changes;
do not silently narrow the work or mutate a bound audit to make it pass.

Apply the per-tool vendor content contract in
`../references/genai-readiness.md` before closing a selected tool finding.
Inspect the actual SDK/preserved producer's tool output: arguments/results
without input/output message mappings remain a gap. Populate both GenAI pairs
on the same existing tool span, or its supported OpenInference equivalent,
using the same pre-SDK sanitized arguments and produced result. Name the
supported enrichment hook and prove the span ID stays unchanged; preserve the
producer, provider/exporter and business calls. Do not add a wrapper span or
assume `add_tool_span`/a callback supplies fields that were never observed.
Test arguments/results-only and parent-only-message cases as failures, a
schema-valid matching tool as success, and error/no-result as truthful output
applicability without fabricated completion.

For every GenAI plan/report, populate all three **Required GenAI Report
Evidence** tables in `../references/genai-readiness.md`. Each operation row
must join its actual boundary to its exact creator, kind/parent, version/example
revision and safe-content hook. Include separate field rows with official
Opt-In provenance, both vendors' expectations and concrete numeric capture
settings. A global SDK API list plus a separate boundary list is insufficient.

For a plan-only GenAI request, produce the same concrete producer and field
decisions without claiming implementation or runtime proof. Name the existing
or proposed creation API, matching SDK/library version and official example
path/revision for each runtime scenario. Map every selected workflow, agent,
model and tool to its actual source boundary. Include one field row per
applicable input/output, instruction/tool definition, argument/result/message
mapping, provider/model, known parameter/response/usage/stream field and opaque
correlation ID: source value/hook, current value or gap, intended supported API,
schema/redaction policy and test. State exact lifecycle/parent/duplicate and
auxiliary timeout/cancel proof. Copying an old Required Signals subset or
writing only 'SDK logger/schema helpers' does not satisfy a reviewable plan.

For a GenAI plan or report with supplied cases or captures, build a case ledger
before drafting the assessment. Give each distinct source boundary, case and
probe-only operation an addressable entry with these joined facts:

| Case and actual operation | Available source/probe values or exact absence | Chosen public producer/API and applicable `span_type` | Concrete acceptance assertions | Source/capture/proposed/executed proof and remaining gap |
|---|---|---|---|---|

Equivalent prose or grouped sections are fine when each child operation has
its own decision and assertions. Reconcile every ledger entry against the
completed report; a category, parent row or promise to check later does not
close an unassessed child. Keep unavailable facts explicit rather than
inventing arguments, metadata, native node IDs/counts or execution:

- List source-backed owning agent, conversation and tool metadata on each
  tool's own span, with its actual safe source value or absence reason. Assert
  the owning agent and available conversation binding on that tool, and add
  a parent-only negative assertion; parent-only correlation fails acceptance.
  Give an explicit absence reason when the operation has no such source
  context instead of reusing another case's fields.
- Include decorator surfaces represented only in probe observations: bound
  methods, nested distinct operations, sync/async functions and finite
  sync/async iteration, send/asend and cancellation when supplied. Name the
  selected SDK `@log` function and applicable `span_type`, or the exact
  unsupported contract and application-owned function-decorator SDK creator
  fallback for each. Assert actual known arguments/results, receiver capture,
  distinct-operation counts/parentage, yielded values or re-raised errors at
  their own boundary. Separate a planned assertion from captured proof when
  the probe lacks receiver/arguments, native nodes or terminal OTel fields.
  Preserve nesting and business/protocol behavior without duplicate wrappers;
  dispatch support alone does not prove fields, privacy, lifecycle or sink.
- Give normal local logs their own acceptance entry, joined to the consumed
  profile's `OTEL_LOGS_EXPORTER=otlp`, resolved same-namespace logs endpoint and
  matching protocol. Name the planned or captured bounded/redacted body,
  severity, shared service resource and trace/span IDs matching the owning
  span, alongside separate span and metric-datapoint receipts. Assert one
  native LogRecord per application log call, retention of the actual original
  stdout/file sinks, owned log-provider/bridge drain and close, and local-only
  routing with no cloud log forwarding. SDK `@log` spans, stdout correlation
  and exporter settings alone do not supply this application LogRecord proof.
- Assess explicit log opt-out and misconfiguration separately from normal
  acceptance. Honor an operator opt-out and assert zero OTLP LogRecords while
  retaining original local sinks. An unsupported protocol, conflicting route
  or failed log path remains an explicit log gap; preserve unrelated trace,
  metric and original logging paths. A plan states concrete settings/assertions
  and marks execution unproven; a synthetic receipt never closes application
  runtime proof, and an opt-out test never closes the normal default path.

When supplied dependency compatibility facts are sufficient to decide,
select the newest compatible candidate in the plan and explain each rejected
newer candidate using the actual runtime, peer, API and lock constraints.
Do not defer that supplied-case decision to implementation. Keep fictional
policy selections and dated captured versions distinct from a new live
package lookup, actual installation and future shipped defaults.
When actual SDK/exporter/bridge metadata or a project solver result is absent,
record those components as unresolved with the missing evidence; do not invent
an actual compatible graph from historical probe versions. Before authorized
dependency application, resolve the coherent graph and bind installation to
its exact checked specs or lockfile, preserving constraints and checking the
installed graph/APIs. Never apply unresolved placeholders or re-resolve a
floating latest tag after checking a different candidate.

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

When the canonical audit declares GenAI ownership, project
`## GenAI Readiness Closure` in `.observe/otel-instrumentation.md` after
`## Audit Gap Closure` only for selected GenAI finding surfaces. Copy the
selected surface and its complete `Required Signals` cell from the audit
readiness table, then record `Implemented / proven`, `Tests`, `Remaining
signals`, and `Result`. Use one row per selected GenAI finding area in selected
finding order; do not include unselected readiness surfaces. Use `Working`,
`Not working`, `Not proven`, `Not configured`, or `Deferred` to match the bound
instrumentation or verification JSON status. `Working` requires `Remaining
signals` to be exactly `None`; all other results must name the remaining
signal, blocker, or external owner. Omit the section when the source audit
explicitly declares `No` or when no selected finding maps to a GenAI readiness
surface. If the ownership declaration and readiness table disagree, regenerate
the source audit before instrumentation.

When no canonical source audit exists, do not create `## GenAI Readiness
Closure`, invent closure rows from the implementation pass, or continue
audit-driven instrumentation.

If the canonical audit contains `genai_readiness` rows with `partial` or
`missing` status and the user asked to instrument, treat those rows as an
approved request for custom GenAI readiness instrumentation. Do not stop after
auto-instrumentation and do not ask the Step 4 custom-instrumentation question
for GenAI gaps that the repo clearly owns.

### Audit-Driven Gap Closure

Treat the validated dependency-closed selected finding set as the implementation queue, not
report background:

- Implement exactly the selected IDs plus executable dependencies added by
  `select`; never add unselected work. Priority orders the audit only and never
  authorizes instrumentation scope. When a selected GenAI finding lists
  content attributes in `expected_telemetry` or `required_signals`, implement
  those exact attributes without a second content-capture approval or runtime
  enablement flag. Do not add content attributes absent from selected findings.
  Before editing a selected model, retrieval, or tool finding, reconcile its
  listed content attributes with the current source boundaries and all eight
  attributes in the shared Content Capture Governance Contract. If a stale
  audit omits an applicable source-backed attribute, do not silently expand
  selected scope or call the finding complete: refresh the audit and selection
  first. For every listed content attribute, record a redacted, truncated,
  schema-conforming value from its actual owning boundary on the canonical
  model, retrieval, or tool span before that span ends. This includes provider
  input/output messages, observable system instructions and tool definitions,
  retrieval query and documents, and tool-call arguments and result. A
  metadata-only span, an HTTP-body substitute, or a test that checks only span
  existence does not close any listed field. Keep the selected finding partial
  or blocked until focused completed-span tests prove each listed attribute,
  its structured shape, and the absence of raw content.
- For every proposed GenAI metric, match its exact name, unit, instrument type,
  and attributes to a selected finding's `expected_telemetry` or required
  signals before creating it. A selected token-usage histogram does not also
  select input-token and output-token counters merely because those counters
  are current semantic-convention alternatives or can be derived from the
  same provider response. Do not implement, test as selected, or claim those
  additional counters unless a selected finding explicitly requires them.
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
- In audit-driven runs, the selected scope overrides the general default-log
  setup: do not add unselected local log export or attach it to a selected
  finding's `telemetry_changes`. Leave existing logging intact unless a
  selected finding explicitly requires log export.
- Preserve the audit finding_group classification in the bound audit. The
  instrumentation overlay references selected finding IDs and does not repeat
  `finding_group`; do not invent a group for ordinary OTel findings.
- A row may require only verification rather than code. Run the mapped
  scenarios and do not invent a source change.
- Reconcile GenAI gap rows with `## GenAI Readiness`; the readiness row remains
  the detailed required-signal contract and the prioritized gap remains the
  user-facing work item.
- For selected `finding_group: splunk-agent-observability` rows, implement the
  source-backed product or routing configuration described by the finding and
  its executable dependencies. Use `configuration` telemetry changes for
  Agent Observability resource settings rather than inventing spans or metrics. Leave durable
  app/deployment configuration for the selected API and ingest endpoints. In
  gateway mode Studio owns cloud realm/credentials; the application uses only
  supported resource/export configuration and local credentials when required.
  Existing non-AO paths use the discovered standard resource HTTP API and
  existing trace exporter; add no AO SDK configuration or dependency.
  For a selected Python SDK-owned Studio gateway path, follow the shared AO reference's populated
  profile contract: persist `SPLUNK_AO_API_URL`, `SPLUNK_AO_CONSOLE_URL`, and
  `SPLUNK_AO_API_KEY=local-gateway` in the actual loaded env profile before
  running provisioning. Use the discovered API base, preserve non-default
  ports, and prove the generator and provisioning process receive all three
  values. Adding keys to a pass-through list or unused sample is insufficient.
  Preserve project/stream headers on each export, never a global Studio route
  registration. Keep unselected AO findings untouched.
  Include and execute a supported provisioning step instead of implementing
  only `Projects().get()` and `AgentStreams().get()` with placeholders. For
  Python, use `scripts/resolve_ao_resources.py` through the project runner, or
  implement an application-native equivalent with the same tested contract.
  Persist the resolved project/stream bindings in the actual launch profile
  before initializing the selected trace export path. Verify both-existing
  (zero creates), both-missing, mixed, repeated-run, duplicate-race, and
  failure-isolation paths with real loopback HTTP API fakes for SDK-free
  paths, or compatible SDK clients for an SDK-owned path. A live API failure blocks resource delivery
  proof, not implementation and testing of creation. Record creation as
  attempted/blocked/recovered accurately and rerun when the prerequisite is
  available; do not replace the selected creation work with an operator task.
- When selected Agent Observability work needs an additional exporter package,
  persist only that required package in both the dependency manifest and the project lockfile, in the
  dependency set installed by the application's actual launch. An optional
  extra that the normal launch never selects is not an installed AO route.
  If the project's configured runner is `uv sync`, create or update `uv.lock`,
  run `uv sync --locked` for the default launch (or the same locked extra/group
  profile used by the actual launch), then import and
  exercise the actual selected exporter without live credentials. Existing
  SDK-free exporters do not require installing the AO SDK. A preflight
  environment containing an optional exporter does not prove that a later normal sync kept
  it installed. Treat missing credentials for remote project, Agent Stream,
  or delivery proof separately from dependency resolution: credentials do not
  block local lockfile, import, or configuration checks. If package resolution
  itself is unavailable, record that exact blocker and keep export
  `Not proven` or `Not configured` as appropriate; a manifest entry plus
  placeholder environment variables is not durable deployed routing.

Build an internal closure matrix before editing:
`finding ID -> area -> priority -> required fix -> instrument mode -> planned action ->
verification scenarios`. Update it after validation and verification. Do not
mark a row `Working` merely because code changed or a shared helper test
passed. Closure requires the source change or proven existing implementation,
the applicable project-runtime validation gate, and `$otel-verify` proof at the
audit scenario's proof level. In particular, execute every named route, span
call site, metric path, log pipeline, and duplicate-prevention scenario the row
references.

