# splunk-dashboard Sanity Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | sanity |
| Skill | splunk-dashboard |
| Run ID | 20260702T194810597252Z |
| Agent model | gpt-5.5 |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Sanity Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | 1 | 100% (10/10) | 342.8K | 5.8m | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | 2 | 100% (4/4) | 35.1K | 4.7m | - | - | - |
| with_skill | sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | 1 | 100% (4/4) | 81.7K | 3.3m | - | - | - |

## Sanity Failures

No sanity failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
