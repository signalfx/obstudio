# splunk-detector-publish Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | splunk-detector-publish |
| Run ID | 20260722T192944113617Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |
| Report scope | scoped |
| Selected prompts | 1 |
| Expected prompts | 3 |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | 1 | evals/dashboards/checkout-detectors/eval/qual/detector-publish.json | 0 | 6 | 0 |
