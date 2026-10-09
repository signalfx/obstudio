# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261008T211520204794Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/content-coverage-instrument | python/ai-assistant-demo | 1 | 100% (6/6), avg score 94 | 6.1M | 15.7m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | 1 | 100% (14/14), avg score 90 | 11.2M | 36.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/content-coverage-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 6076544 | 5887232 | 0 | 36998 | 13534 | unknown | 6113542 |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 11109635 | 10696320 | 0 | 68712 | 20111 | unknown | 11178347 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/content-coverage-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 433543 | 370816 | 0 | 8612 | 4571 | unknown | 442155 |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1050423 | 935936 | 0 | 16292 | 8783 | unknown | 1066715 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
