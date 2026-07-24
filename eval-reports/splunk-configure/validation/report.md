# splunk-configure Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | splunk-configure |
| Run ID | 20260722T172408151060Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |
| Report scope | full |
| Selected prompts | 5 |
| Expected prompts | 5 |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | 1 | evals/dashboards/checkout-configure/eval/qual/configure.json | 0 | 7 | 0 |
| dashboards/checkout-configure/qual/configure-audit-only-source | dashboards/checkout-configure | 1 | evals/dashboards/checkout-configure/eval/qual/configure-audit-only-source.json | 0 | 5 | 0 |
| dashboards/checkout-configure/qual/configure-partial-overlay | dashboards/checkout-configure | 1 | evals/dashboards/checkout-configure/eval/qual/configure-partial-overlay.json | 0 | 4 | 0 |
| sanity/skill-smoke/sanity/configure | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/configure.json | 0 | 0 | 0 |
