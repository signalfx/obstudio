# splunk-dashboard Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | splunk-dashboard |
| Run ID | 20260910T204305984508Z |
| Agent model | gpt-5.5 |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | 1 | 100% (11/11) | 299.0K | 2.9m | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | 2 | 100% (6/6) | 79.4K | 22.3s | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | 1 | 100% (5/5) | 62.0K | 19.0s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 291552 | 255744 | unknown | 7421 | 1978 | unknown | 298973 |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 79300 | 56832 | unknown | 112 | 0 | unknown | 79412 |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 61519 | 49280 | unknown | 452 | 146 | unknown | 61971 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
