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

Exercise every API endpoint and use the Observer REST API to confirm
that each KPI's signal is present with correct attributes. The
Observer MCP server auto-starts via stdio in MCP-capable agents
(Cursor, Claude Code, Windsurf, Codex, etc.) -- when it is running,
no manual collector build or launch is needed. Updates the Verified
column in `.observe/inventory.md` to `OK` for confirmed signals.

> **NOTE:** MCP query tools are under active development and may
> return null. **Always use the REST API** (`http://localhost:3000`)
> for trace and metric validation until MCP tools are fully
> operational. The MCP server still functions as the collector (OTLP
> receiver) even when query tools are not yet working.

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

**MCP server path (preferred):** If the `obstudio` MCP server is
configured in the agent, it auto-starts via stdio and *is* the
collector -- no manual build or process management is needed.
Verify the collector is reachable by hitting the REST API:

```
curl -s http://localhost:3000/api/query/stats
```

Clear stale data: `curl -s -X DELETE http://localhost:3000/api/data`.

> **Do not build or start the collector when the MCP server is running.**
> The MCP server already embeds the OTLP receiver, in-memory store,
> and query API. Building `make build` or spawning `./build/obstudio`
> when the MCP server is running will fail on port conflicts and is
> the single most common mistake agents make in this step.

**Manual fallback:** Only if no MCP server is configured, build and
start the collector:

1. Build observer if the binary does not exist:
   ```
   make build
   ```
2. Start the collector in the background:
   ```
   ./build/obstudio
   ```
3. Wait until `http://localhost:3000/api/query/stats` responds.
4. Clear any stale data: `curl -s -X DELETE http://localhost:3000/api/data`.

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

Query the REST API to list traces, then fetch detail for each:

1. `GET /api/query/traces?serviceName=<service-name>` -- confirm
   traces exist.
2. For each trace, fetch detail via
   `GET /api/query/traces/{traceId}`:
   - **Root span** matches expected HTTP method + route.
   - **Child spans** for custom instrumentation are present.
   - **Span attributes** match OTel semantic conventions.
   - **Error spans** have `status.code == ERROR` and recorded exceptions.

Future MCP: once MCP query tools are operational, use
`observer_traces_overview` and `observer_trace_detail` instead.

### Step 6 -- Validate Metrics

Query the REST API to list metrics, then inspect each KPI:

1. `GET /api/query/metrics?serviceName=<service-name>` -- list all
   metrics.
2. For each KPI with `Metric: Yes` in inventory:
   - `GET /api/query/metrics?metricName=<signal-name>&serviceName=<svc>`
   - Confirm `dataPointCount >= 1`.
   - Confirm metric `type` matches (sum/counter, histogram, gauge).
3. Verify auto-instrumented metrics exist (e.g.,
   `http.server.duration`, `http.server.active_requests`).

Future MCP: once MCP query tools are operational, use
`observer_metrics_overview` and `observer_metric_detail` instead.

### Step 7 -- Validate Stats

Query `GET /api/query/stats` and confirm:
- Traces exist for the expected service name.
- `spanCount > 0`, `traceCount > 0`.
- Metric count > 0 if metrics are expected.

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

Once the user confirms, tear down:

1. Kill the application process: `lsof -ti :<app-port> | xargs kill`.
2. Clear the Observer store so the next run starts fresh:
   `curl -s -X DELETE http://localhost:3000/api/data`. The MCP
   server is never brought down between runs, so stale data from
   this session will pollute the next verification if not cleared.
3. Clean up temporary data (e.g., SQLite DBs created during the run).

**Do not kill the Observer / MCP server.** On the MCP path the agent
runtime manages the server lifecycle. On the manual-fallback path,
also kill observer: `lsof -ti :3000 | xargs kill`.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I need to build the binary first" | If the MCP server is running, it *is* the collector. Building and spawning a second instance causes port conflicts and wastes time. Check `GET /api/query/stats` before reaching for `make build`. |
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

- [ ] REST API (`/api/query/stats`) checked before attempting to build/start collector
- [ ] Coverage percentage reported to user
- [ ] Observer REST API queried for every KPI signal
- [ ] Verified column updated in `.observe/inventory.md`
- [ ] User offered dashboard review before teardown
- [ ] Application process killed after user confirms
- [ ] Temporary data cleaned up
