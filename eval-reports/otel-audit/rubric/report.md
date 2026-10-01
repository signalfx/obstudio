# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261001T063334249488Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | 2 | 94% (17/18), avg score 92 | 5.3M | 29.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 5215555 | 4803328 | 0 | 69696 | 21953 | unknown | 5285251 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 2761804 | 2479616 | 0 | 18925 | 8576 | unknown | 2780729 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-4 FAIL | genai_readiness has one combined 'GenAI tool and retrieval telemetry' row; OTEL-004 is 'Tool execution and retrieval spans are missing'; scenario genai.retrieval.parentage expects a nested retrieval demo_docs span but only names gen_ai.operation.name as an attribute. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
