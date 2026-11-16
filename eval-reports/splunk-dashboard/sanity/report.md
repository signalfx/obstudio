# splunk-dashboard Sanity Codex Eval Report

Evaluated source: `7db9a57ada23292c0047e9d5cac24fbf0208847b`. Case outcomes: 4 passed. These are the saved run's results; no actor or judge was rerun for this publication.

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | splunk-dashboard |
| Run ID | 20261116T170554Z-consolidated-report |
| Agent model | gpt-6.1-sol |
| Workers | 8 |
| Config | evals/codex-evals.logging.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | Case outcomes | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | 1 | 1 passed | 100% (11/11) | 147.3K | 1.8m | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | 2 | 2 passed | 100% (6/6) | 68.0K | 28.5s | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | 1 | 1 passed | 100% (5/5) | 52.9K | 18.0s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 142680 | 124544 | 0 | 4607 | 481 | unknown | 147287 |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 67826 | 30720 | 0 | 183 | 48 | unknown | 68009 |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 52675 | 43520 | 0 | 272 | 49 | unknown | 52947 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
