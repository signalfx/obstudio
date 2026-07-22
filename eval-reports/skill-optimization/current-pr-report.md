# Current PR OTel Skill Evaluation Report

## Status

The current source and every nondeprecated skill eval definition pass local,
deterministic validation. Current-head model-rubric proof is incomplete:
repository-data policy denied new transmissions after the admitted Audit and
focused Instrument runs, and the long Audit capture became provenance-stale
because its source changed while it was running.

Do not interpret a policy-denied run as a failed skill, a structurally valid
eval as a semantic pass, or a stale result as current-head proof.

## Model And Comparison Basis

- Historical published rubrics and the admitted comparison runs use
  `gpt-5.5` for both the task agent and rubric judge.
- The historical Instrument summary combines runs whose config names record
  different reasoning-effort settings. It is the same model, but it is not an
  identical scheduling/effort comparison.
- Historical Audit used seven prompts across four evals. The current Audit
  suite has 31 prompts across 17 eval definitions, so whole-suite tokens are
  not directly comparable.
- Every current model result below that is labelled `stale` or `scoped` is
  diagnostic only.

## Skill Coverage

| Skill | Historical published rubric | Current model evidence | Current local validation |
|---|---|---|---|
| [`otel-audit`](../otel-audit/validation/report.md) | 42/42 checks, 7 prompts, 10,064,071 agent tokens | A [29-prompt diagnostic](../otel-audit/rubric/scoped/20260722T132009620744Z/report.md) executed 147/173 checks successfully and used 27,919,646 agent tokens, but all 29 captures are stale after concurrent skill/eval edits; no patched current-head rubric is admitted | 31/31 prompts structurally valid; 170 rubric definitions |
| [`otel-instrument`](../otel-instrument/validation/report.md) | 19/19 checks, 3 prompts, 24,295,989 agent tokens | Two admitted pre-final-patch focused runs completed: [decision-gated 4/8](../otel-instrument/rubric/scoped/20260722T152331088618Z/report.md) and [chi-partial 4/6](../otel-instrument/rubric/scoped/20260722T154633721819Z/report.md). Their failures produced one eval split, one corrected HTTP-status rubric, and one bounded-outcome skill fix. Policy denied the patched reruns | 39/39 prompts structurally valid; 179 rubric and 6 runtime definitions |
| [`otel-verify`](../otel-verify/validation/report.md) | No historical published rubric | Current model rubric unavailable because repository-data transmission was denied | 3/3 prompts structurally valid; 16 rubric definitions |
| [`splunk-configure`](../splunk-configure/validation/report.md) | 6/6 checks, 1 prompt, 383,020 agent tokens | Current model rubric unavailable because repository-data transmission was denied | 5/5 prompts structurally valid; 16 rubric definitions |
| [`splunk-dashboard`](../splunk-dashboard/validation/report.md) | 7/7 checks, 1 prompt, 456,985 agent tokens | Current model rubric unavailable because repository-data transmission was denied | 5/5 prompts structurally valid; 10 sanity and 7 rubric definitions |
| [`splunk-detector-publish`](../splunk-detector-publish/validation/report.md) | 6/6 checks, 1 prompt, 267,590 agent tokens | Current model rubric unavailable because repository-data transmission was denied | 3/3 prompts structurally valid; 6 rubric definitions |
| [`splunk-dashboard-publish`](../splunk-dashboard-publish/validation/report.md) | 6/6 checks, 1 prompt, 310,676 agent tokens | Current model rubric unavailable because repository-data transmission was denied | 3/3 prompts structurally valid; 6 rubric definitions |

Historical reports remain in each skill's `eval-reports/<skill>/rubric/`
directory. The stale Audit diagnostic is intentionally not promoted over the
published report. Its retained run artifacts are under
`.workspace/codex-evals/otel-audit/20260722T132009620744Z/`.

## Token Comparison

The current evidence does **not** support a claim that total model-token use is
lower after this PR.

The earlier historical optimization benchmark measured lower median tokens for
Audit, Instrument, and Verify at an earlier checkpoint. Later report contracts,
canonical overlays, accessibility rules, and broader eval coverage expanded the
work. In an earlier retained diagnostic Audit comparison, the four historical eval IDs
used 10,064,071 agent tokens and the later captured versions used 14,306,804,
an increase of 42.16%. That aggregate is not a causal before/after measurement:
two of the four task/rubric definitions expanded and the later capture is stale.

The two eval definitions whose task/rubric text was unchanged show mixed
diagnostic results:

| Audit eval | Agent tokens | Commands | Agent time | Rubric result |
|---|---:|---:|---:|---:|
| Assistant v3 framework bridge | 1,464,068 -> 1,322,783 (-9.65%) | 62 -> 78 (+25.81%) | 430.276s -> 441.629s (+2.64%) | 6/6 -> 5/6 |
| MCP AI tool demo | 3,356,703 -> 4,980,419 (+48.37%) | 138 -> 196 (+42.03%) | 891.947s -> 1,248.713s (+40.00%) | 12/12 -> 10/12 |

Those rows show why a blanket token-reduction statement would be misleading:
one case used fewer tokens but more commands and time, while the other regressed
on every cost measure. Both later rows predate the final reconciliation and
progressive-loading fixes.

## Deterministic Static Reduction In This PR

The PR does establish a smaller mandatory instruction payload before any new
model benchmark:

| Flow | Before mandatory words | Current mandatory words | Static reduction |
|---|---:|---:|---:|
| Audit | 7,698-word skill + 8,437-word shared contract = 16,135 | 8,119-word self-contained Audit skill = 8,119 | 49.68% |
| Canonical Instrument | 10,051-word skill + 8,437-word shared contract = 18,488 | 10,841-word skill + 2,175-word scoped handoff = 13,016 | 29.60% |

This is a deterministic reduction in required instruction words, not measured
model tokens. A fresh, capture-sealed `gpt-5.5` rerun is still required to show
its effect on agent tokens, commands, time, and semantic quality.

## Failure Reconciliation

The completed Audit diagnostics exposed two different classes of failure:

- Real report defects: inspected entrypoint/config roles, messaging direction
  and acknowledgement behavior, silent bounded outcomes, dependency package
  coverage, and bounded business aggregates were sometimes lost between source
  discovery and the final report. The Audit skill now has a terminal
  source-to-report reconciliation gate and explicit bounded-outcome rules. Its
  Go chi guidance is also version-aware: `WithRouteTag` is named only when the
  selected `otelhttp` source exports it, with current-span/labeler annotation
  required for v0.65.0 and later.
- Eval mismatches: older prompts prohibited every file write even though Audit
  must write `.observe` artifacts, while their first replacement weakened the
  read-only boundary. All 29 qualitative Audit prompts now permit only the
  required `.observe` artifacts and continue to protect service code,
  dependencies, configuration, and tests. FastAPI no longer requires a
  redundant ASGI label. Spring's Java-agent-primary policy is now explicit in
  the language reference and enforced by its rubric.

The focused Instrument diagnostics likewise separated failures:

- The decision-only prompt was graded against unrelated HTTP instrumentation;
  it now has its own eval definition and scoped rubric.
- The grader required `RecordError`/`SetStatus` on ordinary handled 4xx server
  responses, which conflicts with OpenTelemetry HTTP server semantics; the
  rubric now leaves handled 4xx span status unset.
- Two source-defined 409 causes collapsed into one coarse outcome; the skill
  now requires a bounded per-call reason when selected scope authors that
  telemetry.
- A stopped failed child previously mixed external or authority boundaries
  into repair-only fields. Canonical verification now keeps application
  repairs in `remaining`/`next_steps`, records stop causes in structured
  `stop_boundaries[]`, renders them plainly, and still rejects the state at the
  final-completion gate.

## Current Local Proof

- All seven nondeprecated skill validation reports were refreshed successfully.
- `make test-skills`: 513 passed.
- `make test-eval-harness`: 361 passed.
- `make test-pytest-plugin`: 101 passed.
- Audit and Instrument pass Skill Creator structural validation.
- `git diff --check` passes.

## Required Follow-Up

When repository-data policy permits, run capture-sealed full rubrics from an
unchanged commit using the same `gpt-5.5` agent/judge configuration. Compare
only identical prompt/rubric definitions for token claims, and report expanded
coverage separately. Until then, the defensible conclusion is:

**The PR deterministically reduces mandatory instruction loading and fixes
known semantic/eval defects, but current-head model-token reduction is not yet
proven.**
