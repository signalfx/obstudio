---
name: splunk-audit
description: >-
  Analyze a codebase for observability readiness and generate a structured
  .observe/ directory with inventory, fault domains, and SLI/signal mappings.
  Use when the user types /splunk-audit, asks about observability gaps,
  wants to assess instrumentation coverage, says "what signals am I
  missing", "scan this service for observability", or asks about
  "observability readiness". Do NOT use for implementing code changes --
  use /splunk-instrument instead.
metadata:
  author: splunk-inc
  version: 0.0.1
  category: observability
---

# Audit -- Observability Gap Analysis

## Overview

Scan a service repository to discover its components, map fault domains,
identify KPIs using the four golden signals, and produce a structured
`.observe/` directory containing an inventory document and placeholder
directories for Terraform and alert artifacts. No code is modified --
this skill is read-only analysis.

## When to Use

- Starting observability work on a new or existing service
- Assessing current instrumentation coverage
- Generating the `.observe/inventory.md` that downstream skills
  (`/splunk-instrument`, `/splunk-verify`) consume
- Re-auditing after code changes to catch new gaps

**When NOT to use:** If `.observe/inventory.md` already exists and you
only need to implement instrumentation, use `/splunk-instrument` instead.

## Process

Execute each step in order. Present findings after each step before
proceeding.

### Step 1 -- Repository Discovery

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
5. **Load language guide**: read `skills/references/languages/<detected>.md`
   from the repository root. Only load the file matching the detected
   language. Do not load others.
6. Summarize to user: language, framework, existing instrumentation
   (if any), entry points, and config mechanism.

### Step 2 -- Component Mapping

Identify all components the service interacts with and its internal
layers.

**External components** -- search for client libraries, connection
strings, driver imports for databases, caches, message queues,
external APIs, file storage, and auth providers.

**Internal layers** -- identify architectural tiers: presentation
(HTTP/gRPC), business logic, data access, background workers,
and middleware.

Present a component interaction list or diagram. Use a mermaid diagram
when there are 3+ external components.

### Step 3 -- Fault Domain Analysis

Read [fault-domain-patterns.md](../references/fault-domain-patterns.md)
for common patterns organized by component type.

For each component from Step 2, assess:
- **Connectivity**: connection drops, DNS failures, TLS issues
- **Latency**: slow operations, timeouts, backpressure
- **Data integrity**: corruption, deserialization errors, schema drift
- **Capacity**: pool exhaustion, memory pressure, queue growth, disk full
- **Availability**: single point of failure, failover path

Also consider cross-cutting SRE concerns: cascading failures, retry
storms, poison pill messages, stale state, cold start.

Present fault domains grouped by component as a table.

### Step 4 -- SLI Identification

For each component and fault domain, identify Service Level Indicators
using the four golden signals:

| Golden Signal | Question                                    |
|---------------|---------------------------------------------|
| Latency       | How long do operations take? (p50, p95, p99) |
| Traffic       | How much demand is the system handling?      |
| Errors        | What is the rate of failed requests?         |
| Saturation    | How full are resources? (pools, queues, mem) |

Also identify business-logic SLIs specific to the domain.

### Step 5 -- SLI Definitions and Signal Tables

Read [signal-mapping-guide.md](../references/signal-mapping-guide.md)
for guidance on mapping SLIs to OTel signal types.

Build four tables using the schema from
[observability-template.md](../references/observability-template.md):
SLI Definitions, Spans, Metrics, and Logs. Each signal row must include
Signal Name, Category (`OOB`/`Custom`/`Derived`), Component, SLIs,
Status (blank for gaps, `OK` for instrumented), and Verified (blank).

Present coverage summaries per signal type. Highlight the gap count as
the implementation scope.

### Step 6 -- Generate or Update .observe/ Directory

This directory is the single output artifact of the audit skill and the
input for downstream skills (`/splunk-instrument`, `/splunk-verify`).

#### If `.observe/inventory.md` already exists

1. Read the existing `inventory.md`.
2. Parse the existing Spans, Metrics, and Logs tables to extract the
   list of previously tracked signals with their Status, Signal Name,
   Category, and Component.
3. Compare against the signals identified in Steps 4-5 of this run:
   - **New signals**: add to the appropriate table with blank Status.
   - **Removed signals**: remove from the table, note in a changelog
     comment at the top.
   - **Changed signals**: update the relevant columns.
   - **Unchanged signals**: preserve as-is, including Status and
     Verified values.
4. Update the SLI Definitions table if new SLIs were identified or
   existing ones changed.
5. Update the Architecture diagram and Components table if dependencies
   changed.
6. Update the Fault Domains table with any new components.
7. Append `<!-- Last updated: {date} -->`.
8. Present summary: N new signals, N removed, N status changes.

#### If `.observe/inventory.md` does not exist (first run)

Read [observability-template.md](../references/observability-template.md)
for the inventory document template.

Create the `.observe/` directory at the repository root:

```
.observe/
  inventory.md              # Audit results: overview, components, fault
                            #   domains, SLIs, signal tables, configurability
```

Create `.observe/inventory.md` with sections:
1. Service Overview
2. Architecture (component diagram from Step 2)
3. Components
4. Fault Domains (from Step 3)
5. SLI Definitions (from Step 5)
6. Spans (from Step 5)
7. Metrics (from Step 5)
8. Logs (from Step 5)
9. Configurability

## Examples

**New service:** User says "Scan this Flask app" -> detect Python+Flask, load language guide, find SQLAlchemy+Redis+3 endpoints, map fault domains, identify 8 SLIs, generate 12 signals (all Status blank). Result: `.observe/` created.

**Re-audit:** User says "I added Kafka, re-audit" -> read existing inventory (10 signals, 8 OK), detect new dependency, add 4 new blank-Status signals preserving existing Status values. Result: inventory updated with changelog.

## Red Flags

- Fewer than 3 SLIs identified for a service with external dependencies
- No Custom-category signals when the service has domain logic
- Missing fault domains for any external component
- Audit completed but `.observe/inventory.md` not generated
- All signal tables have no entries with blank Status (nothing to instrument)
- Metrics table missing Derived entries when OOB spans exist

## Troubleshooting

**No dependency manifest found:** Ask the user which subdirectory contains the service, then re-scan from that root.

**Inventory already exists:** Follow the merge path (Step 6). Preserve existing Status/Verified values and append new signals.

**Zero signals despite dependencies:** Check for dynamic imports or config-driven clients. Ask the user to confirm which components are actively used.

## Verification

- [ ] `.observe/inventory.md` exists with all 11 sections
- [ ] SLI Definitions table lists every identified SLI with golden signal type
- [ ] Spans, Metrics, and Logs tables have entries for every component boundary found in Step 2
- [ ] Every signal row has an SLIs column referencing at least one SLI
- [ ] Architecture diagram is present and matches discovered components
- [ ] Gap count (blank Status rows across all signal tables) is reported to the user
