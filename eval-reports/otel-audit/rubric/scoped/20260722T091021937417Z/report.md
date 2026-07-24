# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260722T091021937417Z |
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
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 100% (17/17), avg score 97 | 4.6M | 27.3m | - | - | - |
| with_skill | go/chi-basic/qual/benchmark-audit | go/chi-basic | 1 | 100% (5/5), avg score 96 | 2.1M | 11.5m | - | - | - |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | 2 | 79% (11/14), avg score 82 | 1.0M | 10.1m | - | - | - |
| with_skill | go/kvstore/qual/audit | go/kvstore | 2 | 80% (8/10), avg score 87 | 1.1M | 9.6m | - | - | - |
| with_skill | java/kafka-batch-consumer/qual/audit | java/kafka-batch-consumer | 2 | 67% (8/12), avg score 79 | 1.1M | 9.8m | - | - | - |
| with_skill | java/kafka-listener-container/qual/audit | java/kafka-listener-container | 2 | 58% (7/12), avg score 77 | 1.0M | 8.6m | - | - | - |
| with_skill | java/kafka-producer-consumer/qual/audit | java/kafka-producer-consumer | 2 | 75% (9/12), avg score 82 | 1.4M | 17.8m | - | - | - |
| with_skill | java/kafka-streams/qual/audit | java/kafka-streams | 2 | 93% (13/14), avg score 89 | 1.3M | 17.0m | - | - | - |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | 2 | 90% (9/10), avg score 88 | 1.4M | 11.0m | - | - | - |
| with_skill | node/express-basic/qual/audit | node/express-basic | 2 | 100% (10/10), avg score 97 | 648.7K | 6.7m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | 2 | 100% (12/12), avg score 97 | 6.2M | 28.3m | - | - | - |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/audit | python/assistant-v3-framework-bridge-demo | 1 | 83% (5/6), avg score 88 | 1.5M | 8.6m | - | - | - |
| with_skill | python/checkout-red-demo/qual/audit | python/checkout-red-demo | 1 | 100% (5/5), avg score 97 | 1.3M | 7.7m | - | - | - |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | 2 | 70% (7/10), avg score 81 | 831.4K | 7.3m | - | - | - |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | 2 | 100% (10/10), avg score 100 | 797.3K | 6.4m | - | - | - |
| with_skill | python/mcp-ai-tool-demo/qual/audit | python/mcp-ai-tool-demo | 2 | 83% (10/12), avg score 88 | 5.5M | 25.6m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-6 FAIL | The final response lists the route but has no note about `already done` vs `already reserved` or metric attributes. |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-7 FAIL | Recommendations are phrased as gaps such as using env config and adding providers/resources, without a concrete default fix-all action plan. |
| with_skill | go/chi-partial | with_skill | readiness-review | rubric:rubric-6 FAIL | service/main.go returns 409 for `already done` and `already reserved`, but last_message.md does not mention this distinction or the metric-attribute gap. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-3 FAIL | Current Instrumentation says no OTel spans, metrics, SDK providers, OTLP exporters, resource config, propagator, or OTel log pipeline; no dependency statement is present. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-4 FAIL | `OTEL-004` covers async file writes, index goroutine, `indexCh`, startup reload, and LRU eviction, under `Required Gaps`. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-1 FAIL | Final response says: "Entrypoint creates the Kafka consumer and runs forever" with a BatchConsumerApplication.java link. It does not name BatchConsumerConfig.java. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-5 FAIL | Final gaps mention Kafka consume activity, consumer lag/backlog, batch duration, processed records, failed records, high-value payments, and commit failures. Valid record counts and offset visibility are not explicitly listed as gaps. |
| with_skill | java/kafka-batch-consumer | with_skill | readiness-review | rubric:rubric-1 FAIL | last_message.md says `main()` creates a `KafkaConsumer` and later mentions `mvn exec:java`, but has no `BatchConsumerApplication.java` or `BatchConsumerConfig.java` references. |
| with_skill | java/kafka-batch-consumer | with_skill | readiness-review | rubric:rubric-5 FAIL | last_message.md lists `Batch size, duration, valid/failed record count, parse failures, and commit outcome` plus `consumer lag, or backlog signal`, but not missing high-value-payment counts or offset visibility. |
| with_skill | java/kafka-listener-container | with_skill | direct | rubric:rubric-2 FAIL | Final response references AlertListener.java, @KafkaListener, and onAlert, but omits the concrete topic/group values. |
| with_skill | java/kafka-listener-container | with_skill | direct | rubric:rubric-3 FAIL | Final response only refers generically to service processing and service::process. |
| with_skill | java/kafka-listener-container | with_skill | direct | rubric:rubric-5 FAIL | Final response mentions missing listener spans, malformed/null payload visibility, processed count, listener error attribution, and Kafka lag/backpressure. |
| with_skill | java/kafka-listener-container | with_skill | readiness-review | rubric:rubric-3 FAIL | Final response discusses service::process and alert processing outcomes, but never names AlertService.java or explains the CRITICAL severity to pagingRequired business logic. |
| with_skill | java/kafka-listener-container | with_skill | readiness-review | rubric:rubric-5 FAIL | Final response calls out missing Kafka consumer/listener spans, malformed payload drop visibility, processed/dropped/failed counts, and lag/backpressure. It does not explicitly call out null payload visibility or critical alert counts. |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-1 FAIL | last_message.md cites ProducerConsumerApplication.java in OTEL-002 and KafkaClientConfig.java in OTEL-003, but lacks explicit role labels. |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-5 FAIL | OTEL-002 covers producer/consumer spans; OTEL-003 covers lag; OTEL-004 covers valid/malformed/null order outcomes; OTEL-005 focuses on malformed JSON and serialization failures, not producer send callback/error visibility. |
| with_skill | java/kafka-producer-consumer | with_skill | readiness-review | rubric:rubric-3 FAIL | Final response discusses `config.ordersTopic()`/`config.shipmentsTopic()` behavior only indirectly and mentions shipment commands, but does not state `orders` is consumed and `shipments` is produced. |
| with_skill | java/kafka-streams | with_skill | direct | rubric:rubric-1 FAIL | last_message.md: Entrypoint: KafkaStreamsApplication.java. No mention of StreamProcessingModule.java or its @Provides KafkaStreams method. |
| with_skill | java/springboot-basic | with_skill | direct | rubric:rubric-5 FAIL | last_message.md says: "Add a startup surface for the OpenTelemetry Java agent or Spring Boot starter..." |
| with_skill | python/assistant-v3-framework-bridge-demo | with_skill | framework-bridge | rubric:rubric-5 FAIL | service/.observe/otel.md: HTTP scenario says the POST server span should be parent or trace ancestor for `invoke_workflow assistant_v3_turn`; no explicit `must not become the GenAI workflow card` statement appears. |
| with_skill | python/fastapi-celery | with_skill | direct | rubric:rubric-3 FAIL | Gaps include opentelemetry-instrumentation-fastapi and opentelemetry-instrumentation-celery; there is no ASGI-specific gap. |
| with_skill | python/fastapi-celery | with_skill | readiness-review | rubric:rubric-2 FAIL | It cites pyproject.toml, docker-compose.yml, Dockerfile, and app.py; it lists worker task names but does not cite or name worker.py directly. |
| with_skill | python/fastapi-celery | with_skill | readiness-review | rubric:rubric-3 FAIL | It recommends opentelemetry-instrumentation-fastapi, opentelemetry-instrumentation-celery, and opentelemetry-instrumentation-redis, but there is no mention of ASGI or HTTP client instrumentation. |
| with_skill | python/mcp-ai-tool-demo | with_skill | direct | rubric:rubric-3 FAIL | service/.observe/otel.md:107-112, 118-124, and 156-173 cover most paths. Text search found no auth/authorization/401/backpressure/send-write gap in service/.observe/otel.md or service/.observe/otel-audit.json. |
| with_skill | python/mcp-ai-tool-demo | with_skill | mcp-readiness | rubric:rubric-3 FAIL | The report covers JSON-RPC method outcome, sessions, active streams, close_reason, stream duration, send/write failure, tool execution, and provider/model calls, but rg found no auth/authorization/401/authentication coverage in otel.md or otel-audit.json despite app.py having _require_auth. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
