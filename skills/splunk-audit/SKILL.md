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
  (`/splunk-instrument`, `/splunk-verify`, `/splunk-provision`) consume
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
strings, driver imports:
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

Cross-cutting SRE concerns:
- Cascading failures, retry storms, thundering herd
- Poison pill messages, head-of-line blocking
- Stale state, split brain, clock skew
- Cold start, deployment rollback impact

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

Build four tables: an SLI Definitions table and one table per signal
type (Spans, Metrics, Logs).

#### 5a. SLI Definitions

| Column        | Description                                           |
|---------------|-------------------------------------------------------|
| SLI           | Name of the Service Level Indicator                   |
| Golden Signal | Latency / Traffic / Errors / Saturation               |
| Component     | Which component it belongs to                         |
| Target        | Threshold target (e.g., `p99 < 500ms`) or `--`       |

#### 5b. Spans

| Column      | Description                                            |
|-------------|--------------------------------------------------------|
| Signal Name | Span name pattern (e.g., `HTTP {method} {route}`)     |
| Category    | `OOB` (auto-instrumentation) or `Custom` (hand-written)|
| Component   | Which component it belongs to                          |
| SLIs        | Comma-separated SLI names this span feeds              |
| Status      | `OK` if instrumented, blank if missing                 |
| Verified    | Blank initially; set to `OK` by `/splunk-verify`       |

#### 5c. Metrics

| Column      | Description                                            |
|-------------|--------------------------------------------------------|
| Signal Name | Metric name (e.g., `http.server.request.duration`)     |
| Type        | Counter / Histogram / Gauge / UpDownCounter            |
| Category    | `OOB` / `Custom` / `Derived`                          |
| Component   | Which component it belongs to                          |
| SLIs        | Comma-separated SLI names this metric feeds            |
| Unit        | Metric unit (e.g., `s`, `{requests}`, `{bytes}`)      |
| Status      | `OK` if instrumented, blank if missing                 |
| Verified    | Blank initially; set to `OK` by `/splunk-verify`       |

#### 5d. Logs

| Column      | Description                                            |
|-------------|--------------------------------------------------------|
| Signal Name | Log event name pattern                                 |
| Category    | `OOB` or `Custom`                                      |
| Component   | Which component it belongs to                          |
| SLIs        | Comma-separated SLI names this log feeds               |
| Level       | Log level (ERROR, WARN, INFO, DEBUG)                   |
| Status      | `OK` if instrumented, blank if missing                 |
| Verified    | Blank initially; set to `OK` by `/splunk-verify`       |

#### Categories

- **OOB**: out-of-the-box from auto-instrumentation libraries, zero custom code
- **Custom**: requires hand-written instrumentation code
- **Derived**: backend computes from span data (metrics only); no explicit emission needed

Present coverage summaries per signal type. Highlight the gap count as
the implementation scope.

### Step 6 -- Generate or Update .observe/ Directory

This directory is the single output artifact of the audit skill and the
input for downstream skills (`/splunk-instrument`, `/splunk-verify`, `/splunk-provision`).

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
  terraform/                # (placeholder) Splunk O11y Cloud terraform
  alerts/                   # (placeholder) Alert rule definitions
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
10. Alerts (placeholder -- populated by `/splunk-provision`)
11. Dashboard Recommendations (placeholder -- populated by `/splunk-provision`)

Create `terraform/` and `alerts/` directories with brief READMEs noting
they will be populated by the `/splunk-provision` skill.

## Examples

### Example 1: New Flask service

**User says:** "Scan this Flask app for observability gaps"

**Actions:**
1. Detect Python + Flask from `requirements.txt`
2. Load `skills/references/languages/python.md`
3. Find SQLAlchemy, Redis, and 3 HTTP endpoints
4. Map fault domains (DB connectivity/latency, cache availability, HTTP errors)
5. Identify 8 SLIs across 4 golden signals
6. Generate signal tables: 3 Spans (2 OOB, 1 Custom), 8 Metrics (3 OOB, 2 Derived, 3 Custom), 1 Log (Custom)

**Result:** `.observe/` directory created with `inventory.md` (12 signals, all Status blank), `terraform/`, and `alerts/` placeholders.

### Example 2: Re-audit after adding a Kafka consumer

**User says:** "I added a Kafka consumer, re-audit for new gaps"

**Actions:**
1. Read existing `.observe/inventory.md` (10 signals, 8 Status=OK)
2. Detect new `confluent-kafka` dependency
3. Add new SLIs for Kafka (consumer lag, processing latency, error rate, partition saturation)
4. Add 4 new signals across Spans and Metrics tables, preserving existing Status values

**Result:** Inventory updated with 4 new blank-Status signals. Changelog comment added.

## Red Flags

- Fewer than 3 SLIs identified for a service with external dependencies
- No Custom-category signals when the service has domain logic
- Missing fault domains for any external component
- Audit completed but `.observe/inventory.md` not generated
- All signal tables have no entries with blank Status (nothing to instrument)
- Metrics table missing Derived entries when OOB spans exist

## Troubleshooting

**Error:** No dependency manifest found (no `requirements.txt`, `go.mod`, etc.)
**Cause:** The repository uses an uncommon layout or monorepo structure.
**Solution:** Ask the user which subdirectory contains the service, then re-scan from that root.

**Error:** Inventory already exists but user ran `/splunk-audit` again
**Cause:** User may want a re-audit or may have run the wrong command.
**Solution:** Follow the merge path (Step 6, "If `.observe/inventory.md` already exists"). Preserve existing Status/Verified values and append new signals.

**Error:** Zero signals identified despite external dependencies
**Cause:** Dependencies detected but no active usage found in code (e.g., imported but unused).
**Solution:** Check for dynamic imports, factory patterns, or configuration-driven clients. Ask the user to confirm which components are actively used.

## Verification

- [ ] `.observe/inventory.md` exists with all 11 sections
- [ ] SLI Definitions table lists every identified SLI with golden signal type
- [ ] Spans, Metrics, and Logs tables have entries for every component boundary found in Step 2
- [ ] Every signal row has an SLIs column referencing at least one SLI
- [ ] Architecture diagram is present and matches discovered components
- [ ] `terraform/` and `alerts/` directories exist
- [ ] Gap count (blank Status rows across all signal tables) is reported to the user
