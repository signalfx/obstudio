# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261001T071341553837Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | 1 | 75% (9/12), avg score 78 | 8.9M | 21.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 8844762 | 8591616 | 0 | 49544 | 18636 | unknown | 8894306 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 662005 | 591488 | 0 | 11309 | 6404 | unknown | 673314 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-2 FAIL | service/app.py has FastAPI instrumentation, chat span, tool spans, token histogram, and assistant.stream.active gauge; build_turn() and export_feedback() are not wrapped in custom telemetry. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-5 FAIL | service/tests/test_genai_telemetry.py asserts one tool span, one retrieval child, parent ID, required attributes, and forbidden raw-content attributes; running unittest fails with ModuleNotFoundError: No module named 'opentelemetry'. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-6 FAIL | service/.observe/otel-instrumentation.md lists runtime proof gaps and blockers; service/app.py implements token usage, token-limit error, and truncation attributes but no prompt/schema-size or fanout telemetry. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
