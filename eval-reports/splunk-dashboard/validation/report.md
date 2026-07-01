# splunk-dashboard Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | splunk-dashboard |
| Run ID | 20260701T180200306628Z |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | 1 | evals/dashboards/checkout-red/eval/sanity/dashboard.json | 8 | 0 | 0 |
| sanity/skill-smoke/sanity/dashboard | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/dashboard.json | 0 | 0 | 0 |
| sanity/skill-smoke/sanity/dashboard-no-audit | sanity/skill-smoke | 1 | evals/sanity/skill-smoke/eval/sanity/dashboard-no-audit.json | 2 | 0 | 0 |
