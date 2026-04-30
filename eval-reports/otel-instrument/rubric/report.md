# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260430T171007325917Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 2 | 70% (7/10), avg score 70 | 8.0M | 17.0m | - | - | - |
| with_skill | go/chi-partial/qual/instrument | go/chi-partial | 2 | 80% (8/10), avg score 80 | 2.6M | 11.5m | - | - | - |
| with_skill | go/kvstore/qual/instrument | go/kvstore | 2 | 100% (10/10), avg score 100 | 3.4M | 12.2m | - | - | - |
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | 2 | 100% (10/10), avg score 52 | 1.0M | 7.2m | - | - | - |
| with_skill | node/express-basic/qual/instrument | node/express-basic | 2 | 100% (10/10), avg score 50 | 1.7M | 9.8m | - | - | - |
| with_skill | python/fastapi-celery/qual/instrument | python/fastapi-celery | 2 | 100% (10/10), avg score 91 | 1.0M | 9.1m | - | - | - |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | 2 | 100% (10/10), avg score 5 | 829.3K | 5.6m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-1 FAIL | trace.jsonl agent preflight: existing native Go HTTP service in ./service using chi on :8000, no existing OTel; last_message.md later states OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES=deployment.environment=... |
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-3 FAIL | service/main.go uses otelhttp.NewHandler(r, "server") only. |
| with_skill | go/chi-basic | with_skill | runtime-preserving | rubric:rubric-3 FAIL | service/main.go:127 wraps the chi router with otelhttp.NewHandler(r, "server"), which keeps the router in place, but there is no otelchi middleware, otelhttp.WithRouteTag, or span name formatter using chi route patterns. Spans will use the constant operation name "server" rather than route-aware low-cardinality name... |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-5 FAIL | rg found no RecordError, SetStatus, or codes.* usage; service/main.go:65,73,91,108,122 write 404/400 responses without span error/status handling. |
| with_skill | go/chi-partial | with_skill | runtime-preserving | rubric:rubric-5 FAIL | service/main.go has no RecordError or SetStatus calls; 400/404 paths only call writeJSON. The local otelhttp v0.68.0 server status helper sets Error only for status >=500. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
