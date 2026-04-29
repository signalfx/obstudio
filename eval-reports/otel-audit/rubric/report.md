# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260429T171547534589Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 100% (10/10), avg score 52 | 437.8K | 2.9m | - | - | - |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | 2 | 100% (10/10), avg score 100 | 442.5K | 4.0m | - | - | - |
| with_skill | go/kvstore/qual/audit | go/kvstore | 2 | 100% (10/10), avg score 52 | 834.9K | 4.4m | - | - | - |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | 2 | 100% (10/10), avg score 5 | 397.3K | 3.3m | - | - | - |
| with_skill | node/express-basic/qual/audit | node/express-basic | 2 | 100% (10/10), avg score 52 | 398.7K | 2.7m | - | - | - |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | 2 | 100% (12/12), avg score 52 | 406.0K | 3.5m | - | - | - |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | 2 | 100% (10/10), avg score 100 | 364.3K | 3.2m | - | - | - |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
