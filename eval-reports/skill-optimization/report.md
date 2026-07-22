# Historical OTel Skill Optimization Benchmark

## Status

This file is a historical performance snapshot from the benchmark run described
below. It predates the capture-sealed eval provenance and current report-flow
validators, so it is **not current correctness or release proof**. The measured
timings and token counts remain useful as historical observations only.

## Historical Outcome

At the time of this benchmark, the audit, instrument, and verify skills
delegated repeatable discovery, dependency resolution, command execution,
environment isolation, report validation, and benchmark comparison to
deterministic Python tools. The final three-run benchmark was complete under
the validators used at that time.

Audit and instrument improved on the primary independent-median wall-time
measure. Verify used fewer commands and tokens, but its independent median was
4.632% slower; two of its three interleaved treatment runs were faster and the
paired median improved by 6.349%. With only three stochastic runs, neither view
is a significance claim.

## Remote Baseline

`git fetch origin` completed before analysis and again after benchmarking.

| Ref | Commit |
|---|---|
| Local starting HEAD | `cc4e9adfa0a3e20d6b9568113893d11f5e4002c3` |
| `origin/main` | `b5ce53aa2bed97538a62da83cfd4dedd93719c55` |

The histories differ because the local branch contains the pre-merge shortcut
commits while `origin/main` contains their merged commit. Their Git trees are
identical, so there was no upstream content conflict to merge before this work.

## Deterministic Work Moved Out Of Skill Prose

- `skills/references/scripts/inspect_otel_project.py` provides one bounded,
  deterministic inventory for manifests, languages, entrypoints, runtime
  surfaces, routes, and OTel/config hits. Thin audit, instrument, and verify
  wrappers preserve skill-local invocation.
- `skills/otel-instrument/scripts/resolve_go_otel_versions.py` performs bounded,
  cache-backed compatibility and transitive-closure selection for the fixed Go
  HTTP bundle. It returns an explicit bootstrap-probe candidate only when a
  complete cached closure is unavailable and the preconditions are safe.
- `skills/otel-instrument/scripts/run_go_otel_command.py` owns the isolated Go
  environment and argv, probe staging, exact pinned edit, accepted-plan ledger,
  hash/directive/pin checks, rollback, follow-up validation, and compact cleanup.
- `skills/otel-instrument/scripts/probe_loopback_bind.py` and the verify wrapper
  replace repeated ad hoc listener probes.
- `skills/otel-verify/scripts/validate_reader_report.py` validates the report
  contract, including escaped Markdown table pipes and expected item inventory.
- `evals/compare_otel_reports.py` compares normalized metadata and all table
  cells instead of exact stochastic prose.
- `evals/aggregate_skill_benchmark.py` enforces three-run completeness, numeric
  metrics, loader identity, current validators, independent and paired
  statistics, and stable report-fact consensus.
- Skill prose now front-loads only the relevant language/GenAI references and
  uses the direct small-repository path when a full inventory would cost more
  than focused inspection.

## Benchmark Method

- Model: `gpt-5.5`
- Repetitions: three baseline and three treatment runs per skill
- Execution: one worker, sequential, rubric grading disabled
- Primary statistic: independent median of agent duration, command count, and
  agent tokens
- Fixtures: the same Go chi audit/instrument cases on both sides; verify used a
  uniquely named copied skill and an interleaved B1/A1/B2/A2/B3/A3 order to
  eliminate the installed-overlay collision found during early runs
- Admission: successful harness exit, expected report present, exact or
  hash-equivalent intended skill load, numeric metrics, and every applicable
  current report validator passing
- Report comparison: stable normalized facts from metadata and complete tables;
  exact report prose is not expected to match between stochastic runs

Audit and instrument baseline/treatment samples were sequential rather than
interleaved, so their paired fields are descriptive only. Verify's interleaved
pairing is the stronger run-order comparison. The complete machine-readable
summary is in `benchmark.json`.

## Results

| Skill | Median seconds, before -> after | Time result | Median commands | Median tokens |
|---|---:|---:|---:|---:|
| Audit | 178.974 -> 135.640 | 24.212% faster | 36 -> 30 (16.667% fewer) | 585,101 -> 297,441 (49.164% fewer) |
| Instrument | 512.024 -> 468.356 | 8.529% faster | 106 -> 66 (37.736% fewer) | 2,117,506 -> 1,238,456 (41.513% fewer) |
| Verify | 303.935 -> 318.012 | 4.632% slower | 58 -> 46 (20.690% fewer) | 792,829 -> 559,168 (29.472% fewer) |

Instrumentation has meaningful variance: its treatment runs were 676.801,
468.356, and 340.123 seconds. The median improved, but the treatment mean was
495.093 seconds versus 480.915 seconds before, a 2.948% mean regression caused
by the retained slow run. The result therefore supports lower command/token
cost and a better median, not an unconditional wall-time speedup.

Verify's interleaved duration changes were 9.652% slower, 11.428% faster, and
6.349% faster. Its paired median improved 6.349%, while the independent median
regressed 4.632%. Both are reported because `n=3` is too small to choose one as
definitive.

## Are The Reports The Same?

No exact Markdown reports are identical, including repeated runs on the same
side. Their narrative, evidence granularity, and optional rows vary with the
agent. The proof-relevant stable consensus did not regress:

| Skill | Stable before facts | Stable after facts | Shared | Lost | Added | Consensus overlap |
|---|---:|---:|---:|---:|---:|---:|
| Audit | 29 | 29 | 29 | 0 | 0 | 100% |
| Instrument | 13 | 14 | 13 | 0 | 1 | 92.9% |
| Verify | 7 | 7 | 7 | 0 | 0 | 100% |

Instrumentation added one stable fact rather than losing one: a passing
`Dependency edit` validation gate. All audit and verify reports passed their
current validators. Instrument reports passed every applicable validator; a
validator marked not applicable was not treated as positive telemetry proof.

## Proof-Led Conflict Resolution

Claude Opus was run at the highest available model alias with high effort for
adversarial read-only reviews. Its first final review returned `SHIP`, but an
independent reviewer then produced a counterexample: on a complete resolver
plan, pre-`go-get` `go mod tidy` could mutate `go.sum` without an accepted-plan
ledger. A temporary fixture reproduced the mutation. The runner now fails that
path closed; the regression proves no command executes, no `go.sum` appears,
and no ledger is fabricated. Opus re-reviewed the patched action/ledger paths
and returned `SHIP` with a code-path proof.

A later real benchmark trace exposed a separate sequencing failure: the agent
cleaned the ledger after an initial green validation, made another source edit
during final review, then fell back to manual `GOCACHE`, `go`, and noisy `find`
cleanup. That 500.251-second run was rejected rather than counted. Cleanup is
now explicitly the final project command after report edits, verification
decisions, final review, and any re-opened validation. A fresh Opus review and
an independent review both found the revised control flow unambiguous, and all
three admitted instrumentation traces end with runner cleanup and no later Go
or cache branch.

Other rejected experiments remain diagnostic only:

- an audit scanner-first variant took 227.193 seconds, showing that the bounded
  scanner should not replace direct inspection for a two-file service;
- early instrumentation treatments manually selected rejected versions or
  performed cache archaeology, so their apparent speed was inadmissible;
- early verify runs mixed stale installed overlays or introduced a `go.sum`
  fixture difference; the final unique-skill interleaved series removed both
  confounds;
- an unescaped Markdown pipe initially broke item accounting; the validator and
  tests now cover escaped table pipes.

## Verification Recorded At Benchmark Time

The counts below describe that historical run. They must not be read as the
current repository test result; use the latest CI run or rerun the documented
test targets for current proof.

- Focused final runner/resolver/guidance suite: 54 passed, 4 subtests passed
- `make test-skills`: 32, 62, 3, 3, and 3 tests passed
- `make test-eval-harness`: 255 passed
- `make test`: passed for all Go packages and embedded-skill staging
- Skill Creator validation: audit, instrument, and verify all valid
- `git diff --check`: passed
- Final benchmark aggregate: complete, all metrics present, loader guards pass,
  and validators OK

## Limits

These are three-run agent benchmarks, not statistically powered performance
tests. Network/model scheduling, agent choices, and optional nested verification
produce large variance. The results justify the deterministic tool conversions
and clear command/token reductions. They do not justify claiming that every
future verify or instrument run will finish faster.
