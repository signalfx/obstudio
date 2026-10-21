# Agent Observability eval failures and corrections

These failures were observed in model-generated application code and reports.
This record distinguishes valid failures from grading errors, retains the
original counterexamples, and records the focused corrections below. Fixture
log-endpoint fixes alone do not resolve these findings. A later passing model
sample does not erase the earlier failures or establish a fixed-version
reliability rate.

## Failure adjudication

The pre-correction archived counterexamples are valid failures of the intended
acceptance contract. No content-safety or actual applicability requirement is
relaxed in this correction. Redaction leakage, invalid
known typed parts, mismatched trace citations and contradictory source-case
ownership/applicability are application/report defects; helper-only resource
checks and absent outage captures are proof gaps. The historical runs do not
establish that every failure is a regression from a known-good fixed version.
The permissive official `GenericPart` extension does not satisfy this profile's
additional concrete validation requirement for a **known** discriminator.

The earlier requirement to relookup a complete, prevalidated same-destination
binding on every launch was a rubric/contract inconsistency; that was corrected
in the preceding review. The current nineteen failed checks below do not
reintroduce that obsolete requirement. Their failed criterion notes are
preserved in the archive.

| Failure family | Valid requirement / correction |
|---|---|
| Quoted scalar, labelled-value, typed-reasoning leakage and aggregate overflow | Keep content-safety rubric. Strengthen shared capture guidance and add source-shaped input/output/native-export counterexamples. |
| Malformed known part accepted through generic fallback | Keep concrete-schema rubric. Select the known discriminator schema before allowing an extension fallback. |
| Foreign-scenario trace IDs | Keep provenance rubric. Resolve IDs in their exact mode/scenario/destination capture and reject swapped associations. |
| Per-mode operation ownership; Python support in Go; non-agent AO rows | Keep source/applicability rubric. Reconcile each independent source ledger with required/excluded findings and every state row. |
| Resource routing tied to unrelated operations; missing cached-launch acceptance | Keep scoped routing and lookup-free persisted-binding requirements. These paths were clarified in prior corrections; preserve their historical failures. |
| Helper-only API/race/recovery tests; missing native outage observations | Keep app-bootstrap proof requirement. Exercise the actual integration and independently observe native signals when delivery is unavailable. |

## Observed failure rates before this correction

The [tracked history archive](evidence/agent-observability-eval-history.json)
contains all **19 retained graded runs / 69 task grades** for the fifteen-task
cohort ending at run `20261020T224014321690Z`, whose source packet was committed
as `ab8d7e8`, including partial reruns: **412/431 checks**, with
**9/15 distinct tasks failing at least once**. The eleven complete sweeps alone
contain **59 task grades, 45 fully passing, 356/373 checks**, and **8/15 distinct
tasks with a failure**. There were three complete audit sweeps, five instrument
sweeps and three verify sweeps; partial reruns were three, two and three,
respectively. Ungraded/aborted attempts are not successful samples.

These runs span changing skill, fixture and rubric revisions. These are observed
iterative-history rates, **not** an estimate from independent trials of a fixed
version. The archive retains every run's source manifest to expose that change.
The previously published 93/93 combines selected successful runs, not the
aggregate history or one coordinated sweep. A fresh pass cannot erase a prior
counterexample.

| Skill | Complete-sweep checks, in time order |
|---|---|
| Audit | 22/24, 21/24, 24/24 |
| Instrument | 42/47, 44/47, 45/47, 46/47, 47/47 |
| Verify | 22/22, 21/22, 22/22 |

“Task failures” counts any failed criterion. Criterion rates use all retained
completed grades of that task, including partial reruns; denominators differ
from the complete-sweep column. Criterion IDs are task-local; their text also
changed across revisions. Use each archived failed-check note and source
manifest for the exact requirement, rather than treating the ID as a fixed
statistical measure.

| Skill / task | Task failures / complete sweeps | Task failures / all runs | Failed criteria / all runs |
|---|---|---|---|
| otel-audit / `active-signal-matrix-audit` | 2/3 | 3/4 | rubric-2: 1/4, rubric-3: 1/4, rubric-4: 1/4 |
| otel-audit / `agent-resource-table-audit` | 2/3 | 2/4 | rubric-2: 1/4, rubric-6: 1/4, rubric-7: 1/4 |
| otel-audit / `agent-role-from-behavior` | 0/3 | 0/3 | None |
| otel-audit / `studio-connection-modes` | 0/3 | 1/5 | rubric-5: 1/5 |
| otel-instrument / `native-agent-resource-defaults` | 2/5 | 2/6 | rubric-3: 1/6, rubric-6: 1/6 |
| otel-instrument / `native-connection-modes` | 0/5 | 0/6 | None |
| otel-instrument / `preserve-genai-instrument` | 3/5 | 3/5 | rubric-3: 2/5, rubric-6: 1/5 |
| otel-instrument / `preserve-generic-instrument` | 1/5 | 1/6 | rubric-5: 1/6, rubric-6: 1/6 |
| otel-instrument / `preserve-logs-instrument` | 2/5 | 2/5 | rubric-3: 2/5, rubric-8: 1/5 |
| otel-instrument / `preserve-metrics-instrument` | 1/5 | 1/5 | rubric-6: 1/5 |
| otel-instrument / `repair-mislabeled-agent` | 0/5 | 0/5 | None |
| otel-verify / `agent-resource-table-verify` | 1/3 | 1/3 | rubric-3: 1/3 |
| otel-verify / `preserved-baseline-negative-verify` | 0/3 | 0/3 | None |
| otel-verify / `reject-green-workflow-test` | 0/3 | 0/3 | None |
| otel-verify / `studio-connection-modes` | 0/3 | 0/6 | None |

For example, GenAI failed the task in **3/5** complete sweeps, but content-safety
`rubric-3` failed in **2/5**; the third task failure was bootstrap/API proof
`rubric-6`. Audit operation ownership `rubric-2` failed **1/4** retained task
grades, not 2/3; the other task failures concerned routing closure and concrete
part validation. The resource-table audit's `rubric-2` likewise failed **1/4**;
its other failures concerned applicability and cached-launch acceptance.

The archive embeds all failed check notes/evidence, every check ID/boolean,
four independent reproduction receipts, four original failing sanitizer source
snapshots and the baseline report summaries/failures. SHA-256 values retain
provenance. This content survives a squash merge without the original commit
or ignored `.workspace` tree. Passing-check commentary is omitted explicitly;
no historical grade is changed or relabelled.

## Correction-round adjudication

The [correction evidence](evidence/agent-observability-correction-runs.json)
retains new raw grades, both non-agent report objects, repaired runtime source
and independent replay receipts. The first updated audit run was **23/24**, instrumentation **53/53**
(including all four preservation modes and the focused repair), and verification
**21/22**: **14/16 tasks fully passing, 97/99 raw rubric checks**; their pytest wrappers exited successfully despite the
failed rubric checks. Command success is not semantic rubric success.

The audit failure is **confirmed**: its source ledger says a single inference
facade, but an unscoped lifecycle row prescribes an agent with model/tool
children. The skill now requires field/lifecycle rows to agree with the same
case's operation ledger, including a negative report association test.

The verification failure is a **grading false positive**: the whole
`provisioning_acceptance` section is explicitly `Not applicable`, as are every
resource, route and state outcome. Its nested `required` list is a conditional
catalog in that non-applicable scope, not an instruction to provision this
control. The rubric now evaluates effective scope; it still rejects active
required/Blocked child outcomes or instructions to provision a non-agent.
The original failed grade is retained, not overwritten or counted as a raw
pass. A separate regrade of the unchanged original actor output with the
clarified rubric passes **6/6**; service-file hashes and the original grade hash
remain unchanged. It is supplementary grading evidence, not a new actor run. This differs from the older baseline's active Blocked/required state
contradiction, which remains a valid failure.


The paired report-only negative control changes one copied artifact to require
AO project creation before the non-agent can start. The same frozen rubric
correctly fails `rubric-3` while source files remain unchanged. This expected
failure is test evidence, not another model-generated application defect.

A second full audit/verification sweep produced **6/8 fully passing tasks,
44/46 checks**. Its two failures are confirmed: a fresh Go routing row refers
to an existing exporter that the source lacks, and names-only recovery
acceptance omits timeout/rate bounds. These raw grades and concrete report
fragments are retained. The next correction adds current/proposed sink closure
and explicitly assesses per-call time, retry frequency/backoff, business/local
telemetry progress and shutdown cancellation. It does not require stopping
retries permanently before a late Studio connection or inventing missing
numeric settings. The third sweep below evaluates that correction.

A third full audit/verification sweep produced **7/8 fully passing tasks,
44/46 checks**: audit **22/24**, verification **22/22**. The audit's remaining
failures were a Python `SpanExporter.export`/`ReadableSpan` fix copied into a
Go case and omitted names-only retry bounds. Both are valid. Inspection found
their source in the shared AO reference: an unlabelled Python carrier example
and a formal recovery checklist missing the bounds described elsewhere.
Those shared instructions now identify language-specific public interfaces and
include request time, retry rate/backoff, progress and shutdown in the formal
names-only acceptance. Every declared consumer is rerun after this change.

The third audit judge also objected to a supported SDK helper using a registered
native OTel provider. That explanation is rejected: **SDK span creation and
transport ownership are separate**. The supplied public helper contract permits
that binding; its selected native model exception was explicit. The Go defect
still makes the criterion fail, so its original failing grade remains intact.
The shared reference and a fresh-SDK planning rubric now explicitly preserve
this distinction without requiring a private vendor logger sink.

The focused sanitizer repair passed all six rubric criteria. Independent
clean-runtime replays on SDK **1.44.0** and **1.45.1** each captured **18 native
and 18 matching OTLP spans**, preserved original owners/business output, removed
the protected values and retained useful content under final serialized bounds.
Four malformed known parts were rejected; a valid extension remained valid.
These are local app-prompt and explicitly labelled synthetic output-seam tests,
not live model or cloud delivery. The final full consumer rerun is recorded
below; intermediate runs are not silently replaced by it.

## Targeted guidance correction result

The fourth run used the corrected shared reference and passed **17/17 tasks,
107/107 checks**: audit **24/24**, instrumentation **61/61**, verification
**22/22**. All four native preservation modes ran and passed **8/8** each. The
instrumentation cohort also includes the focused six-case content repair and
the fresh-SDK planning case. This is the targeted feature cohort, not the whole
repository's rubric inventory. Every raw grade and source manifest for each
correction round is in the tracked correction archive.

| Correction phase | Tasks fully passing / graded | Raw checks passed / graded |
|---|---:|---:|
| Representation/capture guidance | 14/16 | 97/99 |
| Source-ledger lifecycle and scoped N/A | 6/8 | 44/46 |
| Exporter topology and retry assessment | 7/8 | 44/46 |
| Shared language, SDK ownership and formal recovery acceptance | 17/17 | 107/107 |
| Stdlib logging fixture and normal CI coverage | 17/17 | 107/107 |
| Public logging handler reuse | 17/17 | 107/107 |

These phases include concrete source or grading corrections between runs;
they are not repeated samples of one unchanged version. The original failing
grades remain failed in the archive. The unchanged-output N/A regrade is kept
separately and is not substituted into the raw-check totals above.

The actual generated recovery integration additionally records a **12-second
API503 interval**, **0.5-second HTTP timeout**, retry gaps rising to a
**2-second cap**, continuing native/business turns, zero creates after late
same-PID binding, and cancellation of pending retries at shutdown. A stalled
API test confirms business/native progress despite a request exceeding its
timeout. The generated launcher/resolver/test sources and receipts are retained
in the archive. These are loopback API/OTLP tests, not live Cloud proof.

Final validation commands use `codex-evals.agent-role.toml` for actor/judge
runs. Audit and verification select
`python/model-directed-agent/eval/qual` plus their respective
`python/existing-otel-agent-demo/eval/qual/{audit,verify}.json` files.
Instrumentation selects those model-directed cases, the connection fixture,
all four preservation modes, the focused content repair, and
`python/ai-assistant-demo/eval/qual/genai-sdk-default-instrument.json`.
Exact invocations and final deterministic results are provided in the handover.

## Combined review: stdlib logging compatibility

Review of `98c75c7` confirmed a separate fixture defect. The declared
`opentelemetry-instrumentation-logging==0.48b0` injects correlation without
installing an OTel log handler. The fixture relied on automatic installation,
and its startup test bypassed the bridge by emitting through the OTel log API.
An ordinary stdlib log therefore produced no native LogRecord at the supported
SDK 1.27.0 floor. Newer instrumentation also lost those logs with its automatic
handler disabled. This is a code/test defect, not a reason to weaken a rubric.

The fixture now owns one public SDK `LoggingHandler`, disables the
instrumentor's automatic handler to prevent duplicates, preserves existing
console sinks and externally owned correlation, and removes only its own
handler at shutdown. A follow-up negative test exposed duplicate records when
an external instrumentor or SDK handler already existed. The final correction
reuses those supported public handler types and preserves their ownership.
The real stdlib-to-protobuf startup test now covers fourteen
configuration cases, repeated installation/shutdown, nonzero trace context,
opt-out and header/destination isolation. Its original-code negative control
fails, while the corrected code passes on SDK 1.27.0, 1.44.0 and 1.45.1.
All eleven fixture regression methods now run through normal harness validation
using declared development dependencies.

The [tracked review receipt](evidence/agent-stdlib-logging-review.json) preserves
the original absence failure, intermediate duplicate failure, exact source
snapshots/hashes, dependency versions and positive matrix logs. Its replay
cases identify the twelve-profile and fourteen-profile source revisions
separately. The SDK 1.27.0 test environment supplies legacy setuptools for
the old instrumentor's `pkg_resources` import; no SDK source or application
version cap was changed. The first fixture correction passed all 107 checks in
the same seventeen-task cohort and is archived as an intermediate result.
The final public-handler-reuse cohort also passed **17/17 tasks, 107/107
checks**: audit **24/24**, instrumentation **61/61**, verification **22/22**.
All four preservation modes passed **8/8**. Both fixture-correction rounds
retain every raw grade and source manifest in the correction archive; the
intermediate result does not substitute for the final source. Direct final-
checkout replays additionally pass all eleven methods on all three SDKs.
These are targeted local proofs, not a fixed-version reliability estimate
or new live Cloud delivery evidence.

## Completed evidence baseline

Commit `53406c89fa8128748e0223a4c10adf46df9a691a` contains the complete affected
sweep: **15 tasks, 10 fully passing, 86/93 checks**. All four preservation modes
passed the changed resource/API criterion (`rubric-6`). Overall grades were
generic 8/8, GenAI 7/8, metrics 8/8, and logs 6/8.

The tracked archive embeds those three baseline report summaries and all seven
failed criteria with evidence; the commit is provenance, not the only copy.
Full local actor artifacts additionally remain under
`.workspace/codex-evals/<skill>/<run-id>/cases/`.

| Finding | Task / criterion | Observed failure | Status |
|---|---|---|---|
| Quoted scalar redaction bypass | `preserve-logs-instrument` / `rubric-3` | JSON-encoded scalar email, token/reasoning text, and `private-prompt-sentinel` survive sanitization. Object/list JSON tests missed the scalar branch. | Shared guidance corrected; exact original scalar replays and native/wire corpus pass. |
| Hidden reasoning and size bounds | `preserve-genai-instrument` / `rubric-3` | `hidden_reasoning=HIDDEN_SENTINEL` survives. Sanitizing embedded JSON with sixteen 2,000-character fields produces 16,614 bytes, then assigns retrieval text directly despite declared 1,024/8,192-byte bounds. | Shared guidance corrected; original typed/labelled/aggregate cases pass on SDK 1.44/1.45 native and wire. |
| Verification trace provenance | `preserve-logs-instrument` / `rubric-8` | Public and rejected scenarios cite the Studio scenario's trace IDs; both intersections with their cited captures are empty. | Capture/scenario association guidance corrected; full verification rerun and negative association check pass. |
| Per-mode producer ownership | `active-signal-matrix-audit` / `rubric-2` | Metrics/logs plans exclude workflow/model creators as if existing trace producers owned them. The modes have no such producers; provider binding is also contradictory. | Independent current/proposed source ledgers required; full audit rerun passes. |
| Language-specific support evidence | `agent-resource-table-audit` / `rubric-2` | A fresh Go case cites Python exporter 1.45.1 and an existing exporter absent from that snapshot. | Shared carrier example scoped by language; full audit rerun passes. |
| Source-bound applicability | `agent-resource-table-audit` / `rubric-6` | Template leakage carries Python support into Go and an applicable AO-header row into a non-agent control marked N/A. | Source-case field/lifecycle/state reconciliation required; full audit rerun passes. |
| Non-agent state consistency | `agent-resource-table-verify` / `rubric-3` | Top-level AO resources are N/A, while state rows require or block resource resolution and delivery. | Active contradictions remain failures; explicit N/A scope clarified and paired positive/negative grading controls pass. |

## Reproduction and source locations

The logs and GenAI safety/provenance failures were independently reproduced.
Their receipts are embedded in the tracked archive; the original local paths are
`.workspace/claude-review-fixes-pass2-20261020/independent-new-failure-repro.json`
and `independent-genai-failure-repro.json`.

| Skill | Baseline run |
|---|---|
| `otel-audit` | `20261020T200853939788Z` |
| `otel-instrument` | `20261020T200855159694Z` |
| `otel-verify` | `20261020T200855276877Z` |

Each task's `with_skill/rubric_grade.json` records its full criterion notes.
The logs-generated sanitizer is at `service/instrumentation.py:62-72`; its
incorrect trace citations are at `service/.observe/otel-verify.json:376,402`.
The GenAI-generated sanitizer/query assignment is at
`service/instrumentation.py:31,55,169` within its own case directory.

## Fresh recurrence

The fresh instrumentation run `20261020T210914152057Z` repeats the content
safety failure in `preserve-logs-instrument` (7/8, `rubric-3`). Its generated
`service/content_capture.py:15-51` preserves
`hidden_reasoning=thought-sentinel` and transforms
`private_prompt=hidden-sentinel` into `[redacted]=hidden-sentinel`.
Both were independently reproduced; local evidence is in
`.workspace/claude-review-fixes-pass3-20261020/independent-current-logs-redaction-repro.json`.
The evaluator also reproduced propagation through native OTLP encode/decode.

The same run has an additional evidence gap in
`native-agent-resource-defaults` (5/6, `rubric-6`). Its complete receiver/API
outage case records business success, zero receipts, and an exporter error,
without independently capturing completed native spans, metric points or
LogRecords. Signal emission during that outage remains unproven. Closing this
gap requires independent native/in-memory observations in the outage case.

The full instrumentation run `20261020T214331268302Z` adds a typed-part
counterexample in `preserve-genai-instrument` (7/8, `rubric-3`). Its generated
`service/safe_content.py:17-35` redacts sensitive field names but preserves
`{"type":"reasoning","content":"hidden-reasoning-sentinel"}`, including when
JSON-encoded inside the actual prompt. An independent copied-runtime replay
preserved the business result while exposing the sentinel on completed
retrieval, chat, agent and workflow spans and in the encoded native OTLP payload.
Evidence is retained in
`.workspace/combined-review-67a2503-20261020/fresh-reasoning-repro.json`.
The connection-probe corrections do not resolve this sanitizer failure.

## Closure requirements

Closure requires a focused correction and a regression exercising the original
failing input or report association. Preserve the prior evidence when publishing
fresh full-scope results. Local correction does not establish that every future
generated app is safe or that live-cloud delivery has been verified. The
archives preserve both failing and corrected source snapshots so a later
reviewer can replay the evidence after a squash merge.
