# splunk-dashboard Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | splunk-dashboard |
| Run ID | 20261103T222957681165Z |
| Agent model | gpt-6.1-sol |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | 1 | 100% (11/11) | 194.2K | 1.8m | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | 2 | 100% (6/6) | 77.8K | 17.1s | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | 1 | 100% (5/5) | 60.1K | 12.6s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | with_skill | codex | cumulative | measured | 1/1 recognized | 189993 | 168320 | 0 | 4254 | 538 | unknown | 194247 |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | with_skill | codex | cumulative | measured | 2/2 recognized | 77640 | 47616 | 0 | 178 | 66 | unknown | 77818 |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | with_skill | codex | cumulative | measured | 1/1 recognized | 59835 | 50944 | 0 | 238 | 45 | unknown | 60073 |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
