# otel-instrument Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Modes | validation |
| Eval kind | validation |
| Skill | otel-instrument |
| Run ID | 20260428T234224181132Z |
| Runtime enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Validation

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | evals/python/fastapi-celery/eval/runtime/instrument.json | 0 | 0 | 1 |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
