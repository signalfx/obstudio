# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261030T205410022918Z |
| Agent model | gpt-6-luna |
| Judge model | gpt-6-luna |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-instrument | python/ai-assistant-demo | 1 | 100% (7/7), avg score 100 | 684.1K | 4.6m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | 1 | 100% (6/6), avg score 98 | 994.9K | 5.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 673263 | 619008 | 0 | 10848 | 2699 | unknown | 684111 |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 985959 | 905088 | 0 | 8944 | 1728 | unknown | 994903 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 333956 | 291200 | 0 | 2101 | 751 | unknown | 336057 |
| with_skill | python/ai-assistant-demo/qual/finding-group-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1339684 | 1241216 | 0 | 4636 | 1740 | unknown | 1344320 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
