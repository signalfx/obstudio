# splunk-dashboard Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-dashboard |
| Run ID | 20260911T020830511743Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | 1 | 100% (7/7), avg score 98 | 240.4K | 6.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 230456 | 179200 | unknown | 9946 | 4365 | unknown | 240402 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 183375 | 157312 | unknown | 4404 | 1151 | unknown | 187779 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
