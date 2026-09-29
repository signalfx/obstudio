# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20260928T200954020233Z-post-rebase |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | 2 | 83% (15/18), avg score 84 | 4.0M | 21.5m | - | - | - |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | 2 | 83% (10/12), avg score 86 | 5.1M | 20.2m | - | - | - |
| with_skill | go/kvstore/qual/audit | go/kvstore | 2 | 83% (10/12), avg score 88 | 5.1M | 22.6m | - | - | - |
| with_skill | java/kafka-batch-consumer/qual/audit | java/kafka-batch-consumer | 2 | 75% (9/12), avg score 87 | 4.4M | 20.5m | - | - | - |
| with_skill | java/kafka-listener-container/qual/audit | java/kafka-listener-container | 2 | 92% (12/13), avg score 89 | 4.2M | 20.9m | - | - | - |
| with_skill | java/kafka-producer-consumer/qual/audit | java/kafka-producer-consumer | 2 | 92% (11/12), avg score 91 | 3.6M | 18.0m | - | - | - |
| with_skill | java/kafka-streams/qual/audit | java/kafka-streams | 2 | 100% (14/14), avg score 97 | 3.7M | 19.5m | - | - | - |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | 2 | 83% (10/12), avg score 86 | 4.6M | 20.9m | - | - | - |
| with_skill | node/express-basic/qual/audit | node/express-basic | 2 | 100% (12/12), avg score 96 | 3.7M | 18.2m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | 2 | 100% (12/12), avg score 93 | 5.7M | 28.3m | - | - | - |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/audit | python/assistant-v3-framework-bridge-demo | 1 | 67% (4/6), avg score 84 | 2.7M | 13.4m | - | - | - |
| with_skill | python/checkout-red-demo/qual/audit | python/checkout-red-demo | 1 | 100% (5/5), avg score 94 | 1.8M | 11.6m | - | - | - |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | 2 | 90% (9/10), avg score 88 | 4.1M | 23.9m | - | - | - |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | 2 | 92% (11/12), avg score 90 | 3.2M | 18.1m | - | - | - |
| with_skill | python/mcp-ai-tool-demo/qual/audit | python/mcp-ai-tool-demo | 2 | 100% (12/12), avg score 94 | 4.6M | 25.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 3939064 | 3713792 | 0 | 49334 | 20125 | unknown | 3988398 |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | with_skill | codex | cumulative | measured | 2/2 recognized | 5016626 | 4686720 | 0 | 52702 | 21342 | unknown | 5069328 |
| with_skill | go/kvstore/qual/audit | go/kvstore | with_skill | codex | cumulative | measured | 2/2 recognized | 5007603 | 4735488 | 0 | 55172 | 17647 | unknown | 5062775 |
| with_skill | java/kafka-batch-consumer/qual/audit | java/kafka-batch-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 4385915 | 4158720 | 0 | 47144 | 22178 | unknown | 4433059 |
| with_skill | java/kafka-listener-container/qual/audit | java/kafka-listener-container | with_skill | codex | cumulative | measured | 2/2 recognized | 4128201 | 3909504 | 0 | 49731 | 18045 | unknown | 4177932 |
| with_skill | java/kafka-producer-consumer/qual/audit | java/kafka-producer-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 3557139 | 3329152 | 0 | 42452 | 18254 | unknown | 3599591 |
| with_skill | java/kafka-streams/qual/audit | java/kafka-streams | with_skill | codex | cumulative | measured | 2/2 recognized | 3694721 | 3449344 | 0 | 49902 | 19991 | unknown | 3744623 |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 4528632 | 4286336 | 0 | 50475 | 20386 | unknown | 4579107 |
| with_skill | node/express-basic/qual/audit | node/express-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 3662537 | 3427456 | 0 | 46561 | 20320 | unknown | 3709098 |
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 5667883 | 5348224 | 0 | 66261 | 22199 | unknown | 5734144 |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/audit | python/assistant-v3-framework-bridge-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2638814 | 2434048 | 0 | 29377 | 12138 | unknown | 2668191 |
| with_skill | python/checkout-red-demo/qual/audit | python/checkout-red-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1795024 | 1678208 | 0 | 28408 | 13061 | unknown | 1823432 |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | with_skill | codex | cumulative | measured | 2/2 recognized | 4028894 | 3779200 | 0 | 62336 | 21975 | unknown | 4091230 |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 3191993 | 2992640 | 0 | 41941 | 16092 | unknown | 3233934 |
| with_skill | python/mcp-ai-tool-demo/qual/audit | python/mcp-ai-tool-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 4497854 | 4164352 | 0 | 59753 | 21170 | unknown | 4557607 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/audit | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 1121053 | 928896 | 0 | 14395 | 7396 | unknown | 1135448 |
| with_skill | go/chi-partial/qual/audit | go/chi-partial | with_skill | codex | cumulative | measured | 2/2 recognized | 352807 | 277376 | 0 | 7281 | 3330 | unknown | 360088 |
| with_skill | go/kvstore/qual/audit | go/kvstore | with_skill | codex | cumulative | measured | 2/2 recognized | 429089 | 368000 | 0 | 12247 | 6961 | unknown | 441336 |
| with_skill | java/kafka-batch-consumer/qual/audit | java/kafka-batch-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 639425 | 529536 | 0 | 12317 | 5982 | unknown | 651742 |
| with_skill | java/kafka-listener-container/qual/audit | java/kafka-listener-container | with_skill | codex | cumulative | measured | 2/2 recognized | 492379 | 397952 | 0 | 12592 | 6981 | unknown | 504971 |
| with_skill | java/kafka-producer-consumer/qual/audit | java/kafka-producer-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 502188 | 413696 | 0 | 11033 | 5208 | unknown | 513221 |
| with_skill | java/kafka-streams/qual/audit | java/kafka-streams | with_skill | codex | cumulative | measured | 2/2 recognized | 295274 | 217856 | 0 | 8273 | 3591 | unknown | 303547 |
| with_skill | java/springboot-basic/qual/audit | java/springboot-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 539426 | 439680 | 0 | 10707 | 4770 | unknown | 550133 |
| with_skill | node/express-basic/qual/audit | node/express-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 312808 | 218880 | 0 | 7494 | 3313 | unknown | 320302 |
| with_skill | python/ai-assistant-demo/qual/audit | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 1659946 | 1484416 | 0 | 18249 | 9426 | unknown | 1678195 |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/audit | python/assistant-v3-framework-bridge-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1309269 | 1183872 | 0 | 9550 | 5131 | unknown | 1318819 |
| with_skill | python/checkout-red-demo/qual/audit | python/checkout-red-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 396641 | 325376 | 0 | 7370 | 4330 | unknown | 404011 |
| with_skill | python/fastapi-celery/qual/audit | python/fastapi-celery | with_skill | codex | cumulative | measured | 2/2 recognized | 325017 | 230912 | 0 | 10260 | 5128 | unknown | 335277 |
| with_skill | python/flask-basic/qual/audit | python/flask-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 663592 | 553088 | 0 | 12010 | 6240 | unknown | 675602 |
| with_skill | python/mcp-ai-tool-demo/qual/audit | python/mcp-ai-tool-demo | with_skill | codex | cumulative | measured | 2/2 recognized | 1755159 | 1486720 | 0 | 16625 | 7507 | unknown | 1771784 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-9 FAIL | `last_message.md` contains: `Blocked: the audit JSON and HTML were written, but this sandbox denies loopback socket binding...`; no `Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)` line was produced. |
| with_skill | go/chi-basic | with_skill | readiness-review | rubric:rubric-8 FAIL | otel.html first screen shows Executive Summary and Findings. Audit Evidence contains row "GenAI ownership" -> "No". No separate Incident/GenAI readiness sections were found. |
| with_skill | go/chi-basic | with_skill | readiness-review | rubric:rubric-9 FAIL | last_message.md: "Review report: [otel.html](/private/var/.../service/.observe/otel.html)". trace.jsonl item_47: "FAIL: could not start the loopback audit report server". |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-6 FAIL | The audit only says reserve conflict is `already done or reserved` and recommends a bounded conflict/reason family; it does not make the specific metric-gap observation required by the rubric. |
| with_skill | go/chi-partial | with_skill | readiness-review | rubric:rubric-6 FAIL | Search of otel-audit.json shows 'already done' only in http.tasks.reserve.conflict; no 'already reserved' occurrence, and no explicit discussion of distinguishing both 409 causes on http.server.request.duration. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-2 FAIL | routes contains PUT/GET/DELETE /kv/{key} and GET /search; verification later mentions trigger GET /search?word=bar. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-4 FAIL | OTEL-002 requires kvstore.persist and kvstore.index.update spans; OTEL-003 recommends kvstore.evictions and queue/inflight metrics. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-1 FAIL | otel-audit.json evidence says BatchConsumerApplication creates KafkaConsumer and runs PaymentBatchConsumer; searching the audit artifacts finds no BatchConsumerConfig reference. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-5 FAIL | OTEL-002 lists batch size, duration, failed records, high-value records, and commit outcome; expected telemetry includes payments receive spans and batch valid/failed attributes. Searches for lag find no audit references, and offset appears only in privacy/cardinality constraints. |
| with_skill | java/kafka-batch-consumer | with_skill | readiness-review | rubric:rubric-5 FAIL | Findings include Kafka consumer spans, batch duration, batch records with valid/failed counts, high-value counts, and commit error metrics; rg found no lag visibility requirement in the audit artifacts. |
| with_skill | java/kafka-listener-container | with_skill | direct | rubric:rubric-5 FAIL | It calls out missing Kafka listener spans, malformed payload visibility, processed message counts, and listener error visibility, but rg found no audit mentions of null payload telemetry, lag, offset, or critical alert count metrics. |
| with_skill | java/kafka-producer-consumer | with_skill | readiness-review | rubric:rubric-6 FAIL | OTEL-001 recommends OpenTelemetry Java agent bootstrap first; however OTEL-002 has priority=required and required_fix asks to add service-owned metrics for order/shipment outcomes. |
| with_skill | java/springboot-basic | with_skill | direct | rubric:rubric-5 FAIL | `OTEL-001` recommends a generic single startup path; `OTEL-002` says to enable Spring MVC/servlet/Tomcat instrumentation, without explicitly naming the OpenTelemetry Java agent as the primary path. |
| with_skill | java/springboot-basic | with_skill | readiness-review | rubric:rubric-5 FAIL | The recommendation only says to use the HTML report and run `$otel-instrument`; findings say to bootstrap OpenTelemetry or enable Spring MVC/Servlet instrumentation without naming the Java agent as the primary path. |
| with_skill | python/assistant-v3-framework-bridge-demo | with_skill | framework-bridge | rubric:rubric-5 FAIL | OTEL-003 treats POST /v2/assistant/sessions as an HTTP server span and verification expects HTTP route -> workflow -> agent -> chat, while OTEL-002 keeps assistant_v3_turn as the workflow. However the audit does not explicitly state that POST /v2/assistant/sessions may remain the HTTP root span but must not become t... |
| with_skill | python/assistant-v3-framework-bridge-demo | with_skill | framework-bridge | rubric:rubric-6 FAIL | Bundled validator reports PASS for service/.observe/otel-audit.json. HTML contains Audit Evidence with GenAI ownership=Yes and a source-derived Verification plan, but rg finds no visible 'GenAI ownership detected' phrase and no visible 'GenAI Readiness' table; genai_readiness appears only in embedded JSON. last_mess... |
| with_skill | python/fastapi-celery | with_skill | direct | rubric:rubric-3 FAIL | OTEL-002 covers `opentelemetry-instrumentation-fastapi`; OTEL-003 covers Celery producer/worker instrumentation. Searches of the audit found no `ASGI`, `httpx`, `requests`, or `HTTP client` coverage. |
| with_skill | python/flask-basic | with_skill | direct | rubric:rubric-4 FAIL | OTEL-002 mentions no Flask auto-instrumentation and no FlaskInstrumentor, but searches of otel-audit.json and otel.html show no opentelemetry-instrumentation-flask string. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
