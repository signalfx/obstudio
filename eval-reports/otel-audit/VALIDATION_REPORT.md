# otel-audit Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Skill | otel-audit |
| Run ID | 20260427T173318557615Z |
| Config | /Users/pavankri/Cisco/obstudio/evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks |
|---|---|---:|---|---:|---:|
| go/chi-basic/audit | go/chi-basic | 2 | evals/go/chi-basic/audit_eval.json | 5 | 5 |
| go/chi-partial/audit | go/chi-partial | 2 | evals/go/chi-partial/audit_eval.json | 6 | 5 |
| go/kvstore/audit | go/kvstore | 2 | evals/go/kvstore/audit_eval.json | 4 | 5 |
| java/springboot-basic/audit | java/springboot-basic | 2 | evals/java/springboot-basic/audit_eval.json | 4 | 5 |
| node/express-basic/audit | node/express-basic | 2 | evals/node/express-basic/audit_eval.json | 4 | 5 |
| python/fastapi-celery/audit | python/fastapi-celery | 2 | evals/python/fastapi-celery/audit_eval.json | 4 | 5 |
| python/flask-basic/audit | python/flask-basic | 2 | evals/python/flask-basic/audit_eval.json | 4 | 5 |
