# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261013T165434638526Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/resource-selector-length-audit | python/ai-assistant-demo | 1 | 100% (3/3), avg score 97 | 1.4M | 12.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/resource-selector-length-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1325103 | 1210368 | 0 | 25568 | 8682 | unknown | 1350671 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/resource-selector-length-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1705770 | 1590784 | 0 | 8755 | 2719 | unknown | 1714525 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
