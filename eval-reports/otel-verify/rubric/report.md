# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261020T200855276877Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | 1 | 100% (7/7), avg score 98 | 1.6M | 10.5m | - | - | - |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 933.1K | 9.4m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | 1 | 83% (5/6), avg score 94 | 4.7M | 17.6m | - | - | - |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 3.4M | 13.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1539148 | 1406592 | 0 | 25435 | 5099 | unknown | 1564583 |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 910273 | 826240 | 0 | 22821 | 3388 | unknown | 933094 |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 4620623 | 4417920 | 0 | 41645 | 8434 | unknown | 4662268 |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3382377 | 3210624 | 0 | 33877 | 7525 | unknown | 3416254 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 454150 | 378752 | 0 | 2891 | 466 | unknown | 457041 |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 603648 | 519552 | 0 | 2790 | 619 | unknown | 606438 |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1075065 | 968832 | 0 | 5219 | 1353 | unknown | 1080284 |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 306556 | 243840 | 0 | 2358 | 299 | unknown | 308914 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/model-directed-agent | with_skill | agent-resource-table-verify | rubric:rubric-3 FAIL | service/.observe/agent-resource-cases.json#/cases/non_agent_control/configuration versus studio_states/disconnected; service/.observe/otel-verify.md, Studio States table, non_agent_control connected row. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
