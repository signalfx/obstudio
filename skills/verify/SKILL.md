---
name: verify
description: >-
  Validate that instrumented telemetry is actually flowing by starting
  the Observer collector, exercising the service APIs, and checking
  traces and metrics against the .observe/inventory.md. Use when the
  user types /verify or asks to validate instrumentation.
---

# Verify -- Telemetry Validation

## Overview

Start the observer-go collector and the instrumented application,
exercise every API endpoint, then use the Observer MCP tools (preferred)
or REST API to confirm that each KPI's signal is present with correct
attributes. When running inside Cursor the MCP server is auto-started
via stdio -- no manual collector launch is needed for tool access.
Updates the Verified column in `.observe/inventory.md` to `OK` for
confirmed signals. Tears down all processes when done.

## When to Use

- After `/instrument` has added OTel code
- User wants to confirm telemetry is flowing end-to-end
- Debugging why signals are missing in the collector
- Re-verifying after code changes

**When NOT to use:** If `.observe/inventory.md` does not exist or has
no Status=OK rows, tell the user to run `/audit` and `/instrument`
first.

## Process

### Step 1 -- Read Inventory

1. Read `.observe/inventory.md`.
2. Extract KPI rows where Status=OK.
3. Build a checklist of Signal Names to validate (traces and metrics).
4. If no Status=OK rows, stop: "No instrumented KPIs to verify."

### Step 2 -- Start Observer

If the MCP server is already running (Cursor auto-starts it via stdio),
skip directly to Step 3 -- the MCP tools are available without a
separate collector process.

Otherwise start the full collector:

1. Build observer-go if the binary does not exist:
   ```
   make build
   ```
2. Start the collector in the background:
   ```
   ./observer-go/obstudio
   ```
3. Wait until `http://localhost:3000/api/query/stats` responds.
4. Clear any stale data: call `observer_clear` MCP tool or
   `DELETE /api/data`.

### Step 3 -- Start the Application

Start the instrumented app with fast-flush settings:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_SERVICE_NAME=<service-name>
OTEL_BSP_SCHEDULE_DELAY=100
OTEL_METRIC_EXPORT_INTERVAL=1000
```

Use the project's existing run command (Makefile, `uv run`, `go run`,
`npm start`, etc.). Start in the background.

### Step 4 -- Exercise the API

For each endpoint / operation identified in the inventory:

1. Determine method, path, and a minimal valid payload from the route
   definitions.
2. Fire the request using `curl`.
   - One happy-path call per CRUD operation.
   - One error-path call (e.g., GET a non-existent resource for 404).
3. Wait 3 seconds after the batch for the SDK to export.

### Step 5 -- Validate Traces

Query the Observer REST API (or MCP tools):

1. `GET /api/query/traces?serviceName=<service-name>` -- confirm traces
   exist.
2. For each trace, fetch detail via `GET /api/query/traces/{traceId}`:
   - **Root span** matches expected HTTP method + route.
   - **Child spans** for custom instrumentation are present.
   - **Span attributes** match OTel semantic conventions.
   - **Error spans** have `status.code == ERROR` and recorded exceptions.

MCP alternatives: `observer_traces_overview`, `observer_trace_detail`.

### Step 6 -- Validate Metrics

1. `GET /api/query/metrics?serviceName=<service-name>` -- list metrics.
2. For each KPI with `Metric: Yes` in inventory:
   - `GET /api/query/metrics?metricName=<signal-name>&serviceName=<svc>`
   - Confirm `dataPointCount >= 1`.
   - Confirm metric `type` matches (sum, histogram, gauge).
3. Verify auto-instrumented metrics exist (e.g.,
   `http.server.duration`, `http.server.active_requests`).

MCP alternatives: `observer_metrics_overview`, `observer_metric_detail`.

### Step 7 -- Validate Stats

Query `GET /api/query/stats` and confirm:
- `serviceNames` contains the expected service name.
- `spanCount > 0`, `traceCount > 0`.
- `metricCount > 0` if metrics are expected.

### Step 8 -- Update Inventory

For each KPI row in `.observe/inventory.md`:

1. If the Signal Name was found (trace span matched or metric matched
   with `dataPointCount >= 1`), set **Verified** to `OK`.
2. If expected but not found, leave Verified blank and add a comment.
3. Present a summary:

```
Verification Results
--------------------
Total KPIs:      N
Verified:        N  OK
Not verified:    N  (list signal names)
Coverage:        N%
```

### Step 9 -- Teardown

After verification is complete, **always** stop processes:

1. Kill the application process: `lsof -ti :<app-port> | xargs kill`.
2. Kill observer-go: `lsof -ti :3000 | xargs kill`.
3. Clean up temporary data (e.g., SQLite DBs created during the run).

Do not leave background processes running.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The spans are in the code, they must be there" | Code presence is not proof. Spans must appear in the collector with correct attributes. |
| "Verification takes too long" | Manual checking misses attribute errors and wrong metric types. Automation catches what eyes miss. |
| "Metrics will show up eventually" | If dataPointCount is 0 after exercising the API, the wiring is wrong. Waiting will not fix a code bug. |
| "I'll just check the Observer UI manually" | Manual spot-checks miss missing child spans, wrong status codes, and uncovered endpoints. |

## Red Flags

- Observer starts but no traces arrive after exercising APIs
- Traces exist but custom child spans are missing
- Metrics have wrong type (counter instead of histogram)
- Span attributes use non-standard names
- Error-path requests produce spans without ERROR status
- Processes left running after verification completes

## Verification

- [ ] Coverage percentage reported to user
- [ ] Observer REST API queried for every KPI signal name
- [ ] Verified column updated in `.observe/inventory.md`
- [ ] All processes (app + observer) killed after validation
- [ ] Temporary data cleaned up
