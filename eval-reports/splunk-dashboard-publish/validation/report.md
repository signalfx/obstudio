# splunk-dashboard-publish Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | splunk-dashboard-publish |
| Run ID | 20260703T004610270747Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| dashboards/checkout-sync/qual/dashboard-publish | dashboards/checkout-sync | 1 | evals/dashboards/checkout-sync/eval/qual/dashboard-publish.json | 0 | 6 | 0 |
| sanity/skill-smoke/sanity/dashboard-publish | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/dashboard-publish.json | 0 | 0 | 0 |
