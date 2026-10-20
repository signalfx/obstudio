# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261020T210914084855Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | 1 | 100% (7/7), avg score 100 | 4.5M | 15.9m | - | - | - |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 3.5M | 13.4m | - | - | - |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 949.4K | 8.3m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | 1 | 100% (7/7), avg score 98 | 3.4M | 15.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 4436015 | 4240512 | 0 | 37754 | 10345 | unknown | 4473769 |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3506503 | 3339008 | 0 | 30889 | 5073 | unknown | 3537392 |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 929698 | 833536 | 0 | 19707 | 2498 | unknown | 949405 |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3361554 | 3170944 | 0 | 36863 | 4736 | unknown | 3398417 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 884720 | 797952 | 0 | 5052 | 1095 | unknown | 889772 |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 880138 | 777216 | 0 | 4693 | 853 | unknown | 884831 |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 629053 | 545792 | 0 | 2813 | 213 | unknown | 631866 |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1263267 | 1150720 | 0 | 5409 | 1110 | unknown | 1268676 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
