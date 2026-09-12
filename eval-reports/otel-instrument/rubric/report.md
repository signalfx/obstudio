# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260912T001348020695Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument-runtime-blocker | go/chi-basic | 1 | 100% (4/4), avg score 97 | 168.8K | 3.2m | - | - | - |
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | 1 | 100% (10/10), avg score 88 | 1.8M | 13.9m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument-runtime-blocker | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 165027 | 112512 | unknown | 3780 | 1922 | unknown | 168807 |
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1770781 | 1678848 | unknown | 27261 | 11635 | unknown | 1798042 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument-runtime-blocker | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 193693 | 157952 | unknown | 4670 | 1672 | unknown | 198363 |
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 451150 | 379776 | unknown | 11446 | 8463 | unknown | 462596 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
