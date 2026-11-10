# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261110T184739892749Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-verify-contract | go/chi-basic | 1 | 100% (14/14), avg score 100 | 112.0K | 1.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-verify-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 111396 | 70144 | 0 | 581 | 107 | unknown | 111977 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-verify-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 248019 | 191616 | 0 | 2274 | 136 | unknown | 250293 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
