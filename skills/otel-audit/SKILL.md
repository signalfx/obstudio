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
  version: 0.7.0
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

**Metrics inventory** -- build a list of every metric source. This includes
both OpenTelemetry metrics and non-OTel custom application metrics that may be
exported through an agent, bridge, legacy reporter, or sidecar.

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
- Custom application metric registrations, even when they do not use the OTel
  Metrics API. Examples include Java `com.splunk.o11y.metrics.Metrics`,
  Dropwizard/Codahale `Counter`, `Timer`, `Histogram`, `MetricRegistry`,
  Micrometer `Counter`/`Timer`, Prometheus clients, StatsD clients, and
  framework-specific metric helpers.
Record the metric name, source file with line number, type, and export path.
Use type values such as `auto`, `source OTel`, `custom app`, or `agent-exported`.
For Java Dropwizard/Codahale/Splunk metrics, state when export is conditional on
the Splunk/OpenTelemetry Java agent, Codahale reporter, or runtime config.
Do not write "No metrics detected" when custom app metrics exist only because
no source-level OTel `Meter` usage was found.

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

**Gap priority and instrument handoff** -- classify every grouped gap before
writing the report:

- `required`: needed for baseline RED coverage, trace continuity, error
  attribution, exporter/resource correctness, or removal of an OTel
  anti-pattern that can break signals. Plain `$otel-instrument <service>`
  should be able to fix these gaps by default.
- `recommended`: useful deeper visibility, business metrics, optional log
  export when trace-correlated stdout logs already exist, or client/cache
  operational metrics beyond baseline RED. These are included when the user
  asks `$otel-instrument fix all <service>`.
- `deferred`: needs product/operator input, external infrastructure, secrets,
  or a downstream ownership decision. Do not imply `$otel-instrument` will fix
  it without clarification.

If no `required` gaps remain, say that explicitly in `## Recommendation`.

**Flow and gap synthesis** -- before writing the final report, synthesize the
findings into a reader-first map:

- **Signal Flow:** show the actual runtime topology as a component or edge map,
  not a generic mental-model explanation and not a forced single request path.
  Use concrete components discovered in the repo: runtime startup/export,
  entry points, middleware/filters, controllers/handlers, service logic,
  DAO/database calls, caches, queues, outbound clients, downstream services,
  background workers, scheduled jobs, migration/maintenance runners, and
  telemetry export.
- Separate independent roots. Show synchronous request/RPC entry points,
  message/queue consumers, scheduled/background services, maintenance runners,
  and telemetry startup/export as separate branches when they are started by
  different processes or lifecycle modules.
- Do not place a component under an upstream branch unless the code proves that
  it is invoked by that branch. For example, a Kafka/background process should
  not appear under a Thrift/HTTP request branch just because it shares clients
  or data stores.
- Mark `[COVERED]` only for the exact component or edge where instrumentation
  evidence exists. Coverage does not automatically flow through child data
  stores, clients, queues, or helpers; mark those separately if evidence is
  present, otherwise show the appropriate gap marker.
- Include a `### Component Flow Map` under `## Signal Flow`. Prefer a compact
  text flow with `[COVERED]` for covered edges and numbered gap markers like `[GAP1]`, `[GAP2]`, and `[GAP3]` over Mermaid when there are more than
  four nodes or any edge needs explanation. Keep the map visually simple:
  component names and markers only, no long edge labels. Use `[GAP1]` rather than `[G1]`; do not generate `[G1]`, `[G2]`, or `[G3]`.
- Include a `### Map Legend` table immediately after the map when symbols are
  used. Columns must be exactly `Symbol`, `Location`, `Meaning`,
  `Signals Affected`. Use this table to explain coverage gaps, broken
  propagation boundaries, missing metrics, missing log correlation, and missing
  error recording.
- Include a `### Step-by-Step Signal Coverage` table under `## Signal Flow`.
  Use a normalized table with one row per flow step and signal type. Columns
  must be exactly `Step`, `Component / Edge`, `Signal`, `Shows Today`,
  `Missing Today`.
  For each step, include rows for `Trace`, `Metric`, and `Log` when applicable.
  Use `None detected` when that signal has no coverage for the step, and
  `None identified` when no missing coverage is apparent. This table is
  diagnostic: it shows where visibility stops in the flow, not the remediation
  backlog.
- **Gap:** convert the detailed gaps into an action-oriented table with
  exactly these columns: `Priority`, `Area`, `Gap`, `User Impact`, `Fix`,
  `Instrument Mode`. The `Priority` values must be `required`, `recommended`,
  or `deferred`. Use `Instrument Mode` values `default`, `fix all`, or
  `manual decision`. The `Fix` column is the target remediation and must not be
  presented as current behavior.
  Deduplicate and group related flow blind spots into remediation themes so the
  `## Gap` table does not repeat the flow table one row at a time.

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

## Audit Evidence

| Check | Finding | Source |
|-------|---------|--------|
| Manifest | {dependency and build evidence} | {path} |
| Entry point | {process entry point} | {path} |
| Route source | {route/controller files inspected} | {path(s)} |
| Runtime/startup | {startup surface and telemetry config} | {path(s) or "none detected"} |

## Routes

| Method | Path |
|--------|------|
| GET | /health |
| GET | /tasks |
| POST | /tasks |
| GET | /tasks/{id} |
| ... | ... |

## Signal Flow

Use this section to show the component flow first, then the signal coverage for
each step. The user should be able to point at a node or edge and understand
what traces, metrics, and logs can explain today, and what remains invisible.

### Component Flow Map

```text
Inbound request
  |
  v
[Router / controller] [COVERED]
  |-- [COVERED] [Repository / database]
  |-- [GAP1] [Downstream service]
  `-- [GAP2] [Telemetry export]
```

### Map Legend

| Symbol | Location | Meaning | Signals Affected |
|--------|----------|---------|------------------|
| COVERED | Router / controller -> Repository / database | Trace context and enough RED signal coverage were detected | Trace, Metric, Log |
| GAP1 | Router / controller -> Downstream service | Propagation: downstream visibility is incomplete | Trace |
| GAP2 | Service -> Telemetry export | Export config: resource or exporter configuration is inconsistent | Trace, Metric, Log |

### Step-by-Step Signal Coverage

| Step | Component / Edge | Signal | Shows Today | Missing Today |
|------|------------------|--------|-------------|---------------|
| 1 | Client -> Router / controller | Trace | GET /tasks server span from otelhttp | Missing in non-instrumented startup path |
| 1 | Client -> Router / controller | Metric | Request rate and duration from http.server.request.duration | None identified |
| 1 | Client -> Router / controller | Log | Request log with trace_id/span_id | None identified |
| 2 | Handler -> Repository / client | Trace | tasks.lookup custom span | Missing recordException on failures |
| 2 | Handler -> Repository / client | Metric | db.client.operation.duration | None identified |
| 2 | Handler -> Repository / client | Log | Repository error log with trace_id/span_id | None identified |
| ... | ... | ... | ... | ... |

## Gap

Highest-impact fixes derived from the flow map. Group related blind spots so
this is a prioritized remediation backlog, not a second signal inventory.

| Priority | Area | Gap | User Impact | Fix | Instrument Mode |
|----------|------|-----|-------------|-----|-----------------|
| required | Startup | Java agent/env setup only appears in one startup path | Local runs can miss HTTP, DB, and client spans | Standardize startup with OTel enabled for every runtime | default |
| required | Errors | Custom spans do not record exceptions | Failed operations are hard to find from traces | Set span status and record exceptions on failure paths | default |
| recommended | Logs | OTel log export is not configured, but trace-correlated stdout logs exist | Logs can be correlated but may not appear as OTel log signals | Add a supported OTel log bridge/exporter only if log signals are required | fix all |
| deferred | Downstream owner | External service does not publish telemetry | Cross-service traces stop outside this repo | Coordinate downstream instrumentation with the owning team | manual decision |
| ... | ... | ... | ... | ... | ... |

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
instrumented or custom application metrics with vague labels like "(+ related)"
or parenthetical summaries.

| Name | Source | Type | Export Path |
|------|--------|------|-------------|
| http.server.request.duration | otelhttp | auto | OTel SDK/exporter |
| http.server.active_requests | otelhttp | auto | OTel SDK/exporter |
| http.server.request.size | otelhttp | auto | OTel SDK/exporter |
| http.server.response.size | otelhttp | auto | OTel SDK/exporter |
| orders.processed.count | orders/metrics.go:15 | source OTel | OTel SDK/exporter |
| orders.queue.depth | orders/worker.go:88 | custom app | Prometheus scrape |
| service.query.timer | QueryManager.java:120 | custom app | Dropwizard/Codahale; may be exported by Java agent or legacy reporter when enabled |

If custom application metrics exist but no source-level OTel `Meter`
instruments are found, list the custom metrics and add a short note:
"No source-level custom OpenTelemetry `Meter` instruments were detected."
Only write "No metrics detected." when no OTel, auto-instrumented, or custom
application metric sources are found.

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

## Anti-Patterns
- {any issues found, or "None detected"}

## Recommendation
- {actionable next step: "Run $otel-instrument to add auto-instrumentation
  for X, Y, Z" or "Instrumentation looks complete -- consider
  $otel-instrument for custom business metrics"}

---
*Generated by obstudio v0.7.0 otel-audit on {YYYY-MM-DD HH:MM UTC}*
```

Report requirements:

- Do not include a generic mental-model section. Apply that reasoning inside the
  `## Signal Flow` map and coverage table instead.
- Use `## Audit Evidence` instead of a generic `## Evidence` heading. The table
  columns must be exactly `Check`, `Finding`, `Source`; do not use
  `Area | Evidence`, because it repeats the section title and is hard for users
  to scan.
- Always include `## Signal Flow` after `## Routes`.
- Under `## Signal Flow`, always include `### Component Flow Map`. If the map
  uses symbols, include `### Map Legend` next, followed by
  `### Step-by-Step Signal Coverage`.
- Always include `## Gap` before `## Current Instrumentation`, with columns
  `Priority`, `Area`, `Gap`, `User Impact`, `Fix`, `Instrument Mode`.
- Do not include a separate `## Gaps` section. `## Gap` is the single
  gap summary for the report.
- The component flow map must use concrete service components and edges from the
  scanned repo. Do not use placeholder-only maps in the final report.
- Prefer compact text maps with markers over Mermaid when Mermaid edge labels
  would make the map hard to read. Do not put long explanations on map edges.
- Use `[COVERED]` for covered flow edges and `[GAP1]`, `[GAP2]`, etc. for gap markers. Do not use opaque shortened markers like `[G1]`, `[G2]`, or `[G3]`.
- The map legend table must explain each symbol with columns `Symbol`,
  `Location`, `Meaning`, `Signals Affected`.
- The signal coverage table must make it easy to follow one request through
  traces, metrics, and logs. Use one row per flow step and signal type with
  columns `Step`, `Component / Edge`, `Signal`, `Shows Today`, `Missing Today`.
- Do not use nested sub-rows, multiple Markdown paragraphs inside a cell, or
  separate `Trace: Catches`, `Metric: Catches`, and `Log: Catches` columns.
- The `## Gap` table must be grouped by fix area, not by flow step. It should
  be possible for one gap row to cover several flow-step blind spots.
- The `## Gap` table is consumed by `$otel-instrument` during its static
  validation loop. Use exact lowercase `Priority` values (`required`,
  `recommended`, `deferred`) and exact `Instrument Mode` values (`default`,
  `fix all`, `manual decision`). Do not use variants such as `Required`,
  `fix-all`, `optional`, or `manual`.
- If no gaps remain, keep the `## Gap` heading plus the table header and
  separator row, then write the sentence `No gaps found.` directly below the
  table. This lets the instrument skill count zero remaining rows without
  guessing.
- Broken inter-service propagation, missing downstream spans, missing request
  metrics, missing log correlation, and missing error recording should appear on
  the flow map or in the flow-step gap column when evidence supports them.
- The Metrics inventory must include all discovered custom application metrics,
  not only metrics created through the OTel `Meter` API. Include legacy and
  library-backed metrics such as Dropwizard/Codahale, Micrometer, Prometheus,
  StatsD, `com.splunk.o11y.metrics.Metrics`, and similar wrappers.
- Do not say `No metrics detected` if custom application counters, timers,
  gauges, histograms, or summaries are present. If no OTel `Meter` calls exist,
  say `No source-level custom OpenTelemetry Meter instruments were detected`
  and still list the app metrics.
- For each metric row, explain the export path when evidence is available:
  source OTel SDK/exporter, Java agent auto-instrumentation, Dropwizard/Codahale
  reporter, Prometheus scrape, StatsD, or unknown. If export depends on runtime
  settings such as `OTEL_AGENT_ENABLED`, `OTEL_METRICS_EXPORTER`, or a reporter
  module, state that conditionality.
- The gap table must be action-oriented: one row per major gap, clear user
  impact, and a concrete fix.
- The gap table must rank gaps. Use `required` only for fixes needed to make
  baseline OTel instrumentation complete and trustworthy. Use `recommended` for
  useful but non-baseline improvements. Use `deferred` for items that require
  external decisions or infrastructure.
- If instrumentation is incomplete, always include the exact token `$otel-instrument` in the recommendation.
- If `required` gaps exist, recommend `$otel-instrument <service>` to fix the
  required gaps. If only `recommended` gaps exist, say baseline required
  instrumentation is complete and recommend `$otel-instrument fix all <service>`
  only if the user wants the recommended improvements too.
- If OpenTelemetry is absent, include both words `OpenTelemetry` and `missing`.
- Name the concrete files that support findings; do not only refer to "the service" or "./service".
- For Node.js, mention `package.json` and the app entry point such as `app.js`.
- For Python, mention `pyproject.toml` or `requirements.txt`, the app file such as `app.py`, and runtime files such as `Dockerfile` or `docker-compose.yml` when present.
- For FastAPI/Celery services, mention the web app, worker file, Dockerfile, compose commands, FastAPI/ASGI coverage, Celery instrumentation, Redis instrumentation if Redis is present, and HTTP client instrumentation only when an HTTP client dependency is detected.
- For Java/Spring Boot, mention the Spring Boot entry point such as `TasksApplication.java`, controller files such as `TaskController.java`, and the Java agent recommendation.
- For Go multi-package services, name the process entry point such as `cmd/kvstore-server/main.go` and relevant library files. If filesystem persistence, background indexing, or LRU eviction exists, call those out explicitly.

**Chat summary:** After writing `.observe/otel.md`, present a brief summary in
chat that includes: RED signal statuses, count of gaps found by priority using
the exact labels `Required gaps: N`, `Recommended gaps: N`, and
`Deferred gaps: N`, plus the recommendation line. End with:
`Full report: .observe/otel.md`.

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
- Kafka, RabbitMQ, gRPC
- Servlet containers (Tomcat, Jetty, Undertow)
- JDBC drivers

## Troubleshooting

**No dependency manifest found:** Ask the user which subdirectory contains the service, then re-scan from that root.

**Multiple languages detected:** Ask which service to audit, or audit each independently.
