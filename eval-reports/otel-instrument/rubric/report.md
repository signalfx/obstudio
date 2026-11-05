# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261103T215421211726Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-instrument | python/ai-assistant-demo | 1 | 100% (6/6), avg score 100 | 1.5M | 7.4m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | 1 | 100% (7/7), avg score 100 | 1.8M | 5.8m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1497906 | 1392896 | 0 | 17010 | 2508 | unknown | 1514916 |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1795794 | 1679744 | 0 | 10469 | 1178 | unknown | 1806263 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 264198 | 212864 | 0 | 1596 | 152 | unknown | 265794 |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1012840 | 916096 | 0 | 2899 | 346 | unknown | 1015739 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
