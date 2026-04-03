---
name: observe
description: >-
  Analyze a codebase for observability readiness, generate a structured
  .observe/ audit directory, and implement OpenTelemetry instrumentation.
  Use when the user types /observe, asks about observability, wants to add
  OpenTelemetry, or asks to instrument a service.
---

# Observe -- Observability Audit and Instrumentation

Audit a repository for observability readiness, produce a `.observe/`
directory with an inventory and placeholder artifact directories, and
implement OpenTelemetry instrumentation for the gaps.

Execute each step in order. Present findings after each step before proceeding.

If the user only wants instrumentation (not a full audit), run the
**fast path**: Step 1 (discovery) -> Step 2 (component mapping) -> Step 5
(KPI table) -> Step 6 (generate .observe/) -> Step 7 (implement) ->
Step 8 (verify).
Always run Step 1 first -- the language guide must be loaded before
instrumentation can begin. Always run Step 6 -- `.observe/` must exist.
Always offer Step 8 after instrumentation.

---

## Step 1 - Repository Discovery

Scan the repository to determine language, framework, and existing
instrumentation.

1. Detect primary language and framework:
   - Go: `go.mod`
   - Python: `requirements.txt`, `pyproject.toml`, `setup.py`
   - Node.js: `package.json`
   - Java: `pom.xml`, `build.gradle`
   - Rust: `Cargo.toml`
   - .NET: `*.csproj`, `*.sln`
2. Search for existing instrumentation:
   - OpenTelemetry imports/dependencies (`opentelemetry`, `otel`, `otlp`)
3. Identify entry points (`main`, `cmd/`, `app.py`, `index.ts`, etc.)
4. Identify configuration files (`config.yaml`, `.env`, env var bindings)
5. **Load language guide**: read `languages/<detected>.md` in this directory.
   Only load the file matching the detected language. Do not load others.
6. Summarize to user: language, framework, existing instrumentation (if any),
   entry points, and config mechanism.

---

## Step 2 - Component Mapping

Identify all components the service interacts with and its internal layers.

**External components** -- search for client libraries, connection strings,
driver imports:
- Databases (SQL, NoSQL, key-value)
- Caches (Redis, Memcached)
- Message queues / brokers (Kafka, RabbitMQ, Redis pub/sub, NATS)
- External HTTP/gRPC APIs
- File storage (S3, local FS, GCS)
- Auth providers (OAuth, LDAP, SAML)

**Internal layers** -- identify architectural tiers:
- Presentation (HTTP handlers, gRPC servers, CLI)
- Business logic (services, use cases, domain)
- Data access (repositories, DAOs, ORM models)
- Background workers (cron, schedulers, consumers)
- Middleware (auth, logging, rate limiting)

Present a component interaction list or diagram. Use a mermaid diagram when
there are 3+ external components.

---

## Step 3 - Fault Domain Analysis

Read [fault-domain-patterns.md](references/fault-domain-patterns.md) for
common patterns organized by component type.

For each component from Step 2, assess:
- **Connectivity**: connection drops, DNS failures, TLS issues
- **Latency**: slow operations, timeouts, backpressure
- **Data integrity**: corruption, deserialization errors, schema drift
- **Capacity**: pool exhaustion, memory pressure, queue growth, disk full
- **Availability**: single point of failure, failover path

Cross-cutting SRE concerns:
- Cascading failures, retry storms, thundering herd
- Poison pill messages, head-of-line blocking
- Stale state, split brain, clock skew
- Cold start, deployment rollback impact

Present fault domains grouped by component as a table.

---

## Step 4 - KPI Identification

For each component and fault domain, identify Key Performance Indicators
using the four golden signals:

| Signal     | Question                                    |
|------------|---------------------------------------------|
| Latency    | How long do operations take? (p50, p95, p99) |
| Traffic    | How much demand is the system handling?      |
| Errors     | What is the rate of failed requests?         |
| Saturation | How full are resources? (pools, queues, mem) |

Also identify business-logic KPIs specific to the domain.

---

## Step 5 - Unified KPI Table

Read [signal-mapping-guide.md](references/signal-mapping-guide.md) for
guidance on mapping KPIs to OTel signal types.

Build a single table containing all KPIs -- already instrumented and missing.

| Column          | Description                                              |
|-----------------|----------------------------------------------------------|
| Status          | `OK` if already instrumented, blank if missing           |
| KPI             | Name of the KPI                                          |
| Component       | Which component it belongs to                            |
| Class           | `Standard` (auto-instrumentation) or `Business` (custom) |
| Metric          | Yes/No                                                   |
| Trace           | Yes/No                                                   |
| Log             | Yes/No                                                   |
| Signal Name     | Actual name if exists, proposed name if not               |
| Trace-Derivable | Yes/No -- can the metric be derived from span data?       |
| Verified        | Blank initially; set to `OK` by Step 8 validation        |

Classify each KPI:
- **Standard**: provided by auto-instrumentation libraries
- **Business**: requires custom code

Present the table. Highlight the gap count as the implementation scope.

---

## Step 6 - Generate or Update .observe/ Directory

This directory is the single output artifact of the observe skill and the
input for downstream skills (terraform, alerting).

### If `.observe/inventory.md` already exists

1. Read the existing `inventory.md`.
2. Parse the existing KPI Table to extract the list of previously tracked
   KPIs with their Status, Signal Name, and Component.
3. Compare against the KPIs identified in Steps 4-5 of this run:
   - **New KPIs**: components or operations added to the codebase since the
     last audit that are not in the existing table. Add them with blank
     Status.
   - **Removed KPIs**: components or operations deleted from the codebase
     whose signals no longer exist. Mark them with a strikethrough or
     remove them, and note the removal in a changelog comment at the top of
     the file.
   - **Changed KPIs**: status changes (e.g., a KPI that was blank is now
     instrumented, or vice versa). Update the Status column.
   - **Unchanged KPIs**: preserve as-is, including any manually added
     notes, runbook links, or alert overrides.
4. Update the Architecture diagram and Components table if new external
   dependencies or internal layers were added or removed.
5. Update the Fault Domains table with any new components.
6. Append a `<!-- Last updated: {date} -->` comment.
7. Present a summary of changes to the user: N new KPIs, N removed, N
   status changes.

### If `.observe/inventory.md` does not exist (first run)

Read [observability-template.md](references/observability-template.md) for
the inventory document template.

Create the `.observe/` directory at the repository root:

```
.observe/
  inventory.md              # Audit results: service overview, components,
                            #   fault domains, KPI table, configurability,
                            #   dashboard recommendations
  terraform/                # (future) Splunk O11y Cloud terraform
                            #   dashboards, detectors, tokens
  alerts/                   # (future) Alert rule definitions
                            #   prometheus-rules.yaml, signalfx-detectors.tf
```

Create `.observe/inventory.md` with sections:
1. Service Overview
2. Architecture (component diagram from Step 2)
3. Components
4. Fault Domains (from Step 3)
5. KPI Table (from Step 5)
6. Configurability
7. Dashboard Recommendations

Create the `terraform/` and `alerts/` directories as empty placeholders
with a brief README noting they will be populated by future skills.

---

## Step 7 - Implement Instrumentation

Prompt the user:

> "The observability audit is complete. There are N KPIs without
> instrumentation. Ready to implement?"

If the user confirms (or if the user requested instrumentation directly
without an audit), implement using the language guide loaded in Step 1.

### OOB vs Custom Decision

For each component boundary in the KPI table:

1. Check the language guide's auto-instrumentation library map.
2. If an OOB library exists and covers the KPI, install and register it.
3. If no OOB library exists, or OOB coverage is too coarse for the KPI,
   generate manual spans or metrics following the language guide's patterns.
4. For KPIs marked `Class: Business`, always generate custom instrumentation.

### Implementation Rules

- Do not initialize the SDK more than once per process.
- Find any existing OTel setup before adding new code. Extend it instead of
  creating parallel initialization paths.
- Place OTel initialization code in a separate file.
- Minimize changes to existing code. Do not move functions between files.
- Do not create spans for trivial helpers. Only span real diagnostic boundaries.
- Set span status to ERROR and call recordException on failed operations.
- Use OTel semantic conventions for span names, attributes, and metric names.
  Custom attribute names must follow `{domain}.{noun}.{adjective}` format.
- Span names must be low-cardinality (no IDs, no variable path segments).
- Metric attributes must avoid high cardinality.
- Preserve existing env-var patterns for telemetry config instead of
  hardcoding endpoints.
- If the app is a library, provide an opt-in setup path rather than forcing
  SDK initialization on import.
- Keep the codebase idiomatic. Match the repo's dependency manager, config
  style, and lifecycle patterns.

---

## Step 8 - Verify Instrumentation

After instrumentation is complete, prompt the user:

> "Instrumentation is done. Want me to validate the telemetry against
> the Observer? I'll start the collector, run the app, fire the APIs,
> and verify each KPI is emitting."

If the user declines, skip to Output. If the user confirms, execute the
sub-steps below. Do **not** generate test files -- perform all validation
inline.

### 8a - Start Observer

1. Build observer-go if the binary does not exist:
   ```
   cd observer-go && make build
   ```
2. Start the collector in the background:
   ```
   ./observer-go/obstudio
   ```
3. Wait until `http://localhost:3000/api/query/stats` responds.
4. Clear any stale data: `DELETE /api/data`.

### 8b - Start the Application

Start the instrumented app with fast-flush settings so telemetry
arrives quickly:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_SERVICE_NAME=<service-name>
OTEL_BSP_SCHEDULE_DELAY=100
OTEL_METRIC_EXPORT_INTERVAL=1000
```

Use the project's existing run command (Makefile, `uv run`, `go run`,
`npm start`, etc.). Start in the background.

### 8c - Exercise the API

For each endpoint / operation identified in Step 2:

1. **Identify a representative request** -- determine method, path, and
   a minimal valid payload from the route definitions.
2. **Fire the request** using `curl` or the language's HTTP client.
   Include at least:
   - One happy-path call per CRUD operation.
   - One error-path call (e.g., GET a non-existent resource to trigger
     a 404 and validate error span status).
3. **Wait for telemetry flush** -- sleep 3 seconds after the batch of
   requests to let the SDK export.

### 8d - Validate Traces

Query the Observer REST API (or use MCP tools if available):

1. `GET /api/query/traces?serviceName=<service-name>` -- confirm traces
   exist.
2. For each trace, fetch detail via
   `GET /api/query/traces/{traceId}` and check:
   - **Root span** matches the expected HTTP method + route (e.g.,
     `POST /bookmarks`).
   - **Child spans** for custom instrumentation are present (e.g.,
     `bookmarks.db.insert`).
   - **Span attributes** match OTel semantic conventions (`db.system`,
     `db.operation.type`, `http.method`, etc.).
   - **Error spans** have `status.code == ERROR` and recorded exceptions
     for the error-path calls.

Alternatively, use MCP tools:
- `observer_traces_overview` to list traces.
- `observer_trace_detail` to inspect span trees.

### 8e - Validate Metrics

1. `GET /api/query/metrics?serviceName=<service-name>` -- list all
   metrics.
2. For each KPI in the inventory that has `Metric: Yes`:
   - Query by name:
     `GET /api/query/metrics?metricName=<signal-name>&serviceName=<svc>`
   - Confirm `dataPointCount >= 1`.
   - Confirm the metric `type` matches expectation (sum, histogram,
     gauge).
3. Verify auto-instrumented metrics exist (e.g.,
   `http.server.duration`, `http.server.active_requests`).

Alternatively, use MCP tools:
- `observer_metrics_overview` to list metrics.
- `observer_metric_detail` to inspect a specific metric.

### 8f - Validate Stats

Query `GET /api/query/stats` and confirm:
- `serviceNames` contains the expected service name.
- `spanCount > 0`, `traceCount > 0`.
- `metricCount > 0` if any metrics are expected.

### 8g - Update Inventory with Verified Column

For each KPI row in `.observe/inventory.md`:

1. If the KPI's Signal Name was found in the Observer (trace span name
   matched or metric name matched with `dataPointCount >= 1`), set the
   **Verified** column to `OK`.
2. If the signal was expected but not found, leave Verified blank and
   add a comment noting what was missing.
3. Present a summary table to the user:

```
Verification Results
──────────────────────────────
Total KPIs:      N
Verified:        N  ✓
Not verified:    N  (list signal names)
Coverage:        N%
```

### 8h - Teardown

After verification is complete, **always** stop the processes started
in 8a-8b:

1. Kill the application process (find by port, e.g., `lsof -ti :8080 | xargs kill`).
2. Kill the observer-go process (find by port, e.g., `lsof -ti :3000 | xargs kill`).
3. Clean up temporary data created during the run (e.g., SQLite DBs).

Do not leave background processes running.

---

<!-- TODO: Step 9 - Alerts & Detectors
     Populate .observe/alerts/ and .observe/terraform/ from the KPI table:
     - .observe/terraform/dashboards.tf -- Splunk O11y Cloud dashboards
     - .observe/terraform/detectors.tf -- SignalFx detector definitions
     - .observe/alerts/prometheus-rules.yaml -- Prometheus alerting rules
     - .observe/alerts/grafana.yaml -- Grafana alert definitions
     - .observe/alerts/pagerduty.yaml -- PagerDuty integration templates
     See docs/skills/observe-skill.md Section 9 for spec. -->

---

## Output

When complete, summarize briefly:
- What was instrumented
- Where SDK initialization lives
- How OTLP export is configured
- KPIs identified vs implemented vs remaining gaps
- Verification coverage (if Step 8 was run): N/N KPIs verified
- What was written to `.observe/`
