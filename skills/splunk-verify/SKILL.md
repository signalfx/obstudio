---
name: splunk-verify
description: >-
  Validate that instrumented telemetry is actually flowing by starting
  the Observer collector, exercising the service APIs, and checking
  traces and metrics against the .observe/inventory.md. Use when the
  user types /splunk-verify, asks to "validate instrumentation", "check
  if telemetry is flowing", "test my traces", "are my metrics working",
  or wants to confirm OTel signals are reaching the collector. Do NOT
  use if no instrumented KPIs exist -- use /splunk-instrument first.
metadata:
  author: splunk-inc
  version: 0.0.1
  category: observability
---

# Verify -- Telemetry Validation

## Overview

Exercise every API endpoint and use the Observer REST API to confirm
that each signal in the Spans, Metrics, and Logs tables is present
with correct attributes. The Observer MCP server auto-starts via stdio
in MCP-capable agents (Cursor, Claude Code, Windsurf, Codex, etc.) --
when it is running, no manual collector build or launch is needed.
Updates the Verified column in the appropriate signal table in
`.observe/inventory.md` to `OK` for confirmed signals.

> **NOTE:** MCP query tools are under active development and may
> return null. **Always use the REST API** (`http://localhost:3000`)
> for trace and metric validation until MCP tools are fully
> operational. The MCP server still functions as the collector (OTLP
> receiver) even when query tools are not yet working.

## When to Use

- After `/splunk-instrument` has added OTel code
- User wants to confirm telemetry is flowing end-to-end
- Debugging why signals are missing in the collector
- Re-verifying after code changes

**When NOT to use:** If `.observe/inventory.md` does not exist or has
no Status=OK rows across the Spans, Metrics, and Logs tables, tell
the user to run `/splunk-audit` and `/splunk-instrument` first.

## Process

### Step 1 -- Read Inventory

1. Read `.observe/inventory.md`.
2. Parse the Spans, Metrics, and Logs tables. Extract rows where
   Status=OK.
3. Build a checklist of Signal Names to validate, grouped by signal
   type (spans, metrics, logs).
4. If no Status=OK rows across any table, stop: "No instrumented
   signals to verify."

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

### Step 5 -- Validate Spans

Query the REST API to list traces, then check each span from the
Spans table:

1. `GET /api/query/traces?serviceName=<service-name>` -- confirm
   traces exist.
2. For each Signal Name in the Spans table with Status=OK, fetch
   trace detail via `GET /api/query/traces/{traceId}`:
   - **OOB spans**: root span matches expected HTTP method + route.
   - **Custom spans**: child spans for custom instrumentation are
     present.
   - **Span attributes** match OTel semantic conventions.
   - **Error spans** have `status.code == ERROR` and recorded
     exceptions.

Future MCP: once MCP query tools are operational, use
`observer_traces_overview` and `observer_trace_detail` instead.

### Step 6 -- Validate Metrics

Query the REST API to list metrics, then inspect each entry from the
Metrics table:

1. `GET /api/query/metrics?serviceName=<service-name>` -- list all
   metrics.
2. For each Signal Name in the Metrics table with Status=OK:
   - `GET /api/query/metrics?metricName=<signal-name>&serviceName=<svc>`
   - Confirm `dataPointCount >= 1`.
   - Confirm metric type matches the Type column (Counter, Histogram,
     Gauge).
   - For Derived-category metrics, verify the backend is computing
     them from span data.
3. Verify OOB-category metrics exist (e.g.,
   `http.server.duration`, `http.server.active_requests`).

Future MCP: once MCP query tools are operational, use
`observer_metrics_overview` and `observer_metric_detail` instead.

### Step 7 -- Validate Stats

Query `GET /api/query/stats` and confirm:
- Traces exist for the expected service name.
- `spanCount > 0`, `traceCount > 0`.
- Metric count > 0 if metrics are expected.

### Step 8 -- Update Inventory

For each signal row across the Spans, Metrics, and Logs tables in
`.observe/inventory.md`:

1. If the Signal Name was found (span matched, metric matched with
   `dataPointCount >= 1`, or log event confirmed), set **Verified**
   to `OK` in the appropriate signal table.
2. If expected but not found, leave Verified blank and add a comment.
3. Present a summary:

```
Verification Results
--------------------
Spans:     N/N verified
Metrics:   N/N verified
Logs:      N/N verified
Total:     N/N signals verified (N%)
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

## Examples

### Example 1: Verify a Flask app with MCP server running

**User says:** "Check if my traces are flowing"

**Actions:**
1. Read inventory: 3 Spans, 6 Metrics, 1 Log with Status=OK
2. Confirm MCP server is running via `GET /api/query/stats`
3. Clear stale data via `DELETE /api/data`
4. Start Flask app with `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`
5. Fire `curl` requests: `POST /items`, `GET /items`, `GET /items/999` (404)
6. Query REST API: traces found, all spans present, error span has ERROR status
7. Query metrics: OOB and Custom metrics present, Derived metrics computed
8. Update Spans, Metrics, Logs tables: 10/10 Verified=OK

**Result:** All signals confirmed flowing. User prompted to review dashboard at localhost:3000.

### Example 2: Partial verification failure

**User says:** "Validate my instrumentation"

**Actions:**
1. Read inventory: 2 Spans, 4 Metrics with Status=OK
2. Exercise APIs, query Observer
3. Spans verified, but Custom metric `cache.hit_ratio` missing (dataPointCount=0)
4. Update tables: Spans 2/2, Metrics 3/4 Verified=OK

**Result:** 83% coverage reported. User informed that cache metric wiring needs debugging.

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

## Troubleshooting

**Error:** Port 4318 or 3000 already in use
**Cause:** A second collector instance was started, or a previous run was not cleaned up.
**Solution:** Check `GET http://localhost:3000/api/query/stats` first. If it responds, the MCP server is already running. Do not build or start another collector.

**Error:** Traces exist but custom child spans are missing
**Cause:** Custom instrumentation code is not reached during test requests, or context propagation is broken.
**Solution:** Verify the test request exercises the code path containing the custom span. Check that the parent context is passed correctly (especially in Go goroutines or Python async handlers).

**Error:** Metrics have dataPointCount=0 after exercising APIs
**Cause:** Metric export interval too long, or the metric is registered but never recorded.
**Solution:** Ensure `OTEL_METRIC_EXPORT_INTERVAL=1000` is set. Check that the code path recording the metric is actually hit by the test requests. Verify the metric instrument type matches the recording method.

## Verification

- [ ] REST API (`/api/query/stats`) checked before attempting to build/start collector
- [ ] Coverage percentage reported to user per signal type and total
- [ ] Observer REST API queried for every signal in Spans, Metrics, and Logs tables
- [ ] Verified column updated in the appropriate signal table in `.observe/inventory.md`
- [ ] User offered dashboard review before teardown
- [ ] Application process killed after user confirms
- [ ] Temporary data cleaned up
