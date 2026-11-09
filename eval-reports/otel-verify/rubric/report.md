# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261103T220736897205Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-verify | python/ai-assistant-demo | 1 | 100% (6/6), avg score 100 | 1.2M | 6.8m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-verify | python/ai-assistant-demo | 1 | 100% (7/7), avg score 100 | 459.4K | 5.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1197780 | 1107968 | 0 | 15906 | 2128 | unknown | 1213686 |
| with_skill | python/ai-assistant-demo/qual/finding-group-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 449114 | 379648 | 0 | 10301 | 1915 | unknown | 459415 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 186511 | 133632 | 0 | 1952 | 228 | unknown | 188463 |
| with_skill | python/ai-assistant-demo/qual/finding-group-verify | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 469917 | 401152 | 0 | 2950 | 170 | unknown | 472867 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
