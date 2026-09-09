# splunk-dashboard Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-dashboard |
| Run ID | 20260909T080406572258Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.token-benchmark.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard-genai | dashboards/checkout-red | 1 | 100% (8/8), avg score 97 | 308.3K | 5.4m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard-genai | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 299091 | 269824 | unknown | 9249 | 2318 | unknown | 308340 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/qual/dashboard-genai | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 204539 | 150784 | unknown | 4336 | 1472 | unknown | 208875 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
