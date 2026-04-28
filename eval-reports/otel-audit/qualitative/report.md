# otel-audit Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Modes | ab |
| Eval kind | qualitative |
| Skill | otel-audit |
| Run ID | 20260428T192421826689Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Qualitative enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

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

## Deterministic

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | go/chi-basic/audit | go/chi-basic | 2 | 100% (4/4) | 493.0K | 2.8m | 100% (6/6) | 358.4K | 3.3m |
| ab | go/chi-partial/audit | go/chi-partial | 2 | 100% (4/4) | 548.2K | 3.7m | 100% (6/6) | 941.5K | 6.1m |
| ab | go/kvstore/audit | go/kvstore | 2 | 100% (4/4) | 646.4K | 4.1m | 100% (6/6) | 653.2K | 4.1m |
| ab | java/springboot-basic/audit | java/springboot-basic | 2 | 100% (4/4) | 547.7K | 3.7m | 100% (6/6) | 380.5K | 4.0m |
| ab | node/express-basic/audit | node/express-basic | 2 | 100% (4/4) | 475.4K | 3.9m | 100% (6/6) | 315.4K | 2.9m |
| ab | python/fastapi-celery/audit | python/fastapi-celery | 2 | 100% (4/4) | 589.9K | 4.3m | 100% (6/6) | 540.6K | 4.0m |
| ab | python/flask-basic/audit | python/flask-basic | 2 | 100% (4/4) | 459.4K | 3.0m | 100% (6/6) | 369.2K | 2.9m |

### Deterministic Failures

No deterministic failures.

## Qualitative

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | go/chi-basic/audit | go/chi-basic | 2 | 100% (12/12), avg score 100 | 493.0K | 2.8m | 50% (5/10), avg score 59 | 358.4K | 3.3m |
| ab | go/chi-partial/audit | go/chi-partial | 2 | 100% (10/10), avg score 100 | 548.2K | 3.7m | 80% (8/10), avg score 82 | 941.5K | 6.1m |
| ab | go/kvstore/audit | go/kvstore | 2 | 100% (10/10), avg score 98 | 646.4K | 4.1m | 50% (5/10), avg score 55 | 653.2K | 4.1m |
| ab | java/springboot-basic/audit | java/springboot-basic | 2 | 100% (14/14), avg score 100 | 547.7K | 3.7m | 60% (9/15), avg score 62 | 380.5K | 4.0m |
| ab | node/express-basic/audit | node/express-basic | 2 | 100% (10/10), avg score 52 | 475.4K | 3.9m | 70% (7/10), avg score 42 | 315.4K | 2.9m |
| ab | python/fastapi-celery/audit | python/fastapi-celery | 2 | 100% (10/10), avg score 98 | 589.9K | 4.3m | 60% (6/10), avg score 68 | 540.6K | 4.0m |
| ab | python/flask-basic/audit | python/flask-basic | 2 | 100% (14/14), avg score 100 | 459.4K | 3.0m | 50% (5/10), avg score 31 | 369.2K | 2.9m |

### Qualitative Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| ab | go/chi-basic | with_baseline | direct | qualitative:qualitative-2 FAIL | Final response mentions /health, but does not list GET /tasks, GET /tasks/{id}, POST /tasks, PATCH /tasks/{id}, or DELETE /tasks/{id}. |
| ab | go/chi-basic | with_baseline | direct | qualitative:qualitative-4 FAIL | Mentions "route-level tracing," "status/duration metrics," and unobserved handler errors; does not mention request rate or OTLP. |
| ab | go/chi-basic | with_baseline | direct | qualitative:qualitative-5 FAIL | "instrument routes with OpenTelemetry chi middleware" |
| ab | go/chi-basic | with_baseline | readiness-review | qualitative:qualitative-1 FAIL | Mentions chi router creation at main.go:28 and ListenAndServe at main.go:110, but never states that main.go is the entry point. |
| ab | go/chi-basic | with_baseline | readiness-review | qualitative:qualitative-2 FAIL | Lists `/health`, `/tasks`, `/tasks/{id}`, `POST /tasks`, `PATCH /tasks/{id}`, and `DELETE /tasks/{id}`. |
| ab | go/chi-partial | with_baseline | direct | qualitative:qualitative-4 FAIL | Says span names like `GetTask-123` are bad cardinality; no separate finding says `otel.Tracer("task-service")` is created inside `GET /tasks/{id}`. |
| ab | go/chi-partial | with_baseline | readiness-review | qualitative:qualitative-4 FAIL | Anti-Patterns section discusses GetTask-%d including task ID, but has no specific finding about tracer := otel.Tracer("task-service") inside GET /tasks/{id}. |
| ab | go/kvstore | with_baseline | direct | qualitative:qualitative-1 FAIL | Final response cites service/cmd/kvstore-server/main.go:32 only for the missing health/readiness endpoint. |
| ab | go/kvstore | with_baseline | direct | qualitative:qualitative-2 FAIL | Final response: "route labels for `/kv/` and `/search`". |
| ab | go/kvstore | with_baseline | direct | qualitative:qualitative-3 FAIL | Final response says "No tracing or context propagation" but does not mention OTel SDK initialization, dependencies, or exporter absence. |
| ab | go/kvstore | with_baseline | direct | qualitative:qualitative-5 FAIL | Final response is organized as P1/P2/P3 findings rather than distinct coverage-gap and anti-pattern sections. |
| ab | go/kvstore | with_baseline | readiness-review | qualitative:qualitative-2 FAIL | Final response only says routing starts in kvstore/http.go and discusses HTTP handlers generally; it never lists the required route templates. |
| ab | java/springboot-basic | with_baseline | direct | qualitative:qualitative-1 FAIL | last_message.md never mentions TasksApplication.java, SpringApplication.run, main, or entry point. |
| ab | java/springboot-basic | with_baseline | direct | qualitative:qualitative-2 FAIL | It mentions /health and create/update/delete paths, but omits explicit identification of GET /tasks and GET /tasks/{id} and does not enumerate TaskController routes. |
| ab | java/springboot-basic | with_baseline | direct | qualitative:qualitative-4 FAIL | last_message.md does not mention RED, request rate, HTTP latency, or error-rate visibility together. |
| ab | java/springboot-basic | with_baseline | direct | qualitative:qualitative-5 FAIL | Recommended first fixes are Actuator, metrics/tracing config, health/readiness/liveness, structured logging, and domain counters/timers; Java agent is only mentioned conditionally, not recommended. |
| ab | java/springboot-basic | with_baseline | readiness-review | qualitative:qualitative-1 FAIL | TasksApplication.java contains main() calling SpringApplication.run(TasksApplication.class, args), but last_message.md does not mention TasksApplication.java or the main entry point. |
| ab | java/springboot-basic | with_baseline | readiness-review | qualitative:qualitative-4 FAIL | last_message.md lacks RED terminology and request-rate coverage; it only mentions no distributed tracing, framework-level timing, and no error instrumentation beyond HTTP statuses. |
| ab | node/express-basic | with_baseline | direct | qualitative:qualitative-2 FAIL | It references `/health` only indirectly through app context and mentions task create/update/delete paths, but does not list GET /health, GET /tasks, GET /tasks/:id, POST /tasks, PATCH /tasks/:id, and DELETE /tasks/:id. |
| ab | node/express-basic | with_baseline | direct | qualitative:qualitative-3 FAIL | It says dependencies only include Express and there is no request/response instrumentation, but does not name missing HTTP or Express OpenTelemetry instrumentation packages. |
| ab | node/express-basic | with_baseline | readiness-review | qualitative:qualitative-2 FAIL | service/app.js defines GET /health, GET /tasks, GET /tasks/:id, POST /tasks, PATCH /tasks/:id, and DELETE /tasks/:id; last_message.md only says /health, /tasks, /tasks/:id, and write endpoints. |
| ab | python/fastapi-celery | with_baseline | direct | qualitative:qualitative-3 FAIL | Final response says there are no OpenTelemetry packages and startup commands do not use opentelemetry-instrument, but it never mentions ASGI or HTTP client instrumentation. |
| ab | python/fastapi-celery | with_baseline | readiness-review | qualitative:qualitative-2 FAIL | Final response references pyproject.toml, app.py, worker.py, and docker-compose.yml, but has no mention of service/Dockerfile or the image CMD. |
| ab | python/fastapi-celery | with_baseline | readiness-review | qualitative:qualitative-3 FAIL | Final response says there is no FastAPI request tracing and no Celery producer/consumer tracing, but it never mentions ASGI instrumentation or HTTP client instrumentation. |
| ab | python/fastapi-celery | with_baseline | readiness-review | qualitative:qualitative-4 FAIL | Final response says API and worker are not configured to export to the observer and recommends `OTEL_EXPORTER_OTLP_ENDPOINT=http://observer:4318`, but does not discuss Dockerfile CMD or docker-compose worker command instrumentation. |
| ab | python/flask-basic | with_baseline | direct | qualitative:qualitative-2 FAIL | The response only explicitly names `/health`, `create_task`, and `update_task`; it omits a route list such as GET /tasks, GET /tasks/<id>, POST /tasks, PATCH /tasks/<id>, DELETE /tasks/<id>. |
| ab | python/flask-basic | with_baseline | direct | qualitative:qualitative-4 FAIL | No occurrence of `opentelemetry-instrumentation-flask`, `OpenTelemetry`, or `auto-instrumentation` appears in last_message.md. |
| ab | python/flask-basic | with_baseline | direct | qualitative:qualitative-5 FAIL | The response says "latency" and "exception outcome" and "exporter setup", but does not mention request rate or OTLP. |
| ab | python/flask-basic | with_baseline | readiness-review | qualitative:qualitative-2 FAIL | Missing explicit list of GET /tasks, GET /tasks/<int:task_id>, POST /tasks, PATCH /tasks/<int:task_id>, and DELETE /tasks/<int:task_id>. |
| ab | python/flask-basic | with_baseline | readiness-review | qualitative:qualitative-4 FAIL | It says “No Flask auto-instrumentation” and recommends FlaskInstrumentor, but omits the exact package name. |

## Runtime

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | go/chi-basic/audit | go/chi-basic | 2 | - | 493.0K | 2.8m | - | 358.4K | 3.3m |
| ab | go/chi-partial/audit | go/chi-partial | 2 | - | 548.2K | 3.7m | - | 941.5K | 6.1m |
| ab | go/kvstore/audit | go/kvstore | 2 | - | 646.4K | 4.1m | - | 653.2K | 4.1m |
| ab | java/springboot-basic/audit | java/springboot-basic | 2 | - | 547.7K | 3.7m | - | 380.5K | 4.0m |
| ab | node/express-basic/audit | node/express-basic | 2 | - | 475.4K | 3.9m | - | 315.4K | 2.9m |
| ab | python/fastapi-celery/audit | python/fastapi-celery | 2 | - | 589.9K | 4.3m | - | 540.6K | 4.0m |
| ab | python/flask-basic/audit | python/flask-basic | 2 | - | 459.4K | 3.0m | - | 369.2K | 2.9m |

### Runtime Failures

No runtime failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
