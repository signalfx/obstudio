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
