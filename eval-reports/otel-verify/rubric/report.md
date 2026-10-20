# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261020T210913467717Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.agent-role.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | 1 | 100% (7/7), avg score 97 | 1.5M | 8.4m | - | - | - |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | 1 | 100% (5/5), avg score 95 | 700.5K | 7.6m | - | - | - |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | 1 | 100% (6/6), avg score 98 | 3.6M | 15.7m | - | - | - |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | 1 | 100% (4/4), avg score 100 | 3.2M | 13.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1472484 | 1366528 | 0 | 19047 | 3764 | unknown | 1491531 |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 684471 | 608256 | 0 | 15992 | 2595 | unknown | 700463 |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3603112 | 3441408 | 0 | 37974 | 8460 | unknown | 3641086 |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 3124378 | 2965120 | 0 | 32350 | 5485 | unknown | 3156728 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 514856 | 442112 | 0 | 3586 | 552 | unknown | 518442 |
| with_skill | python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 849556 | 758912 | 0 | 4202 | 1482 | unknown | 853758 |
| with_skill | python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 794177 | 706944 | 0 | 3872 | 721 | unknown | 798049 |
| with_skill | python/model-directed-agent/qual/verify | python/model-directed-agent | with_skill | codex | cumulative | measured | 1/1 recognized | 560465 | 491904 | 0 | 2463 | 319 | unknown | 562928 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
