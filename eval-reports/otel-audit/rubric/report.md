# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261021T051843575616Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | 1 | 100% (7/7), avg score 100 | 7.2M | 19.3m | - | - | - |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 5.0M | 15.1m | - | - | - |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 1.0M | 8.9m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | 1 | 100% (7/7), avg score 100 | 7.0M | 20.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 7111458 | 6912256 | 0 | 46082 | 12506 | unknown | 7157540 |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 4977825 | 4769664 | 0 | 35094 | 5190 | unknown | 5012919 |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1005148 | 914048 | 0 | 20930 | 2229 | unknown | 1026078 |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 6954067 | 6745344 | 0 | 47294 | 11168 | unknown | 7001361 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/audit | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 865485 | 774272 | 0 | 4537 | 755 | unknown | 870022 |
| with_skill | python/model-directed-agent/qual/audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 668586 | 581376 | 0 | 3457 | 533 | unknown | 672043 |
| with_skill | python/model-directed-agent/qual/connection-modes-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 784754 | 702976 | 0 | 3305 | 636 | unknown | 788059 |
| with_skill | python/model-directed-agent/qual/resource-table-audit | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1826940 | 1699712 | 0 | 6368 | 1860 | unknown | 1833308 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
