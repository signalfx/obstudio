# otel-instrument Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | otel-instrument |
| Run ID | 20261116T061527188024Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/kvstore/qual/dependency-log-compatibility | go/kvstore | 1 | evals/go/kvstore/eval/qual/dependency-log-compatibility.json | 0 | 6 | 0 |
| python/flask-basic/qual/local-log-launcher-policy | python/flask-basic | 1 | evals/python/flask-basic/eval/qual/local-log-launcher-policy.json | 0 | 6 | 0 |
| python/flask-basic/qual/logging-instrument-contract | python/flask-basic | 3 | evals/python/flask-basic/eval/qual/logging-instrument-contract.json | 0 | 63 | 0 |
