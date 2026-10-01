# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261001T191036539522Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | 1 | 83% (10/12), avg score 78 | 6.5M | 20.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 6438106 | 6233472 | 0 | 52279 | 22553 | unknown | 6490385 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 592284 | 513536 | 0 | 10017 | 5297 | unknown | 602301 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-2 FAIL | service/app.py has FastAPIInstrumentor, chat/tool/retrieval spans, and assistant.stream.active; /v1/feedback/export has no custom span/metric; build_turn has no enclosing turn span. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-6 FAIL | last_message.md says 'Remaining GenAI signals: none at source level'; service/.observe/otel-instrumentation.md lists remaining proof gaps, not remaining token-pressure signal gaps. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
