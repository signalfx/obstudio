# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | grade-only-ccff3b7-to-d507eb43 |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-verify-contract | python/flask-basic | 1 | 100% (61/61), avg score 100 | 171.8K | 2.9m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-verify-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 170791 | 120576 | 0 | 970 | 274 | unknown | 171761 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-verify-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 330499 | 262912 | 0 | 6269 | 356 | unknown | 336768 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.

## Execution provenance

This is a grader-only reassessment of the retained actor from `ccff3b7`, judged against the actual corrected definition at `d507eb43`. No actor, application, test or workflow was rerun. Actor token usage and time are retained actual execution facts; judge usage and time come from the corrected executed judge. Canonical skills, bare task, approved eval inputs, fixture actor sources and applicable harness inputs were proved unchanged; only the recorded judge definition inputs differ. This report covers only `python/flask-basic`, `logging-trial-1`, with 61 criteria. It supplies zero fresh actor/workflow/cohort credit. Audit is plan-only and standalone verification is prerequisite-only. Detailed stage source hashes and actual model metadata are in benchmark.json execution_provenance.
