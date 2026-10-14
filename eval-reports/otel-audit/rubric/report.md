# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261014T113442652329Z-aggregate |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/audit-focused-decorator-logs | python/ai-assistant-demo | 1 | 100% (3/3), avg score 94 | 1.7M | 11.1m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/audit-focused-metadata | python/ai-assistant-demo | 1 | 100% (4/4), avg score 92 | 2.0M | 13.2m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-audit | python/ai-assistant-demo | 1 | 100% (9/9), avg score 92 | 4.0M | 15.9m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/audit-focused-decorator-logs | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1663388 | 1531648 | 0 | 27058 | 7404 | unknown | 1690446 |
| with_skill | python/ai-assistant-demo/qual/audit-focused-metadata | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2004581 | 1867648 | 0 | 31142 | 8969 | unknown | 2035723 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3966004 | 3776000 | 0 | 34206 | 7862 | unknown | 4000210 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/audit-focused-decorator-logs | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 315287 | 265600 | 0 | 6978 | 3582 | unknown | 322265 |
| with_skill | python/ai-assistant-demo/qual/audit-focused-metadata | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 388800 | 333952 | 0 | 9411 | 5560 | unknown | 398211 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1383535 | 1251328 | 0 | 13864 | 7335 | unknown | 1397399 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
