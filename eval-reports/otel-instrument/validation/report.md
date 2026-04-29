# otel-instrument Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | otel-instrument |
| Run ID | 20260429T161229087446Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-basic/qual/instrument | go/chi-basic | 2 | evals/go/chi-basic/eval/qual/instrument.json | 0 | 5 | 0 |
| go/chi-partial/qual/instrument | go/chi-partial | 2 | evals/go/chi-partial/eval/qual/instrument.json | 0 | 5 | 0 |
| go/kvstore/qual/instrument | go/kvstore | 2 | evals/go/kvstore/eval/qual/instrument.json | 0 | 5 | 0 |
| java/springboot-basic/qual/instrument | java/springboot-basic | 2 | evals/java/springboot-basic/eval/qual/instrument.json | 0 | 5 | 0 |
| node/express-basic/qual/instrument | node/express-basic | 2 | evals/node/express-basic/eval/qual/instrument.json | 0 | 5 | 0 |
| python/fastapi-celery/qual/instrument | python/fastapi-celery | 2 | evals/python/fastapi-celery/eval/qual/instrument.json | 0 | 5 | 0 |
| python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | evals/python/fastapi-celery/eval/runtime/instrument.json | 0 | 0 | 1 |
| python/flask-basic/qual/instrument | python/flask-basic | 2 | evals/python/flask-basic/eval/qual/instrument.json | 0 | 5 | 0 |
| sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/instrument.json | 0 | 0 | 0 |
