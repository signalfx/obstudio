# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261110T184739893764Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | 1 | 100% (14/14), avg score 97 | 3.8M | 16.9m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 3768219 | 3601536 | 0 | 31150 | 5351 | unknown | 3799369 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2029366 | 1870848 | 0 | 8566 | 4220 | unknown | 2037932 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
