# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260703T005240819871Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 92% (11/12), avg score 92 | 585.6K | 6.6m | - | - | - |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | 2 | 80% (8/10), avg score 89 | 445.7K | 5.8m | - | - | - |
| with_skill | go/kvstore/qual/audit | go/kvstore | 2 | 100% (10/10), avg score 91 | 561.3K | 6.1m | - | - | - |
| with_skill | java/kafka-batch-consumer/qual/audit | java/kafka-batch-consumer | 2 | 83% (10/12), avg score 87 | 617.7K | 15.5m | - | - | - |
| with_skill | java/kafka-listener-container/qual/audit | java/kafka-listener-container | 2 | 83% (10/12), avg score 88 | 421.3K | 5.2m | - | - | - |
| with_skill | java/kafka-producer-consumer/qual/audit | java/kafka-producer-consumer | 2 | 58% (7/12), avg score 79 | 486.6K | 4.5m | - | - | - |
| with_skill | java/kafka-streams/qual/audit | java/kafka-streams | 2 | 93% (13/14), avg score 88 | 711.6K | 5.8m | - | - | - |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | 2 | 90% (9/10), avg score 90 | 495.0K | 7.8m | - | - | - |
| with_skill | node/express-basic/qual/audit | node/express-basic | 2 | 100% (10/10), avg score 96 | 530.7K | 4.7m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | 2 | 83% (10/12), avg score 88 | 1.4M | 9.7m | - | - | - |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/audit | python/assistant-v3-framework-bridge-demo | 1 | 100% (6/6), avg score 96 | 374.8K | 3.6m | - | - | - |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | 2 | 60% (6/10), avg score 82 | 549.0K | 5.9m | - | - | - |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | 2 | 91% (10/11), avg score 92 | 410.9K | 4.0m | - | - | - |
| with_skill | python/mcp-ai-tool-demo/qual/audit | python/mcp-ai-tool-demo | 2 | 100% (12/12), avg score 94 | 1.1M | 9.2m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | readiness-review | rubric:rubric-5 FAIL | Recommendation says 'official chi/net/http request instrumentation'; no occurrence of 'otelhttp' or 'otelchi' in service/.observe/otel.md or final response. |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-4 FAIL | last_message.md and .observe/otel.md identify dynamic span name GetTask-%d / fmt.Sprintf("GetTask-%d", id). .observe/otel.md notes the custom tracer at service/main.go:54, but does not explicitly flag creating otel.Tracer inside the handler as a gap or anti-pattern. |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-5 FAIL | .observe/otel.md says no active meter provider, no explicit service.name/resource identity, and no tracer provider shutdown. No mention of TextMapPropagator or propagation configuration was found. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-4 FAIL | Final response says no OTel dependencies, SDK setup, Java agent startup config, OTLP exporter config, spans, metrics, or log correlation; it does not mention Tracer/custom Tracer. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-6 FAIL | Final response says to use Java agent Kafka client instrumentation, but lists batch workflow outcome metrics as required and app-owned/default rather than optional custom signals. |
| with_skill | java/kafka-listener-container | with_skill | direct | rubric:rubric-6 FAIL | Final response says there is no Java agent startup path and no matching OTel Java agent configuration for Kafka consumer/listener spans, but contains no explicit recommendation section and no manual Kafka client avoidance guidance. |
| with_skill | java/kafka-listener-container | with_skill | readiness-review | rubric:rubric-5 FAIL | Final response calls out missing Kafka listener consume telemetry/spans, malformed parse/drop visibility, processed counts, critical alert counts, listener error status/exception visibility, and consumer lag/backpressure. It omits explicit null payload visibility and explicit consumer offset visibility. |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-1 FAIL | Final response: "Entry point \| `ProducerConsumerApplication.main` creates Kafka producer/consumer and runs forever". KafkaClientConfig is not called out as the configuration surface. |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-3 FAIL | Final response says "consumed order to produced shipment" but does not mention `orders` or `shipments`. |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-4 FAIL | Final response: "No OTel SDK, Java agent startup config, OTLP exporter config, resource attributes, custom spans, metrics, or log correlation were found." |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-5 FAIL | Final response lists gaps for "Kafka consume/process/produce trace continuity", "Dropped malformed/null orders", "Kafka backpressure/lag", and "Producer send outcome". |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-6 FAIL | Final response says "Add Java agent startup or SDK bootstrap" and "Enable official Java Kafka client instrumentation", which is weaker and less specific than the rubric requirement. |
| with_skill | java/kafka-streams | with_skill | direct | rubric:rubric-1 FAIL | Final response says: "Framework: Kafka Streams with Guice" and mentions Kafka workflow, but omits both KafkaStreamsApplication.java and StreamProcessingModule.java. |
| with_skill | java/springboot-basic | with_skill | direct | rubric:rubric-4 FAIL | Final response says "No route-level request spans, latency, count, status, or error metrics exist" and mentions "HTTP duration/count metrics," but does not name exact signals such as route-level server spans and HTTP server request duration/count metrics with status/error attributes. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-6 FAIL | Top-level sections include `Executive Summary`, `Flow`, `Audit Evidence`, `Routes`, `Signal Flow`, `Current Instrumentation`, `GenAI Readiness`, `Gaps`, `Verification Plan`, `Anti-Patterns`, and `Recommendation`, rather than only `Current Instrumentation`, `GenAI Readiness`, `Gaps`, and `Verification Plan`. |
| with_skill | python/ai-assistant-demo | with_skill | genai-readiness | rubric:rubric-6 FAIL | Additional top-level headings include Executive Summary, Flow, Audit Evidence, Routes, Signal Flow, Anti-Patterns, and Recommendation. |
| with_skill | python/fastapi-celery | with_skill | direct | rubric:rubric-2 FAIL | The audit evidence references `pyproject.toml`, `app.py`, `worker.py`, `docker-compose.yml`, and `Makefile`; no `Dockerfile` reference appears in `last_message.md`. |
| with_skill | python/fastapi-celery | with_skill | direct | rubric:rubric-3 FAIL | The response says FastAPI routes lack server spans and Celery task paths lack telemetry, but contains no explicit `ASGI` or HTTP client instrumentation finding. |
| with_skill | python/fastapi-celery | with_skill | readiness-review | rubric:rubric-3 FAIL | Gaps include `API request telemetry`, `Queue publish and context propagation`, and `Worker task telemetry`; no explicit `ASGI` or `HTTP client` instrumentation finding appears. |
| with_skill | python/fastapi-celery | with_skill | readiness-review | rubric:rubric-4 FAIL | It says API starts `uvicorn app:app`, worker starts `celery -A worker worker`, and notes missing service names/OTLP config, but does not tie these concretely to docker-compose environment and command wiring. |
| with_skill | python/flask-basic | with_skill | direct | rubric:rubric-3 FAIL | Final response says no SDK/provider setup and no Flask instrumentation/exporters, while pyproject.toml only declares Flask. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
