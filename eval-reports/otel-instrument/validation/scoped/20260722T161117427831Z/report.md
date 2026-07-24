# otel-instrument Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | otel-instrument |
| Run ID | 20260722T161117427831Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |
| Report scope | scoped |
| Selected prompts | 3 |
| Expected prompts | 39 |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-partial/qual/instrument | go/chi-partial | 2 | evals/go/chi-partial/eval/qual/instrument.json | 0 | 6 | 0 |
| go/chi-partial/runtime/instrument | go/chi-partial | 1 | evals/go/chi-partial/eval/runtime/instrument.json | 0 | 0 | 1 |
