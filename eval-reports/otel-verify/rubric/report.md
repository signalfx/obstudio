# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261021T005225351643Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | 1 | 100% (7/7), avg score 97 | 1.7M | 10.9m | - | - | - |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 1.4M | 10.3m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | 1 | 100% (6/6), avg score 100 | 4.1M | 15.5m | - | - | - |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 4.8M | 14.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1650595 | 1532032 | 0 | 23909 | 5137 | unknown | 1674504 |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1340389 | 1250048 | 0 | 25414 | 4953 | unknown | 1365803 |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 4067502 | 3890944 | 0 | 35547 | 6697 | unknown | 4103049 |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 4734114 | 4553472 | 0 | 34429 | 7094 | unknown | 4768543 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 698637 | 606592 | 0 | 5520 | 1387 | unknown | 704157 |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 564032 | 499840 | 0 | 2545 | 436 | unknown | 566577 |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1192193 | 1085824 | 0 | 5196 | 1007 | unknown | 1197389 |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 456210 | 385408 | 0 | 2640 | 267 | unknown | 458850 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
