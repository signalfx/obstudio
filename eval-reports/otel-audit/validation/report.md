# otel-audit Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Modes | validation |
| Eval kind | validation |
| Skill | otel-audit |
| Run ID | 20260428T192359575799Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Validation

| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-basic/audit | go/chi-basic | 2 | evals/go/chi-basic/audit_eval.json | 5 | 5 | 0 |
| go/chi-partial/audit | go/chi-partial | 2 | evals/go/chi-partial/audit_eval.json | 6 | 5 | 0 |
| go/kvstore/audit | go/kvstore | 2 | evals/go/kvstore/audit_eval.json | 4 | 5 | 0 |
| java/springboot-basic/audit | java/springboot-basic | 2 | evals/java/springboot-basic/audit_eval.json | 4 | 5 | 0 |
| node/express-basic/audit | node/express-basic | 2 | evals/node/express-basic/audit_eval.json | 4 | 5 | 0 |
| python/fastapi-celery/audit | python/fastapi-celery | 2 | evals/python/fastapi-celery/audit_eval.json | 4 | 5 | 0 |
| python/flask-basic/audit | python/flask-basic | 2 | evals/python/flask-basic/audit_eval.json | 4 | 5 | 0 |
| sanity/skill-smoke/audit_sanity | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/audit_sanity_eval.json | 0 | 0 | 0 |

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
