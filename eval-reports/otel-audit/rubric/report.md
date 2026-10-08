# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261008T180128169316Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | 2 | 100% (28/28), avg score 94 | 5.9M | 31.5m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/content-coverage-audit | python/ai-assistant-demo | 1 | 100% (4/4), avg score 92 | 3.6M | 14.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 5794264 | 5435008 | 0 | 70652 | 21519 | unknown | 5864916 |
| with_skill | python/ai-assistant-demo/qual/content-coverage-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3583633 | 3173376 | 0 | 37172 | 11358 | unknown | 3620805 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 2505935 | 2224000 | 0 | 24595 | 12127 | unknown | 2530530 |
| with_skill | python/ai-assistant-demo/qual/content-coverage-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 369407 | 289152 | 0 | 6730 | 4243 | unknown | 376137 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
