# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261014T171343355258Z |
| Agent model | gpt-6-sol |
| Judge model | gpt-6-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.model-override.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/per-function-decorator-audit | python/ai-assistant-demo | 1 | 100% (6/6), avg score 100 | 1.3M | 7.9m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/per-function-decorator-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1301016 | 1214464 | 0 | 14161 | 2463 | unknown | 1315177 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/per-function-decorator-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 325346 | 286976 | 0 | 2872 | 1056 | unknown | 328218 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
