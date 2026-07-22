# otel-verify Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | otel-verify |
| Run ID | 20260722T043951012756Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |
| Report scope | full |
| Selected prompts | 3 |
| Expected prompts | 3 |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-basic/qual/verify | go/chi-basic | 1 | evals/go/chi-basic/eval/qual/verify.json | 0 | 6 | 0 |
| go/chi-partial/qual/benchmark-verify | go/chi-partial | 1 | evals/go/chi-partial/eval/qual/benchmark-verify.json | 0 | 4 | 0 |
| java/springboot-basic/qual/verify | java/springboot-basic | 1 | evals/java/springboot-basic/eval/qual/verify.json | 0 | 6 | 0 |
