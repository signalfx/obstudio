---

## name: splunk-instrument
description: >-
  Implement OpenTelemetry instrumentation for a service based on its
  .observe/inventory.md. Adds auto-instrumentation libraries and custom
  spans/metrics for every gap. Use when the user types /splunk-instrument,
  asks to "add OTel", "add tracing", "add metrics", "implement
  observability", "wire up telemetry", or says "instrument this service".
  Do NOT use if no .observe/inventory.md exists -- use /splunk-audit first.
metadata:
  author: splunk-inc
  version: 0.0.1
  category: observability

# Instrument -- OTel Implementation

## Overview

Read the `.observe/inventory.md` produced by `/splunk-audit`, identify
signals with blank Status across the Spans, Metrics, and Logs tables,
and implement OpenTelemetry instrumentation for each gap. Installs
auto-instrumentation libraries for OOB signals and generates custom
spans, metrics, and log events for Custom signals. Updates the Status
column to `OK` in the appropriate signal table after implementation.

## When to Use

- `.observe/inventory.md` exists and has signals with blank Status
- User asks to "instrument this service" or "add OpenTelemetry"
- After running `/splunk-audit` to implement the identified gaps

**When NOT to use:** If no `.observe/inventory.md` exists, tell the
user to run `/splunk-audit` first. If all Status columns across Spans,
Metrics, and Logs tables are already `OK`, suggest `/splunk-verify`
instead.

## Process

### Step 1 -- Detect Language and Load Guide

1. Detect the primary language from project files (`go.mod`,
  `requirements.txt`, `package.json`, etc.).
2. Read `skills/references/languages/<detected>.md`.
  Only load the matching language guide.
3. Check for existing OTel SDK initialization (imports, setup files).

### Step 2 -- Read Inventory

1. Read `.observe/inventory.md`.
2. Parse the Spans, Metrics, and Logs tables. Identify rows where
  Status is blank across all three tables.
3. If no blank rows exist, report "All signals are instrumented" and
  stop.
4. Group gaps by component for ordered implementation.

### Step 3 -- Implement Instrumentation

For each signal with blank Status:

1. **OOB-category signals**: consult the language guide's
  auto-instrumentation library map.
  - Install the package via the project's dependency manager.
  - Register the instrumentation in the SDK init file.
2. **Derived-category metrics**: no explicit emission needed. The
  backend computes these from span data. Ensure the corresponding
   OOB span is instrumented.
3. **Custom-category signals**: generate hand-written spans, metrics,
  or log events following the language guide's patterns.

#### Implementation Rules

- Do not initialize the SDK more than once per process.
- Find any existing OTel setup before adding new code. Extend it.
- Place OTel initialization code in a separate file.
- Minimize changes to existing code. Do not move functions between files.
- Do not create spans for trivial helpers. Only span real diagnostic
boundaries.
- Set span status to ERROR and call recordException on failed operations.
- Strictly adhere to OTel [semantic conventions](https://opentelemetry.io/docs/specs/semconv/)
for span and metric naming and attributes for domains where such semantic
conventions are defined.
- For domains where OTel semantic conventions exist emit required spans and metrics only, 
with required attributes only. Do not emit spans or metrics that are marked optional,
do not include attributes that are marked optional. Do not invent custom spans, 
metrics or attributes in domains where OTel semantic conventions exist.
- For custom attribute names use `{domain}.{noun}.{adjective}` format.
- Span names must be low-cardinality (no IDs, no variable path segments).
- Metric attributes must avoid high cardinality.
- Preserve existing env-var patterns for telemetry config instead of
hardcoding endpoints.
- If the app is a library, provide an opt-in setup path rather than
forcing SDK initialization on import.
- Keep the codebase idiomatic. Match the repo's dependency manager,
config style, and lifecycle patterns.
- Obtain OTel Tracer, Meter once during startup and reuse it. Do not call `getTracer` 
or `getMeter` in hot paths.
- Create metric instruments once during startup and reuse them. Do not create 
instruments in hot paths.
- Metric instruments must be created with appropriate unit and description parameters.

### Step 4 -- Update Inventory

1. For each implemented signal, set the Status column to `OK` in the
  appropriate signal table (Spans, Metrics, or Logs) in
   `.observe/inventory.md`.
2. Update the coverage summary lines for each signal type.
3. Present a summary: N spans, N metrics, N logs instrumented,
  N remaining gaps (if any).

### Step 5 -- Enable debugging in VS Code

This step is REQUIRED whenever `.vscode/launch.json` exists.

1. Check whether `.vscode/launch.json` exists.
2. If it exists, you MUST update at least one debug configuration for this service to include:
  - `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`
    - `OTEL_METRIC_EXPORT_INTERVAL=1000`
    - `OTEL_BSP_SCHEDULE_DELAY=100`
3. After editing, you MUST report:
  - which configuration was updated
    - the file path
    - whether the env vars were added or already present
4. If `.vscode/launch.json` exists and you do not update it, stop and explain why.
5. If `.vscode/launch.json` does not exist, explicitly report: `No .vscode/launch.json found; Step 5 skipped.`

## Examples

### Example 1: Python Flask with 3 gaps

**User says:** "Instrument this service"

**Actions:**

1. Detect Python, load `languages/python.md`
2. Read inventory: 2 blank-Status OOB spans, 1 blank-Status Custom metric
3. Install `opentelemetry-instrumentation-flask` and `opentelemetry-instrumentation-sqlalchemy` via `pyproject.toml`
4. Create `otel_setup.py` with SDK init, register both instrumentors
5. Add custom counter for `order.created.count` in the order handler
6. Update Spans and Metrics tables: 3 signals now Status=OK

**Result:** App starts with OTel, auto-instruments HTTP and DB, custom metric for business SLI.

### Example 2: Go service with existing OTel init

**User says:** "Add the missing metrics"

**Actions:**

1. Detect Go, load `languages/go.md`
2. Find existing `initOTel()` in `telemetry.go`
3. Read inventory: 1 blank-Status OOB metric (cache), 1 blank-Status Custom metric (queue depth)
4. Add `otelredis` wrapper registration in existing init
5. Add gauge callback for queue depth in worker package
6. Update Metrics table: 2 signals now Status=OK

**Result:** No duplicate init, existing setup extended with 2 new signals.

## Common Rationalizations


| Rationalization                                | Reality                                                                                       |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------- |
| "Auto-instrumentation covers everything"       | It covers HTTP/DB boundaries (OOB). Custom signals for business logic still need manual code. |
| "I'll add error recording later"               | Spans without `recordException` hide bugs in traces. Add it now.                              |
| "Semantic conventions don't matter internally" | Non-standard names break cross-service dashboards and alerts.                                 |


## Red Flags

- SDK initialized in multiple places
- Spans created for trivial getters/setters instead of real boundaries
- Hardcoded OTLP endpoints instead of env vars
- High-cardinality attributes on metrics (user IDs, request IDs)
- Custom-category signals skipped because "auto-instrumentation is enough"
- `recordException` missing from error handling paths
- New dependencies added without using the project's package manager

## Troubleshooting

**No inventory found:** Run `/splunk-audit` first to generate `.observe/inventory.md`.

**Duplicate SDK init:** Search for `TracerProvider`/`MeterProvider` across the codebase before adding a new init file. Extend the existing one.

**App fails to start after instrumentation:** Check OTel package version compatibility. For Python, ensure `otel_setup.py` is imported before the framework starts. For Node, ensure `--require` loads instrumentation before app code.

## Verification

- Every signal that had blank Status now shows `OK` in its table
- SDK init file exists and is imported by the entry point
- App compiles/starts without errors after instrumentation
- No duplicate SDK initialization paths
- Custom spans follow semantic conventions
- Error paths call `recordException` and set span status to ERROR
- Derived metrics have corresponding OOB spans instrumented
- If `.vscode/launch.json` exists, at least one service debug config includes the required OTEL env vars