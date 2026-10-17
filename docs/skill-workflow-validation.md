# Skill workflow validation

## Revision and preservation

Work started from a fresh clone of remote `main` at
`f56299311afa7c62c9896de1aa76d4ff5a22106f`; the remote head was rechecked and
unchanged before handoff. The original working checkout was left untouched.
The initial extraction compared all 15 stage reference bodies byte-for-byte with
their original sections. The correctness follow-up adds optional guidance to
verification's report stage without removing the original instructions. Public
skill names, local discovery links, report schemas,
producer rules and original rubric criteria are retained. Plugin skill copies
are generated from the canonical source. Default `git diff --check` reports
blank separators at the ends of extracted references; these preserve original
section bytes. `git -c core.whitespace=-blank-at-eof diff --cached --check` passes;
no other whitespace errors are present.

## Rubric comparison

Each result is one representative Go chi-basic task, not a statistical guarantee
across languages or model versions. The installed Codex CLI was
`0.162.0-alpha.17.2`; baseline and candidate used the same CLI default model,
reasoning setting and isolated authenticated home. The report records model as
`-` because no explicit model was pinned.

| Skill | Clean-main original criteria | Candidate original criteria | New workflow criterion | Raw judge score, baseline → candidate |
|---|---:|---:|---:|---:|
| otel-audit | 10/11 | 11/11 | Pass | 96 → 100 |
| otel-instrument | 7/7 | 7/7 | Pass | 100 → 100 |
| otel-verify | 5/5 | 5/5 | Pass | 100 → 99 |

Audit's baseline failure concerned the existing GenAI No presentation. No
criteria were removed or weakened. Verification's one-point deduction concerned
omitted per-signal zero counts in the final chat response; the report retained
them and all original criteria passed. Consequently, original criterion pass
rates are preserved, but a claim that every numerical score increased or stayed
identical would be false.

Final rubric run IDs are `20261016T061547573822Z` (audit),
`20261016T061548674738Z` (instrument), and `20261016T061549808263Z` (verify).
Superseded runs interrupted after source changes are not the reported results.

The exact run config is committed at its recorded path,
`evals/.workspace/skill-observability-proof/evals.toml`, so source receipts can be
verified in a clean checkout without rewriting their fingerprints. No auth files
or run caches are committed. Its contents are:

```toml
[run]
mode = "with_skill"
[rubric]
enabled = true
[runtime]
enabled = false
[agent]
backend = "codex"
timeout = 1800
extra_args = ["--config", 'model_reasoning_effort="xhigh"', "--config", "sandbox_workspace_write.network_access=true"]
```

Commands below ran from `evals/`, with `UV_NO_CONFIG=1`,
`OBSTUDIO_SKILL_MCP_ENDPOINT=none`, an authenticated isolated `EVAL_CODEX_HOME`,
and the installed CLI on PATH. They deliberately did not publish eval runs into
the native demonstration Studio.

```sh
make eval-rubric SKILL=skills/otel-audit CASE=go/chi-basic PROMPT=direct EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
make eval-rubric SKILL=skills/otel-instrument CASE=go/chi-basic PROMPT=direct EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
make eval-rubric SKILL=skills/otel-verify CASE=go/chi-basic PROMPT=canonical-proof-packet EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
```

## Deterministic and integration proof

The environment used Go 1.27.2, Node 24.19.0 and project-managed Python 3.11.
The Python eval virtual environment was first on PATH; system Python 3.9 is too
old for existing guidance tests. npm used the official registry because the
machine's inherited private registry was unavailable. A dependency reinstall
race between build and client tests was corrected by running those targets
sequentially. A final validation attempt also omitted Node from PATH; its two
Node subprocess checks failed with FileNotFoundError, then both passed after
restoring the configured Node runtime. No skill changes were needed.

| Command from repository root unless stated | Result |
|---|---|
| `cd observer && go test ./internal/mcp ./internal/store` | Pass; protocol, projection, recorder ingestion and telemetry evaluation tests |
| `make test` | Pass, full Go suite |
| `make vet` | Pass |
| `cd observer && go test -race ./internal/mcp ./internal/store` | Pass |
| `make build` | Pass; staged skills, client assets and binary |
| `cd observer/client && npx vitest run src/traces/TraceWaterfall.test.tsx` | 17 passed |
| `cd observer/client && npm run typecheck` | Pass |
| `make test-client` | 406 passed |
| `make test-pytest-plugin` | 217 passed |
| `make test-eval-harness` | 722 passed, 1 skipped; report freshness passed |
| `make test-interactive-otel-scripts` | Pass, including 8 recorder tests and 184 guidance checks |
| `make agent-policy-check` | Pass, 49 policy tests and 8 guideline checks |
| `claude plugin validate ./plugins/obstudio --strict` | Pass |
| `claude plugin validate .` | Pass |
| `make eval-validation SKILL=skills/otel-audit` | 611 passed, 1 skipped |
| `make eval-validation SKILL=skills/otel-instrument` | 631 passed, 1 skipped |
| `make eval-validation SKILL=skills/otel-verify` | 577 passed, 1 skipped |

Protocol proof covers HTTP and stdio using the same catalog, complete manifest
byte/digest checks, materialized remote helpers and validators for all three
skills, legacy tools, invalid-skill isolation, malformed requests, and concurrent
replay without duplicate metrics. Recorder tests exercise offline/redirect
failure, unsafe paths, cancellation, command failure, and concurrent writers.
Evaluation tests check real ingestion through the existing GenAI projection,
custom definitions, invalid rules, partial traces, missing retention, actual
zero versus unknown usage, and idempotent evaluation receipts. Changed-package
coverage was inspected to locate missed branches rather than target a global
percentage.

The final audit trajectory sanity command (from `evals/`) was:

```sh
make eval-sanity SKILL=skills/otel-audit CASE=go/chi-basic PROMPT=stage-path EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
```

It passed all 5 checks, including loading guards, declared stage path and
independent report evidence. Instrumentation's existing smoke report was also refreshed with:

```sh
make eval-sanity SKILL=skills/otel-instrument CASE=sanity/skill-smoke EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
```

Both existing prompts passed. The reusable harness also tests independent
command witnesses rather than accepting a journal's execution claim alone.

## Ordinary execution demonstration

A separate copy of the demo application ran ordinary CLI prompts containing
only `$otel-audit`, `$otel-instrument`, or `$otel-verify`, outside the eval runner.
The local recorder exported to an isolated Studio at `127.0.0.1:3006`. Its Go
integration driver used the real production MCP/API/store/web/OTLP packages
without registering global runtime state or cloud credentials. Native provider
OTel exporters were disabled only for those individual processes; existing
user configuration was preserved.

Audit recorded a passed workflow. Instrumentation initially recorded Partial
when the app exported to the isolated receiver but the agent inspected a
different Studio. A later ordinary verification used the correct MCP endpoint
and passed 16/16 application telemetry items. The initial errors and recovered
attempts remain visible rather than being relabeled as successful history.
The resulting application code, report, CLI output and workflow journals were
retained locally under the isolated demo and ignored workspace proof directory.

After replaying those journals through the current server, all four retained
runs appeared as GenAI workflow traces. Actual commands became tool spans;
checkpoints remained ordinary instantaneous spans. No model calls or tokens
were synthesized. Custom rules against the stored audit telemetry returned:
Go branch Pass, report command under 1500 ms Pass (490.084 ms measured), and
discovery command latency Unknown because discovery was a checkpoint. Default
evaluations exposed real command failures on instrumentation/verification runs.

UI inspection exercised trace selection, the workflow graph and its evaluation
issue action, which opens named evaluation explanations. Screenshots cover
756×923, a live resize to an actual 716×863 constrained viewport, and
1100×850. A requested 360×740 override was clamped by the embedded host, so
360-pixel support is not claimed. The changed token summary remained legible
without page horizontal overflow at the recorded widths. Temporary viewport
overrides were reset. The standalone app exposes the existing dark theme; no
light-theme or editor-host rendering claim is made.

## Correctness follow-up

The follow-up adds `observer_skill_correctness_evaluate` and an optional
`otel-verify` path for a separately supplied contract. A reported skill pass is
not accepted as proof. The server compares retained application spans, metric
datapoints and correlated logs with explicit finding/scenario expectations,
checking run/service/source identity and consistency with a producer-declared
complete capture. Results include exact count differences, mismatched field
names, report bindings and a receipt; raw log bodies and attribute values are
not copied into the evaluation events. The source capture is linked for review.

Independent execution proof uses `TestCorrectnessIndependentAppSDKOTLPAndMCP`:
an actual HTTP handler executes, the real Go tracing SDK captures its spans,
a test exporter serializes those SDK observations to OTLP, the production
OTLP/HTTP receiver ingests them, and the public MCP tool evaluates them against
separate fixed JSON contracts. Expectations are loaded before execution and
are not generated from the observed spans or a skill's reported outcome.

| Executed fixture | Instrumentation claim | Audit gap claim |
|---|---|---|
| Correct route instrumentation | Pass | Fail: gap refuted |
| Wrong route attribute | Fail | Pass: gap supported |
| No instrumentation despite the handler running | Fail | Pass |
| Duplicate server spans | Fail | Pass |
| Wrong parent span | Fail | Pass |
| Application failure with expected HTTP 500, ERROR and error.type | Pass | Fail |
| Capture labeled contract-only | Unknown | Unknown |

Focused unit checks additionally cover metric type/unit/dimensions/value bounds,
empty histogram measurements, log severity/attributes/owning-span correlation,
missing versus evicted evidence, stale revisions, inconsistent/absent manifests,
invalid requests, immutable/replay-safe receipts, capture arrival order, and
one unavailable scenario beside a working scenario. Coverage inspection of the
new evaluator was used to identify the missing arrival-order and histogram
branches; no repository-wide coverage target was used.

The earlier Copilot review's four concrete findings are addressed: workflow and
evaluation insertion no longer trigger idle application-session resets;
deduplication/conflict validation and insertion share the store lock; Claude
foreground command outcomes are normalized without converting absent,
background or interrupted results into success; shell operators with or without
spaces cannot mask recorder failures; and huge/invalid durations fail the check
instead of aborting grading. A real shell reproduction exits 7 in the recorder
and 0 in its pipeline, which the corrected grader rejects. Existing Codex checks,
ordinary application-session resets and explicit Clear/replay remain covered.
These harden the workflow-check feature introduced by this draft; existing
sanity check kinds and public report schemas remain unchanged.

Commands for this follow-up use the same runtime/PATH setup as above:

| Command from repository root unless stated | Result |
|---|---|
| `cd observer && go test ./internal/mcp -run TestCorrectnessIndependentAppSDKOTLPAndMCP -count=1 -v` | Pass, all 7 executed fixtures |
| `cd observer && go test ./internal/mcp -run TestCorrectness -count=1` | Pass, focused contract and isolation checks |
| `cd observer && go test ./internal/store -run 'TestSkillWorkflow\|TestSessionReset' -count=1` | Pass, retention/bookkeeping and existing reset behavior |
| `make test` | Pass, full Go suite |
| `make vet` | Pass |
| `cd observer && go test -race ./internal/mcp ./internal/store` | Pass |
| `make build` | Pass, embedded skills/client/binary |
| `uv run --project pytest-codex-evals pytest pytest-codex-evals/tests/test_workflow.py -q` | 8 passed |
| `make test-pytest-plugin` | 221 passed |
| `make test-eval-harness` | 722 passed, 1 skipped |
| `make -C evals eval-report-freshness` | All 26 tracked report manifests verified |
| `make test-interactive-otel-scripts` | Pass, including 184 guidance checks |
| `make agent-policy-check` | 49 policy tests and 8 guideline checks passed |
| `claude plugin validate ./plugins/obstudio --strict` and `claude plugin validate .` | Both passed |
| `make eval-validation SKILL=skills/otel-audit` | 611 passed, 1 skipped |
| `make eval-validation SKILL=skills/otel-instrument` | 631 passed, 1 skipped |
| `make eval-validation SKILL=skills/otel-verify` | 577 passed, 1 skipped |

The follow-up rubric command was:

```sh
make eval-rubric SKILL=skills/otel-verify CASE=go/chi-basic PROMPT=canonical-proof-packet EVAL_CONFIG=.workspace/skill-observability-proof/evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
```

Run `20261016T165657113677Z` passed all **7/7** criteria, raw score **100**,
including the unchanged original criteria and the new independent-contract
criterion. This follows the initial stage-refactor verification result of 6/6,
score 99; the clean-main baseline was 5/5, score 100. No criteria were weakened.
One preparatory rubric invocation was interrupted after discovering that the
new fixture input had not been included in the prompt's explicit seed list;
the reported run includes that input and matches the final skill/eval sources.
The task and schema-constrained judge ran outside Studio with recorder export
disabled, separately from the SDK/OTLP integration fixtures above.

No new UI code or editor-host behavior is introduced in this follow-up. It reuses
the existing evaluation rendering; this validation proves the backend events
and trace projection, not a new browser screenshot or native SEP client run.
Cloud delivery, authenticated provenance, all-language correctness, automatic
audit precision/recall and LLM judging are outside this implementation. The
contract author and capture producer remain trust inputs. A passing result
establishes only the explicitly checked scenario, not all skill recommendations
or instrumentation throughout an application.

## Limits and review boundary

The design and telemetry contract are described in
[the implementation plan](skill-workflow-observability.md). Request human review
of the stage contract, optional SEP adapter, and measurement/evaluation boundaries
before merging this architectural change.

Native SEP-2640 loading/activation has not been demonstrated in Codex or Claude;
the adapters were exercised at the server protocol and materialized-bundle
boundaries. Claude manifest validation is not an execution proof. No formal
upstream conformance suite, Windows runtime, editor extension host, Docker
runtime eval, live provider-token correlation, or Galileo/Splunk cloud receipt
was exercised. Representative Go evals do not establish all-language quality.
Checkpoints, root outcomes and digest identity remain recorder reports rather
than independent evidence of everything the host or model did. Missing telemetry
cannot be graded as success. Bounded Studio memory can evict observations; replay
can restore retained local journals, and explicit Clear still clears telemetry.

## Measured audit accuracy across three applications

The [protocol](skill-workflow-accuracy-protocol.json) froze 18 source-backed
binary gap checks before the six audit executions. It compares the original
skill at `f56299311afa7c62c9896de1aa76d4ff5a22106f` with the staged skill at
`adce7109604135e53bc7a276b498cb057004251a`. Subsequent measurement commits do
not change those audit skill bytes. Each side received identical source files and
only `$otel-audit`, with Codex `0.162.0-alpha.17.2`, observed model
`gpt-6.1-sol`, and `xhigh` reasoning. There was one paired run per application.

| Application | Known gaps / negative controls | Original precision / recall | Staged precision / recall |
|---|---:|---:|---:|
| Go chi-basic | 3 / 2 | 100% / 100% | 100% / 100% |
| Go chi-partial | 5 / 3 | 100% / 100% | 100% / 100% |
| Python checkout-red-demo | 3 / 2 | 100% / 100% | 100% / 100% |
| Combined | 11 / 7 | 100% / 100% | 100% / 100% |

Both sides classified all 18 checks correctly: 11 true positives, seven true
negatives, no false positives or false negatives. This measures preserved
performance on this small set, **not an accuracy improvement**. Precision is
closed-set gap precision, not precision across every generated recommendation.
The [results](skill-workflow-accuracy-results.json) retain manual labels,
finding IDs, relevant report evidence, all finding summaries, source/report
hashes, and command timings. Findings outside the predefined units are listed
and excluded from the scores. Their correctness was not comprehensively graded.

A separate observation, discovered after reading the reports, concerned
chi-partial's resource configuration. Original finding `OTEL-002` says its
SDK setup does not read `OTEL_SERVICE_NAME` or `OTEL_RESOURCE_ATTRIBUTES`.
The staged report correctly observes that SDK 1.45's `WithResource` merges
`resource.Environment()`. An independent Go SDK 1.45 in-memory probe reproduced
the exact `resource.New(ctx)` and `WithResource(res)` construction and confirmed
`service.name`, `service.version`, and `deployment.environment.name` survive.
The actual missing application-default identity remains a gap on both sides.
This configuration probe passed; it does not constitute application OTLP proof.
It is a post-hoc correction, excluded from the primary scores, and one
stochastic comparison cannot establish that the stage refactor caused it.

The commands used the isolated authenticated Codex home from the rubric runs,
`--ignore-user-config --sandbox danger-full-access`, explicit per-process
`otel.exporter="none"` and `otel.trace_exporter="none"`, and
`OBSTUDIO_SKILL_MCP_ENDPOINT=none`. The audit subjects wrote reports/evidence under `.observe`; orchestration saved
CLI output separately. Source hashes were checked before scoring. No benchmark telemetry
was published into the ordinary demonstration Studio. The complete local
orchestration and raw CLI outputs are under
`.workspace/skill-observability-proof/followup/`; the protocol and expectation
files were committed before scoring. Raw elapsed times vary in both directions;
concurrent runs do not isolate latency overhead. A single small sample is not
statistical evidence of broader accuracy, repeatability, or performance gains.

## Ordinary demo pipeline with independent correctness contracts

A fresh copy of Go chi-basic, outside the eval runner, received only the ordinary
`$otel-audit`, `$otel-instrument`, and `$otel-verify` prompts. The
[acceptance expectations](skill-workflow-demo-expectations.json) were fixed
before audit or instrumentation output existed. The audit selected four findings;
instrumentation and the final ordinary verifier reported all 26 telemetry items
and 21 scenarios passing. The two new independent contracts specifically cover
`OTEL-002`: POST `/tasks` returning 201 and malformed JSON returning 400, with
one SERVER span named `POST /tasks` and exact route/method/status attributes.
They do not independently grade all 26 items.

The first standalone verification passed its ordinary checks but skipped the
optional evaluator because the supplied contract targeted an earlier
instrumentation invocation. That was a real handoff defect. The verification
reference now preserves the supplied completed target run and tests actual
source/report/witness bindings, rather than treating a different current run ID
as stale. It also explains discovery through an explicitly configured loopback
MCP endpoint when a host does not advertise the tool, while respecting `none`.
The matching rubric adds a semantic prior-invocation/offline regression case.
The rerun invoked `observer_skill_correctness_evaluate` through its native MCP
tool, with arguments checked to be exactly the supplied contract. Its two rules
passed and its report retained the immutable MCP receipt.

The [capture fixture](../observer/internal/mcp/testdata/skill-correctness-runtime-capture/main.go)
is a separate POSIX runtime harness. It launches the actual compiled app,
propagates real SDK witness contexts through HTTP, asserts the two responses,
collects the app's SDK OTLP exports, and waits for synchronous shutdown before
constructing manifests from captured records. It does not construct app spans.
The application source digest becomes `service.version`; source bytes were
checked unchanged across verification. This demo's generated local-log policy
supports a build-time endpoint binding; the capture build uses
`-ldflags '-X main.approvedLocalLogsEndpoint=http://127.0.0.1:4348/v1/logs'`
so all app signals pass through the independent receiver. This is an explicit
test profile, not a generic requirement for application instrumentation.

From `observer/`, the capture invocation has this form (replace paths, run ID,
and source digest with the recorded values):

```sh
go run ./internal/mcp/testdata/skill-correctness-runtime-capture -binary /absolute/demo-app -dir /absolute/demo -out /absolute/capture -run <completed-instrumentation-run-id> -version sha256:<tested-source-digest> -expect /absolute/scenario-requests.json -port 4348
```

The scenario request file preserves the frozen method/path/body/status values;
its IDs are mapped to the audit's `http.tasks.create.success` and
`http.tasks.create.invalid_json`. Studio is isolated at `127.0.0.1:3007`, with
OTLP on 4337/4338. The helper keeps its connection alive and emits a separate
real harness-liveness gauge to retain the bounded session while inspection
continues. That gauge is not app correctness or skill usage evidence. App
aggregate metrics lack per-scenario verification labels, so the new contracts
here assert spans only; zero scenario-correlated metric points does not mean no
aggregate metrics were exported. Ordinary verification also checked metrics/logs.

The [result ledger](skill-workflow-demo-results.json) includes source and binary
hashes, exact contracts, raw observed span fields, workflow histories and receipts:

| Capture / check | Result |
|---|---|
| Original instrumented app, two fixed scenarios | Both instrumentation contracts pass |
| Throwaway copy with only the emitted `http.route` value deliberately broken | Both instrumentation contracts fail specifically on `span.attribute.http.route` |
| Same controlled fault evaluated as a known gap | Both predicate-scoped `audit_gap` checks pass |
| Supplied source revision deliberately mismatched | Two unknown results, null scores, no numeric events |
| Replay original passing contract | Identical receipt; no duplicate evaluation span |

The controlled audit-gap checks concern that predicate in the deliberately
broken copy, not correctness of the entire original audit. Receipts remain
producer-declared runtime evidence; authenticated execution/provenance is not
implemented. The final native verification run was
`fec9f21fc81ca2defbad15f72db16025`; its supplied target remained completed
instrumentation run `add7a886331489fb1d6e973cac8b9ee5`. Initial test/report failures
remain in their original workflow histories. Provider tokens remain unknown in
Studio. Global Codex and Claude telemetry configuration hashes were unchanged.
Native loading used local discovery links; no SEP client activation or cloud
receipt is claimed.

The handoff-fix rubric command is the same exact `make eval-rubric` command
above. Run `20261016T182808983321Z` passed **8/8**, score **100**, preserving all
previous criteria. It ran with recorder export disabled, separately from the
ordinary Studio demonstration. Final checks for this measurement follow-up:

| Command | Result |
|---|---|
| `make test` | Pass, full Go suite |
| `cd observer && go vet ./internal/mcp/testdata/skill-correctness-runtime-capture` | Pass |
| `make eval-validation SKILL=skills/otel-instrument` | 631 passed, 1 skipped; refreshed the Observer fixture source receipt |
| `make eval-validation SKILL=skills/otel-verify` | 577 passed, 1 skipped |
| `make test-interactive-otel-scripts` | Pass, including 184 guidance checks |
| `make agent-policy-check` | Pass, 49 policy tests and 8 guideline checks |
| `make test-eval-harness` | 722 passed, 1 skipped; all 26 source manifests verified |
| `quick_validate.py skills/otel-verify` using isolated uv PyYAML | Skill is valid |

The first eval-harness attempt correctly rejected the old instrumentation
validation receipt after the capture fixture was added. Its owning validation
was rerun; no receipt was hand-edited. A capture-preparation command also retried
with the digest helper's correct positional audit argument before app execution.
No new UI code or editor integration was changed. Existing browser rendering
was inspected with real passing/failing application evaluations; screenshots and
raw CLI/OTLP artifacts are retained locally in
`.workspace/skill-observability-proof/followup/`. No new Windows, editor-host,
Claude execution, Docker, cloud, or provider-token test is claimed.


## Repeated audit accuracy challenge (2026-10-16)

The stronger comparison **did not demonstrate improved audit accuracy**.
[Protocol](skill-workflow-accuracy-challenge-protocol.json) was committed in
`b771e41` before audited outputs; [results](skill-workflow-accuracy-challenge-results.json)
retain both grader responses, finding inventories, actual SDK captures, source
hashes and raw artifact hashes. Both frozen skill versions remained unchanged.

Six newly authored synthetic Go/Python applications exercise lost request/thread
context, unbounded span names and metric dimensions, duplicate server spans,
caught errors without ERROR status, raw sensitive attributes, and covered
provider/context/error/metric/shutdown predicates. Two applications are covered
controls for their declared predicates. Separate real-SDK probes executed actual
application functions before auditing; their code was outside audited workspaces.
These in-memory captures do not prove HTTP transport, OTLP delivery, every
lifecycle interleaving, or cloud ingestion.

Each version ran twice per application with only `$otel-audit`, model
`gpt-6.1-sol`, effort `xhigh`, the same source/dependencies and a 1,500-second
budget. All 24 audits completed successfully with source unchanged and no
unexpected files outside allowed outputs. Every report was graded in two fresh
version-blinded sessions: 24 paired grading sessions, 48 individual report grades.
This is model-assisted grading using the same model, not independent human review.

| Frozen primary result | Original | Revised |
|---|---:|---:|
| Known gaps detected | 22 / 22 | 22 / 22 |
| Covered predicates correctly left unflagged | 62 / 62 | 62 / 62 |
| Closed-set precision / recall | 100% / 100% | 100% / 100% |
| Mean per-application F1 | 100% | 100% |

There were zero predicate disagreements between graders. Primary gain was **0
percentage points**; the paired application-cluster bootstrap interval was
`[0, 0]`. The predeclared superiority gate failed: it requires at least five
points of gain and an interval lower bound above zero, plus the factual-support
guard. A degenerate resampling interval over tied observed cases does not prove
population equivalence or exclude differences on future applications.

The SDK environment-resource predicate had been investigated in the earlier
post-hoc probe, so it was explicitly excluded from primary scoring before this
challenge. It exposed one incorrect resource explanation in each version:
original `order-api` repetition 1 and revised `feed-api` repetition 0. Both
misread SDK 1.45's final resource composition; actual application SDK captures
retain supplied service name/version/environment through `WithResource`.
The matched final reports, not provisional commentary, were scored.

All 112 findings, including extra findings, received a factual-premise review.
Original: **46 supported, 1 contradicted, 7 unresolved** out of 54. Revised:
**54 supported, 1 contradicted, 3 unresolved** out of 58. The established-support
shares (85.2% vs 93.1%) measure evidence established from the grading inputs;
they do not demonstrate improved factual accuracy. Unknown premises can be true,
some audit sidecars were not supplied to graders, proposed fixes were not all
executed, and the conditional support bounds overlap. The ledger preserves
unresolved findings instead of turning them into correctness passes.

Execution used the frozen `b771e41` harness for preparation, SDK probes and
audits. A scheduling-only change in `0df00da` allowed complete pairs to be graded
while later audits ran and recorded each grading harness hash. Prompt, schema,
scoring functions and acceptance rules were unchanged (AST-checked). After all
model processes exited, the published runner gained PATH/explicit runtime
resolution and a Python fixture-version guard. No model task, source expectation,
score or threshold changed; recomputing the summary preserved every result.
See the ledger's phase provenance and benchmark README for reproduction.

Exact experiment commands, from the repository root (isolated authenticated
Codex home; recorded Go 1.27.2 and Python SDK/exporter 1.45.1):

```sh
evals/.venv/bin/python3 evals/audit_accuracy.py prepare --workspace /private/tmp/obstudio-audit-challenge-20261016-final
evals/.venv/bin/python3 evals/audit_accuracy.py truth --workspace /private/tmp/obstudio-audit-challenge-20261016-final
evals/.venv/bin/python3 evals/audit_accuracy.py run --workspace /private/tmp/obstudio-audit-challenge-20261016-final --codex-home /Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home --workers 4
evals/.venv/bin/python3 -u .workspace/skill-observability-proof/challenge/grade_ready.py
evals/.venv/bin/python3 evals/audit_accuracy.py summarize --workspace /private/tmp/obstudio-audit-challenge-20261016-final
evals/.venv/bin/python3 .workspace/skill-observability-proof/challenge/collect_results.py
```

The local grade scheduler invokes `audit_accuracy.grade(workspace, home, 2)`
repeatedly for completed pairs; the published `grade` action with the same
workspace/home reproduces its fixed grading procedure. Raw local artifacts are
retained in the ledger-linked ignored `raw-artifacts.tar.gz`; all original source,
report and grading-copy bindings were checked before publication. Captured read
commands mention each audit entrypoint, and no explicit reads of the truth,
protocol or grading paths appeared in captured audit commands. This is a bounded
command-path check, not authenticated activation, complete-context proof, or a
security sandbox.

Final local checks (PATH included the eval venv, pinned Go/Node and local tools;
`UV_NO_CONFIG=1` for Make):

- `make test-eval-harness`: **734 passed, 1 skipped**, all 26 tracked report
  manifests valid. An initial run without Node on PATH failed two existing Node
  checks; the corrected complete runs passed.
- `make agent-policy-check`: **49 policy tests + 8 guideline tests passed**;
  agent policy check passed.
- `evals/.venv/bin/python3 -m pytest -q evals/test_audit_accuracy.py`: initial
  scoring suite **7 passed**, pair scheduling suite **8 passed**; final full
  harness includes all **12** scoring/scheduling/runtime-resolution/version tests.
- `evals/.venv/bin/python3 evals/audit_accuracy.py truth --workspace /private/tmp/obstudio-audit-challenge-20261016-final`:
  **6 real-SDK application-function probes passed**.
- Supplemental `go test -count=1 -v -run TestSourceExporterDefaultsWithoutNetwork ./...`:
  **passed**; actual pinned SDK requests `https://localhost:4318/v1/traces` by
  default and the explicit no-options resource has zero attributes without
  operator values. A custom RoundTripper intercepted the request; this was
  post-hoc configuration proof, outside the scores and grading inputs.

No shipped skill changed in this follow-up, so no fresh skill rubric run was
required. Core Observer/client/editor behavior and full application HTTP/OTLP
pipelines were not changed or re-exercised locally by this benchmark; the earlier
ordinary native pipeline proof remains separate. Six small synthetic applications
share bootstrap templates, there are only two repetitions per version, and both
graders use the same model. These limits preclude a general production accuracy,
causal, equivalence, or broad non-regression claim. Native/skill-workflow telemetry
export was disabled; no evaluation usage was presented as Studio OTel or native
provider token telemetry.

After measurement, `main` advanced to `f4166e5` (PR #288), adding Copilot
installation configuration tests and their CI matrix coverage. The only merge
conflicts were the two generated otel-instrument validation reports. The main
tests/workflow were preserved and the combined report was regenerated through
`make eval-validation SKILL=skills/otel-instrument`: **643 passed, 1 skipped**.
The exact narrow command below passed on Darwin; it exercises the newly merged
tests without changing real user configuration. The application fixture and
skill bytes used by the completed benchmark were unchanged by this merge.

```sh
go -C observer test ./cmd/obstudio -run 'Test(CopilotTargetUsesVSCodeUserMCPJSON|CopilotMCPConfigPathResolvesPerOS|ConfigureMCPCopilot.*)$' -count=1 -v
```

## MCP report writer follow-up (2026-10-16)

The three canonical report stages now prefer server-owned publication. The new
MCP tools reuse the existing canonical schema/binding normalizers and HTML
renderer, generate Markdown from structured inputs, and return compact receipts
and absolute report links. Existing local commands and direct baseline
instrumentation remain supported. No application code, provider telemetry
configuration or user-owned host settings were changed by this follow-up.

`docs/skill-report-publication-results.json` records the source hashes, artifact
digests and four measured operations for re-publication of the ordinary demo's
existing evidence: audit, instrumentation, verification and verification replay.
The demonstration checks canonical JSON equality, downstream audit HTML byte
preservation and an identical replay receipt. It does not rerun the application
or provide new correctness proof for that application. All four operations are
recognized as GenAI tool operations, have measured server durations, and expose
`tokenUsageObserved: false`. Their scope is `report_validation_only`.

Native Claude also successfully invoked the audit-writing tool using a private
per-process MCP configuration: four turns, approximately 34 seconds. That smoke
test preceded the final selection-preservation fix and establishes native tool
invocation, not a complete Claude audit or SEP activation. HTTP and stdio tests
exercise the final implementation directly, including unavailable Python,
discovery isolation, cancellation, retained workflow links, replay and a real
restricted loopback HTML server that survives worker cleanup.

The first model-backed runs exposed report-contract regressions rather than a
quality pass: audit 12/13 (score 95), instrumentation 8/9 (94), verification 6/9
(88). Fixes made the ownership declaration visible in the audit summary,
qualified empty inventories and proof limits early, preserved required final
response headings and summaries, supplied absolute preformatted links, and
finished evidence reconciliation before publication. Corrected broad tasks each
passed every criterion: audit 13/13 (score 100), instrumentation 9/9 (98), and
verification 9/9 (100). The instrumentation run is `20261017T022146320185Z`;
audit and verification are `20261017T021301634223Z` in their respective skill
directories. All used `CASE=go/chi-basic`, with `PROMPT=direct` for audit and
instrumentation and `PROMPT=canonical-proof-packet` for verification, plus the
same config/home arguments as the commands below. These broader runs preceded
the final selection-preservation adjustment. The
final focused publication cases and their exact current-source manifests are
published under `eval-reports/otel-{audit,instrument,verify}/rubric/`.

| Final publication case | Criteria passed | Judge score | Run ID |
|---|---:|---:|---|
| Audit | 6/6 | 100 | `20261017T022719447823Z` |
| Instrumentation | 6/6 | 98 | `20261017T022719447865Z` |
| Verification | 6/6 | 100 | `20261017T022719447868Z` |

All criteria pass; the instrumentation judge's soft score is 98, so these
results must not be described as three scores of 100. These new publication
cases are not a matched before/after score comparison.

Each focused case rejects an intentionally invalid schema, then publishes the
original bound fixture without modifying application code or inventing test
execution. The original broad rubric criteria were retained, and a new
publication criterion was added; none was relaxed to accept the new writer.
One representative Go case per skill is not evidence of general statistical
non-regression across applications, hosts or model versions.

Commands ran from the repository root with the eval venv, cached Go/Node/npm,
local tools on PATH and `UV_NO_CONFIG=1`. Model-backed runs used the isolated
authenticated home from earlier demonstrations and the committed local proof
configuration at `evals/.workspace/report-mcp-tools/final-evals.toml`. Its
machine-specific launcher adds the loopback MCP server to writable Codex tasks
only; read-only judges do not receive that mutation capability. No global
configuration was changed. Reproduction requires a running server with the
current skill catalog and a launcher available at the configured command path.

```sh
make eval-rubric SKILL=skills/otel-audit CASE=go/chi-basic/eval/qual/mcp-report-audit.json EVAL_CONFIG=.workspace/report-mcp-tools/final-evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
make eval-rubric SKILL=skills/otel-instrument CASE=go/chi-basic/eval/qual/mcp-report-instrument.json EVAL_CONFIG=.workspace/report-mcp-tools/final-evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
make eval-rubric SKILL=skills/otel-verify CASE=go/chi-basic/eval/qual/mcp-report-verify.json EVAL_CONFIG=.workspace/report-mcp-tools/final-evals.toml EVAL_CODEX_HOME=/Users/tithumma/code/splunk/obstudio/.workspace/codex-evals/codex-home
```

Deterministic checks on the final report-writing source:

| Command | Result |
|---|---|
| `go -C observer test ./...` | Pass |
| `go -C observer vet ./...` | Pass |
| `go -C observer test -race ./internal/mcp -run 'TestReportWriter\|TestWorkflowReplayMetricsAndHonestIncompleteState' -count=1` | Pass |
| `make build` | Pass, embedded skill staging, client assets and binary |
| `make test-interactive-otel-scripts` | 157 shared, 1 audit, 117 instrumentation, 17 verification unit tests; 184 guidance checks passed |
| `make eval-validation SKILL=skills/otel-audit` | 624 passed, 1 skipped |
| `make eval-validation SKILL=skills/otel-instrument` | 644 passed, 1 skipped |
| `make eval-validation SKILL=skills/otel-verify` | 590 passed, 1 skipped |
| `make agent-policy-check check-obstudio-plugin-skills` | 49 policy and 8 guideline tests passed; policy and generated plugin parity passed |
| `make test-eval-harness` | 737 passed, 1 skipped; all 26 retained report manifests verified |
| `claude plugin validate ./plugins/obstudio --strict` and `claude plugin validate .` | Both passed |

Freshness-required sanity reruns also passed: `make eval-sanity
SKILL=skills/otel-audit CASE=go/chi-basic/eval/sanity/stage-path-audit.json` (one
prompt, run `20261017T022719447849Z`) and `make eval-sanity
SKILL=skills/otel-instrument CASE=sanity/skill-smoke/eval/sanity/instrument.json`
(two prompts, run `20261017T022719447843Z`). Both used the same
`EVAL_CONFIG` and `EVAL_CODEX_HOME` arguments as the rubric commands above, with
`OBSTUDIO_SKILL_MCP_ENDPOINT=http://127.0.0.1:3011/mcp`.

Initial attempts lacked the Node/npm launcher on PATH; subsequent commands used
the cached npm CLI through the bundled Node runtime. A renderer metadata change
also correctly invalidated frozen AO source/browser snapshots. The report-writer
adapter now adds that declaration without changing the shared renderer or
rewriting historical snapshots. Corrected complete checks pass.

Browser interaction and responsive visual inspection were deferred while the Mac
was locked, in accordance with the workspace instructions. HTML generation,
selection retention and existing renderer interaction tests run through the
terminal, but they do not replace new browser visual proof. No cloud delivery,
new full application runtime run, or full language/editor matrix was attempted
for this reporting change. Python must be available on the MCP server; per-file
atomic replacement does not make a multi-file publication transactional, and
operation telemetry retains the existing in-memory lifetime.

Token reduction is **unmeasured**. Avoided duplicate model-authored Markdown is
the expected saving; previously deterministic HTML bytes are not token savings.
Canonical evidence, required final responses, new tool schemas and instructions
still consume context. CLI usage recorded by the eval harness is not native
provider OTel and is not attributed as Studio-measured skill token usage.
