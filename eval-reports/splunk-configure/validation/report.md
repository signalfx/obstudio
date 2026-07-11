# splunk-configure Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | splunk-configure |
| Run ID | 20260711T033945604906Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | 1 | evals/dashboards/checkout-configure/eval/qual/configure.json | 0 | 7 | 0 |
| sanity/skill-smoke/sanity/configure | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/configure.json | 0 | 0 | 0 |
