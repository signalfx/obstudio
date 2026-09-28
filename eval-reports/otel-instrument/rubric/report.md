# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260921T234133309675Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | 1 | 67% (2/3), avg score 82 | 5.9M | 14.7m | - | - | - |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 2 | 100% (14/14), avg score 85 | 13.1M | 38.2m | - | - | - |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | 1 | 100% (4/4), avg score 94 | 6.5M | 15.1m | - | - | - |
| with_skill | go/chi-partial/qual/instrument | go/chi-partial | 2 | 67% (8/12), avg score 70 | 7.4M | 25.6m | - | - | - |
| with_skill | go/kvstore/qual/incident-readiness | go/kvstore | 1 | 100% (6/6), avg score 86 | 8.1M | 21.9m | - | - | - |
| with_skill | go/kvstore/qual/instrument | go/kvstore | 2 | 62% (13/21), avg score 48 | 13.0M | 32.6m | - | - | - |
| with_skill | java/kafka-batch-consumer/qual/instrument | java/kafka-batch-consumer | 2 | 90% (9/10), avg score 94 | 3.1M | 18.2m | - | - | - |
| with_skill | java/kafka-listener-container/qual/instrument | java/kafka-listener-container | 2 | 100% (10/10), avg score 94 | 3.9M | 18.9m | - | - | - |
| with_skill | java/kafka-producer-consumer/qual/instrument | java/kafka-producer-consumer | 2 | 100% (10/10), avg score 94 | 2.8M | 19.3m | - | - | - |
| with_skill | java/kafka-streams/qual/incident-readiness | java/kafka-streams | 1 | 100% (6/6), avg score 91 | 3.6M | 12.3m | - | - | - |
| with_skill | java/kafka-streams/qual/instrument | java/kafka-streams | 2 | 100% (12/12), avg score 95 | 3.8M | 19.2m | - | - | - |
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | 2 | 70% (14/20), avg score 63 | 2.9M | 20.4m | - | - | - |
| with_skill | node/express-basic/qual/instrument | node/express-basic | 2 | 56% (10/18), avg score 68 | 4.4M | 28.4m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | 1 | 75% (6/8), avg score 78 | 6.0M | 19.0m | - | - | - |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/instrument | python/assistant-v3-framework-bridge-demo | 1 | 100% (7/7), avg score 90 | 2.8M | 11.6m | - | - | - |
| with_skill | python/checkout-red-demo/qual/instrument | python/checkout-red-demo | 1 | 75% (6/8), avg score 78 | 1.7M | 12.2m | - | - | - |
| with_skill | python/fastapi-celery/qual/incident-readiness | python/fastapi-celery | 1 | 43% (3/7), avg score 40 | 2.7M | 12.0m | - | - | - |
| with_skill | python/fastapi-celery/qual/instrument | python/fastapi-celery | 2 | 100% (10/10), avg score 89 | 4.6M | 24.9m | - | - | - |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | 2 | 75% (15/20), avg score 77 | 3.0M | 22.7m | - | - | - |
| with_skill | python/mcp-ai-tool-demo/qual/instrument | python/mcp-ai-tool-demo | 1 | 57% (4/7), avg score 74 | 3.1M | 14.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 5870291 | 5713664 | 0 | 34346 | 12964 | unknown | 5904637 |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 13027105 | 12554880 | 0 | 68624 | 25734 | unknown | 13095729 |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 6466573 | 6177920 | 0 | 36809 | 13872 | unknown | 6503382 |
| with_skill | go/chi-partial/qual/instrument | go/chi-partial | with_skill | codex | cumulative | measured | 2/2 recognized | 7293347 | 6917760 | 0 | 63654 | 24238 | unknown | 7357001 |
| with_skill | go/kvstore/qual/incident-readiness | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 8064698 | 7830144 | 0 | 50971 | 20255 | unknown | 8115669 |
| with_skill | go/kvstore/qual/instrument | go/kvstore | with_skill | codex | cumulative | measured | 2/2 recognized | 12924986 | 12426496 | 0 | 72150 | 25852 | unknown | 12997136 |
| with_skill | java/kafka-batch-consumer/qual/instrument | java/kafka-batch-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 3035519 | 2820736 | 0 | 42775 | 20431 | unknown | 3078294 |
| with_skill | java/kafka-listener-container/qual/instrument | java/kafka-listener-container | with_skill | codex | cumulative | measured | 2/2 recognized | 3844236 | 3622400 | 0 | 44074 | 22586 | unknown | 3888310 |
| with_skill | java/kafka-producer-consumer/qual/instrument | java/kafka-producer-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 2795954 | 2587776 | 0 | 46628 | 23225 | unknown | 2842582 |
| with_skill | java/kafka-streams/qual/incident-readiness | java/kafka-streams | with_skill | codex | cumulative | measured | 1/1 recognized | 3542782 | 3394304 | 0 | 29700 | 14624 | unknown | 3572482 |
| with_skill | java/kafka-streams/qual/instrument | java/kafka-streams | with_skill | codex | cumulative | measured | 2/2 recognized | 3733401 | 3497728 | 0 | 45274 | 20358 | unknown | 3778675 |
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 2838762 | 2632832 | 0 | 40241 | 18432 | unknown | 2879003 |
| with_skill | node/express-basic/qual/instrument | node/express-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 4347258 | 4105600 | 0 | 55548 | 27091 | unknown | 4402806 |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 5916748 | 5700096 | 0 | 49029 | 19545 | unknown | 5965777 |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/instrument | python/assistant-v3-framework-bridge-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2729336 | 2601216 | 0 | 22629 | 11342 | unknown | 2751965 |
| with_skill | python/checkout-red-demo/qual/instrument | python/checkout-red-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 1679079 | 1570304 | 0 | 27424 | 13720 | unknown | 1706503 |
| with_skill | python/fastapi-celery/qual/incident-readiness | python/fastapi-celery | with_skill | codex | cumulative | measured | 1/1 recognized | 2712896 | 2577536 | 0 | 28361 | 13321 | unknown | 2741257 |
| with_skill | python/fastapi-celery/qual/instrument | python/fastapi-celery | with_skill | codex | cumulative | measured | 2/2 recognized | 4527370 | 4284544 | 0 | 64955 | 31619 | unknown | 4592325 |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 2967946 | 2770176 | 0 | 43805 | 23618 | unknown | 3011751 |
| with_skill | python/mcp-ai-tool-demo/qual/instrument | python/mcp-ai-tool-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3053921 | 2867968 | 0 | 34476 | 13670 | unknown | 3088397 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 388524 | 322560 | 0 | 7269 | 4210 | unknown | 395793 |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 1842203 | 1583360 | 0 | 26043 | 15141 | unknown | 1868246 |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 356068 | 304896 | 0 | 6339 | 2863 | unknown | 362407 |
| with_skill | go/chi-partial/qual/instrument | go/chi-partial | with_skill | codex | cumulative | measured | 2/2 recognized | 255032 | 188544 | 0 | 11345 | 6710 | unknown | 266377 |
| with_skill | go/kvstore/qual/incident-readiness | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 324915 | 254976 | 0 | 10337 | 6694 | unknown | 335252 |
| with_skill | go/kvstore/qual/instrument | go/kvstore | with_skill | codex | cumulative | measured | 2/2 recognized | 691034 | 592768 | 0 | 17118 | 10021 | unknown | 708152 |
| with_skill | java/kafka-batch-consumer/qual/instrument | java/kafka-batch-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 508499 | 403840 | 0 | 11392 | 5697 | unknown | 519891 |
| with_skill | java/kafka-listener-container/qual/instrument | java/kafka-listener-container | with_skill | codex | cumulative | measured | 2/2 recognized | 483810 | 412416 | 0 | 10245 | 5473 | unknown | 494055 |
| with_skill | java/kafka-producer-consumer/qual/instrument | java/kafka-producer-consumer | with_skill | codex | cumulative | measured | 2/2 recognized | 499094 | 384000 | 0 | 11373 | 5129 | unknown | 510467 |
| with_skill | java/kafka-streams/qual/incident-readiness | java/kafka-streams | with_skill | codex | cumulative | measured | 1/1 recognized | 315904 | 262528 | 0 | 6779 | 2780 | unknown | 322683 |
| with_skill | java/kafka-streams/qual/instrument | java/kafka-streams | with_skill | codex | cumulative | measured | 2/2 recognized | 479213 | 392576 | 0 | 11406 | 5152 | unknown | 490619 |
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 738448 | 639872 | 0 | 20223 | 11399 | unknown | 758671 |
| with_skill | node/express-basic/qual/instrument | node/express-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 207479 | 151296 | 0 | 16912 | 12126 | unknown | 224391 |
| with_skill | python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 256314 | 221568 | 0 | 7984 | 4222 | unknown | 264298 |
| with_skill | python/assistant-v3-framework-bridge-demo/qual/instrument | python/assistant-v3-framework-bridge-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 360484 | 291200 | 0 | 9703 | 5932 | unknown | 370187 |
| with_skill | python/checkout-red-demo/qual/instrument | python/checkout-red-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 228331 | 177792 | 0 | 9206 | 5866 | unknown | 237537 |
| with_skill | python/fastapi-celery/qual/incident-readiness | python/fastapi-celery | with_skill | codex | cumulative | measured | 1/1 recognized | 211203 | 158720 | 0 | 5955 | 2755 | unknown | 217158 |
| with_skill | python/fastapi-celery/qual/instrument | python/fastapi-celery | with_skill | codex | cumulative | measured | 2/2 recognized | 168486 | 133504 | 0 | 10122 | 5881 | unknown | 178608 |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 444263 | 281216 | 0 | 22243 | 16389 | unknown | 466506 |
| with_skill | python/mcp-ai-tool-demo/qual/instrument | python/mcp-ai-tool-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 277732 | 214656 | 0 | 8488 | 5235 | unknown | 286220 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | benchmark | rubric:rubric-2 FAIL | service/.observe/otel-instrumentation.json includes audit_sha256, selection_sha256, OTEL-001 status not_proven, telemetry_changes, tests/evidence, scenario mappings, and next_steps. service/.observe/otel-instrumentation.md exists. find service/.observe found no otel-verify.json or otel-verify.md, despite the report ... |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-5 FAIL | GET /tasks/{id} no longer starts a span named with the task id, but handlers for invalid body, not found, and conflict do not call RecordError, SetStatus, or add failure attributes. |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-6 FAIL | POST /tasks/{id}/reserve returns 409 for both already done and already reserved, but service/main.go has no otelhttp.LabelerFromContext call and no outcome.reason or equivalent attribute. |
| with_skill | go/chi-partial | with_skill | runtime-preserving | rubric:rubric-5 FAIL | service/main.go starts the child span as "tasks.get" and sets task.lookup.outcome, but there are no RecordError, SetStatus, or codes.Error usages; the not_found path only writes HTTP 404. |
| with_skill | go/chi-partial | with_skill | runtime-preserving | rubric:rubric-6 FAIL | service/main.go returns 409 for both "already done" and "already reserved", but service contains no otelhttp.LabelerFromContext usage and adds no outcome.reason or equivalent labeler attribute for the HTTP duration metric. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-5 FAIL | service/go.mod only adds otelhttp, core otel, trace/metric exporters, sdk, and sdk/metric; service/cmd/kvstore-server/otel.go:40-72 configures only trace and metric providers. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-6 FAIL | service/kvstore/http.go:59-63 logs only message and operation; service/cmd/kvstore-server/otel.go:23 sets defaultServiceName = "kvstore"; no log provider exists to attach trace/span IDs. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-7 FAIL | rg finds OTEL_LOGS_EXPORTER only in service/.vscode/launch.json, not application code. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-9 FAIL | service/cmd/kvstore-server/otel.go:70-71 shuts down only tp and mp; service/cmd/kvstore-server/main.go:34-40 defers telemetryShutdown. |
| with_skill | go/kvstore | with_skill | runtime-preserving | rubric:rubric-5 FAIL | last_message.md:22 says logs/events are not configured; .observe/otel-instrumentation.md:14 and :102 state otelslog was not added; service/cmd/kvstore-server/otel.go only configures trace and metric providers. |
| with_skill | go/kvstore | with_skill | runtime-preserving | rubric:rubric-6 FAIL | service/kvstore/http.go:59-63 emits slog.WarnContext with only operation=put; service/cmd/kvstore-server/otel.go:21 defaults service.name to kvstore; last_message.md:22 confirms logs are not exported. |
| with_skill | go/kvstore | with_skill | runtime-preserving | rubric:rubric-9 FAIL | service/cmd/kvstore-server/main.go:40-46 defers telemetryShutdown; service/cmd/kvstore-server/otel.go:59-61 shuts down only tp and mp. |
| with_skill | go/kvstore | with_skill | runtime-preserving | rubric:task-runtime-preserving FAIL | service/go.mod:3 is go 1.24.0; last_message.md:7 says the module floor is now go 1.24.0; .observe/otel-instrumentation.md:39 and :105 state it was raised from 1.22. |
| with_skill | java/kafka-batch-consumer | with_skill | direct | rubric:rubric-5 FAIL | README and report say Kafka consumer spans come from the Java agent and defer batch-size, failed-record, and high-value-payment metrics as optional custom instrumentation. They do not explicitly mention commit latency as optional. |
| with_skill | java/springboot-basic | with_skill | direct | rubric:rubric-5 FAIL | The report says runtime proof was blocked by missing app jar, Java agent jar, and local OTLP receiver. service/otel-run.sh sets OTEL_SERVICE_NAME=springboot-basic, not java-springboot-basic. |
| with_skill | java/springboot-basic | with_skill | direct | rubric:rubric-7 FAIL | service/otel-entrypoint.sh does not reject non-space/tab control whitespace in JAVA_TOOL_OPTIONS/JDK_JAVA_OPTIONS/_JAVA_OPTIONS, scans JDK_JAVA_OPTIONS as plain words instead of launcher options, skips only a small subset of launcher option values, and adds OTEL_LOGS_EXPORTER=otlp even when an empty -Dotel.logs.expo... |
| with_skill | java/springboot-basic | with_skill | runtime-preserving | rubric:rubric-4 FAIL | service/otel-entrypoint.sh:67-101 only reads OTEL_LOGS_EXPORTER/OTEL_EXPORTER_OTLP_LOGS_* from the environment and defaults OTEL_LOGS_EXPORTER=otlp plus /v1/logs for HTTP. |
| with_skill | java/springboot-basic | with_skill | runtime-preserving | rubric:rubric-5 FAIL | .observe/otel-instrumentation.md and last_message.md state full runtime acceptance/log verification was blocked; service/otel-entrypoint.sh:55 sets OTEL_SERVICE_NAME=springboot-basic. |
| with_skill | java/springboot-basic | with_skill | runtime-preserving | rubric:rubric-6 FAIL | service/otel-entrypoint.sh:67-74 does not scan JVM property sources; with JAVA_TOOL_OPTIONS='-Dotel.logs.exporter=none' and a nonlocal generic endpoint, the launcher still entered the local logs branch and failed. |
| with_skill | java/springboot-basic | with_skill | runtime-preserving | rubric:rubric-7 FAIL | service/otel-entrypoint.sh:11-23 has host/docker selection, but lines 67-112 are a simple env and -javaagent scan; JAVA_TOOL_OPTIONS='@opts' was not rejected before the missing-agent check. |
| with_skill | node/express-basic | with_skill | direct | rubric:rubric-3 FAIL | service/instrumentation.js:21-23 calls `new BatchLogRecordProcessor({ exporter: new OTLPLogExporter(...) })`; the SDK API expects the exporter itself, not an object wrapper. service/package.json:13 and :20 use 0.221.0-era log packages while service/package.json:16 pins `@opentelemetry/instrumentation-console` to `0.... |
| with_skill | node/express-basic | with_skill | direct | rubric:rubric-4 FAIL | service/app.js:30 emits `console.warn("runtime request completed")`; no runtime OTLP evidence is present. last_message.md says app startup/full runtime acceptance could not run because dependencies were unmet. |
| with_skill | node/express-basic | with_skill | direct | rubric:rubric-6 FAIL | service/instrumentation-config.js:70-81 checks `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS`; no checks exist for logs-specific headers/credentials. |
| with_skill | node/express-basic | with_skill | direct | rubric:rubric-8 FAIL | service/app.js:60-77 closes the server, logs completion/failure, awaits `shutdownOnce`, and sets `exitCode`; service/instrumentation.js:47-49 memoizes `sdk.shutdown()`. No timeout or forced nonzero timeout path is implemented. |
| with_skill | node/express-basic | with_skill | runtime-preserving | rubric:rubric-3 FAIL | service/instrumentation.js:94-97 creates OTLPLogExporter and BatchLogRecordProcessor; lines 113-124 import ConsoleInstrumentation; service/package.json:11-22 declares mixed OTel versions; .observe/otel-verify.md:23-24 says dependencies/startup were not proven. |
| with_skill | node/express-basic | with_skill | runtime-preserving | rubric:rubric-4 FAIL | service/app.js:31 emits console.warn("runtime request completed"); service/instrumentation.js:141-144 installs one ConsoleInstrumentation; .observe/otel-verify.md:23-28 and 40-42 report missing dependencies and no runtime telemetry proof. |
| with_skill | node/express-basic | with_skill | runtime-preserving | rubric:rubric-6 FAIL | service/instrumentation.js:79-92 rejects non-local OTEL_EXPORTER_OTLP_LOGS_ENDPOINT and generic OTEL_EXPORTER_OTLP_HEADERS; no comparable guard exists for OTEL_EXPORTER_OTLP_LOGS_HEADERS or other log-specific credentials. |
| with_skill | node/express-basic | with_skill | runtime-preserving | rubric:rubric-8 FAIL | service/app.js:57-79 closes the server, logs shutdown completion/failure, and calls shutdownTelemetry; service/instrumentation.js:150-154 makes sdk.shutdown idempotent; no timeout or forced exit path is present. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-2 FAIL | service/app.py adds chat/tool spans and assistant.stream.active; /v1/feedback/export has no custom span or metric; build_turn has no parent assistant lifecycle span. |
| with_skill | python/ai-assistant-demo | with_skill | direct | rubric:rubric-4 FAIL | service/app.py has assistant.context.budget and assistant.response.truncated attributes, but no dedicated truncation/token-limit/prompt-size/tool-schema/fanout metrics or tests; .observe reports mainly list runtime proof as remaining. |
| with_skill | python/checkout-red-demo | with_skill | direct | rubric:rubric-7 FAIL | .observe/otel-instrumentation.md has Source audit: not applicable and a Signals Changed section, then an Audit Gap Closure table with invented DIR-001 through DIR-005 rows. |
| with_skill | python/checkout-red-demo | with_skill | direct | rubric:rubric-8 FAIL | last_message.md and .observe/otel-instrumentation.md record uv sync failing to fetch https://pypi.org/simple/opentelemetry-api/ due DNS lookup failure; .observe/otel-instrumentation.md says $otel-verify was not run and all route scenarios are blocked/Not proven. grade.json sanity guard checks passed. |
| with_skill | python/fastapi-celery | with_skill | mttd | rubric:rubric-1 FAIL | service/docker-compose.yml keeps redis/api/worker and adds OTEL_API/WORKER service-name env. service/app.py initializes OTel and FastAPI/Redis instrumentation. service/worker.py gates worker OTel and enables Celery/Redis instrumentation only for worker process. |
| with_skill | python/fastapi-celery | with_skill | mttd | rubric:rubric-2 FAIL | rg found no Counter/Histogram/custom metric instruments in app.py or worker.py. .observe/otel-instrumentation.md explicitly lists order enqueue failure, stuck/delayed fulfillment, and worker task failure detectors as None/uncovered/deferred. |
| with_skill | python/fastapi-celery | with_skill | mttd | rubric:rubric-3 FAIL | service/app.py calls celery_app.send_task at lines 71-74 without try/except or telemetry. service/worker.py fulfill_order at lines 44-52 has no exception handling, span status updates, or failure metrics. |
| with_skill | python/fastapi-celery | with_skill | mttd | rubric:rubric-6 FAIL | service/tests/test_otel_setup.py only tests resource/log endpoint helpers. The report records py_compile, 5 unittest helper tests, and docker compose config passing, with dependency import and runtime acceptance blocked. |
| with_skill | python/flask-basic | with_skill | direct | rubric:rubric-3 FAIL | LoggerProvider/log processor/exporter setup is in service/otel_setup.py lines 94-113 and 164-174. _instrument_logging only adds inject_trace_context if inspect.signature(logging_instrumentor.instrument) exposes that named parameter at lines 116-124. |
| with_skill | python/flask-basic | with_skill | direct | rubric:rubric-6 FAIL | service/otel_setup.py rejects generic OTEL_EXPORTER_OTLP_HEADERS at lines 103-107, rejects non-local OTEL_EXPORTER_OTLP_LOGS_ENDPOINT at lines 84-90, and has no corresponding guard for OTEL_EXPORTER_OTLP_LOGS_HEADERS or other log credentials. |
| with_skill | python/flask-basic | with_skill | direct | rubric:rubric-7 FAIL | service/app.py registers shutdown_opentelemetry at line 11; service/otel_setup.py shuts down logging before metrics/traces at lines 194-203, but TracerProvider, MeterProvider, and LoggerProvider are created without shutdown_on_exit=False at lines 140, 159, and 166. |
| with_skill | python/flask-basic | with_skill | runtime-preserving | rubric:rubric-3 FAIL | otel_setup.py creates LoggerProvider, BatchLogRecordProcessor, OTLPLogExporter, and LoggingInstrumentor, but only adds inject_trace_context when it appears in inspect.signature(logging_instrumentor.instrument). |
| with_skill | python/flask-basic | with_skill | runtime-preserving | rubric:rubric-6 FAIL | _local_log_exporter() rejects OTEL_EXPORTER_OTLP_HEADERS but still constructs OTLPLogExporter(endpoint=local); no equivalent guard or override is present for OTEL_EXPORTER_OTLP_LOGS_HEADERS or other log-specific credentials. |
| with_skill | python/mcp-ai-tool-demo | with_skill | direct | rubric:rubric-1 FAIL | service/telemetry.py:149-167 creates TracerProvider and MeterProvider and calls trace.set_tracer_provider/metrics.set_meter_provider; service/app.py:19 invokes it at import/startup. |
| with_skill | python/mcp-ai-tool-demo | with_skill | direct | rubric:rubric-6 FAIL | .observe/otel-instrumentation.md:1-7 is the report header and no-audit statement; .observe/otel-instrumentation.md:34-42 has Signals Changed; .observe/otel-instrumentation.md:65-74 contains Audit Gap Closure rows without a source audit. |
| with_skill | python/mcp-ai-tool-demo | with_skill | direct | rubric:rubric-7 FAIL | last_message.md:20-24 and .observe/otel-instrumentation.md:82-87 record uv sync DNS failure for https://pypi.org/simple/uvicorn/, ModuleNotFoundError for httpx, and that $otel-verify/full runtime acceptance were not run. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
