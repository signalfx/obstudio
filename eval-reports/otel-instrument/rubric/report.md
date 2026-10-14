# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261014T200302308380Z |
| Agent model | gpt-6-sol |
| Judge model | gpt-6-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.model-override.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/per-function-decorator-instrument | python/ai-assistant-demo | 1 | 100% (6/6), avg score 97 | 2.3M | 8.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/per-function-decorator-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2258298 | 2156544 | 0 | 21582 | 4666 | unknown | 2279880 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/per-function-decorator-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 307370 | 261760 | 0 | 3061 | 1268 | unknown | 310431 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
