# splunk-dashboard Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | splunk-dashboard |
| Run ID | 20260909T161343466918Z |
| Agent model | gpt-5.5 |
| Workers | 1 |
| Config | evals/codex-evals.token-benchmark.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | 1 | 100% (11/11) | 401.4K | 4.4m | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | 2 | 100% (6/6) | 72.2K | 25.8s | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | 1 | 100% (5/5) | 55.9K | 19.8s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 389571 | 340608 | unknown | 11816 | 2143 | unknown | 401387 |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 71973 | 48640 | unknown | 219 | 0 | unknown | 72192 |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 55427 | 46208 | unknown | 433 | 138 | unknown | 55860 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
