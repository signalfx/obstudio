# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261001T204443469104Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | 1 | 75% (9/12), avg score 78 | 9.4M | 21.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 9365421 | 9078528 | 0 | 46552 | 20511 | unknown | 9411973 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1542613 | 1417216 | 0 | 13801 | 6831 | unknown | 1556414 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-2 FAIL | service/app.py:93, service/app.py:125, service/app.py:165, service/app.py:179, service/app.py:224, service/app.py:265 |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-5 FAIL | service/tests/test_genai_telemetry.py:76, service/tests/test_genai_telemetry.py:90, last_message.md:9 |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-6 FAIL | service/app.py:138, service/app.py:159, service/.observe/otel-instrumentation.md:114 |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
