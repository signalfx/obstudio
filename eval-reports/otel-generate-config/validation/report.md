# otel-generate-config Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | otel-generate-config |
| Run ID | 20260811T194647915845Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| deployments/generate-config-basic/qual/generate | deployments/generate-config-basic | 1 | evals/deployments/generate-config-basic/eval/qual/generate.json | 0 | 9 | 0 |
| deployments/generate-config-basic/sanity/generate | deployments/generate-config-basic | 1 | evals/deployments/generate-config-basic/eval/sanity/generate.json | 20 | 0 | 0 |
| sanity/skill-smoke/sanity/generate-config | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/generate-config.json | 0 | 0 | 0 |
