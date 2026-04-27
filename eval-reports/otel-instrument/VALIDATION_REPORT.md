# otel-instrument Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Skill | otel-instrument |
| Run ID | 20260427T173318557615Z |
| Config | /Users/pavankri/Cisco/obstudio/evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks |
|---|---|---:|---|---:|---:|
| go/chi-basic/instrument | go/chi-basic | 2 | evals/go/chi-basic/instrument_eval.json | 5 | 5 |
| go/chi-partial/instrument | go/chi-partial | 2 | evals/go/chi-partial/instrument_eval.json | 5 | 5 |
| go/kvstore/instrument | go/kvstore | 2 | evals/go/kvstore/instrument_eval.json | 5 | 5 |
| java/springboot-basic/instrument | java/springboot-basic | 2 | evals/java/springboot-basic/instrument_eval.json | 4 | 5 |
| node/express-basic/instrument | node/express-basic | 2 | evals/node/express-basic/instrument_eval.json | 4 | 5 |
| python/fastapi-celery/instrument | python/fastapi-celery | 2 | evals/python/fastapi-celery/instrument_eval.json | 4 | 5 |
| python/flask-basic/instrument | python/flask-basic | 2 | evals/python/flask-basic/instrument_eval.json | 4 | 5 |
