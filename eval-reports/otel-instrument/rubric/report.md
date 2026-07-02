# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260702T053425175067Z-mttd-summary |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | .workspace/codex-evals-gpt55-high.toml, .workspace/codex-evals-local-xhigh.toml, .workspace/codex-evals-xhigh.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | java/kafka-streams/qual/incident-readiness | java/kafka-streams | 1 | 100% (6/6), avg score 92 | 4.9M | 19.5m | - | - | - |
| with_skill | go/kvstore/qual/incident-readiness | go/kvstore | 1 | 100% (6/6), avg score 90 | 17.8M | 36.7m | - | - | - |
| with_skill | python/fastapi-celery/qual/incident-readiness | python/fastapi-celery | 1 | 100% (7/7), avg score 84 | 2.8M | 13.8m | - | - | - |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
