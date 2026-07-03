# splunk-detector-publish Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | splunk-detector-publish |
| Run ID | 20260701T172548033321Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | 1 | evals/dashboards/checkout-detectors/eval/qual/detector-publish.json | 0 | 6 | 0 |
| sanity/skill-smoke/sanity/detector-publish | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/detector-publish.json | 0 | 0 | 0 |
