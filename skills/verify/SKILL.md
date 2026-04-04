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

Exercise every API endpoint and use the Observer MCP tools (preferred)
or REST API to confirm that each KPI's signal is present with correct
attributes. Any MCP-capable agent (Cursor, Claude Code, Windsurf,
Codex, etc.) can auto-start the Observer via stdio -- when the MCP
server is available, no manual collector build or launch is needed.
Updates the Verified column in `.observe/inventory.md` to `OK` for
confirmed signals.

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

**MCP path (preferred):** The Observer MCP server may already be
running -- any MCP-capable agent (Cursor, Claude Code, Windsurf,
Codex, etc.) can auto-start it via stdio. Check for the `obstudio`
MCP server and its tools (`observer_clear`,
`observer_traces_overview`, `observer_trace_detail`,
`observer_metrics_overview`, `observer_metric_detail`). If these
tools are available, **skip directly to Step 3** -- no manual build
or process management is needed. The MCP server *is* the collector;
building the binary separately is redundant and wastes time. Clear
stale data by calling `observer_clear`.

> **Do not build or start the collector when MCP tools are available.**
> The MCP server already embeds the OTLP receiver, in-memory store,
> and query API. Building `make build` or spawning `./build/obstudio`
> when the MCP server is running will fail on port conflicts and is
> the single most common mistake agents make in this step.

**Manual fallback:** Only if MCP tools are not available (i.e., the
agent has no MCP server configured), build and start the collector:

1. Build observer-go if the binary does not exist:
   ```
   make build
   ```
2. Start the collector in the background:
   ```
   ./build/obstudio
   ```
3. Wait until `http://localhost:3000/api/query/stats` responds.
4. Clear any stale data: `DELETE /api/data`.

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

Use `observer_traces_overview` (MCP) to list traces, then
`observer_trace_detail` for each trace:

1. `observer_traces_overview(serviceName=<service-name>)` -- confirm
   traces exist.
2. For each trace, fetch detail via
   `observer_trace_detail(traceId=<id>)`:
   - **Root span** matches expected HTTP method + route.
   - **Child spans** for custom instrumentation are present.
   - **Span attributes** match OTel semantic conventions.
   - **Error spans** have `status.code == ERROR` and recorded exceptions.

REST fallback: `GET /api/query/traces?serviceName=<service-name>` and
`GET /api/query/traces/{traceId}`.

### Step 6 -- Validate Metrics

Use `observer_metrics_overview` (MCP) to list metrics, then
`observer_metric_detail` for each KPI:

1. `observer_metrics_overview(serviceName=<service-name>)` -- list all
   metrics.
2. For each KPI with `Metric: Yes` in inventory:
   - `observer_metric_detail(metricName=<signal-name>, serviceName=<svc>)`
   - Confirm `dataPointCount >= 1`.
   - Confirm metric `type` matches (sum/counter, histogram, gauge).
3. Verify auto-instrumented metrics exist (e.g.,
   `http.server.duration`, `http.server.active_requests`).

REST fallback: `GET /api/query/metrics?serviceName=<service-name>` and
`GET /api/query/metrics?metricName=<name>&serviceName=<svc>`.

### Step 7 -- Validate Stats

Use `observer_metrics_overview` and `observer_traces_overview` to
confirm:
- Traces exist for the expected service name.
- `spanCount > 0`, `traceCount > 0`.
- Metric count > 0 if metrics are expected.

REST fallback: `GET /api/query/stats`.

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

### Step 9 -- Dashboard Review and Teardown

After verification is complete, prompt the user before shutting down:

> "The service is running and telemetry is flowing. You can view
> traces and metrics in the Observer dashboard at
> http://localhost:3000. Take a look and let me know when you're
> done -- I'll shut down the test harness."

Do **not** kill the service process until the user confirms they are
finished reviewing.

Once the user confirms, stop the **application process only**:

1. Kill the application process: `lsof -ti :<app-port> | xargs kill`.
2. Clean up temporary data (e.g., SQLite DBs created during the run).

**Do not kill the Observer / MCP server.** On the MCP path the agent
runtime manages the server lifecycle. On the manual-fallback path,
also kill observer-go: `lsof -ti :3000 | xargs kill`.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I need to build the binary first" | If the MCP server is running, it *is* the collector. Building and spawning a second instance causes port conflicts and wastes time. Check for MCP tools before reaching for `make build`. |
| "The spans are in the code, they must be there" | Code presence is not proof. Spans must appear in the collector with correct attributes. |
| "Verification takes too long" | Manual checking misses attribute errors and wrong metric types. Automation catches what eyes miss. |
| "Metrics will show up eventually" | If dataPointCount is 0 after exercising the API, the wiring is wrong. Waiting will not fix a code bug. |
| "I'll just check the Observer UI manually" | Manual spot-checks miss missing child spans, wrong status codes, and uncovered endpoints. |

## Red Flags

- Agent builds the binary when MCP tools are already available
- Port conflicts from spawning a second collector instance
- Observer starts but no traces arrive after exercising APIs
- Traces exist but custom child spans are missing
- Metrics have wrong type (counter instead of histogram)
- Span attributes use non-standard names
- Error-path requests produce spans without ERROR status
- Application killed before user had a chance to view the dashboard
- Processes left running after verification completes

## Verification

- [ ] MCP tools checked before attempting to build/start collector
- [ ] Coverage percentage reported to user
- [ ] Observer MCP tools (or REST API) queried for every KPI signal
- [ ] Verified column updated in `.observe/inventory.md`
- [ ] User offered dashboard review before teardown
- [ ] Application process killed after user confirms
- [ ] Temporary data cleaned up
