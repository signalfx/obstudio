# otel-instrument Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex A/B execution.

| Case | Prompt | Eval File | Deterministic Checks | Qualitative Checks |
|---|---|---|---:|---:|
| go/chi-basic | direct | evals/go/chi-basic/instrument_eval.json | 5 | 5 |
| go/chi-basic | runtime-preserving | evals/go/chi-basic/instrument_eval.json | 5 | 5 |
| go/kvstore | direct | evals/go/kvstore/instrument_eval.json | 5 | 5 |
| go/kvstore | runtime-preserving | evals/go/kvstore/instrument_eval.json | 5 | 5 |
| node/express-basic | direct | evals/node/express-basic/instrument_eval.json | 4 | 5 |
| node/express-basic | runtime-preserving | evals/node/express-basic/instrument_eval.json | 4 | 5 |
| python/fastapi-celery | direct | evals/python/fastapi-celery/instrument_eval.json | 4 | 5 |
| python/fastapi-celery | runtime-preserving | evals/python/fastapi-celery/instrument_eval.json | 4 | 5 |
| python/flask-basic | direct | evals/python/flask-basic/instrument_eval.json | 4 | 5 |
| python/flask-basic | runtime-preserving | evals/python/flask-basic/instrument_eval.json | 4 | 5 |
