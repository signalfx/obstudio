# OpenTelemetry logging rules and issue remediation

This PR adds nine shared logging rules for `otel-audit`, `otel-instrument` and
`otel-verify`, strengthens their language-specific guidance, and maintains real
Java, Python, Go and Node.js SDK/bridge tests. The rules help agents identify
concrete logging defects, implement selected repairs through existing owners,
and prove behavior at the claimed boundary. They do not certify every application
or require optional SDK features to be implemented in application code.

**Current state:** Claude independently verified the 183-row primary-source
inventory and subsequent source corrections, including the version-neutral
Java guidance. Real bare-skill development workflows then exposed a selected
Java framework-log privacy failure and incomplete Node delivery accounting.
Their source-backed clarifications and a Java native regression are applied;
Claude is checking the exact changed clauses. All 88 native cases and 203
focused checks pass. The strict complete three-run gate has **0/3** clean passes.
Prior clean runs and partial development workflows are historical; the final
whole-PR combined review follows three complete unchanged-source clean passes.
Publication and current-head CI status are tracked in
[PR 352](https://github.com/signalfx/obstudio/pull/352).

## What was missing and why

The [baseline evidence](logging-skill-analysis-evidence.json) binds the first findings
to original merge base `4e1e51f3`, with source paths, hashes and surrounding policy.
The branch now includes upstream `e2c31a57`; that update changed fixture
dependencies and generated metadata, not these logging skill instructions.
Search absence alone was not treated as runtime failure. Existing instructions
already required trace correlation and preserving application sinks; the missing
parts were explicit record/context/loss policies and proof strong enough to
support the claimed coverage.

The first correlation tests injected known `SpanContext` IDs. They proved
context copying, including unsampled and async controls, but could pass while
real tracer initialization or span export was broken. The corrected native
scenario creates real SDK parent/child spans, traverses the owned executor,
thread/goroutine or callback, logs inside that worker, then joins the emitted
log's canonical TraceId/SpanId to its exact received span. It checks flags,
parentage and resource identity. Independent known-ID async and synchronous
real-span tests cannot substitute for that joint scenario.

The process gap was a theme-based checklist without a required reconciliation
of source clause, requirement level, owner, installed capability, selected
application path and proof boundary. `otel-verify` also did not originally
consume the shared logging guide. `LOG-SPEC-CLOSURE`, per-consumer semantic
controls and source-bound execution receipts correct that omission. The
expanded Claude inventory below then exposed environment-first classification
and several conditional-feature decisions that needed clarification.

## Rules added and expected repairs

| Rule | Gap addressed | Expected behavior and proof |
|---|---|---|
| `LOG-RECORD` | Source numeric severity, timestamps and structured meaning could be misrepresented. | Use the detected bridge mapping; preserve occurrence versus observation time and supported precision. Check actual records, optional fields and selected event/attribute conventions. |
| `LOG-CONTEXT` | Unsampled flags, stale context and real log/span joins were insufficiently explicit. | Check exact canonical IDs/flags for sampled, valid unsampled and outside-span logs. Join the same owned async log to a real received SDK span; never fabricate IDs or force sampling. |
| `LOG-ASYNC-HANDOFF` | Executor and logging-queue placement could lose caller context or leak a reused worker's context. | Capture per work item before dispatch, reuse verified propagation, restore/detach after success/error/cancellation, and prove request pairing under concurrency. |
| `LOG-EXCEPTION` | Invented aliases, raw exception serialization and formatter/MDC paths could bypass capture policy. | Apply the selected allowlist before capture/export, retain permitted type/category and assert forbidden field absence. Bridge messages and instrumentation exception events keep their different convention scope. |
| `LOG-LIMITS` | Span limits could be mistaken for log limits; attribute limits could be mistaken for a Body cap. | Name supported log count/value settings on the existing provider. Test below/at/above boundaries and separate Body/privacy policy. Preserve adequate defaults; guard expensive construction using supported current enablement. |
| `LOG-DELIVERY` | Enqueue, flush or HTTP200 could be mistaken for full acceptance; retries and shutdown could exceed the budget. | Identify the actual processor, bound supported batch/export/lifecycle waits, and distinguish attempted, received, rejected, dropped and unknown outcomes. A simple processor has different obligations. |
| `LOG-DIAGNOSTICS` | Exporter failures could re-enter their own bridge recursively or flood diagnostics. | Name safe routing/suppression, preserve the original sink and application progress, and test bounded diagnostics/attempts under a fault. Check other configured signals separately. |
| `LOG-VERIFY-FRESH` | Stale XML, zero child exit and aggregate counts could hide skipped or mismatched runs. | Use unique report storage, actual pass/fail/error/skip counts, source/version/command bindings, incremental results and timeout cleanup. Missing evidence cannot pass. |
| `LOG-SPEC-CLOSURE` | Mentioning a rule or counting tests could conceal an omitted applicable guideline. | Reconcile official clauses with owner, applicability, effective configuration/default, finding/scenario and proof boundary. Unverified and unselected features stay explicit; combined claims require the same owned path. |

The canonical [common guide](../skills/references/logging-readiness.md) owns
these decisions. Concrete bridge APIs, numeric mappings, async mechanisms,
limits, whole-deadline options and diagnostic routing live in the existing
[Java](../skills/references/languages/java.md#logging-readiness-checks),
[Python](../skills/references/languages/python.md#logging-readiness-checks),
[Go](../skills/references/languages/go.md#logging-readiness-checks) and
[Node.js](../skills/references/languages/node.md#logging-readiness-checks) guides.
Only the detected language section is loaded. The Java guide resolves supported value mapping from the actual dependency and
appender test, with no fixed release assumption or internal main-branch mapper
link. Release pins remain in reproducible test evidence. The old instrumentation paths
remain forwarding references, and all three consumers are declared in
`skills/references/consumers.json`. Canonical/plugin mirrors match.

A real isolated-workspace probe exposed a refactoring defect: the shared guides
still referenced a sibling instrumentation skill that is not staged for audit
or verification. **8 of 12 references were missing.** The focused regression
failed for audit and verification before the fix (**2 failed / 1 passed**),
then passed for all three. Shared logging checks now work with only the selected
skill, without requiring another skill installation or widening read-only scope.

## Expanded Claude guidance inventory and corrections


Claude Desktop produced an official-source inventory against the prior frozen
`62e0391` instructions: **183 clauses from 30 source entries**, comprising 148
applicable instruction rows (87 covered, 35 partial, 26 missing) and 35 not
applicable. These are Claude's original instruction verdicts, not runtime
results or a current-source clean review. Its 16 grouped findings expand to
**25 candidates** when the ten minor sub-findings are counted individually.
The [machine-readable evidence](logging-skill-analysis-evidence.json) preserves
all 183 rows, source links, original verdicts, limitations and the 25 Codex
verification dispositions. It also records the actual Desktop session and
raw output digest. No Codex conclusion has been relabeled as a Claude rereview.

The following corrections extend the existing nine rules. Conditional features
remain conditional; absence of an optional SDK feature is not missing application
code. The root cause was an environment-first decision path and a thematic
checklist that did not consistently resolve each clause's owner and proof
boundary. Searching for `log` also missed existing requirement-level, resource
and privacy instructions. The source-to-owner matrix and negative controls now
require those surrounding rules to be read and reconciled.

| Candidate | Verified instruction correction or disposition | How it prevents a wrong repair |
|---|---|---|
| GAP-1 | Resolve a supported active declarative loader, substitutions and overlays before flat environment recipes. | An ignored `OTEL_LOGS_EXPORTER=none` cannot falsely disable a file-configured route; unsupported loaders stay unverified. |
| GAP-2, 6h | Inspect effective SDK disable, supported logger filters and current native enablement. | Distinguishes intentional filtering from missing wiring, retains severity-0/no-context controls, and avoids expensive disabled-record construction without suppressing an enabled original sink. |
| GAP-3 | Name the Collector boundary, retaining pre-SDK/pre-writer privacy policy. | Approved downstream redaction is coverage only at that boundary; it cannot erase an earlier forbidden capture. |
| GAP-4, 10 | Selected semantic event names exclude dynamic IDs; custom keys avoid reserved/colliding namespaces. | Preserves queryable categories without demanding EventName on ordinary messages or moving forbidden data to attributes. |
| GAP-5, 7 | Verify server throttling, status-specific retry and supported byte bounds separately from Body limits. | HTTP400 retry and per-attempt deadline reasoning cannot be called conformant; no application retry loop replaces SDK behavior. |
| GAP-6a | User exception attributes win when a selected supported Emit API derives fields. | Prevents supported exception processing from overwriting an explicit allowed value. |
| GAP-6b, 6c | Selected event-to-span processing continues the log; custom async mutation needs a verified safe snapshot. | Avoids log loss and shared-record races while retaining built-in processors and unsupported-feature limits. |
| GAP-6d, 6i, 6j | Scope instrumentation exception rules and deprecations to the selected producer/version. | Artificial status exceptions and type/message requirements cannot force extra bridge events, forbidden capture or an unrequested migration. |
| GAP-6e, 6f | Check per-record discard diagnostics and consistent scope identity. | Prevents per-attribute diagnostic storms and conflicting identity; SDK-owned internals stay SDK-owned. |
| GAP-6g, 16 | Syslog and HEC sinks are not selected. | Their optional/non-normative format examples do not create mandatory work from language choice or Splunk branding. |
| GAP-8 | An SDK console exporter can use a simple processor. | Avoids false missing-BLRP/queue findings and assesses synchronous cost on the actual path. Native console sinks are separate. |
| GAP-9 | State code-over-environment resource merge and effective decoding; preserve operator identity when adding defaults by avoiding conflicts. | The prior preservation policy was valid, but assuming env overrides explicit code was not. Existing resource/provider owners remain intact. |
| GAP-11 | Inspect an already selected development `_ref` path only. | Requires a registry-defined base and string reference without authorizing new storage or sensitive-content offload. |
| GAP-12 | Inspect selected development UID/stream/original fields. | Distinguishable records cannot share a UID; trace IDs are not record IDs, and original content is bounded before construction. No mandatory UID on every log. |
| GAP-13 | Follow verified bridge/convention version for call-site attributes. | Avoids blindly rewriting an SDK or upgrading solely to copy newer dotted keys. |
| GAP-14 | Use supported SDK self-metrics with their documented pipeline stage. | A created/processed count cannot establish receiver acceptance; no duplicate application metrics are introduced. |
| GAP-15 | Record language Logs signal and feature maturity. | Development/RC status triggers capability verification, not an automatic upgrade or skipped language. |

These decisions follow the [SDK configuration specification](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/),
[Logs SDK](https://opentelemetry.io/docs/specs/otel/logs/sdk/),
[event conventions](https://opentelemetry.io/docs/specs/semconv/general/events/),
[OTLP delivery](https://opentelemetry.io/docs/specs/otlp/), and
[resource merge contract](https://opentelemetry.io/docs/specs/otel/resource/sdk/).
The complete per-candidate source catalog is in the linked evidence JSON.
Codex also read the previously deferred filelog configuration, declarative SDK
configuration and four language log-instrumentation sections. Unrelated
span/metric tutorial sections and unselected sink formats remain outside scope.

All twelve skill/language eval definitions now have **14 semantic criteria**
and three prompt variants. Every task is exactly `$otel-audit ./service`,
`$otel-instrument ./service`, or `$otel-verify ./service`. The previous coached,
plan-only synthetic overlays have been removed. Their old results remain
historical decision evidence and do not satisfy the current gate.

The real fixtures expose bounded sync and owned async logging paths plus an
outside-span startup record. The host runner keeps each service through the
normal audit → instrumentation → verification handoff, stages the three skills,
and independently runs the generated app after implementation and verification.
Two concurrent requests share a trace but have different client/server ancestry;
each worker log must join its exact received SDK span and its own request tree.
Original native output, WARN mapping, Resource identity and outside-span context
are checked too. The actor receives no extra repair prompt. Detailed expectations
belong to the fixture, runtime checker and grader.

Each language gained a real native worker/callback test that first demonstrates
eager construction of an INFO payload discarded at ERROR level, then checks
current enablement before construction through disabled/enabled/disabled states.
Java uses Logback `isInfoEnabled`, Python uses `isEnabledFor`, Go uses `Enabled`
and Node uses Winston `isLevelEnabled`. All retain the original sink when an
intentionally disabled OTel path has no processors. Node's Console planning
control uses the supplied application predicate; the Winston runtime result
is not Console runtime proof. The Go test exposed an additional fixture bug:
its fanout dispatched to a disabled native handler when only the OTel side was
enabled. It now checks each handler and preserves both errors without preventing
the other handler from running. The focused race-enabled native run passes
**83/83**: Java 23, Python 22, Go 19 and Node 19, with zero skips/errors/failures.

## Retry-After acceptance-plan correction

The first expanded complete pass met **155/156 criteria** with all **83 native
cases passing**. Node audit's saved plan proposed `Retry-After=100ms` for an
HTTP429/503 response. This is invalid header syntax: the
[OTLP throttling specification](https://opentelemetry.io/docs/specs/otlp/#otlphttp-throttling)
requires an HTTP-date or a number of seconds. The failure was an acceptance-plan
defect, not evidence of an installed Node SDK or application defect. The original
grade and plan are retained; a high aggregate score and successful task command
did not satisfy the every-criterion gate.

`LOG-DELIVERY` now names the valid representation and its interaction with the
earlier whole deadline. A new control supplies `Retry-After: 1` arriving 100ms
into an 800ms export budget, inside a 1000ms caller budget: the one-second wait
cannot fit, so the plan must retain the initial request, forbid an early/forced
retry and finish within the earlier budget. It must not lengthen operator
budgets to make a retry occur. All twelve rubrics assess the invalid-header
observation and that independent control. Native fixtures are unchanged; actual
server-throttle conformance stays conditional on installed support and a future
controlled receiver test. This correction resets the current streak to zero.

## Remaining inventory clauses and final source verification

The 25 grouped findings do not enumerate every partial row: **12 of the 61
original partial/missing instruction rows** sit outside those candidate groups.
The evidence JSON now records a separate disposition for all twelve, so a
complete inventory check cannot stop at the grouped findings. Clarifications
cover selected event definitions and signal choice (G1/G5), conditional exception
API/name preferences (H4/H7), low-entropy hashing limits (L4), SDK-owned OTLP
header parsing (M7) and supported canonical EventName rather than a deprecated
attribute (U1). Existing per-destination and empty-env rules cover I11/K2.
Direct-API alternatives (A4), upstream release maintenance (H10) and SDK codec
internals (I13) do not mandate new application implementations.

A fourteenth criterion in every language/consumer rubric exercises those
conditional decisions, ordinary-log controls, privacy permissions and SDK/upstream
ownership. These source-derived checks do not add optional features to the native
fixtures or certify unsupported SDK behavior.

Claude Desktop independently verified all 13 supplied files at instruction
snapshot `c89c166b`, then opened the 23 remaining primary sources. All **183
inventory rows** now have directly read source corroboration; zero rely only
on supplied paraphrases. One shared SDK-duration instrument outside the inspected
log-metrics section remained unverified and is included in the changed-clause
follow-up. The source review does not establish runtime behavior.

Five independently checked corrections extend the existing rules:

| Source-verification correction | Expected effect |
|---|---|
| OTLP populated partial success forbids retrying the request, including an inferred rejected subset and a zero-rejection warning. | Prevents duplicate acceptance; keeps request attempts, accepted/rejected records and local queue drops separate. |
| Instrumentation libraries and semantic-convention authors have distinct ownership. | Avoids filing upstream release duties as missing application code while retaining obligations on a library this repository actually owns. |
| A known erroneous event from a source with no level concept has a recommendation for ERROR17. | Retains unknown severity0 for levelled sources and avoids elevating the narrow recommendation to a universal MUST. |
| Supported environment Booleans treat only case-insensitive true as true. | `1`/`yes` cannot falsely establish an SDK opt-out; active file configuration keeps its own precedence. |
| Exactly-one receiver counts apply to healthy delivery. | Observed acknowledgement-loss retries are counted separately from SDK emissions; healthy duplicate bridges and native sink duplication remain defects. |

The common guide also clarifies meaningful zero/false/empty values, Resource's
SHOULD exemption from common limits, and recursive attribute versus nested-Body
limits. Non-normative security guidance and stronger local policies are labeled.
Every language/consumer rubric has meaningful new negative and positive cases
for these distinctions. Claude verified all five corrections and every changed file at `bb3d38c8`.
It found one additional omission: the enumeration lacked supported empty/null
AnyValue. That source-backed correction now preserves accepted null array
positions and scopes permitted substitution to exporters unable to represent
null. All twelve rubrics include deletion/misalignment, valid same-position
substitution and unknown installed API controls. The interrupted `fd180b1d`
attempt earns no clean credit; Claude verified this final D1-only change
at `d9ae5700` and confirms D1 closed with no remaining verified mismatch in
the inspected source scope. Source verification remains separate from the final whole-PR
combined review, which waits for three complete clean runs.

Four new native value tests pass. Python, Go and Winston preserve approved
zero, false, empty string and empty array attributes. Java's pinned official
Logback appender preserves enabled approved scalar fields but **omits empty
collections**. The failed probe and official tagged mapper independently prove
that limitation. The evidence JSON includes the exact disposable test method,
fixture setup reference, command, actual failure message and source/XML hashes
so the counterexample is reviewable without the local cache. Java's separate
typed SDK empty-array assertion passes; it is
not presented as a bridge repair. A required empty-array bridge field stays
uncovered until an authorized supported mapping is proven. The new rule/evals
require that honest classification rather than a second provider, duplicate
bridge or mandatory dependency upgrade. Current focused totals are **88/88**:
Java25, Python23, Go20 and Node20, zero failures/errors/skips. Null-array rules
have plan/decision coverage; installed SDK/bridge null acceptance and actual
exporter fallback stay unverified until a selected capability test runs.

The preceding retry batch timed out all twelve model subprocesses across recorded
clamshell/maintenance sleep; 83 native cases passed, but no completed semantic
reports were available. It earns no clean-run credit. A new awake attempt was
interrupted before grades completed to finish the twelve-clause reconciliation;
its partial evidence is retained. No timeout or interrupted run is reported as clean.

## Current validation and three-run gate

The current 13-file instruction snapshot is
`07a6809ad77e9d1d7243e11ec6f47be5593134775c75e802dfb6734e574ac1f3`.
Claude verified B1/B2/B3 at `b117b995`; four subsequent changed files are pending
its exact-source check. The previous full-workflow development attempt executed
10 of 12 stages: all four audits passed 14/14, Python and Go passed their full
42/42 criteria, Java instrumentation passed 12/14 and Node 13/14. That is
137/140 executed criteria, with two verify stages not run; it is not a complete
168-criterion pass. All four actual framework core sync/async correlation
checks passed. The failed privacy/accounting criteria remain failures.

Java's Spring validation WARN exposed an invalid-path sentinel in native and
OTLP output. The implementation wrongly treated preserving original formatting
as requiring that forbidden content remain. A paired real Spring/agent prototype
kept the same agent/POM and HTTP behavior: baseline leaked three native and three
OTLP records; the supported native hook produced three bounded WARN replacements,
zero sentinel leaks in either sink, and retained all four real SDK log/span joins.
It used an owned transparent loopback HTTP relay into Studio; it does not prove
the prototype's direct producer-to-Studio transport, whose earlier failed attempts
are retained. The maintained native Java regression separately proves safe
replacement, unchanged effective levels and unrelated diagnostics, and no emission
on enablement queries through the actual appender. Neither result certifies
arbitrary framework sanitization.

Node's implementation labeled completed 429/502/503/504 responses as still
awaiting a stalled-server response and omitted four acknowledged accepted records
from a five-record/one-rejected partial response. The shared delivery rule now
separates completed protocol failure, unacknowledged timeout, acknowledged counts
and backend persistence, retaining protocol-unspecified acceptance. All twelve
role/language rubrics semantically check both corrections. Claude's pre-adoption
review supplied four boundary/capability qualifiers, all incorporated. These
clarifications preserve conditional privacy policy and SDK ownership.

Each complete pass requires all four languages and all three skills:
**12 bare-skill stages / 168 individual criteria, eight independent real-app
startup checks, 88 native cases, 55 runner/receiver/workflow checks and plugin
parity**. Pass 2 starts only after pass 1 is clean; pass 3
starts only after pass 2 is clean. Any source fix, failed obligation or stale
receipt resets the streak. Expected faults in deliberately bad fixtures must
still be found; they are not hidden to obtain a clean result.

| Current native language | Cases per pass | Three-pass result |
|---|---:|---|
| Java | 25 | Pending |
| Python | 23 | Pending |
| Go, race enabled | 20 | Pending |
| Node.js | 20 | Pending |

The separate focused development run and interrupted setup attempts passed **88/88**, with zero skips, errors
or failures. It does not count as three complete passes. Each native pass also
contains **80 actual sampled async log/span joins**, four valid unsampled
non-export controls and four outside-span controls. Healthy receipts, partial
success and client-timeout/late-acceptance cases are distinct. A successful
client enqueue/flush is never used as receiver acceptance.

| Deterministic command | Current result |
|---|---|
| From `evals/`: `UV_NO_CONFIG=1 uv run pytest -q test_default_local_log_export_guidance.py test_incident_readiness_skill_guidance.py test_logging_contract_runner.py test_logging_receiver.py test_logging_workflow_check.py` | 203 passed |
| `UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-audit` | 743 passed, 5 scoped skips |
| `UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-instrument` | 774 passed, 5 scoped skips |
| `UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-verify` | 709 passed, 5 scoped skips |
| `PATH="$PWD/evals/.venv/bin:$PATH" make agent-policy-check` | 49 unit + 8 contract checks passed; policy passed |
| `PATH="$PWD/evals/.venv/bin:$PATH" make test-interactive-otel-scripts` | 188 passed |
| `make check-obstudio-plugin-skills` | Passed |

The five validation skips are one optional module and four Python cases that
require the runner-owned receiver. Formal native trials supply that receiver
and require zero skips. The full-harness target initially rejected the previous
rubric summaries as stale; it must pass again after current semantic reports.
The freshness guard has not been bypassed. The earlier source's full harness
passed 880 checks / 5 scoped skips and verified 26 manifests; that is historical,
not the result for this revision.

The full host workflow command for one language/trial is:

```sh
cd evals
UV_NO_CONFIG=1 uv run python run_logging_workflow.py --language python --trial 1 --studio-binary /path/to/obstudio --codex-home ../.workspace/codex-evals/codex-home --output ../.workspace/logging-workflow/python-trial-1
```

The gate supplies the installed receiver binary and prepared Java 21/Maven/Go
paths, runs all four languages concurrently within each pass, and runs passes
1–3 sequentially. Every task and grader is checked against its actual isolated
Codex session `model` and `effort` metadata. HTTP success, a model's self-report
or a plan with “Not run” cannot establish positive runtime coverage.

The repository also requires representative local per-skill commands:

```sh
UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-audit CASE=go/chi-basic EVAL_PATTERN=go/chi-basic/eval/qual/logging-audit-contract.json PROMPT=logging-trial-1 MODEL=gpt-6.1-sol
UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-instrument CASE=go/chi-basic EVAL_PATTERN=go/chi-basic/eval/qual/logging-instrument-contract.json PROMPT=logging-trial-1 MODEL=gpt-6.1-sol
UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-verify CASE=go/chi-basic EVAL_PATTERN=go/chi-basic/eval/qual/logging-verify-contract.json PROMPT=logging-trial-1 MODEL=gpt-6.1-sol
```

Fresh commands are running for the final task definitions and post-upstream fixture.
Their actual rubric decisions, not pytest exit status alone, determine semantic
success. A preceding standalone instrumentation run passed 13/14; the missing
requirement-strength/maturity classification is now explicit at finalization. A standalone verify
on a fresh uninstrumented fixture exercises its missing-precondition behavior;
positive verification is supplied only by the same-workspace workflow above.

Both task and judge request **`gpt-6.1-sol` with high reasoning**, using
`evals/codex-evals.toml`. These are local PR-branch evaluations. The disabled
GitHub live-model workflow is not described as a GitHub Actions eval run.
A prior Go-only 33-criterion semantic check proved the isolated-reference fix;
it predates the expanded 13-criterion revision and does not count toward this gate.

Native runs use `evals/run_logging_contract.py` against the source-frozen fixture
revision for each pass. Dependencies belong to the parent `evals/pyproject.toml`
and `uv.lock`, Node `package-lock.json`, pinned Go module graph and Maven POM.
The runner performs dependency preflight, uses Go `-race -count=1`, and records
exact interpreter/toolchain commands, dependency versions, fixture hashes,
report paths, receipts and actual counts. The local JDK/Maven settings/toolchain
paths are execution evidence, not portable required repository locations.

## Evidence, review and limits

[Structured remediation results](logging-remediation-results.json) preserve
source-bound outcomes, failed/interrupted attempts, dependency versions,
correlation examples and historical datasets. The original 72-case assessment,
disposable 75-case async assessment and previous maintained 237-case matrix
are separate datasets; they are not added to the current 264-case native target.
Raw `.workspace/logging-analysis/` artifacts are local untracked receipts,
explicitly distinct from portable report links and committed test sources.

The completed Desktop inventory and prior `62e0391` reviews are retained with
their scope limits: the standard pass fully read 64/98 paths, while the adapted
Toolkit continuation declared 98/98. They are not final current-source reviews.
A fresh complete merge-base review in Codex protocol/Toolkit/baseline and
independent Claude Desktop standard/Toolkit passes follows the new streak of
three. The Toolkit code-simplifier criteria were applied directly to the cohesive
fixes; no further code simplification was needed. No review or current-head CI
success is claimed before its actual result.

The native fixtures prove selected SDK/bridge and owned loopback OTLP receiver
behavior. All four actual basic framework startups and core joins passed in development;
three complete final-source workflows remain pending. The host checker does not expose every trace flag bit;
the native fixtures separately check those flags. Neither suite proves
distributed queues, arbitrary payload sanitization, configured cross-signal
outage continuity, production Collector/cloud delivery, or every optional
Development feature. An actual service needs selected repairs and verification
through its real call sites and runtime wiring before those claims can close.
OTel also does not prescribe every business event an application should log;
that selection remains tied to the service's incident and privacy requirements.

The previously reviewed 70-file skill bundle was backed up and installed with
the existing aliases preserved. The current follow-up needs validated reinstall
before task completion; the old installation is not current-source proof.
