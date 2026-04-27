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
  version: 0.1.0
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
3. Load the matching language reference from `skills/references/languages/<detected>.md` to know what auto-instrumentation packages are available for the detected dependencies.

### Step 2 -- Instrumentation Assessment

Check for existing OTel instrumentation and identify gaps.

**Existing instrumentation** -- search for:
- OTel SDK initialization files (`otel_setup.py`, `instrumentation.ts`, `otel.go`, etc.)
- OTel imports/dependencies (`opentelemetry`, `otel`, `otlp`, `go.opentelemetry.io`)
- Auto-instrumentation packages matching detected frameworks/clients
- `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT` in env files or configs
- Tracer/Meter creation calls in application code

**Dependencies without instrumentation** -- for each dependency detected in Step 1:
- Check if a matching auto-instrumentation package is installed
- Use the language reference's auto-instrumentation library map as the checklist
- Flag any dependency that has an available auto-instrumentation package but is not instrumented

**Anti-patterns** -- flag any of these:
- Multiple SDK initializations in the same process
- Hardcoded OTLP endpoints instead of env vars
- Tracer/Meter created in hot paths instead of at startup
- High-cardinality attributes on metrics (user IDs, request IDs)
- Missing `recordException` in error handling paths
- Custom span names with variable segments (IDs, paths)

### Step 3 -- Report

Present findings to the user in chat. Use this structure:

```
## Observability Scan: {service-name}

**Language:** {language}  |  **Framework:** {framework}

### Current Instrumentation
- {what's already set up -- SDK init, auto-instrumentation packages, custom spans}

### Coverage Gaps
- {dependencies without matching auto-instrumentation}
- {error paths missing recordException}
- {other gaps}

### Anti-Patterns
- {any issues found, or "None detected"}

### Recommendation
- {one-line summary: "Run $otel-instrument to add auto-instrumentation for X, Y, Z"
   or "Instrumentation looks complete -- consider $otel-instrument for custom business metrics"}
```

If the user asks for a persistent report, write a brief `.observe/report.md` with the same content.

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

## Troubleshooting

**No dependency manifest found:** Ask the user which subdirectory contains the service, then re-scan from that root.

**Multiple languages detected:** Ask which service to audit, or audit each independently.
