# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261110T191507614001Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | 1 | 86% (12/14), avg score 92 | 3.2M | 13.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 3153440 | 2992128 | 0 | 28742 | 3392 | unknown | 3182182 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-audit-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1655539 | 1521536 | 0 | 5881 | 1429 | unknown | 1661420 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-2 FAIL | service/.observe/otel-audit.json:310-336; retained sdk/log/internal/x/features.go accepts SELF_OBSERVABILITY, while otlploghttp/internal/x/observ.go accepts only OBSERVABILITY. sdk/log/setting.go multiplies only time.Duration settings. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-14 FAIL | service/.observe/otel-audit.json evidence rows 57-62 contradict or incompletely resolve the retained setting.go and distinct SDK/exporter internal/x readers. The generic logs.config.capability instruction does not repair those source-derived case mappings. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
