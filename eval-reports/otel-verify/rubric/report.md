# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20260909T172158804033Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.token-benchmark.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | 1 | 100% (4/4), avg score 100 | 835.7K | 5.7m | - | - | - |
| with_skill | go/chi-basic/qual/verify-runtime-blocker | go/chi-basic | 1 | 100% (5/5), avg score 95 | 1.9M | 8.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 824259 | 750080 | unknown | 11445 | 2877 | unknown | 835704 |
| with_skill | go/chi-basic/qual/verify-runtime-blocker | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1898659 | 1808768 | unknown | 15010 | 3920 | unknown | 1913669 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 101491 | 82432 | unknown | 2965 | 1041 | unknown | 104456 |
| with_skill | go/chi-basic/qual/verify-runtime-blocker | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 145009 | 121088 | unknown | 5558 | 2448 | unknown | 150567 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
