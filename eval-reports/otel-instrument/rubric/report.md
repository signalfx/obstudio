# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260703T005240819871Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 2 | 83% (10/12), avg score 82 | 3.7M | 12.8m | - | - | - |
| with_skill | go/chi-partial/qual/instrument | go/chi-partial | 2 | 70% (7/10), avg score 81 | 2.2M | 11.5m | - | - | - |
| with_skill | go/kvstore/qual/incident-readiness | go/kvstore | 1 | 83% (5/6), avg score 76 | 2.7M | 11.2m | - | - | - |
| with_skill | go/kvstore/qual/instrument | go/kvstore | 2 | 92% (12/13), avg score 90 | 6.5M | 18.6m | - | - | - |
| with_skill | java/kafka-batch-consumer/qual/instrument | java/kafka-batch-consumer | 2 | 60% (6/10), avg score 84 | 1.3M | 8.8m | - | - | - |
| with_skill | java/kafka-listener-container/qual/instrument | java/kafka-listener-container | 2 | 80% (8/10), avg score 88 | 1.1M | 8.6m | - | - | - |
| with_skill | java/kafka-producer-consumer/qual/instrument | java/kafka-producer-consumer | 2 | 70% (7/10), avg score 86 | 1.3M | 9.4m | - | - | - |
| with_skill | java/kafka-streams/qual/incident-readiness | java/kafka-streams | 1 | 100% (6/6), avg score 86 | 1.2M | 7.8m | - | - | - |
| with_skill | java/kafka-streams/qual/instrument | java/kafka-streams | 2 | 100% (12/12), avg score 94 | 1.4M | 10.0m | - | - | - |
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | 2 | 100% (10/10), avg score 93 | 1.0M | 8.6m | - | - | - |
| with_skill | node/express-basic/qual/instrument | node/express-basic | 2 | 100% (10/10), avg score 91 | 1.5M | 14.2m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | 1 | 86% (6/7), avg score 82 | 1.9M | 10.2m | - | - | - |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/instrument | python/assistant-v3-framework-bridge-demo | 1 | 86% (6/7), avg score 82 | 895.4K | 5.0m | - | - | - |
| with_skill | python/fastapi-celery/qual/incident-readiness | python/fastapi-celery | 1 | 86% (6/7), avg score 82 | 851.5K | 7.5m | - | - | - |
| with_skill | python/fastapi-celery/qual/instrument | python/fastapi-celery | 2 | 100% (11/11), avg score 89 | 2.1M | 12.0m | - | - | - |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | 2 | 100% (10/10), avg score 94 | 1.1M | 9.3m | - | - | - |
| with_skill | python/mcp-ai-tool-demo/qual/instrument | python/mcp-ai-tool-demo | 1 | 71% (5/7), avg score 82 | 1.2M | 8.8m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-1 FAIL | .observe/otel-instrumentation.md records `service/main.go` with `http.ListenAndServe(":8000", ...)`, Go `go1.26.4`, module `go 1.23`, and `OTEL_SERVICE_NAME`; no explicit environment dimension decision was found. |
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-3 FAIL | service/main.go uses both `r.Use(otelchi.Middleware("server"))` and `handler := otelhttp.NewHandler(r, "server")`. .observe/otel-instrumentation.md expects route-aware chi spans but says proof for stable route patterns and duplicate-span behavior is blocked. |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-4 FAIL | service/main.go:80 has tracer := otel.Tracer("task-service") inside the handler. |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-5 FAIL | service/main.go:81 starts span "task.lookup"; service/main.go:93 calls span.SetStatus for task not found; no RecordError calls are present. |
| with_skill | go/chi-partial | with_skill | runtime-preserving | rubric:rubric-5 FAIL | service/main.go no longer creates GetTask-<id> spans, but invalid JSON paths only call writeJSON(..., http.StatusBadRequest, ...) and return without trace.SpanFromContext(...).RecordError or SetStatus. |
| with_skill | go/kvstore | with_skill | mttd | rubric:rubric-3 FAIL | service/kvstore/store.go sends to s.indexCh then calls s.telemetry.indexEnqueued; service/kvstore/telemetry.go appends to pendingIndex in indexEnqueued and removes from pendingIndex in indexProcessing. If indexProcessing runs first, nothing is removed and later indexEnqueued leaves a permanent pending timestamp. |
| with_skill | go/kvstore | with_skill | runtime-preserving | rubric:runtime-preserving FAIL | service/go.mod declares `go 1.25.0`; .observe/otel-instrumentation.md says the original `go 1.22` directive could not be preserved. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-1 FAIL | .observe/otel-instrumentation.md says `Source audit: not found`, lists `service/pom.xml` and `service/README.md` as runtime selection evidence, and README says the application contains no OTel SDK setup or custom `Tracer` usage. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-3 FAIL | service/bin/run-with-otel exports `OTEL_SERVICE_NAME` and `OTEL_EXPORTER_OTLP_ENDPOINT` and starts `java -javaagent:"$AGENT_PATH"`, but no file contains `OTEL_METRIC_EXPORT_INTERVAL` or `OTEL_METRIC_EXPORT_TIMEOUT`. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-5 FAIL | service/README.md says the agent provides Kafka consumer spans for `KafkaConsumer.poll()` and says batch-size, failed-record, high-value-payment, and batch-duration metrics remain optional; it does not mention commit latency. |
| with_skill | java/kafka-batch-consumer | with_skill | runtime-preserving | rubric:rubric-5 FAIL | `service/README.md` says Java agent provides Kafka client auto-instrumentation and treats batch-size, failed-record, high-value-payment, and batch-duration metrics as optional custom business signals. `.observe/otel-instrumentation.md` similarly says Java agent Kafka consumer/client spans are expected, but lists bat... |
| with_skill | java/kafka-listener-container | with_skill | direct | rubric:rubric-3 FAIL | service/bin/run-with-otel.sh exports OTEL_SERVICE_NAME, OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_TRACES_EXPORTER, OTEL_METRICS_EXPORTER, and JAVA_TOOL_OPTIONS=-javaagent..., then execs mvn spring-boot:run. There are no OTEL_METRIC_EXPORT_INTERVAL or OTEL_METRIC_EXPORT_TIMEOUT entries in the script or README. |
| with_skill | java/kafka-listener-container | with_skill | direct | rubric:rubric-5 FAIL | .observe/otel-instrumentation.md lists 'Kafka consumer/client spans for the Spring Kafka listener container' as 'OpenTelemetry Java agent auto-instrumentation' and the final response says no custom spans/metrics were added. No mention of processed alert counts or malformed-payload counters as optional business instr... |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-1 FAIL | service/.observe/otel-instrumentation.md says Result: Partial, Source audit: not found, no source audit existed, pom.xml unchanged, no OTel dependencies, and no app-created spans. |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-5 FAIL | README.md says Kafka client tracing is provided by the OpenTelemetry Java agent and expected to emit Kafka producer and consumer spans; .observe/otel-instrumentation.md says no custom app metrics were added. |
| with_skill | java/kafka-producer-consumer | with_skill | runtime-preserving | rubric:rubric-1 FAIL | `.observe/otel-instrumentation.md` lists `service/pom.xml` unchanged, Java agent runtime config, and Kafka call sites, but also says `Source audit: not found` and `No source audit gap table was available`. `rg` found no `Tracer` usage in `service`. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-7 FAIL | last_message.md and .observe/otel-instrumentation.md state uv sync, make test, and $otel-verify were blocked by DNS failure resolving PyPI for opentelemetry-instrumentation-fastapi; only python3 -m compileall is reported passed. |
| with_skill | python/assistant-v3-framework-bridge-demo | with_skill | framework-bridge | rubric:rubric-5 FAIL | service/.observe/otel-instrumentation.md says full-runtime acceptance and focused app-code duplicate check were blocked; GENAI-BRIDGE-001 current evidence is only static startup proof. No .observe explorer output or otel-verify result is present. |
| with_skill | python/fastapi-celery | with_skill | mttd | rubric:rubric-4 FAIL | service/telemetry.py record_order_enqueue attributes include workflow, messaging.system, messaging.destination.name, outcome, quantity.bucket, and optional error.type. |
| with_skill | python/mcp-ai-tool-demo | with_skill | direct | rubric:rubric-5 FAIL | `service/tests/test_telemetry.py` includes JSON-RPC success, dynamic tool privacy, stream lifecycle, and provider failure tests. `last_message.md` and `.observe/otel-instrumentation.md` record `uv run pytest tests/test_telemetry.py` as blocked by DNS fetching `opentelemetry-exporter-otlp`. |
| with_skill | python/mcp-ai-tool-demo | with_skill | direct | rubric:rubric-7 FAIL | `last_message.md` says no `.observe/otel-verify.md` was produced and `uv run pytest tests/test_telemetry.py` was blocked by DNS failure fetching `https://pypi.org/simple/opentelemetry-exporter-otlp/`; `.observe/otel-instrumentation.md` repeats the exact blocker and marks scenarios as blocked. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
