# splunk-configure Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | splunk-configure |
| Run ID | 20261013T201547836791Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | 1 | evals/dashboards/checkout-configure/eval/qual/configure.json | 0 | 10 | 0 |
| python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/ao-target-handoff-configure.json | 0 | 3 | 0 |
| sanity/skill-smoke/sanity/configure | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/configure.json | 0 | 0 | 0 |
