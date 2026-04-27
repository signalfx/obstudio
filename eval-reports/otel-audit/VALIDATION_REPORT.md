# otel-audit Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex A/B execution.

| Case | Prompt | Eval File | Deterministic Checks | Qualitative Checks |
|---|---|---|---:|---:|
| go/chi-basic | direct | evals/go/chi-basic/audit_eval.json | 5 | 5 |
| go/chi-basic | readiness-review | evals/go/chi-basic/audit_eval.json | 5 | 5 |
| go/kvstore | direct | evals/go/kvstore/audit_eval.json | 4 | 5 |
| go/kvstore | readiness-review | evals/go/kvstore/audit_eval.json | 4 | 5 |
| node/express-basic | direct | evals/node/express-basic/audit_eval.json | 4 | 5 |
| node/express-basic | readiness-review | evals/node/express-basic/audit_eval.json | 4 | 5 |
| python/fastapi-celery | direct | evals/python/fastapi-celery/audit_eval.json | 4 | 5 |
| python/fastapi-celery | readiness-review | evals/python/fastapi-celery/audit_eval.json | 4 | 5 |
| python/flask-basic | direct | evals/python/flask-basic/audit_eval.json | 4 | 5 |
| python/flask-basic | readiness-review | evals/python/flask-basic/audit_eval.json | 4 | 5 |
