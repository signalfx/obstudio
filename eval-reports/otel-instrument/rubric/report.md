# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261020T224014321690Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | 1 | 100% (5/5), avg score 100 | 4.1M | 15.5m | - | - | - |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | 4 | 100% (32/32), avg score 100 | 23.1M | 1.5h | - | - | - |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 4.0M | 13.3m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | 1 | 100% (6/6), avg score 100 | 8.3M | 29.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 4022148 | 3865984 | 0 | 37669 | 10032 | unknown | 4059817 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 22880911 | 22147584 | 0 | 215912 | 72809 | unknown | 23096823 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3939500 | 3774336 | 0 | 31591 | 7130 | unknown | 3971091 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 8224407 | 7987968 | 0 | 72547 | 25258 | unknown | 8296954 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/agent-connection-demo/qual/instrument | python/agent-connection-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 634479 | 545152 | 0 | 4020 | 556 | unknown | 638499 |
| with_skill | python/existing-otel-agent-demo/qual/instrument | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 4/4 recognized | 4122281 | 3713024 | 0 | 28551 | 8691 | unknown | 4150832 |
| with_skill | python/model-directed-agent/qual/instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 961600 | 863488 | 0 | 3663 | 657 | unknown | 965263 |
| with_skill | python/model-directed-agent/qual/resource-table-instrument | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1020538 | 912384 | 0 | 5947 | 1693 | unknown | 1026485 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
