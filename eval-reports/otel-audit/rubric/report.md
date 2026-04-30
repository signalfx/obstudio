# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260430T171007325917Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 100% (11/11), avg score 100 | 401.2K | 3.4m | - | - | - |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | 2 | 100% (10/10), avg score 100 | 422.3K | 3.9m | - | - | - |
| with_skill | go/kvstore/qual/audit | go/kvstore | 2 | 100% (10/10), avg score 50 | 773.4K | 4.2m | - | - | - |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | 2 | 100% (10/10), avg score 52 | 428.3K | 3.7m | - | - | - |
| with_skill | node/express-basic/qual/audit | node/express-basic | 2 | 100% (10/10), avg score 52 | 426.8K | 2.8m | - | - | - |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | 2 | 90% (9/10), avg score 86 | 464.4K | 4.0m | - | - | - |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | 2 | 100% (10/10), avg score 5 | 454.1K | 2.6m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/fastapi-celery | with_skill | direct | rubric:rubric-4 FAIL | The response says there are no `OTEL_*` env vars/exporter/resource config, but it does not explicitly identify that the `api` and `worker` docker-compose start commands are not wrapped/configured for instrumentation. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
