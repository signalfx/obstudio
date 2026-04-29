# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260429T171547534589Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 2 | 70% (7/10), avg score 70 | 5.6M | 16.2m | - | - | - |
| with_skill | go/chi-partial/qual/instrument | go/chi-partial | 2 | 80% (8/10), avg score 42 | 5.7M | 15.7m | - | - | - |
| with_skill | go/kvstore/qual/instrument | go/kvstore | 2 | 100% (10/10), avg score 100 | 4.4M | 13.5m | - | - | - |
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | 2 | 100% (10/10), avg score 100 | 991.0K | 6.3m | - | - | - |
| with_skill | node/express-basic/qual/instrument | node/express-basic | 2 | 100% (10/10), avg score 52 | 1.3M | 7.5m | - | - | - |
| with_skill | python/fastapi-celery/qual/instrument | python/fastapi-celery | 2 | 100% (10/10), avg score 93 | 863.3K | 8.9m | - | - | - |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | 2 | 100% (10/10), avg score 100 | 783.1K | 5.9m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-3 FAIL | service/main.go:126 uses otelhttp.NewHandler(r, "server"); no otelchi import, middleware, or otelhttp route tag appears in service/main.go or service/otel.go. |
| with_skill | go/chi-basic | with_skill | runtime-preserving | rubric:rubric-1 FAIL | trace.jsonl item_3 states a small Go service under service/ with no Docker/Makefile/alternate launcher and native go run startup. The first explicit service.name and environment source statement appears in last_message.md after edits. |
| with_skill | go/chi-basic | with_skill | runtime-preserving | rubric:rubric-3 FAIL | service/main.go wraps the router with otelhttp.NewHandler(r, "server"). service/go.mod does not include otelchi, and the code contains no WithRouteTag or chi route-derived span naming. |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-5 FAIL | service/main.go lines 65, 73, 91, 108, and 122 write 404/400 responses directly. rg found no RecordError, SetStatus, codes.Error, or trace.SpanFromContext in service. |
| with_skill | go/chi-partial | with_skill | runtime-preserving | rubric:rubric-5 FAIL | No fmt.Sprintf("GetTask-%d") remains, but service/main.go failure paths only call writeJSON with 400/404 and there are no RecordError or SetStatus calls anywhere in ./service. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
