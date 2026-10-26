# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261026T215453778603Z |
| Agent model | gpt-5.6-sol |
| Judge model | gpt-5.6-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | .workspace/codex-evals/codex-evals-gpt-5.6-sol.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | 1 | 100% (6/6), avg score 100 | 3.0M | 12.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2941378 | 2834560 | 0 | 17981 | 7706 | unknown | 2959359 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1057600 | 954624 | 0 | 8752 | 4648 | unknown | 1066352 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
