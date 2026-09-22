# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260921T234133309675Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 83% (15/18), avg score 85 | 3.6M | 17.4m | - | - | - |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | 2 | 83% (10/12), avg score 86 | 4.2M | 20.9m | - | - | - |
| with_skill | go/kvstore/qual/audit | go/kvstore | 2 | 100% (12/12), avg score 92 | 4.8M | 24.5m | - | - | - |
| with_skill | java/kafka-batch-consumer/qual/audit | java/kafka-batch-consumer | 2 | 83% (10/12), avg score 90 | 3.8M | 19.8m | - | - | - |
| with_skill | java/kafka-listener-container/qual/audit | java/kafka-listener-container | 2 | 85% (11/13), avg score 90 | 4.0M | 20.2m | - | - | - |
| with_skill | java/kafka-producer-consumer/qual/audit | java/kafka-producer-consumer | 2 | 85% (11/13), avg score 89 | 4.3M | 20.6m | - | - | - |
| with_skill | java/kafka-streams/qual/audit | java/kafka-streams | 2 | 93% (13/14), avg score 92 | 3.9M | 19.5m | - | - | - |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | 2 | 83% (10/12), avg score 87 | 4.4M | 19.7m | - | - | - |
| with_skill | node/express-basic/qual/audit | node/express-basic | 2 | 100% (12/12), avg score 96 | 5.7M | 21.2m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | 2 | 100% (12/12), avg score 95 | 3.8M | 24.9m | - | - | - |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/audit | python/assistant-v3-framework-bridge-demo | 1 | 83% (5/6), avg score 88 | 3.0M | 11.3m | - | - | - |
| with_skill | python/checkout-red-demo/qual/audit | python/checkout-red-demo | 1 | 80% (4/5), avg score 88 | 1.5M | 10.0m | - | - | - |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | 2 | 80% (8/10), avg score 86 | 4.6M | 20.8m | - | - | - |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | 2 | 92% (11/12), avg score 94 | 3.8M | 19.2m | - | - | - |
| with_skill | python/mcp-ai-tool-demo/qual/audit | python/mcp-ai-tool-demo | 2 | 100% (12/12), avg score 96 | 4.8M | 27.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 3586021 | 3379456 | 0 | 39229 | 13768 | unknown | 3625250 |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | with_skill | codex | cumulative | measured | 2/2 recognized | 4102473 | 3848064 | 0 | 55050 | 23205 | unknown | 4157523 |
| with_skill | go/kvstore/qual/audit | go/kvstore | with_skill | codex | cumulative | measured | 2/2 recognized | 4728611 | 4483712 | 0 | 54774 | 19065 | unknown | 4783385 |
| with_skill | java/kafka-batch-consumer/qual/audit | java/kafka-batch-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 3752725 | 3516928 | 0 | 47930 | 21442 | unknown | 3800655 |
| with_skill | java/kafka-listener-container/qual/audit | java/kafka-listener-container | with_skill | codex | cumulative | measured | 2/2 recognized | 3904985 | 3538048 | 0 | 46818 | 17734 | unknown | 3951803 |
| with_skill | java/kafka-producer-consumer/qual/audit | java/kafka-producer-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 4232882 | 3974912 | 0 | 46930 | 20714 | unknown | 4279812 |
| with_skill | java/kafka-streams/qual/audit | java/kafka-streams | with_skill | codex | cumulative | measured | 2/2 recognized | 3820096 | 3584000 | 0 | 46461 | 22765 | unknown | 3866557 |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 4354494 | 4119808 | 0 | 50316 | 20617 | unknown | 4404810 |
| with_skill | node/express-basic/qual/audit | node/express-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 5636824 | 5368576 | 0 | 53518 | 21914 | unknown | 5690342 |
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 3714855 | 3464960 | 0 | 59276 | 20569 | unknown | 3774131 |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/audit | python/assistant-v3-framework-bridge-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3005017 | 2853120 | 0 | 26282 | 10421 | unknown | 3031299 |
| with_skill | python/checkout-red-demo/qual/audit | python/checkout-red-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1504342 | 1405440 | 0 | 24316 | 10822 | unknown | 1528658 |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | with_skill | codex | cumulative | measured | 2/2 recognized | 4573005 | 4335232 | 0 | 49942 | 18744 | unknown | 4622947 |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 3737691 | 3527296 | 0 | 42211 | 16717 | unknown | 3779902 |
| with_skill | python/mcp-ai-tool-demo/qual/audit | python/mcp-ai-tool-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 4727068 | 4383232 | 0 | 63793 | 22358 | unknown | 4790861 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 482398 | 367232 | 0 | 12750 | 6988 | unknown | 495148 |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | with_skill | codex | cumulative | measured | 2/2 recognized | 375053 | 274304 | 0 | 8463 | 3455 | unknown | 383516 |
| with_skill | go/kvstore/qual/audit | go/kvstore | with_skill | codex | cumulative | measured | 2/2 recognized | 673906 | 567808 | 0 | 13635 | 8029 | unknown | 687541 |
| with_skill | java/kafka-batch-consumer/qual/audit | java/kafka-batch-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 379295 | 299264 | 0 | 11432 | 6687 | unknown | 390727 |
| with_skill | java/kafka-listener-container/qual/audit | java/kafka-listener-container | with_skill | codex | cumulative | measured | 2/2 recognized | 675347 | 559616 | 0 | 12421 | 6903 | unknown | 687768 |
| with_skill | java/kafka-producer-consumer/qual/audit | java/kafka-producer-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 294557 | 225792 | 0 | 10806 | 6060 | unknown | 305363 |
| with_skill | java/kafka-streams/qual/audit | java/kafka-streams | with_skill | codex | cumulative | measured | 2/2 recognized | 613549 | 505984 | 0 | 10810 | 5191 | unknown | 624359 |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 232174 | 170752 | 0 | 7395 | 3408 | unknown | 239569 |
| with_skill | node/express-basic/qual/audit | node/express-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 179183 | 120832 | 0 | 8079 | 4603 | unknown | 187262 |
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 1418616 | 1230464 | 0 | 15803 | 7696 | unknown | 1434419 |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/audit | python/assistant-v3-framework-bridge-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 268452 | 195200 | 0 | 5902 | 2835 | unknown | 274354 |
| with_skill | python/checkout-red-demo/qual/audit | python/checkout-red-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 267717 | 209536 | 0 | 6167 | 3643 | unknown | 273884 |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | with_skill | codex | cumulative | measured | 2/2 recognized | 375248 | 282880 | 0 | 10729 | 5722 | unknown | 385977 |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 866884 | 738944 | 0 | 11980 | 5693 | unknown | 878864 |
| with_skill | python/mcp-ai-tool-demo/qual/audit | python/mcp-ai-tool-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 1234391 | 1081472 | 0 | 15487 | 7501 | unknown | 1249878 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-9 FAIL | last_message.md contains 'Review report: [otel.html](/private/.../service/.observe/otel.html)' rather than 'Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)'. |
| with_skill | go/chi-basic | with_skill | readiness-review | rubric:rubric-5 FAIL | Search of otel-audit.json and otel.html found no occurrences of otelhttp or otelchi. |
| with_skill | go/chi-basic | with_skill | readiness-review | rubric:rubric-9 FAIL | last_message.md contains 'Review report: [otel.html](/private/.../service/.observe/otel.html)' instead of 'Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)'. |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-6 FAIL | service/.observe/otel-audit.json has http.tasks.reserve.conflict for "already done" only; no occurrence of "already reserved" was found in the audit artifacts. |
| with_skill | go/chi-partial | with_skill | readiness-review | rubric:rubric-6 FAIL | Verification scenario http.tasks.reserve.conflict says 'already done or reserved' and asks for a bounded reservation outcome, but the metrics finding only requires route/method/status attributes and does not name the missing conflict-cause dimension. |
| with_skill | java/kafka-batch-consumer | with_skill | readiness-review | rubric:rubric-1 FAIL | service/.observe/otel-audit.json:31 names BatchConsumerApplication and BatchConsumerConfig. Source truth: service/src/main/java/com/example/kafkabatch/BatchConsumerConfig.java:10-27 reads environment values and builds Kafka consumer properties. |
| with_skill | java/kafka-batch-consumer | with_skill | readiness-review | rubric:rubric-5 FAIL | service/.observe/otel-audit.json:84-92 and 179-182 cover Kafka spans and batch metrics; service/.observe/otel-audit.json:130 mentions partition offset only as a value not to add as a metric dimension. No consumer lag gap is present. |
| with_skill | java/kafka-listener-container | with_skill | readiness-review | rubric:rubric-3 FAIL | The report cites AlertService.process at AlertService.java:13-17 and mentions CRITICAL alert processing, but it never explicitly calls out pagingRequired or paging-required alert business logic. |
| with_skill | java/kafka-listener-container | with_skill | readiness-review | rubric:rubric-5 FAIL | The report calls out missing Kafka listener spans, malformed/null payload visibility, processed/dropped counts, listener errors, and consumer lag; expected metrics include alerts.listener.messages and kafka.consumer.records.lag, but no explicit critical alert count metric or offset-position visibility. |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-1 FAIL | otel-audit.json cites ProducerConsumerApplication.java in the entry point and scenarios; searches found no KafkaClientConfig mention in otel-audit.json, otel.html, or last_message.md. |
| with_skill | java/kafka-producer-consumer | with_skill | direct | rubric:rubric-5 FAIL | OTEL-001 covers Kafka consume/send spans; OTEL-002 covers produced/dropped/failure counts, malformed/null payloads, and send failures. Searches for lag and offset in the JSON/HTML found no consumer lag or offset visibility gap. |
| with_skill | java/kafka-streams | with_skill | direct | rubric:rubric-4 FAIL | OTEL-001 expects orders receive, orders.enriched send, and orders.fraud-alerts send spans; OTEL-002 covers dropped malformed/null records. No explicit finding for record-processing latency or stream/error telemetry beyond baseline outage localization. |
| with_skill | java/springboot-basic | with_skill | direct | rubric:rubric-5 FAIL | Required fixes say "Configure one Java OpenTelemetry bootstrap path" and "Instrument Spring MVC/Tomcat," but do not explicitly choose the OpenTelemetry Java agent as the primary recommendation. |
| with_skill | java/springboot-basic | with_skill | readiness-review | rubric:rubric-5 FAIL | OTEL-001 required_fix says to install an official OpenTelemetry Java bootstrap; constraints say prefer the official OpenTelemetry Java agent or official OTel Java SDK instrumentation. |
| with_skill | python/assistant-v3-framework-bridge-demo | with_skill | framework-bridge | rubric:rubric-6 FAIL | HTML shows Audit Evidence with `GenAI ownership` = `Yes` and a Verification plan table. `genai_readiness` exists only inside the embedded DATA script; `rg` found no visible `GenAI Readiness` table or heading in the rendered HTML markup. |
| with_skill | python/checkout-red-demo | with_skill | direct | rubric:rubric-5 FAIL | service/.observe/otel.html shows Findings · 4, Current baseline with 0 span entries and 0 metric entries, and technical appendix tables; rg found no top-level Gaps or readiness table, though the embedded JSON contains incident_readiness and expected telemetry. |
| with_skill | python/fastapi-celery | with_skill | direct | rubric:rubric-3 FAIL | Findings include `FastAPI routes have no route-level telemetry` and `Celery enqueue and task execution are untraced`. Searches found no `ASGI` or outbound HTTP-client instrumentation discussion in the audit output. |
| with_skill | python/fastapi-celery | with_skill | direct | rubric:rubric-4 FAIL | `docker-compose.yml` only sets `REDIS_URL`; the audit cites compose in OTEL-001 and expected OTEL env vars, but does not explicitly call out missing compose wiring such as OTel command wrapping, `OTEL_SERVICE_NAME`, resource attributes, or OTLP endpoint variables for both API and worker. |
| with_skill | python/flask-basic | with_skill | direct | rubric:rubric-4 FAIL | The audit mentions `Flask auto-instrumentation` and `FlaskInstrumentor.instrument_app(app)`, but searches of the JSON/HTML show no `opentelemetry-instrumentation-flask` string. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
