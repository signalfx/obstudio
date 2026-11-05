# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261103T213955588520Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-audit | python/ai-assistant-demo | 1 | 100% (6/6), avg score 100 | 1.4M | 8.3m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-audit | python/ai-assistant-demo | 1 | 100% (7/7), avg score 100 | 647.8K | 6.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1364940 | 1264384 | 0 | 15550 | 2208 | unknown | 1380490 |
| with_skill | python/ai-assistant-demo/qual/finding-group-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 634852 | 568704 | 0 | 12993 | 1971 | unknown | 647845 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/ai-assistant-demo/qual/ao-name-inputs-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 169569 | 128000 | 0 | 1914 | 303 | unknown | 171483 |
| with_skill | python/ai-assistant-demo/qual/finding-group-audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 536599 | 470528 | 0 | 2766 | 344 | unknown | 539365 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
