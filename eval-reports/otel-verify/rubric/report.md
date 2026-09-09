# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20260909T073441320713Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.token-benchmark.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | 1 | 100% (4/4), avg score 98 | 1.3M | 9.8m | - | - | - |
| with_skill | go/chi-basic/qual/verify-runtime-blocker | go/chi-basic | 1 | 100% (5/5), avg score 96 | 1.5M | 8.7m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1319530 | 1252992 | unknown | 10999 | 2672 | unknown | 1330529 |
| with_skill | go/chi-basic/qual/verify-runtime-blocker | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1483000 | 1397632 | unknown | 13539 | 2900 | unknown | 1496539 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 213476 | 155904 | unknown | 3955 | 1464 | unknown | 217431 |
| with_skill | go/chi-basic/qual/verify-runtime-blocker | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 358941 | 302848 | unknown | 5332 | 1636 | unknown | 364273 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
