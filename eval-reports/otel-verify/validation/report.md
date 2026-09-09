# otel-verify Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | otel-verify |
| Run ID | 20260909T072906898929Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-basic/qual/verify | go/chi-basic | 1 | evals/go/chi-basic/eval/qual/verify.json | 0 | 4 | 0 |
| go/chi-basic/qual/verify-runtime-blocker | go/chi-basic | 1 | evals/go/chi-basic/eval/qual/verify-runtime-blocker.json | 0 | 5 | 0 |
