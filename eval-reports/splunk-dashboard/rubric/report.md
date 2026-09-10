# splunk-dashboard Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-dashboard |
| Run ID | 20260910T191903246167Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | 1 | 100% (7/7), avg score 98 | 389.3K | 5.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 378594 | 343936 | unknown | 10734 | 5078 | unknown | 389328 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 167890 | 120064 | unknown | 4043 | 1679 | unknown | 171933 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
