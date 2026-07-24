# otel-instrument Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | otel-instrument |
| Run ID | 20260722T154802827582Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |
| Report scope | scoped |
| Selected prompts | 5 |
| Expected prompts | 39 |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-basic/qual/benchmark-instrument | go/chi-basic | 1 | evals/go/chi-basic/eval/qual/benchmark-instrument.json | 0 | 6 | 0 |
| go/chi-basic/qual/instrument | go/chi-basic | 2 | evals/go/chi-basic/eval/qual/instrument.json | 0 | 7 | 0 |
| go/chi-basic/qual/instrument-decision-gated | go/chi-basic | 1 | evals/go/chi-basic/eval/qual/instrument-decision-gated.json | 0 | 6 | 0 |
| go/chi-basic/runtime/instrument | go/chi-basic | 1 | evals/go/chi-basic/eval/runtime/instrument.json | 0 | 0 | 1 |
