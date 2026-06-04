---
name: otel-audit
description: >-
  Scan a codebase for existing OpenTelemetry instrumentation and report
  on observability coverage gaps. Read-only -- does not modify code.
  Use when the user types $otel-audit, asks about observability gaps,
  wants to assess instrumentation coverage, says "what signals am I
  missing", "scan this service for observability", or asks about
  "observability readiness". Do NOT use for implementing code changes --
  use $otel-instrument instead.
metadata:
  author: otel-studio
  version: 0.6.0
  category: observability
---

# Audit -- Observability Coverage Scan

## Overview

Scan a service repository to detect its language, framework, dependencies,
and existing OpenTelemetry instrumentation. Report what is instrumented,
what is missing, and any anti-patterns. This skill is read-only -- no code
is modified.

## When to Use

- Assessing current instrumentation coverage before deciding whether to instrument
- Checking what auto-instrumentation is already wired up
- Identifying dependencies that lack matching OTel instrumentation
- Quick health check of an existing OTel setup
**When NOT to use:** If you want to add instrumentation, use `$otel-instrument`.

## Process

### Step 1 -- Repository Discovery

Scan the repository to determine language, framework, and existing instrumentation.

1. Detect primary language and framework:
   - Go: `go.mod`
   - Python: `requirements.txt`, `pyproject.toml`, `setup.py`
   - Node.js: `package.json`
   - Java: `pom.xml`, `build.gradle`
   - Rust: `Cargo.toml`
   - .NET: `*.csproj`, `*.sln`
2. Identify entry points (`main`, `cmd/`, `app.py`, `index.ts`, etc.)
3. Enumerate all HTTP routes with method and path pattern (e.g. `GET /tasks`, `POST /tasks`, `GET /tasks/{id}`). List them explicitly in the report.
4. Use the Auto-Instrumentation Library Map below to identify which packages should be present for each detected dependency.
5. Record exact evidence paths that should appear in the report:
  - Dependency manifest: `go.mod`, `package.json`, `pyproject.toml`, `pom.xml`, etc.
  - Process entry point: `main.go`, `cmd/.../main.go`, `app.py`, `app.js`, `TasksApplication.java`, etc.
  - Route source: router/controller files such as `TaskController.java`, `app.py`, `app.js`, or `kvstore/http.go`.
  - Runtime/startup files when present: `Dockerfile`, `docker-compose.yml`, `Makefile`, `package.json` scripts, launch configs, worker files.

### Step 2 -- Instrumentation Assessment

Check for existing OTel instrumentation and identify gaps. Inventory every
signal by type so the report can list them explicitly.

**SDK and configuration** -- search for:

- OTel SDK initialization files (`otel_setup.py`, `instrumentation.ts`, `otel.go`, etc.)
- OTel imports/dependencies (`opentelemetry`, `otel`, `otlp`, `go.opentelemetry.io`)
- Auto-instrumentation packages matching detected frameworks/clients
- `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT` in env files or configs

**Spans inventory** -- build a list of every span source:

- Auto-instrumentation packages that emit spans (check the "Signals" column in
the language reference). Enumerate every individual span name the package
produces -- one row per span. Never group spans with vague labels like
"HTTP server spans" or "gRPC server spans (all N RPCs)". For example,
`otelgrpc` on a server with methods `GetUser` and `ListUsers` produces spans
`/UserService/GetUser` and `/UserService/ListUsers` -- list each as its own
row.
- Custom span creation calls: `tracer.Start` / `span.End` (Go),
`tracer.start_as_current_span` / `tracer.start_span` (Python),
`tracer.startActiveSpan` / `tracer.startSpan` (Node.js),
`@WithSpan` / `Span.current()` (Java).
Record the span name and source file with line number.

**Metrics inventory** -- build a list of every metric source:

- Auto-instrumentation packages that emit metrics (check the "Signals" column).
Enumerate every individual metric name the package produces -- one row per
metric. Never group metrics with vague labels like "(+ related)" or
parenthetical summaries like "(goroutines, memory, GC)". For example,
`otelgrpc` emits `rpc.server.duration`, `rpc.server.request.size`,
`rpc.server.response.size`, `rpc.server.requests_per_rpc`, and
`rpc.server.responses_per_rpc` -- list each as its own row. Similarly,
`runtime.Start()` emits `process.runtime.go.goroutines`,
`process.runtime.go.mem.heap_alloc`, `process.runtime.go.gc.count`, etc. --
list each individually.
- Custom metric registrations: `meter.Int64Counter`, `meter.Float64Histogram`,
`meter.Int64ObservableGauge`, `meter.Int64UpDownCounter` (Go);
`meter.create_counter`, `meter.create_histogram`,
`meter.create_observable_gauge` (Python);
`meter.createCounter`, `meter.createHistogram`,
`meter.createObservableGauge` (Node.js).
Record the metric name and source file with line number.

**Logs inventory** -- build a list of OTel log integrations:

- OTel log bridge or SDK log packages (`opentelemetry-instrumentation-logging`
for Python, `@opentelemetry/instrumentation-winston` /
`@opentelemetry/instrumentation-pino` for Node.js).
- Trace-context injection into log records (`trace_id`, `span_id` fields).
- `span.AddEvent()` / `span.add_event()` calls used as structured log events.

**Dependencies without instrumentation** -- for each dependency detected in Step 1:

- Check if a matching auto-instrumentation package is installed
- Use the Auto-Instrumentation Library Map below as the checklist
- Flag any dependency that has an available auto-instrumentation package but is not instrumented

**RED signal assessment** -- for each RED dimension, determine status:

- **Rate:** Is there a metric or span source that enables request-count
derivation? (e.g. `http.server.request.duration` histogram counts, or
server spans from auto-instrumentation.)
Status: `covered` / `partial` / `missing`.
- **Errors:** Are span status codes set on failures? Is `recordException`
called? Do HTTP auto-instrumentation spans capture 5xx status?
Status: `covered` / `partial` / `missing`.
- **Duration:** Is there a histogram or span data that provides latency
percentiles? (e.g. `http.server.request.duration` histogram, or span
duration from auto-instrumentation.)
Status: `covered` / `partial` / `missing`.

**Anti-patterns** -- flag any of these:

- Multiple SDK initializations in the same process
- Hardcoded OTLP endpoints instead of env vars
- Tracer/Meter created in hot paths instead of at startup
- High-cardinality attributes on metrics (user IDs, request IDs)
- Missing `recordException` in error handling paths
- Custom span names with variable segments (IDs, paths)
- Use of community or third-party OTel wrappers when an official OpenTelemetry package exists (e.g. `go.opentelemetry.io/contrib`, `@opentelemetry/`*, `opentelemetry-*`)

For partially instrumented Go services, explicitly check and report:

- hardcoded OTLP endpoints such as `collector.example.com`
- `otel.Tracer(...)` or `otel.Meter(...)` calls inside request handlers or loops
- high-cardinality span names such as `GetTask-{id}`
- missing `otel.SetTextMapPropagator(...)`
- missing `MeterProvider`, missing `service.name`, and missing provider shutdown/flush

### Step 3 -- Report

Write the report to `.observe/otel.md` inside the scanned service root (create
the `.observe/` directory if it does not exist). Also present a concise summary
in chat that references the file path.

Use this template for `.observe/otel.md`:

```
# Observability Report: {service-name}

**Language:** {language} | **Framework:** {framework} | **Date:** {YYYY-MM-DD}

## Evidence
- Manifest: {path}
- Entry point: {path}
- Route source: {path(s)}
- Runtime/startup: {path(s) or "none detected"}

## Routes

| Method | Path |
|--------|------|
| GET | /health |
| GET | /tasks |
| POST | /tasks |
| GET | /tasks/{id} |
| ... | ... |

## Current Instrumentation

### Spans

List every individual span name -- one row per span. Never group auto-
instrumented spans with vague labels like "HTTP server spans" or
"gRPC server spans (all N RPCs)".

| Name | Source | Type |
|------|--------|------|
| GET /tasks | otelhttp | auto |
| POST /tasks | otelhttp | auto |
| GET /tasks/{id} | otelhttp | auto |
| orders.process | orders/service.go:42 | custom |

If no span sources are found, write: "No spans detected."

### Metrics

List every individual metric name -- one row per metric. Never group auto-
instrumented metrics with vague labels like "(+ related)" or parenthetical
summaries.

| Name | Source | Type |
|------|--------|------|
| http.server.request.duration | otelhttp | auto |
| http.server.active_requests | otelhttp | auto |
| http.server.request.size | otelhttp | auto |
| http.server.response.size | otelhttp | auto |
| orders.processed.count | orders/metrics.go:15 | custom |

If no metric sources are found, write: "No metrics detected."

### Logs

| Integration | Source | Detail |
|-------------|--------|--------|
| trace-context injection | opentelemetry-instrumentation-logging | Injects trace_id/span_id into log records |
| span events | orders/service.go:55 | span.AddEvent("order.validated") |

If no OTel log integrations are found, write: "No OTel log instrumentation detected."

If no OTel packages or setup are found across all three signal types, include
the phrase: "OpenTelemetry instrumentation is missing."

## RED Signals

| Signal | Status | Detail |
|--------|--------|--------|
| Rate | {covered / partial / missing} | {which metric or span provides request counts, or what is missing} |
| Errors | {covered / partial / missing} | {which span status / recordException provides error visibility, or what is missing} |
| Duration | {covered / partial / missing} | {which histogram or span data provides latency percentiles, or what is missing} |

Status values:
- **covered** -- the signal is fully available from existing instrumentation.
- **partial** -- some data exists but key dimensions are missing (e.g. spans
  exist but no histogram for percentile breakdown).
- **missing** -- no data source provides this signal.

## Gaps
- {remaining non-RED gaps: missing auto-instrumentation packages, missing
  context propagation, missing OTLP exporter configuration, missing
  service.name resource, etc.}
- If no gaps remain, write: "No additional gaps detected."

## Anti-Patterns
- {any issues found, or "None detected"}

## Recommendation
- {actionable next step: "Run $otel-instrument to add auto-instrumentation
  for X, Y, Z" or "Instrumentation looks complete -- consider
  $otel-instrument for custom business metrics"}

---
*Generated by obstudio v0.6.0 otel-audit on {YYYY-MM-DD HH:MM UTC}*
```

Report requirements:

- If instrumentation is incomplete, always include the exact token `$otel-instrument` in the recommendation.
- If OpenTelemetry is absent, include both words `OpenTelemetry` and `missing`.
- Name the concrete files that support findings; do not only refer to "the service" or "./service".
- For Node.js, mention `package.json` and the app entry point such as `app.js`.
- For Python, mention `pyproject.toml` or `requirements.txt`, the app file such as `app.py`, and runtime files such as `Dockerfile` or `docker-compose.yml` when present.
- For FastAPI/Celery services, mention the web app, worker file, Dockerfile, compose commands, FastAPI/ASGI coverage, Celery instrumentation, Redis instrumentation if Redis is present, and HTTP client instrumentation only when an HTTP client dependency is detected.
- For Java/Spring Boot, mention the Spring Boot entry point such as `TasksApplication.java`, controller files such as `TaskController.java`, and the Java agent recommendation.
- For Java/Kafka services, mention the main entry point, runtime configuration,
  producer/consumer classes that wrap `KafkaProducer` or `KafkaConsumer`, batch
  poll loops that handle `ConsumerRecords`, listener-container classes or
  methods such as `@KafkaListener`, and Kafka Streams lifecycle/topology code
  that constructs `KafkaStreams`, `Topology`, `StreamsBuilder`, `KStream`, or
  `KTable`.
- For Java/Kafka services, name topics, consumer groups, poll/send/listener or
  topology behavior, offset commit behavior, uncaught exception handling, Java
  agent coverage for Kafka clients, and missing business signals such as
  processed records, failed parses, high-risk alerts, processing errors,
  consumer lag/offset visibility, and record-processing latency.
- For Go multi-package services, name the process entry point such as `cmd/kvstore-server/main.go` and relevant library files. If filesystem persistence, background indexing, or LRU eviction exists, call those out explicitly.

**Chat summary:** After writing `.observe/otel.md`, present a brief summary in
chat that includes: RED signal statuses, count of gaps found, and the
recommendation line. End with: `Full report: .observe/otel.md`.

### Step 4 -- Verify Telemetry (optional)

After presenting the report, prompt the user:

> Would you like me to verify telemetry is flowing? This requires the Observer
> collector to be running locally.

Then wait for the user's answer.

- **If no**: done.
- **If yes**: run the verification:

1. **Check Observer availability:**
  ```
   curl -s http://localhost:3000/api/query/stats
  ```
   If this fails, tell the user the Observer is not reachable and how to start it.
2. **Clear stale data:**
  ```
   curl -s -X DELETE http://localhost:3000/api/data
  ```
3. **Start the app** with fast-flush settings:
  ```
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
   OTEL_SERVICE_NAME=<service-name>
   OTEL_BSP_SCHEDULE_DELAY=100
   OTEL_METRIC_EXPORT_INTERVAL=1000
  ```
4. **Exercise one happy-path endpoint** (e.g. `GET /health` or `GET /tasks`).
5. **Wait 3 seconds** for export, then check:
  ```
   GET /api/query/traces?serviceName=<service-name>
  ```
6. **Report results:**
  - Traces arrived: list service name, span count, root span name
  - No traces: suggest troubleshooting (wrong endpoint, missing SDK init, exporter misconfigured)
7. **Stop the app** after verification.

## Red Flags

- Fewer than expected auto-instrumentation packages for the detected dependencies
- SDK initialized but no auto-instrumentation packages installed
- OTel packages in dependencies but no SDK init file found
- Error handling code without span error status or recordException

## Auto-Instrumentation Library Map

Use these tables to check whether each detected dependency has a matching
auto-instrumentation package installed. Only flag gaps for dependencies that
appear in the project.

### Go

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `net/http` (stdlib) | `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp` | spans + metrics |
| `gorilla/mux` | `go.opentelemetry.io/contrib/instrumentation/github.com/gorilla/mux/otelmux` | spans only |
| `go-chi/chi` | `go.opentelemetry.io/contrib/instrumentation/github.com/go-chi/chi/otelchi` | spans only |
| `gin-gonic/gin` | `go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin` | spans only |
| `google.golang.org/grpc` | `go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc` | spans + metrics |
| `database/sql` | `github.com/XSAM/otelsql` | spans only |
| `go-redis/redis` | `github.com/redis/go-redis/extra/redisotel` | spans only |
| `runtime` | `go.opentelemetry.io/contrib/instrumentation/runtime` | metrics only |
| `host` | `go.opentelemetry.io/contrib/instrumentation/host` | metrics only |
| `segmentio/kafka-go` | `go.opentelemetry.io/contrib/instrumentation/github.com/segmentio/kafka-go/otelsegmentio` | spans only |
| `aws-sdk-go-v2` | `go.opentelemetry.io/contrib/instrumentation/github.com/aws/aws-sdk-go-v2/otelaws` | spans only |

### Python

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `flask` | `opentelemetry-instrumentation-flask` | spans |
| `django` | `opentelemetry-instrumentation-django` | spans |
| `fastapi` / `starlette` | `opentelemetry-instrumentation-fastapi` | spans |
| `requests` | `opentelemetry-instrumentation-requests` | spans |
| `httpx` | `opentelemetry-instrumentation-httpx` | spans |
| `urllib3` | `opentelemetry-instrumentation-urllib3` | spans |
| `aiohttp` | `opentelemetry-instrumentation-aiohttp-client` | spans |
| `psycopg2` | `opentelemetry-instrumentation-psycopg2` | spans |
| `sqlalchemy` | `opentelemetry-instrumentation-sqlalchemy` | spans |
| `pymongo` | `opentelemetry-instrumentation-pymongo` | spans |
| `redis` | `opentelemetry-instrumentation-redis` | spans |
| `celery` | `opentelemetry-instrumentation-celery` | spans |
| `grpcio` | `opentelemetry-instrumentation-grpc` | spans |
| `kafka-python` / `confluent-kafka` | `opentelemetry-instrumentation-kafka-python` / `opentelemetry-instrumentation-confluent-kafka` | spans |
| `boto3` / `botocore` | `opentelemetry-instrumentation-botocore` | spans |
| `logging` (stdlib) | `opentelemetry-instrumentation-logging` | logs |

### Node.js

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `express` | `@opentelemetry/instrumentation-express` | spans |
| `fastify` | `@opentelemetry/instrumentation-fastify` | spans |
| `koa` | `@opentelemetry/instrumentation-koa` | spans |
| `@nestjs/core` | `@opentelemetry/instrumentation-nestjs-core` | spans |
| `http` / `https` (stdlib) | `@opentelemetry/instrumentation-http` | spans |
| `pg` | `@opentelemetry/instrumentation-pg` | spans |
| `mysql2` | `@opentelemetry/instrumentation-mysql2` | spans |
| `mongodb` | `@opentelemetry/instrumentation-mongodb` | spans |
| `ioredis` | `@opentelemetry/instrumentation-ioredis` | spans |
| `redis` (node-redis v4+) | `@opentelemetry/instrumentation-redis-4` | spans |
| `@grpc/grpc-js` | `@opentelemetry/instrumentation-grpc` | spans |
| `kafkajs` | `@opentelemetry/instrumentation-kafkajs` | spans |
| `graphql` | `@opentelemetry/instrumentation-graphql` | spans |
| `aws-sdk` / `@aws-sdk/*` | `@opentelemetry/instrumentation-aws-sdk` | spans |

### Java

The OpenTelemetry Java agent auto-instruments without code changes:
- Spring MVC (REST controllers), Spring WebFlux, Spring Data (JPA, JDBC)
- RestTemplate and WebClient (outbound HTTP)
- Kafka producers/consumers (including clients used internally by Kafka Streams)
- RabbitMQ, gRPC
- Servlet containers (Tomcat, Jetty, Undertow)
- JDBC drivers

## Troubleshooting

**No dependency manifest found:** Ask the user which subdirectory contains the service, then re-scan from that root.

**Multiple languages detected:** Ask which service to audit, or audit each independently.
