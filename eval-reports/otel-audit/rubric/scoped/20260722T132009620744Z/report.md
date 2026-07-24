# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260722T132009620744Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |
| Report scope | stale |
| Selected prompts | 29 |
| Expected prompts | 29 |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 94% (17/18), avg score 93 | 4.0M | 19.8m | - | - | - |
| with_skill | go/chi-basic/qual/benchmark-audit | go/chi-basic | 1 | 100% (5/5), avg score 97 | 1.8M | 10.7m | - | - | - |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | 2 | 79% (11/14), avg score 82 | 2.3M | 13.7m | - | - | - |
| with_skill | go/kvstore/qual/audit | go/kvstore | 2 | 90% (9/10), avg score 86 | 1.2M | 9.4m | - | - | - |
| with_skill | java/kafka-batch-consumer/qual/audit | java/kafka-batch-consumer | 2 | 83% (10/12), avg score 86 | 1.1M | 9.3m | - | - | - |
| with_skill | java/kafka-listener-container/qual/audit | java/kafka-listener-container | 2 | 58% (7/12), avg score 79 | 913.0K | 9.6m | - | - | - |
| with_skill | java/kafka-producer-consumer/qual/audit | java/kafka-producer-consumer | 2 | 67% (8/12), avg score 80 | 974.0K | 9.0m | - | - | - |
| with_skill | java/kafka-streams/qual/audit | java/kafka-streams | 2 | 86% (12/14), avg score 85 | 1.2M | 9.7m | - | - | - |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | 2 | 80% (8/10), avg score 86 | 857.2K | 8.9m | - | - | - |
| with_skill | node/express-basic/qual/audit | node/express-basic | 2 | 100% (10/10), avg score 98 | 1.0M | 10.3m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | 2 | 100% (12/12), avg score 96 | 6.7M | 31.8m | - | - | - |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/audit | python/assistant-v3-framework-bridge-demo | 1 | 100% (6/6), avg score 96 | 2.9M | 11.1m | - | - | - |
| with_skill | python/checkout-red-demo/qual/audit | python/checkout-red-demo | 1 | 100% (5/5), avg score 96 | 1.1M | 7.5m | - | - | - |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | 2 | 50% (5/10), avg score 73 | 786.8K | 8.2m | - | - | - |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | 2 | 100% (11/11), avg score 96 | 948.4K | 6.8m | - | - | - |
| with_skill | python/mcp-ai-tool-demo/qual/audit | python/mcp-ai-tool-demo | 2 | 92% (11/12), avg score 92 | 6.1M | 26.4m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | readiness-review | rubric:rubric-4 FAIL | OTEL-002 expected telemetry includes HTTP server span and `http.server.request.duration` with status code; OTEL-001 covers OTLP exporters. Searches found no explicit `request rate` phrase in generated artifacts, only related wording such as HTTP metrics and throughput. |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-6 FAIL | Final response recommended gap: 'Add low-cardinality app outcome/error attributes or metrics for invalid body, not found, and conflict branches.' |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-7 FAIL | Final response: 'Recommendation: run $otel-instrument next with the required findings selected, then $otel-verify for runtime proof.' |
| with_skill | go/chi-partial | with_skill | readiness-review | rubric:rubric-6 FAIL | service/main.go lines 119-125 return 409 for both "already done" and "already reserved"; last_message.md only lists the route on line 7 and does not discuss this metric attribute gap. |
| with_skill | go/kvstore | with_skill | readiness-review | rubric:rubric-4 FAIL | Mentions "filesystem persistence", "index updates... background goroutine", and "LRU capacity", but not LRU eviction instrumentation. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-5 FAIL | Final response calls out missing batch workflow span, batch size, failed/high-value/duration signals, commit failure, and consumer lag/backlog, but does not explicitly mention valid record counts or offset visibility. |
| with_skill | java/kafka-batch-consumer | with_skill | readiness-review | rubric:rubric-3 FAIL | "The service computes total, valid, failed, high-value, and total amount in PaymentBatchProcessor.java" |
| with_skill | java/kafka-listener-container | with_skill | direct | rubric:rubric-3 FAIL | Final response mentions adding telemetry around AlertService.process, but does not state that it computes pagingRequired for critical alerts. |
| with_skill | java/kafka-listener-container | with_skill | direct | rubric:rubric-5 FAIL | Final response calls out missing consume/process spans, malformed/null payload drops, processed/dropped/error telemetry, and consumer lag, but not explicit critical alert counts or offset visibility. |
| with_skill | java/kafka-listener-container | with_skill | direct | rubric:rubric-6 FAIL | Final response recommends a Java-agent startup surface or equivalent SDK bootstrap and says to preserve listener-container behavior. |
| with_skill | java/kafka-listener-container | with_skill | readiness-review | rubric:rubric-3 FAIL | Final response discusses parse(payload).ifPresent(service::process) and processing outcomes, but omits AlertService.java and pagingRequired/CRITICAL processing. |
| with_skill | java/kafka-listener-container | with_skill | readiness-review | rubric:rubric-5 FAIL | Final response mentions missing Kafka consumer/listener spans, malformed/drop counts, processed counts, processing errors, lag, rebalance, commit/error signals, and logs, but not critical alert counts or offsets. |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-2 FAIL | Final response cites the endless poll loop in OrderConsumer.java and a publish call in OrderConsumer.java, but never names ShipmentProducer.java. |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-3 FAIL | Final response says valid order consume to shipment publish and shipment commands produced, but omits the topic names orders and shipments. |
| with_skill | java/kafka-producer-consumer | with_skill | readiness-review | rubric:rubric-1 FAIL | Final response says the entrypoint creates KafkaProducer and KafkaConsumer in ProducerConsumerApplication.java; KafkaClientConfig.java is not named. |
| with_skill | java/kafka-producer-consumer | with_skill | readiness-review | rubric:rubric-3 FAIL | Final response discusses consumed records, malformed/null orders, and successful shipment commands, but does not state the orders topic and shipments topic by name. |
| with_skill | java/kafka-streams | with_skill | direct | rubric:rubric-1 FAIL | last_message.md mentions Guice tracer binding but has no KafkaStreamsApplication.java or StreamProcessingModule.java entry-point/module discussion. |
| with_skill | java/kafka-streams | with_skill | direct | rubric:rubric-7 FAIL | "select the Java-agent/bootstrap finding first, then use `$otel-instrument` and `$otel-verify`" |
| with_skill | java/springboot-basic | with_skill | direct | rubric:rubric-4 FAIL | Final response says `HTTP route traces and RED metrics are absent` and recommends `http.server.request.duration` with stable route/status/method attributes. |
| with_skill | java/springboot-basic | with_skill | readiness-review | rubric:rubric-4 FAIL | Final response says there are no route latency/error/request metrics and recommends HTTP duration/status metrics, but does not name expected signals such as `http.server.request.duration` with route, method, and status attributes. |
| with_skill | python/fastapi-celery | with_skill | direct | rubric:rubric-2 FAIL | Mentions pyproject.toml, docker-compose.yml, app.py, and worker.py; no Dockerfile mention. |
| with_skill | python/fastapi-celery | with_skill | direct | rubric:rubric-3 FAIL | Lists opentelemetry-instrumentation-fastapi, opentelemetry-instrumentation-celery, and opentelemetry-instrumentation-redis; no ASGI or HTTP client discussion. |
| with_skill | python/fastapi-celery | with_skill | direct | rubric:rubric-4 FAIL | Says docker-compose.yml has no OTEL_* config; does not discuss Dockerfile CMD or worker command needing opentelemetry-instrument. |
| with_skill | python/fastapi-celery | with_skill | readiness-review | rubric:rubric-2 FAIL | Mentions service/app.py, service/worker.py, service/pyproject.toml, and service/docker-compose.yml, but does not identify service/Dockerfile. |
| with_skill | python/fastapi-celery | with_skill | readiness-review | rubric:rubric-3 FAIL | Gaps include `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-celery`, and `opentelemetry-instrumentation-redis`; no ASGI or HTTP client instrumentation is named. |
| with_skill | python/mcp-ai-tool-demo | with_skill | mcp-readiness | rubric:rubric-3 FAIL | Gaps and GenAI Readiness cover JSON-RPC outcomes, tool execution, provider/model calls, session lifecycle, active streams, close reason, stream duration, and send/write failure. Searches only find Authorization in a valid-auth scenario; there is no explicit auth result, invalid token, or 401 telemetry recommendation. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
