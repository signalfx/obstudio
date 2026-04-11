---
name: splunk-instrument
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
---

# Instrument -- OTel Implementation

## Overview

Read the `.observe/inventory.md` produced by `/splunk-audit`, identify KPIs
with blank Status, and implement OpenTelemetry instrumentation for each
gap. Installs auto-instrumentation libraries for standard KPIs and
generates custom spans and metrics for business KPIs. Updates the
Status column to `OK` after implementation.

## When to Use

- `.observe/inventory.md` exists and has KPIs with blank Status
- User asks to "instrument this service" or "add OpenTelemetry"
- After running `/splunk-audit` to implement the identified gaps

**When NOT to use:** If no `.observe/inventory.md` exists, tell the
user to run `/splunk-audit` first. If all Status columns are already `OK`,
suggest `/splunk-verify` instead.

## Process

### Step 1 -- Detect Language and Load Guide

1. Detect the primary language from project files (`go.mod`,
   `requirements.txt`, `package.json`, etc.).
2. Read `skills/references/languages/<detected>.md`.
   Only load the matching language guide.
3. Check for existing OTel SDK initialization (imports, setup files).

### Step 2 -- Read Inventory

1. Read `.observe/inventory.md`.
2. Parse the KPI table. Identify rows where Status is blank.
3. If no blank rows exist, report "All KPIs are instrumented" and stop.
4. Group gaps by component for ordered implementation.

### Step 3 -- Implement Instrumentation

For each KPI with blank Status:

1. **Check OOB coverage**: consult the language guide's
   auto-instrumentation library map.
2. **If OOB library exists** and covers the KPI:
   - Install the package via the project's dependency manager.
   - Register the instrumentation in the SDK init file.
3. **If no OOB library** or coverage is too coarse:
   - Generate custom spans or metrics following the language guide's
     patterns.
4. **Business-class KPIs** (`Class: Business`): always generate custom
   instrumentation.

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

1. For each implemented KPI, set the Status column to `OK` in
   `.observe/inventory.md`.
2. Update the coverage summary line.
3. Present a summary: N KPIs instrumented, N remaining gaps (if any).

## Examples

### Example 1: Python Flask with 3 gaps

**User says:** "Instrument this service"

**Actions:**
1. Detect Python, load `languages/python.md`
2. Read inventory: 3 blank-Status KPIs (HTTP latency, DB query duration, order count)
3. Install `opentelemetry-instrumentation-flask` and `opentelemetry-instrumentation-sqlalchemy` via `pyproject.toml`
4. Create `otel_setup.py` with SDK init, register both instrumentors
5. Add custom histogram for `order.processing.duration` in the order handler
6. Update inventory: 3 KPIs now Status=OK

**Result:** App starts with OTel, auto-instruments HTTP and DB, custom metric for business KPI.

### Example 2: Go service with existing OTel init

**User says:** "Add the missing metrics"

**Actions:**
1. Detect Go, load `languages/go.md`
2. Find existing `initOTel()` in `telemetry.go`
3. Read inventory: 2 blank-Status KPIs (cache hit ratio, queue depth)
4. Add `otelredis` wrapper registration in existing init
5. Add gauge callback for queue depth in worker package
6. Update inventory: 2 KPIs now Status=OK

**Result:** No duplicate init, existing setup extended with 2 new signals.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Auto-instrumentation covers everything" | It covers HTTP/DB boundaries. Business KPIs and custom domain logic need manual spans. |
| "This service is too small for custom metrics" | If it has a KPI, it needs a signal. Size is irrelevant. |
| "I'll add error recording later" | Spans without `recordException` hide bugs in traces. Add it now. |
| "Semantic conventions don't matter internally" | Non-standard names break cross-service dashboards and alerts. |
| "One SDK init file is overkill for a small app" | Scattering init across files causes double-init bugs and makes teardown unreliable. |

## Red Flags

- SDK initialized in multiple places
- Spans created for trivial getters/setters instead of real boundaries
- Hardcoded OTLP endpoints instead of env vars
- High-cardinality attributes on metrics (user IDs, request IDs)
- Business KPIs skipped because "auto-instrumentation is enough"
- `recordException` missing from error handling paths
- New dependencies added without using the project's package manager

## Troubleshooting

**Error:** "No .observe/inventory.md found"
**Cause:** The audit step has not been run yet.
**Solution:** Run `/splunk-audit` first to generate the inventory.

**Error:** SDK initialized in multiple places after instrumentation
**Cause:** Existing init was not detected (different file name, conditional import).
**Solution:** Search for `TracerProvider`, `MeterProvider`, or SDK setup calls across the codebase before adding a new init file. Extend the existing one.

**Error:** App fails to start after adding auto-instrumentation
**Cause:** Version conflict between OTel SDK and instrumentation library, or import order issue.
**Solution:** Check that all `opentelemetry-*` packages use compatible versions. For Python, ensure `otel_setup.py` is imported before the framework starts. For Node, ensure `--require` flag loads instrumentation before app code.

## Verification

- [ ] Every KPI that had blank Status now shows `OK` in inventory
- [ ] SDK init file exists and is imported by the entry point
- [ ] App compiles/starts without errors after instrumentation
- [ ] No duplicate SDK initialization paths
- [ ] Custom spans follow semantic conventions
- [ ] Error paths call `recordException` and set span status to ERROR
