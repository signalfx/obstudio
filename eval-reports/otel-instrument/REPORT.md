# otel-instrument Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Modes | validation |
| Skill | otel-instrument |
| Run ID | 20260427T213342562035Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Qualitative enabled | True |
| Runtime enabled | False |
| Workers | 1 |
| Config | /Users/pavankri/Cisco/obstudio/evals/codex-evals.validation.toml |

## Validation

| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-basic/instrument | go/chi-basic | 2 | evals/go/chi-basic/instrument_eval.json | 5 | 5 | 0 |
| go/chi-partial/instrument | go/chi-partial | 2 | evals/go/chi-partial/instrument_eval.json | 5 | 5 | 0 |
| go/kvstore/instrument | go/kvstore | 2 | evals/go/kvstore/instrument_eval.json | 5 | 5 | 0 |
| java/springboot-basic/instrument | java/springboot-basic | 2 | evals/java/springboot-basic/instrument_eval.json | 4 | 5 | 0 |
| node/express-basic/instrument | node/express-basic | 2 | evals/node/express-basic/instrument_eval.json | 4 | 5 | 0 |
| python/fastapi-celery/instrument | python/fastapi-celery | 2 | evals/python/fastapi-celery/instrument_eval.json | 4 | 5 | 1 |
| python/flask-basic/instrument | python/flask-basic | 2 | evals/python/flask-basic/instrument_eval.json | 4 | 5 | 0 |

## Deterministic

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| - | - | - | 0 | - | - | - | - | - | - |

### Deterministic Failures

No deterministic failures.

## Qualitative

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| - | - | - | 0 | - | - | - | - | - | - |

### Qualitative Failures

No qualitative failures.

## Runtime

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| - | - | - | 0 | - | - | - | - | - | - |

### Runtime Failures

No runtime failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
