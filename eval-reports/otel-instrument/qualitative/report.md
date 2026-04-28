# otel-instrument Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Modes | ab |
| Eval kind | qualitative |
| Skill | otel-instrument |
| Run ID | 20260428T192421826689Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Qualitative enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Validation

| Eval | Service | Prompts | Eval File | Deterministic Checks | Qualitative Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-basic/instrument | go/chi-basic | 2 | evals/go/chi-basic/instrument_eval.json | 5 | 5 | 0 |
| go/chi-partial/instrument | go/chi-partial | 2 | evals/go/chi-partial/instrument_eval.json | 5 | 5 | 0 |
| go/kvstore/instrument | go/kvstore | 2 | evals/go/kvstore/instrument_eval.json | 5 | 5 | 0 |
| java/springboot-basic/instrument | java/springboot-basic | 2 | evals/java/springboot-basic/instrument_eval.json | 4 | 5 | 0 |
| node/express-basic/instrument | node/express-basic | 2 | evals/node/express-basic/instrument_eval.json | 4 | 5 | 0 |
| python/fastapi-celery/instrument | python/fastapi-celery | 2 | evals/python/fastapi-celery/instrument_eval.json | 4 | 5 | 0 |
| python/flask-basic/instrument | python/flask-basic | 2 | evals/python/flask-basic/instrument_eval.json | 4 | 5 | 0 |

## Deterministic

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | go/chi-basic/instrument | go/chi-basic | 2 | 100% (4/4) | 9.5M | 17.6m | 100% (6/6) | 8.5M | 16.7m |
| ab | go/chi-partial/instrument | go/chi-partial | 2 | 100% (4/4) | 8.1M | 16.4m | 100% (6/6) | 5.7M | 11.7m |
| ab | go/kvstore/instrument | go/kvstore | 2 | 100% (4/4) | 9.2M | 18.6m | 100% (6/6) | 7.3M | 16.1m |
| ab | java/springboot-basic/instrument | java/springboot-basic | 2 | 100% (4/4) | 946.1K | 7.2m | 100% (6/6) | 1.1M | 7.3m |
| ab | node/express-basic/instrument | node/express-basic | 2 | 100% (4/4) | 6.8M | 26.5m | 100% (6/6) | 2.3M | 18.0m |
| ab | python/fastapi-celery/instrument | python/fastapi-celery | 2 | 100% (4/4) | 3.8M | 14.7m | 100% (6/6) | 2.5M | 11.7m |
| ab | python/flask-basic/instrument | python/flask-basic | 2 | 100% (4/4) | 2.6M | 9.9m | 100% (6/6) | 1.3M | 7.1m |

### Deterministic Failures

No deterministic failures.

## Qualitative

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | go/chi-basic/instrument | go/chi-basic | 2 | 60% (6/10), avg score 66 | 9.5M | 17.6m | 50% (5/10), avg score 22 | 8.5M | 16.7m |
| ab | go/chi-partial/instrument | go/chi-partial | 2 | 80% (8/10), avg score 80 | 8.1M | 16.4m | 50% (5/10), avg score 58 | 5.7M | 11.7m |
| ab | go/kvstore/instrument | go/kvstore | 2 | 100% (10/10), avg score 100 | 9.2M | 18.6m | 70% (7/10), avg score 70 | 7.3M | 16.1m |
| ab | java/springboot-basic/instrument | java/springboot-basic | 2 | 100% (12/12), avg score 52 | 946.1K | 7.2m | 80% (8/10), avg score 4 | 1.1M | 7.3m |
| ab | node/express-basic/instrument | node/express-basic | 2 | 92% (11/12), avg score 92 | 6.8M | 26.5m | 90% (9/10), avg score 90 | 2.3M | 18.0m |
| ab | python/fastapi-celery/instrument | python/fastapi-celery | 2 | 92% (11/12), avg score 90 | 3.8M | 14.7m | 80% (8/10), avg score 42 | 2.5M | 11.7m |
| ab | python/flask-basic/instrument | python/flask-basic | 2 | 100% (14/14), avg score 100 | 2.6M | 9.9m | 90% (9/10), avg score 42 | 1.3M | 7.1m |

### Qualitative Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| ab | go/chi-basic | with_skill | direct | qualitative:qualitative-1 FAIL | last_message.md only reports post-change configuration: service.name from OTEL_SERVICE_NAME and deployment.environment via OTEL_RESOURCE_ATTRIBUTES. |
| ab | go/chi-basic | with_skill | direct | qualitative:qualitative-3 FAIL | service/main.go:127 uses otelhttp.NewHandler(r, "server") with no chi-aware middleware, http.route tagging, or span name formatter based on chi route patterns. |
| ab | go/chi-basic | with_baseline | direct | qualitative:qualitative-1 FAIL | last_message.md:1-12 contains implementation summary and test command, but no pre-edit confirmation of process/runtime/service-name/env assumptions. |
| ab | go/chi-basic | with_baseline | direct | qualitative:qualitative-4 FAIL | service/main.go:23 defines const serviceName = "go-chi-basic"; service/main.go:146 uses otlptracehttp.New(ctx); service/main.go:151-155 applies resource.WithFromEnv() followed by semconv.ServiceName(serviceName). |
| ab | go/chi-basic | with_skill | runtime-preserving | qualitative:qualitative-1 FAIL | last_message.md describes the Go chi service in ./service, go 1.23, OTEL_SERVICE_NAME, and deployment.environment via OTEL_RESOURCE_ATTRIBUTES after implementation; service/main.go keeps http.ListenAndServe(":8000", ...). |
| ab | go/chi-basic | with_skill | runtime-preserving | qualitative:qualitative-3 FAIL | service/main.go:123 uses otelhttp.NewHandler(r, "http.server") with no otelchi middleware or otelhttp.WithRouteTag usage. |
| ab | go/chi-basic | with_baseline | runtime-preserving | qualitative:qualitative-1 FAIL | last_message.md only summarizes completed changes and mentions keeping go 1.23 and http.ListenAndServe; it does not document the requested pre-edit confirmation. |
| ab | go/chi-basic | with_baseline | runtime-preserving | qualitative:qualitative-3 FAIL | service/main.go uses r.Use(otelhttp.NewMiddleware("go-chi-basic")); there is no otelchi middleware, otelhttp.WithRouteTag, or span-name formatter based on chi route patterns. |
| ab | go/chi-basic | with_baseline | runtime-preserving | qualitative:qualitative-4 FAIL | service/main.go has no OTLP exporter setup, no resource/service.name setup, and no reads of OTEL_EXPORTER_OTLP_ENDPOINT or OTEL_SERVICE_NAME. go.mod only adds auto/sdk, otelhttp, and otel. |
| ab | go/chi-partial | with_skill | direct | qualitative:qualitative-5 FAIL | service/main.go contains no RecordError or SetStatus calls. The otelhttp span name formatter runs before chi sets r.Pattern, while captureRoutePattern assigns r.Pattern only after next.ServeHTTP returns, so spans will fall back to the generic operation name rather than GET /tasks/{id}. |
| ab | go/chi-partial | with_baseline | direct | qualitative:qualitative-1 FAIL | service/main.go:59-65 defines chi.NewRouter() and r.Use(otelchi.Middleware(...)); there is no otelhttp import or otelhttp.NewHandler wrapping. |
| ab | go/chi-partial | with_baseline | direct | qualitative:qualitative-2 FAIL | service/main.go:151-176 only creates an OTLP trace exporter and sdktrace.TracerProvider; there is no sdkmetric.MeterProvider, OTLP metric exporter, or otel.SetMeterProvider call. |
| ab | go/chi-partial | with_baseline | direct | qualitative:qualitative-5 FAIL | service/main.go:63 uses otelchi.WithChiRoutes(r), but failure responses at service/main.go:88, 96, 114, 131, and 145 only write JSON/status codes; there are no RecordError or SetStatus calls. |
| ab | go/chi-partial | with_skill | runtime-preserving | qualitative:qualitative-5 FAIL | No RecordError or SetStatus calls found. Failure branches in service/main.go:75-77, 93-95, 68, 111, and 125 only call writeJSON with 400/404 responses. |
| ab | go/chi-partial | with_baseline | runtime-preserving | qualitative:qualitative-4 FAIL | GET /tasks/{id} still contains tracer := otel.Tracer(serviceName) inside the request handler before starting the tasks.get span. |
| ab | go/chi-partial | with_baseline | runtime-preserving | qualitative:qualitative-5 FAIL | routeSpanMiddleware renames spans to method plus route and sets http.route; however handlers return 400/404 without span.RecordError or span.SetStatus, and no codes package is used. |
| ab | go/kvstore | with_baseline | direct | qualitative:qualitative-1 FAIL | service/cmd/kvstore-server/main.go calls setupOpenTelemetry(...), but service/kvstore/http.go imports otelhttp and returns otelhttp.NewHandler(mux, "kvstore.http", ...). |
| ab | go/kvstore | with_baseline | direct | qualitative:qualitative-5 FAIL | service/.vscode/launch.json still only contains the Go launch configuration with program set to ${workspaceFolder}/cmd/kvstore-server and no env block for OTEL_SERVICE_NAME or OTEL_EXPORTER_OTLP_ENDPOINT. |
| ab | go/kvstore | with_baseline | runtime-preserving | qualitative:qualitative-5 FAIL | service/.vscode/launch.json only contains the Go launch program ${workspaceFolder}/cmd/kvstore-server and has no env block or OTEL_* configuration. |
| ab | java/springboot-basic | with_baseline | direct | qualitative:qualitative-4 FAIL | README only says the agent provides zero-code instrumentation and gives run commands; last_message.md does not mention HTTP server spans or request duration metrics. |
| ab | java/springboot-basic | with_baseline | runtime-preserving | qualitative:qualitative-4 FAIL | README.md says Java agent auto-instrumentation requires no controller/application SDK code, but it does not mention HTTP server spans or request duration metrics. |
| ab | node/express-basic | with_skill | direct | qualitative:qualitative-2 FAIL | service/otel.js configures instrumentations: [new HttpInstrumentation(), new ExpressInstrumentation()]. package-lock resolves express 5.2.1, while @opentelemetry/instrumentation-express 0.47.1 declares support for express >=4.0.0 <5. |
| ab | node/express-basic | with_baseline | runtime-preserving | qualitative:qualitative-4 FAIL | service/instrumentation.js only calls sdk.start() at line 9; there is no process signal handler and no sdk.shutdown() call. |
| ab | python/fastapi-celery | with_skill | direct | qualitative:qualitative-3 FAIL | service/docker-compose.yml defines observer with build context ./.codex-runtime/repo and api/worker depend_on observer, but service/.codex-runtime is absent. |
| ab | python/fastapi-celery | with_baseline | direct | qualitative:qualitative-4 FAIL | service/telemetry.py sets only SERVICE_NAME from OTEL_SERVICE_NAME/default_service_name; service/docker-compose.yml sets OTEL_SERVICE_NAME for api and worker but has no deployment.environment resource attribute, OTEL_RESOURCE_ATTRIBUTES, OTEL_DEPLOYMENT_ENVIRONMENT, or equivalent per-process setting. |
| ab | python/fastapi-celery | with_baseline | runtime-preserving | qualitative:qualitative-4 FAIL | service/docker-compose.yml sets OTEL_SERVICE_NAME separately for api and worker, and telemetry.py reads OTEL_SERVICE_NAME. No deployment environment variable or resource attribute is added for api or worker. |
| ab | python/flask-basic | with_baseline | direct | qualitative:qualitative-1 FAIL | service/app.py imports TracerProvider, Resource, BatchSpanProcessor, OTLPSpanExporter, calls trace.set_tracer_provider(...), and instruments Flask inline. |

## Runtime

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| ab | go/chi-basic/instrument | go/chi-basic | 2 | - | 9.5M | 17.6m | - | 8.5M | 16.7m |
| ab | go/chi-partial/instrument | go/chi-partial | 2 | - | 8.1M | 16.4m | - | 5.7M | 11.7m |
| ab | go/kvstore/instrument | go/kvstore | 2 | - | 9.2M | 18.6m | - | 7.3M | 16.1m |
| ab | java/springboot-basic/instrument | java/springboot-basic | 2 | - | 946.1K | 7.2m | - | 1.1M | 7.3m |
| ab | node/express-basic/instrument | node/express-basic | 2 | - | 6.8M | 26.5m | - | 2.3M | 18.0m |
| ab | python/fastapi-celery/instrument | python/fastapi-celery | 2 | - | 3.8M | 14.7m | - | 2.5M | 11.7m |
| ab | python/flask-basic/instrument | python/flask-basic | 2 | - | 2.6M | 9.9m | - | 1.3M | 7.1m |

### Runtime Failures

No runtime failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
