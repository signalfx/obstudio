# splunk-dashboard-publish Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-dashboard-publish |
| Run ID | 20260911T235516369628Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-sync/qual/dashboard-publish | dashboards/checkout-sync | 1 | 100% (7/7), avg score 100 | 117.3K | 2.9m | - | - | - |
| with_skill | dashboards/checkout-sync/qual/dashboard-publish-live-put-404 | dashboards/checkout-sync | 1 | 100% (5/5), avg score 100 | 137.7K | 3.3m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-sync/qual/dashboard-publish | dashboards/checkout-sync | with_skill | codex | cumulative | measured | 1/1 recognized | 113603 | 86912 | unknown | 3703 | 1819 | unknown | 117306 |
| with_skill | dashboards/checkout-sync/qual/dashboard-publish-live-put-404 | dashboards/checkout-sync | with_skill | codex | cumulative | measured | 1/1 recognized | 133114 | 105344 | unknown | 4554 | 2733 | unknown | 137668 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-sync/qual/dashboard-publish | dashboards/checkout-sync | with_skill | codex | cumulative | measured | 1/1 recognized | 147907 | 109440 | unknown | 4070 | 1933 | unknown | 151977 |
| with_skill | dashboards/checkout-sync/qual/dashboard-publish-live-put-404 | dashboards/checkout-sync | with_skill | codex | cumulative | measured | 1/1 recognized | 138943 | 98176 | unknown | 4471 | 2665 | unknown | 143414 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
