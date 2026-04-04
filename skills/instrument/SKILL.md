---
name: instrument
description: >-
  Implement OpenTelemetry instrumentation for a service based on its
  .observe/inventory.md. Adds auto-instrumentation libraries and custom
  spans/metrics for every gap. Use when the user types /instrument, asks
  to add OTel, or says "instrument this service".
---

# Instrument -- OTel Implementation

## Overview

Read the `.observe/inventory.md` produced by `/audit`, identify KPIs
with blank Status, and implement OpenTelemetry instrumentation for each
gap. Installs auto-instrumentation libraries for standard KPIs and
generates custom spans and metrics for business KPIs. Updates the
Status column to `OK` after implementation.

## When to Use

- `.observe/inventory.md` exists and has KPIs with blank Status
- User asks to "instrument this service" or "add OpenTelemetry"
- After running `/audit` to implement the identified gaps

**When NOT to use:** If no `.observe/inventory.md` exists, tell the
user to run `/audit` first. If all Status columns are already `OK`,
suggest `/verify` instead.

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
- Use OTel semantic conventions for span names, attributes, and metric
  names. Custom attribute names: `{domain}.{noun}.{adjective}` format.
- Span names must be low-cardinality (no IDs, no variable path segments).
- Metric attributes must avoid high cardinality.
- Preserve existing env-var patterns for telemetry config instead of
  hardcoding endpoints.
- If the app is a library, provide an opt-in setup path rather than
  forcing SDK initialization on import.
- Keep the codebase idiomatic. Match the repo's dependency manager,
  config style, and lifecycle patterns.

### Step 4 -- Update Inventory

1. For each implemented KPI, set the Status column to `OK` in
   `.observe/inventory.md`.
2. Update the coverage summary line.
3. Present a summary: N KPIs instrumented, N remaining gaps (if any).

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

## Verification

- [ ] Every KPI that had blank Status now shows `OK` in inventory
- [ ] SDK init file exists and is imported by the entry point
- [ ] App compiles/starts without errors after instrumentation
- [ ] No duplicate SDK initialization paths
- [ ] Custom spans follow semantic conventions
- [ ] Error paths call `recordException` and set span status to ERROR
