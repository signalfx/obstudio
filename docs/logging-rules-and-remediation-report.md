# OpenTelemetry logging rules and issue remediation

This change adds nine shared logging rules to `otel-audit`, `otel-instrument`
and `otel-verify`. The first six rules originated in the assessment at commit
`8600493b`; the follow-up adds explicit async handoff, fresh verification and
source-to-evidence closure. The rules cover record meaning, real trace
correlation, exception privacy, limits, delivery and diagnostic isolation.

These are agent instructions backed by maintained SDK/bridge fixtures and
skill evaluations. Application repairs still require implementation through
the existing provider and bridge, followed by proof at the claimed boundary.
The four verified test-infrastructure findings have code and regression fixes
in this change. This report explains the rules, their repair paths and the
scope of the evidence. Final review and CI status are tracked in
[PR 352](https://github.com/signalfx/obstudio/pull/352).

The completion gate requires **three consecutive complete clean passes** on
unchanged source across all four languages and all three skills before
combined review starts. Failed and interrupted attempts remain retained;
passing older-source results do not count toward the current streak.

## Language reference organization

Language-specific recipes now live in the existing four language guides under
`skills/references/languages/`, shared by audit, instrumentation and verification.
The old `otel-instrument/references/languages/` paths remain forwarding references.
Each original guide is preserved, with its relative skill link repaired and a
**Logging Readiness Checks** section added. The common logging reference keeps
the rules, source-coverage decisions and acceptance requirements, and directs
the agent to only the detected language's section.

The language sections own the concrete bridge mapping, async handoff, queue
placement, public log-limit options, complete deadline examples and diagnostic
routing. All three consumers are declared in `consumers.json`. Seven structural
checks prove those references are present in actual isolated skill workspaces
and that the old paths resolve to the canonical guides. The semantic evaluations
also add a foreign-SDK-options proposal: each skill must reject the wrong API
shape and unauthorized provider replacement while retaining the existing
resource and processors. This adds behavior coverage beyond relocating text.
The installed skill namespace has been backed up and synchronized: all 70
canonical files match, and existing aliases are preserved.

## Current three-pass gate

The preceding source completed two full clean passes. Its third complete pass
met 131/132 criteria despite all 79 native cases passing. A Go audit plan
proposed known-context async checks and synchronous real-span joins separately,
without requiring the same async worker log to join its actual received span.
That omission reset the streak to **0/3**. The failed plan and grades remain
retained; the earlier two clean passes do not count for the corrected source.

The common proof-closure/context/handoff rules and all four language sections
now require an explicitly linked joint scenario through the owned boundary.
All four inputs add a split-proof counterexample, graded by all twelve
skill/language definitions. This addresses the integration-proof gap without
inventing a production defect from missing evidence or adding duplicate SDKs.
The maintained native correlation fixtures already execute that combined path.

The corrected 150-input source completed **three consecutive full clean
passes**. Each met 132/132 declared checks and passed 79 native cases, 37
regressions and skill-copy parity. Independent reconciliation confirms all
396 declared checks, 237 native cases and 240 real span/log joins, including
fresh XML, snapshot and wire evidence. Source and baseline hashes stayed
unchanged. The generated Go audit now names a joint `S-ASYNC-JOIN` scenario
through the owned goroutine and marks the separate-probe claim partial. The
three-pass prerequisite is satisfied; combined review follows on the frozen
complete PR scope.

## Why the trace-correlation proof was incomplete

`LOG-CONTEXT` and the four native bridges already populate the log record's
canonical trace/span context. The earlier 222-result matrix checked that
behavior with supplied non-recording contexts. It did **not** configure a real
tracer and prove that the corresponding spans were exported. The report's
fixture limitation was correct, but those results could not establish a real
application log-to-trace join. That distinction should have been made explicit
at the correlation claim.

The original language recipes already prescribe correlation:
[Java agent/appender proof](/Users/tithumma/code/splunk/obstudio-logging-analysis/skills/references/languages/java.md:700),
[Python bridge/context injection](/Users/tithumma/code/splunk/obstudio-logging-analysis/skills/references/languages/python.md:82),
[Go context-aware calls](/Users/tithumma/code/splunk/obstudio-logging-analysis/skills/references/languages/go.md:547),
and [Node bridge correlation](/Users/tithumma/code/splunk/obstudio-logging-analysis/skills/references/languages/node.md:414).
The omission was the requirement-to-proof reconciliation in this review, rather
than an absence of correlation guidance across those recipes. Source guidance
still has to be applied to each selected application's actual call sites.

| Root cause | Correction | Evidence now available |
|---|---|---|
| Context-copying tests were used without a real span producer/exporter. | Each language now starts real SDK parent/child spans and directly exports both traces and bridged application logs. | Every trial receives 20 sampled spans and 22 logs: 20 exact joins, one valid unsampled log and one outside-span log. |
| Nonempty IDs or an arbitrary `trace_id` attribute can look correlated without matching the actual operation. | Match canonical OTLP TraceId **and** SpanId, full SDK flags, async parentage and the service resource. Keep ordinary attributes distinct. | All 12 new correlation trials pass; receiver negative control preserves attribute-only IDs without promoting them to canonical fields. |
| The thematic checklist had no mandatory reconciliation of all applicable official source clauses. | Added `LOG-SPEC-CLOSURE`: source/version, requirement level, applicability, owner, configuration/default, finding/scenario and proof boundary. Any omitted applicable row keeps completeness partial. | New source catalog, false-coverage observation and valid unsampled/outside controls are graded for audit, instrument and verify in all four languages. Current semantic run status is recorded below. |
| Earlier verification did not consume the shared logging reference. | The verifier now loads it and independently checks obligations at real call sites. | Matching verifier rubric definitions exist for all four languages; canonical/plugin copies are synchronized. |

Real Python SDK spans exposed an additional test assumption: sampled flags were
`3`, rather than the supplied control's `1`. Assertions now compare the actual
SDK flags, preserving supported bits. This was a test correction, not an SDK
correlation defect. Concurrent probes also required a larger listen backlog in
the owned test receiver; the failed initial probes remain retained.

**The broader correction is a source-to-evidence gate.** It covers record
semantics, resource/scope, initialization/ownership, context and propagation,
filtering/opt-out, privacy, limits, delivery, diagnostics and lifecycle. Further
applicable source clauses must also be reconciled. SDK defaults can satisfy SDK
requirements; optional fields are not universally mandatory. A missing or
unexecuted proof remains partial/unverified. This prevents a claim of complete
guideline coverage based only on a named rule or total passing tests.

## Rules and expected behavior

| Added rule | Gap addressed | Expected result when applied |
|---|---|---|
| LOG-RECORD | Incorrect severity, timestamp conversion or record shape | Logs retain the meaning of the original event. |
| LOG-CONTEXT | Missing, stale or mixed request correlation | Logs match the request that emitted them, including unsampled and asynchronous work. |
| LOG-EXCEPTION | Incorrect exception fields or unauthorized sensitive capture | Allowed exception information survives without exporting prohibited content. |
| LOG-LIMITS | Span settings mistaken for log limits, or unbounded payloads | Log costs follow the selected attribute and Body policies. |
| LOG-DELIVERY | Unbounded buffering, misleading delivery claims or incomplete shutdown | Export remains bounded and loss is reported accurately. |
| LOG-DIAGNOSTICS | Exporter failures feeding back into their own logging bridge | Telemetry faults do not create recursive export storms or stop application work. |
| LOG-ASYNC-HANDOFF (follow-up rule) | Context loss at executors/callbacks/logging queues, or MDC leakage | Capture before scheduling, verify exact pairing and restore worker state. |
| LOG-SPEC-CLOSURE (follow-up rule) | Guideline clauses omitted or marked complete without the claimed proof | Map official sources to applicability, owner, implementation and independent acceptance evidence. |
| LOG-VERIFY-FRESH (follow-up rule) | Stale XML, skipped tests or incomplete matrices reported as success | Bind each verdict to fresh execution and retain failure/timeout evidence. |

The canonical implementation is
[logging-readiness.md](/Users/tithumma/code/splunk/obstudio-logging-analysis/skills/references/logging-readiness.md).
Both the [audit entrypoint](/Users/tithumma/code/splunk/obstudio-logging-analysis/skills/otel-audit/SKILL.md:301)
and [instrumentation entrypoint](/Users/tithumma/code/splunk/obstudio-logging-analysis/skills/otel-instrument/SKILL.md:1554)
load it, as does the updated [verification entrypoint](/Users/tithumma/code/splunk/obstudio-logging-analysis/skills/otel-verify/SKILL.md:31).
The plugin copies match the canonical sources.
The updated rules are also installed under `/Users/tithumma/.codex/skills/obstudio`;
the existing skill aliases are preserved and the changed files were backed up.

**LOG-RECORD — preserve record meaning.** Before this change, the skills covered
severity and body generally but lacked explicit occurrence-versus-observation
time and numeric mapping guidance. The new rule directs the agent to use the
detected bridge's mapping rather than copying a source logger's numeric level.
For example, Python source level 40 and Go slog ERROR level 8 must map to the
bridge's supported OTel ERROR range, commonly 17. It also preserves an available
event timestamp separately from collection time, avoids unsafe JavaScript
nanosecond conversion, and retains structured values. Unknown severity and
optional absent fields remain valid where applicable. Native probes cover
severity and timestamps; Node's historical precision subcase uses the SDK
directly, and Python remains subject to its source timestamp precision.

**LOG-CONTEXT — preserve the emitting request's identity.** Existing guidance
required in-span correlation but did not make unsampled behavior, flags,
asynchronous handoff and post-detach isolation equally explicit. The rule
requires exact TraceId, SpanId and TraceFlags checks at the log call. It prevents
using a remembered last span, leaking one request's IDs into another, or
introducing sampled-only logging as a default. An explicitly supported operator
filter remains respected. The follow-up probes below demonstrate both working
handoff and concrete context-loss controls in all four languages.

**LOG-EXCEPTION — apply the actual capture policy.** The rule adds explicit
exception attribute and applicability decisions. Where exception collection is
selected, the agent must use supported mappings such as `exception.type`,
sanitize permitted content before export, and omit message or stack content
when capture is not authorized. It must inspect nested values and formatter/MDC
fields rather than treating truncation as redaction. Existing logging bridges
keep their supported semantics; the rule does not force an extra EventName or
duplicate exception event. The stronger fixtures now pass real exception
objects and synthetic nested/MDC secret canaries through unsafe controls and
a producer allowlist. They verify permitted type/category retention and
prohibited-field absence through the bridge and original sink. This proves
the selected producer policy, not arbitrary application payload sanitization.

**LOG-LIMITS — bound the correct surfaces.** The rule prevents an agent from
claiming that span limits configure logs, or that attribute length limits cap
the log Body. It requires checking effective supported log attribute settings
and a separate Body policy when the application needs one. Adequate SDK defaults
count as coverage. The native tests show attribute limits and drop accounting;
they also show that a 400-character Body survives attribute limiting. That
counterexample explains why an application needing a Body cap must implement
and test it separately. No universal Body cap was added to application code.

**LOG-DELIVERY — distinguish bounded export from successful receipt.** The rule
requires log-specific batching settings or supported public options, a batch
size within queue capacity, bounded export/shutdown behavior, and separate
attempted, accepted, rejected and dropped evidence. It prevents applying
span-only `OTEL_BSP_*` settings to logs or treating HTTP 200, enqueue or flush as
complete delivery. For the synthetic partial-success case, the correct outcome
is three attempted, one accepted and two rejected. Plans were tested against
that distinction. The stronger suites now test bounded-queue overload and
replay bridge-produced SDK records through official OTLP/HTTP exporters into a
local test receiver, including partial success and stalling. They prove that
the receiver can accept after a client timeout. Acceptance remains unknown
until receipt evidence resolves it; a per-request timeout must not be assumed
to bound the whole retry path. In-memory batching provides no durable or
exactly-once promise.

**LOG-DIAGNOSTICS — isolate telemetry's own failures.** The rule extends the
existing Go recursion warning into a cross-language requirement. The agent must
trace diagnostic routing and use supported suppression or separate diagnostics
so an exporter failure does not return through the same application bridge.
Acceptance must check bounded diagnostics/export attempts, application progress,
the original sink, and every other configured signal. The stronger probes now
observe actual SDK failure diagnostics outside the application bridge, bound
attempts and prove subsequent original-sink output. Java observes the pinned
SDK's JUL FINE failure message. Go isolates its one-way global error-handler
transition in a child test process. The separate correlation cases configure trace export on the healthy path.
Metrics and cross-signal outage continuity remain unverified.

## Configuration precedence follow-up

A public-SDK probe found an additional Python recipe gap. With log-specific
environment limits of 128 attributes and 64 characters, generic
`LogRecordLimits(max_attributes=8, max_attribute_length=32)` fallbacks retained
20 attributes at length 64. The SDK correctly followed its documented precedence;
the guidance had not made that conflict explicit. The supported log-specific
arguments `max_log_record_attributes=8` and
`max_log_record_attribute_length=32` produced eight attributes at length 32,
with 12 drops from 20. See the
[Python API documentation](https://opentelemetry-python.readthedocs.io/en/latest/sdk/_logs.html#opentelemetry.sdk._logs.LogRecordLimits).

The Python guide, fixture setup and all three consumer rubrics now cover that
environment-present scenario and preserve an independent authorized 128/64
operator policy. No SDK replacement or upgrade is required. Three native
regression repetitions pass. Separate focused checks show the existing Go,
Node and Java explicit APIs retain their selected 8/32 limits under the same
environment values. This is SDK configuration evidence, not proof of every
deployment surface. The exact before/after values and source hashes are in the
[precedence evidence](/Users/tithumma/code/splunk/obstudio-logging-analysis/.workspace/logging-analysis/remediation/python-limit-precedence-evidence.json).

An auxiliary diagnostic probe initially used an incorrect Node command and
reused one Java XML report path. That dataset is retained as historical and
excluded from final evidence. The fresh 237-case matrix uses a different clean
snapshot and output directory; all six Python/Java XML directories reconcile
with the recorded counts, and 52 raw output files are hashed. No partial or
mutated report counts toward the clean gate. The precedence correction resets
the unchanged-source streak to 0/3 again.

The first complete post-precedence semantic pass met 130/132 criteria despite
all 79 native cases and all three rubric commands passing. Two Python handoffs
were incomplete: one omitted replaying the same 20-attribute positive case;
the other allowed at-most counts that could accept excessive loss. The guide
now requires the controlled SDK-input example to retain exactly eight valid
attributes at length 32 with 12 drops, alongside boundary tests. The input and
rubrics distinguish that isolated mechanism test from application logging,
where bridge-added attributes and unrelated processing must be counted
separately. This does not replace application proof or force 12 drops on a
different payload. That failed pass remains retained and the fresh streak
starts from zero.

## Java export deadline follow-up

The next gate exposed a Java retry fixture assumption: a 200 ms timeout was
described as per-attempt and expected to allow two received requests. The
installed SDK 1.68 OkHttp sender uses that timeout for the whole HTTP call,
including retry waits. Its retry limit is a ceiling; an earlier deadline can
correctly stop before the second request. This agrees with the
[OTLP exporter timeout contract](https://opentelemetry.io/docs/specs/otel/protocol/exporter/#retry),
which covers all attempts and waits in one batch export. The SDK was behaving
correctly; the fixture and guidance needed correction.

A controlled receiver now delays retryable 503 responses by 150 ms. The old
200 ms configuration fails the two-request assertion in all three reproduced
trials. The corrected fixture uses an 800 ms whole-call deadline for that
scenario, retaining a maximum of two attempts, 100 ms base backoff with jitter,
and the measured 1000 ms overall ceiling. A separate stalled case keeps its
200 ms early deadline. Twenty cold Java trials pass all 440 cases, including
exactly two received requests and zero accepted records in each controlled
retry case. The fresh four-language matrix then passes 237/237. These are
fixture budgets, not production defaults or a promise that every export will
reach its maximum attempt count.

The common rule, Java guide, source evidence and all three Java rubrics now
distinguish whole-batch, connection and caller deadlines. The receiver delays
outside its receipt lock; a regression proves another request can succeed
while the retry response remains pending. Source provenance and red/green
results are recorded in the machine-readable report.

## How the rules lead to a repair

The audit first checks source, configuration, installed capability and SDK
defaults. It classifies each applicable rule as covered, partial, missing,
unverified or not applicable. Only concrete application-owned gaps become
selectable findings. Missing execution evidence is recorded separately from
missing implementation.

For a selected gap, `otel-instrument` applies the smallest change through the
existing provider and detected bridge. It preserves operator policy, original
sinks and adequate defaults. It then supplies explicit positive and fault
scenarios in the verification handoff.

The added
[acceptance handoff checklist](/Users/tithumma/code/splunk/obstudio-logging-analysis/skills/references/logging-readiness.md:338)
requires the relevant source values, settings, identities and assertions to be
written down. An omitted obligation leaves the handoff partial. An unexecuted
scenario cannot become a passing runtime result. This closes an instruction and
evidence gap; it does not automatically execute or repair an application.

## Asynchronous logging results

The follow-up checks create context in the caller before scheduling work. They
compare exact IDs and sampling flags, exercise 20 concurrent request contexts
through real batch processors, and check detach, worker reuse, error/cancel
cleanup and preservation of the context captured when the log was emitted.

| Language | Trial 1 | Trial 2 | Trial 3 |
|---|---|---|---|
| Java | 8/8 | 8/8 | 8/8 |
| Python | 7/7 | 7/7 | 7/7 |
| Go | 5/5, race detector clean | 5/5, race detector clean | 5/5, race detector clean |
| Node.js | 5/5 | 5/5 | 5/5 |

All **75 test-case executions passed** across 12 test commands. This includes
deliberately unsafe controls whose assertions expect context loss; passing those
controls does not make the unsafe configuration correct.

| Demonstrated boundary | Observed issue | Working handling tested |
|---|---|---|
| Java prestarted executor without propagation | Child log has zero OTel IDs. | Capture parent Context and wrap the work. Verify existing agent/framework propagation before adding wrappers. |
| Java Context wrapping without MDC handoff | Trace IDs survive but selected `request.id` is absent. | Carry approved MDC fields separately and restore the prior worker map in `finally`. |
| Python raw `run_in_executor` | Worker log has zero OTel IDs. | Use `asyncio.to_thread` or a fresh copied context for the work item. |
| Go worker using background context | The log loses the request's IDs. | Pass request context into the goroutine and use `InfoContext`/`ErrorContext`. |
| Node EventEmitter listener invoked outside the request | Registration inside the request alone does not preserve correlation. | Bind the callback to captured context or prove the framework supplies propagation. |
| Java/Python OTel bridge after an asynchronous logging queue | The bridge reads the logging worker's context and loses caller correlation. | Keep the existing bridge on the caller side beside the original asynchronous sink, then use SDK batch export. A supported context-preserving agent/queue path is another option that needs its own proof. |

These are disposable SDK/bridge probes with in-memory exporters. They do not
execute the actual Spring Boot, Flask, chi or Express applications, a Java
agent, process/distributed-queue handoff, or collector/cloud delivery.
[Detailed async evidence](/Users/tithumma/code/splunk/obstudio-logging-analysis/.workspace/logging-analysis/async-check/.observe/otel-verify.md)
and the
[machine assessment](/Users/tithumma/code/splunk/obstudio-logging-analysis/.workspace/logging-analysis/async-check/assessment.json)
retain the commands, assertions, limitations and receipts.

## Additional acceptance rules

**LOG-ASYNC-HANDOFF** turns the demonstrated boundary cases into a more
specific acceptance checklist under LOG-CONTEXT: capture context per work item,
handle permitted MDC separately, restore worker state, locate record creation
relative to queues, and include exact request pairing plus a missing-propagation
control. LOG-CONTEXT already contains the general async requirement. This named
refinement is now in the canonical reference. The stronger probes are also
persisted in all four maintained native fixtures.

**LOG-SPEC-CLOSURE** requires the source-to-evidence reconciliation above.
It separates SDK-author obligations, application wiring, selected operator policy
and observed runtime proof, including requirements outside the named rules.

**LOG-VERIFY-FRESH** requires fresh results for each repetition, separate
executed/passed/failed/skipped counts, and durable timeout/failure records. It
addresses the false-pass and missing-partial-report findings below. It is a
repository verification rule, not an upstream OTel specification requirement.

All three new names are present in the local canonical shared reference and acceptance
table. The verifier now consumes it while retaining its read-only application
boundary. Matching semantic rubric cases add async handoff and stale-evidence
decisions for each consumer in all four languages. The Python synthetic ERROR
observation now uses 40 consistently with its source overlay.

## Verified findings and corrections

The earlier combined Claude Desktop and Codex review at `8600493b` retained
four findings. Adding logging guidance alone does not close them. The code
and regression fixes below are included in this change; the final source
receives a fresh combined review after the three-pass gate.

| Finding | Original evidence | Local correction and verification |
|---|---|---|
| F1 Java runner can report a false pass | All three reproduced Java trials report 6/6 passed while Maven says tests were skipped; old Surefire XML supplies the count. | Unique report directories and actual testcase outcome parsing reject missing/stale, failed, errored or skipped evidence. A current-source `MAVEN_ARGS=-DskipTests` rerun rejects all three trials despite Maven exit 0 and 22 valid old testcases left in the default XML directory; each fresh report directory has zero executed cases. |
| F2 Clean-checkout dependency setup is incomplete | Tracked-only Go and Node fixtures fail before tests with missing checksums/modules. | Preflight runs Go module download, locked `npm ci`, Java test compilation and Python dependency checks. A clean snapshot without copied `go.sum`, `node_modules` or Java `target` passed all three repetitions. Python uses the existing locked eval environment. |
| F3 Committed concurrency tests provide weaker handoff proof | The Go case creates context inside the worker and checks distinctness rather than exact pairing; Java/Python also create context inside workers/tasks. | All four maintained fixtures now contain caller-handoff, exact-pairing, cleanup and expected-loss controls. The original Go case also checks exact record-to-request pairing. |
| F4 Timeout can prevent a structured partial matrix | `TimeoutExpired` escapes before the trial log write; final JSON is written only after all trials. Earlier stdout remains available. | Timeout becomes a failed trial with saved output and incremental JSON. Owned POSIX process groups are cleaned up and independent trials continue. Actual timeout and orchestration regression tests cover persistence, interruption and continuation. |

The
[combined review](/Users/tithumma/code/splunk/obstudio-logging-analysis/.workspace/logging-analysis/combined-review/combined-review.md)
contains narrow code locations, reproductions and the disposition of Claude's
other candidates. [Runner source](/Users/tithumma/code/splunk/obstudio-logging-analysis/evals/run_logging_contract.py)
and [regression tests](/Users/tithumma/code/splunk/obstudio-logging-analysis/evals/test_logging_contract_runner.py)
contain the fixes and checks. The adapted Toolkit simplifier pass clarified
parsing, lifecycle cleanup and result construction while preserving behavior;
all 37 runner/receiver regressions passed again afterwards.

An additional report-accuracy bug is also fixed locally: xdist workers reported
one worker even when two were running. A real two-worker reproduction failed
the new assertion before the fix. Serial and two-worker regression cases now
pass, and all 214 reusable-plugin tests pass. This preserves the report schema
while correcting its effective worker count.

The default rubric judge also now receives an explicit ID for each declared
criterion and must return one check per item. A compound item keeps all its
obligations in that check. This corrects the observed 12-check result for an
11-item rubric; all 133 generated checks were positive, but that attempt could
not satisfy the declared 132-check matrix. The strict gate rejects extra,
missing or duplicate criterion IDs. Existing custom judge templates and public
JSON schemas are preserved. The focused prompt regression failed before the
fix and passes afterwards; all 214 plugin tests pass again.

## Latest maintained native results

The skill task and rubric judge both run with **`gpt-6.1-sol` and high
reasoning**, pinned in `evals/codex-evals.toml` and verified in the live process
arguments. These model evaluations run locally on the PR branch and bind their
results to source hashes. The disabled GitHub live-eval template does not
establish a GitHub Actions model-eval result; PR CI is recorded separately.


| Language | Trial 1 | Trial 2 | Trial 3 | Async cases included per trial |
|---|---|---|---|---|
| Java | 22/22 | 22/22 | 22/22 | 8 |
| Python | 21/21 | 21/21 | 21/21 | 7 |
| Go | 18/18 | 18/18 | 18/18 | 5; race detector clean |
| Node.js | 18/18 | 18/18 | 18/18 | 5 |

All **237/237 native test-case results** passed across 12 fresh test commands,
with zero failures, errors or skips. This includes 72 original-contract, 75
async, 36 real-exception/overload/diagnostic, 39 OTLP wire and 12 real-span
correlation results, plus three log-limit precedence regression executions. Go's
diagnostic case uses a child test process for isolation. Deliberately skipped
Java controls are correctly rejected and are not counted as logging successes.
The dedicated correlation cases configure real trace and log exporters; the
other fixtures retain their declared signal scope. These tests do not execute
full framework applications or a Java agent.

The 12 dedicated correlation trials produced **240 exact sampled log/span
joins**, 12 valid unsampled logs and 12 outside-span logs. Each sampled child
also matches its actual parent and service resource. These are real SDK-created
IDs; one child from trial 3 of each language is shown below. The log SpanId
and independently received span SpanId match exactly.

| Language | TraceId | Log SpanId = received SpanId |
|---|---|---|
| java | `d0da7a5041adfd3a4f0d4f5991f27a5e` | `b9c0ddd4f5290f54` |
| python | `e029a02bd08578ca8e9fc8cf5318168a` | `c58b1017e35f4c39` |
| go | `f574707ddf29a1fb5a77db2a05e2e50b` | `3e853d148e660ab4` |
| node | `1805ae6a9c5d1cb1e6eda8c522e550b0` | `74ed2b3b2c317b79` |

The live-correlation path uses bounded SDK batch processors: queue 128,
batch 64, scheduled delay 60s and processor export budget 3s. Each trial
asserts one HTTP log batch containing all 22 records and one trace batch
containing all 20 spans. Context therefore survives both application async
handoff and the SDK export worker. Java uses a 1s whole HTTP-call timeout, at most two
attempts with 100ms backoff, a 4s flush wait and a 15s test ceiling. Other
languages use their supported public batch and timeout options. These
controlled budgets are separate from the dedicated wire-fault settings below.

The earlier Java failure occurred with the Simple processor: its flush result
did not complete within 2s even though all 22 logs and 20 spans eventually
arrived. Installed SDK bytecode passes a live concurrent pending-export set to
an aggregate that counts its size separately from iterating callbacks. A
controlled collection interleaving reproduces an incomplete aggregate after
both individual exports succeed. This demonstrates a matching race mechanism;
it does not establish the exact interleaving of the failed trial or claim an
upstream SDK fix. The maintained correction uses public batch processors and
asserts actual batch requests. Ten additional Java repetitions passed.

Each local wire trial records three received/three accepted on the healthy
path; three received/one accepted/two rejected on partial success, without a
whole-batch retry; and one pending then one late acceptance after the client
times out. Java uses an 800ms whole-call timeout for healthy, partial and
controlled delayed-503 exports, and a 200ms timeout for the stalled case.
Its retry policy permits at most two attempts with 100ms base backoff
(80–120ms with jitter). The controlled 503 case receives exactly two requests
within the measured 1000ms overall budget. Go supplies a caller context deadline in addition to
the exporter timeout. Exact SDK timestamps are checked after protobuf export.
These are controlled fixture settings, not universal
production defaults. The overload test distinguishes queue capacity from
in-flight/export buffers and derives local loss after healthy draining.

[Machine-readable remediation results](/Users/tithumma/code/splunk/obstudio-logging-analysis/docs/logging-remediation-results.json)
retain source hashes, setup commands and per-trial receipts. The final run
used an isolated fixture snapshot with no copied dependency/build directories.
The machine-readable
results also record the tested SDK, bridge and runtime versions.
The exact command is recorded in those receipts; the standard local command is:

```sh
cd evals
UV_NO_CONFIG=1 uv sync --frozen
UV_NO_CONFIG=1 uv run python run_logging_contract.py --trials 3 --output ../.workspace/logging-contract
```

Go 1.25+, Node 22.15+ with npm, JDK 17 and Maven must be installed. The runner accepts
explicit `--go`, `--npm`, `--maven`, `--python`, `--java-home` and
`--maven-settings` paths. This four-language matrix is a local gate rather
than a CI job. Python dependencies are already declared and locked in
`evals/pyproject.toml` and `evals/uv.lock`.

## Evidence and completion criteria

The baseline already covered bridge/provider ownership, original sinks,
destination policy, privacy and basic correlation. The
[baseline evidence](/Users/tithumma/code/splunk/obstudio-logging-analysis/docs/logging-skill-analysis-evidence.json)
establishes the missing explicit guidance at the original commit through source
hashes and searches. Search absence establishes an instruction gap; it does not
prove an SDK failure or a model's inability to infer correct behavior.

The original rule evaluation passed **24/24 plan-only cases and 168/168 rubric
criteria**, with three trials for each skill in each language. The original
native suites passed **72/72 test-case executions**. The disposable async check
passed **75/75**. These historical datasets are separate from the latest
237-result maintained run. They are documented in the
[original analysis](/Users/tithumma/code/splunk/obstudio-logging-analysis/docs/logging-skill-analysis.md),
[original results](/Users/tithumma/code/splunk/obstudio-logging-analysis/docs/logging-skill-test-results.json)
and linked async assessment. The first expanded semantic round completed 36
tasks but satisfied only 315/324 individual criteria. Missing acceptance
details remain recorded, including dependency preparation, unique report
storage and timeout-output capture. The handoff guidance is now more explicit.
The second round satisfied 355/360 criteria across 36 tasks. Its five omissions
concerned an excluded exception alias, concrete deadline mechanisms and an
ambiguous output destination. Those contracts are now explicit. Rounds three
and four were cancelled after deterministic source guards failed; their partial
artifacts are retained and do not count as passing runs. A fresh 36-task,
360-criterion round completed with 358/360 criteria. Its two generated-plan
omissions were a final-log shutdown case and a named diagnostic-routing repair;
the handoff now names both explicitly. The current source adds the broader
closure and real-span correlation checks. That evaluation was stopped after a
Node audit plan omitted named limit APIs and the observed request-versus-retry
budget distinction. Its failed criteria and partial artifacts are retained.
The guide now provides checked public limit options, below/at/above-limit
acceptance, and observed-versus-proposed deadline evidence. All three
deterministic validations passed again. The strict sequential gate now runs
12 skill/language cases, 132 criteria and 79 native cases per pass; it stops
on a failure and requires three consecutive clean passes before combined review. Task execution success
is not presented as full semantic success. Deterministic validation passed
721 audit, 752 instrumentation and 687 verification checks, each with five
skips: one unrelated optional module and four wire/correlation cases that require the
runner-owned receiver. The formal native matrix has zero skipped cases.

The first current-source clean pass used these exact rubric commands from
the repository root; each pattern includes all four languages. Subsequent
passes use `PROMPT=logging-trial-2` and `PROMPT=logging-trial-3` with the same
settings. Their individual results are recorded in the three-pass evidence:

```sh
UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-audit CASE=python/flask-basic EVAL_PATTERN='*/*/eval/qual/logging-audit-contract.json' PROMPT=logging-trial-1 EVAL_WORKERS=4 EVAL_PROGRESS=0
UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-instrument CASE=python/flask-basic EVAL_PATTERN='*/*/eval/qual/logging-instrument-contract.json' PROMPT=logging-trial-1 EVAL_WORKERS=4 EVAL_PROGRESS=0
UV_NO_CONFIG=1 make eval-rubric SKILL=skills/otel-verify CASE=python/flask-basic EVAL_PATTERN='*/*/eval/qual/logging-verify-contract.json' PROMPT=logging-trial-1 EVAL_WORKERS=4 EVAL_PROGRESS=0
```

| Deterministic validation command | Result |
|---|---|
| `UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-audit EVAL_PROGRESS=0` | 721 passed, 5 scoped skips |
| `UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-instrument EVAL_PROGRESS=0` | 752 passed, 5 scoped skips |
| `UV_NO_CONFIG=1 make eval-validation SKILL=skills/otel-verify EVAL_PROGRESS=0` | 687 passed, 5 scoped skips |

Exact focused commands: `UV_NO_CONFIG=1 .venv/bin/python -m pytest
test_logging_contract_runner.py test_logging_receiver.py -q` from `evals/`
passed 37 checks; `UV_NO_CONFIG=1 make test-pytest-plugin` from the repository
root passed 214 checks. Each consumer also passed `UV_NO_CONFIG=1 make
eval-validation SKILL=skills/<consumer> EVAL_PROGRESS=0`. The rubric invocation
for each consumer uses `CASE=python/flask-basic`, the matching four-language
`EVAL_PATTERN='*/*/eval/qual/logging-<audit|instrument|verify>-contract.json'`,
`EVAL_WORKERS=4` and `EVAL_PROGRESS=0`.

The reference was checked against official OTel documentation on 2026-11-08:
[data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/),
[Logs SDK](https://opentelemetry.io/docs/specs/otel/logs/sdk/) and
[exception log conventions](https://opentelemetry.io/docs/specs/semconv/exceptions/exceptions-logs/).
The follow-up also reconciles
[non-OTLP trace-context formats](https://opentelemetry.io/docs/specs/otel/compatibility/logging_trace_context/)
and [logging context guidance](https://opentelemetry.io/docs/specs/otel/logs/supplementary-guidelines/).
It preserves optional fields, SDK-owned defaults and explicit operator policy.
Development features such as `trace_based` still require installed capability
checks; exception-event guidance is not forced onto existing logging bridges.

To establish that an application issue is fixed, implement its selected repair,
run the relevant positive and failure scenarios through the real logging call
sites, and complete actual framework/agent startup and local receiver checks
where those claims depend on runtime wiring. Successful focused probes do not
establish universal OTel logging compliance. Full application/Java-agent,
distributed queue, arbitrary sanitization, configured cross-signal outage and
production collector/cloud proof remain unverified. Final combined-review
and current-head CI outcomes are tracked separately in PR 352.

The final deterministic command `PATH="$PWD/evals/.venv/bin:$PATH"
UV_NO_CONFIG=1 make test-eval-harness` verified 26 report source manifests and
passed 880 checks with the five documented scoped skips above. The separate
formal native matrix and every native clean-pass trial had zero skips.
