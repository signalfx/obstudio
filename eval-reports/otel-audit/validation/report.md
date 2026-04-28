# otel-audit Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Modes | validation |
| Eval kind | validation |
| Skill | otel-audit |
| Run ID | 20260428T234352619204Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Validation

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-basic/qual/audit | go/chi-basic | 2 | evals/go/chi-basic/eval/qual/audit.json | 0 | 5 | 0 |
| go/chi-partial/qual/audit | go/chi-partial | 2 | evals/go/chi-partial/eval/qual/audit.json | 0 | 5 | 0 |
| go/kvstore/qual/audit | go/kvstore | 2 | evals/go/kvstore/eval/qual/audit.json | 0 | 5 | 0 |
| java/springboot-basic/qual/audit | java/springboot-basic | 2 | evals/java/springboot-basic/eval/qual/audit.json | 0 | 5 | 0 |
| node/express-basic/qual/audit | node/express-basic | 2 | evals/node/express-basic/eval/qual/audit.json | 0 | 5 | 0 |
| python/fastapi-celery/qual/audit | python/fastapi-celery | 2 | evals/python/fastapi-celery/eval/qual/audit.json | 0 | 5 | 0 |
| python/flask-basic/qual/audit | python/flask-basic | 2 | evals/python/flask-basic/eval/qual/audit.json | 0 | 5 | 0 |
| sanity/skill-smoke/sanity/audit | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/audit.json | 0 | 0 | 0 |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
