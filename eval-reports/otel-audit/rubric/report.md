# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261021T021043040705Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | 1 | 100% (7/7), avg score 97 | 4.4M | 16.7m | - | - | - |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 4.5M | 16.0m | - | - | - |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 1.3M | 10.6m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | 1 | 100% (7/7), avg score 96 | 5.8M | 18.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 4386737 | 4183808 | 0 | 39490 | 9667 | unknown | 4426227 |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 4493000 | 4279040 | 0 | 38940 | 8901 | unknown | 4531940 |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1315513 | 1208704 | 0 | 25983 | 5131 | unknown | 1341496 |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 5740117 | 5534848 | 0 | 42137 | 5540 | unknown | 5782254 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1073728 | 963072 | 0 | 6375 | 1821 | unknown | 1080103 |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 651500 | 569728 | 0 | 3366 | 309 | unknown | 654866 |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 937929 | 838784 | 0 | 3407 | 612 | unknown | 941336 |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1483176 | 1365120 | 0 | 6328 | 2107 | unknown | 1489504 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
