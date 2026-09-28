# splunk-dashboard Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | splunk-dashboard |
| Run ID | 20260923T185032115811Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| dashboards/checkout-red/qual/dashboard | dashboards/checkout-red | 1 | evals/dashboards/checkout-red/eval/qual/dashboard.json | 0 | 8 | 0 |
| dashboards/checkout-red/sanity/dashboard | dashboards/checkout-red | 1 | evals/dashboards/checkout-red/eval/sanity/dashboard.json | 8 | 0 | 0 |
