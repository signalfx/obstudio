# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261014T194128217029Z |
| Agent model | gpt-6-sol |
| Judge model | gpt-6-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.model-override.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/per-function-decorator-verify | python/ai-assistant-demo | 1 | 100% (6/6), avg score 94 | 1.8M | 7.8m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/per-function-decorator-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1804787 | 1713536 | 0 | 17404 | 2763 | unknown | 1822191 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/per-function-decorator-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 419654 | 352512 | 0 | 4122 | 1969 | unknown | 423776 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
