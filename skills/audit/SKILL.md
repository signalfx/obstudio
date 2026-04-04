---
name: audit
description: >-
  Analyze a codebase for observability readiness and generate a structured
  .observe/ directory with inventory, fault domains, and KPI mappings.
  Use when the user types /audit, asks about observability gaps, or wants
  to assess instrumentation coverage before writing any code.
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
  (`/instrument`, `/verify`, `/provision`) consume
- Re-auditing after code changes to catch new gaps

**When NOT to use:** If `.observe/inventory.md` already exists and you
only need to implement instrumentation, use `/instrument` instead.

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

### Step 4 -- KPI Identification

For each component and fault domain, identify Key Performance Indicators
using the four golden signals:

| Signal     | Question                                    |
|------------|---------------------------------------------|
| Latency    | How long do operations take? (p50, p95, p99) |
| Traffic    | How much demand is the system handling?      |
| Errors     | What is the rate of failed requests?         |
| Saturation | How full are resources? (pools, queues, mem) |

Also identify business-logic KPIs specific to the domain.

### Step 5 -- Unified KPI Table

Read [signal-mapping-guide.md](../references/signal-mapping-guide.md)
for guidance on mapping KPIs to OTel signal types.

Build a single table containing all KPIs -- already instrumented and
missing.

| Column          | Description                                              |
|-----------------|----------------------------------------------------------|
| Status          | `OK` if already instrumented, blank if missing           |
| KPI             | Name of the KPI                                          |
| Component       | Which component it belongs to                            |
| Class           | `Standard` (auto-instrumentation) or `Business` (custom) |
| Metric          | Yes/No                                                   |
| Trace           | Yes/No                                                   |
| Log             | Yes/No                                                   |
| Signal Name     | Actual name if exists, proposed name if not               |
| Trace-Derivable | Yes/No -- can the metric be derived from span data?       |
| Verified        | Blank initially; set to `OK` by `/verify`                |

Classify each KPI:
- **Standard**: provided by auto-instrumentation libraries
- **Business**: requires custom code

Present the table. Highlight the gap count as the implementation scope.

### Step 6 -- Generate or Update .observe/ Directory

This directory is the single output artifact of the audit skill and the
input for downstream skills (`/instrument`, `/verify`, `/provision`).

#### If `.observe/inventory.md` already exists

1. Read the existing `inventory.md`.
2. Parse the existing KPI Table to extract the list of previously
   tracked KPIs with their Status, Signal Name, and Component.
3. Compare against the KPIs identified in Steps 4-5 of this run:
   - **New KPIs**: add with blank Status.
   - **Removed KPIs**: mark with strikethrough or remove, note in a
     changelog comment at the top.
   - **Changed KPIs**: update the Status column.
   - **Unchanged KPIs**: preserve as-is, including manually added
     notes, runbook links, or alert overrides.
4. Update the Architecture diagram and Components table if dependencies
   changed.
5. Update the Fault Domains table with any new components.
6. Append `<!-- Last updated: {date} -->`.
7. Present summary: N new KPIs, N removed, N status changes.

#### If `.observe/inventory.md` does not exist (first run)

Read [observability-template.md](../references/observability-template.md)
for the inventory document template.

Create the `.observe/` directory at the repository root:

```
.observe/
  inventory.md              # Audit results: overview, components,
                            #   fault domains, KPI table, configurability
  terraform/                # (placeholder) Splunk O11y Cloud terraform
  alerts/                   # (placeholder) Alert rule definitions
```

Create `.observe/inventory.md` with sections:
1. Service Overview
2. Architecture (component diagram from Step 2)
3. Components
4. Fault Domains (from Step 3)
5. KPI Table (from Step 5)
6. Configurability
7. Alerts (placeholder -- populated by `/provision`)
8. Dashboard Recommendations (placeholder -- populated by `/provision`)

Create `terraform/` and `alerts/` directories with brief READMEs noting
they will be populated by the `/provision` skill.

## Red Flags

- Fewer than 3 KPIs identified for a service with external dependencies
- No business-class KPIs when the service has domain logic
- Missing fault domains for any external component
- Audit completed but `.observe/inventory.md` not generated
- KPI table has no entries with blank Status (nothing to instrument)

## Verification

- [ ] `.observe/inventory.md` exists with all 8 sections
- [ ] KPI table has rows for every component boundary found in Step 2
- [ ] Architecture diagram is present and matches discovered components
- [ ] `terraform/` and `alerts/` directories exist
- [ ] Gap count (blank Status rows) is reported to the user
