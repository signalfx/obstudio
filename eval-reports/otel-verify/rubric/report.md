# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261021T021040733641Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | 1 | 100% (7/7), avg score 100 | 1.7M | 10.6m | - | - | - |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 978.4K | 8.4m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | 1 | 100% (6/6), avg score 100 | 4.3M | 17.0m | - | - | - |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 3.9M | 15.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1667560 | 1547648 | 0 | 25019 | 3530 | unknown | 1692579 |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 958188 | 872832 | 0 | 20178 | 3315 | unknown | 978366 |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 4272531 | 4083840 | 0 | 39451 | 5744 | unknown | 4311982 |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3838984 | 3650816 | 0 | 39115 | 8320 | unknown | 3878099 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 569799 | 472960 | 0 | 4024 | 666 | unknown | 573823 |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 525555 | 457216 | 0 | 2798 | 683 | unknown | 528353 |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1387577 | 1266688 | 0 | 5910 | 1378 | unknown | 1393487 |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 505662 | 425600 | 0 | 2765 | 352 | unknown | 508427 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
