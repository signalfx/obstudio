# splunk-dashboard Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | splunk-dashboard |
| Run ID | 20261105T165726077812Z |
| Agent model | gpt-6.1-sol |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | 1 | 100% (11/11) | 232.4K | 2.4m | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | 2 | 100% (6/6) | 79.4K | 27.6s | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | 1 | 100% (5/5) | 60.6K | 14.3s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 226140 | 206976 | 0 | 6309 | 580 | unknown | 232449 |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 79229 | 66048 | 0 | 192 | 85 | unknown | 79421 |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 60382 | 33408 | 0 | 192 | 33 | unknown | 60574 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
