# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261013T174649586772Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/resource-env-bootstrap | python/ai-assistant-demo | 1 | 100% (8/8), avg score 94 | 7.5M | 24.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/resource-env-bootstrap | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 7474984 | 7269760 | 0 | 56289 | 19262 | unknown | 7531273 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/resource-env-bootstrap | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1849781 | 1710464 | 0 | 15611 | 6848 | unknown | 1865392 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
