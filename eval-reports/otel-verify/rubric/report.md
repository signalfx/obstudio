# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261028T183710176316Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | 1 | 100% (7/7), avg score 100 | 1.5M | 13.2m | - | - | - |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | 1 | 100% (5/5), avg score 100 | 1.2M | 14.4m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | 1 | 100% (6/6), avg score 100 | 2.6M | 18.9m | - | - | - |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 3.1M | 16.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1445050 | 1351680 | 0 | 21425 | 3938 | unknown | 1466475 |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1154966 | 1090560 | 0 | 23853 | 4630 | unknown | 1178819 |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 2561093 | 2432896 | 0 | 31280 | 6192 | unknown | 2592373 |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3035504 | 2912640 | 0 | 30055 | 5358 | unknown | 3065559 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 613093 | 528384 | 0 | 3635 | 753 | unknown | 616728 |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 614246 | 551296 | 0 | 3060 | 592 | unknown | 617306 |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 1121614 | 1041536 | 0 | 4955 | 915 | unknown | 1126569 |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 274867 | 222464 | 0 | 3393 | 159 | unknown | 278260 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
