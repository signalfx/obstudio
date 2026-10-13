# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261013T173320654485Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/resource-selector-length-verify | python/ai-assistant-demo | 1 | 100% (4/4), avg score 97 | 2.0M | 12.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/resource-selector-length-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1966255 | 1823872 | 0 | 28595 | 12044 | unknown | 1994850 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/resource-selector-length-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 883258 | 752000 | 0 | 8160 | 3071 | unknown | 891418 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
