# Skill Eval Report — 2026-04-20

## Summary

| Skill | With Skill | Baseline | Delta | Avg Time | Avg Tokens |
|-------|-----------|----------|-------|----------|------------|
| splunk-audit | 97% | 100% | +-0.03 | 159s | 14,793 |
| splunk-instrument | 71% | 71% | +0.00 | 365s | 28,848 |
| splunk-observe | 60% | 60% | +0.00 | 546s | 52,945 |
| splunk-provision | 62% | 71% | +-0.09 | 201s | 16,981 |
| splunk-verify | 45% | 45% | +0.00 | 254s | 17,584 |

## Detail by Skill

### splunk-audit

#### Eval 1: chi-basic

| | With Skill | Baseline |
|---|---|---|
| Pass rate | 9/10 (90%) | 10/10 (100%) |
| Time | 202s | 155s |
| Tokens | 15,571 | 6,295 |

**Assertions (with skill):**

- [PASS] inventory.md file exists in the app .observe/ directory
- [PASS] inventory.md contains all 11 sections: Service Overview, Architecture, Components, Fault Domains, SLI Definitions, Spans, Metrics, Logs, Configurability, Alerts, Dashboard Recommendations
- [PASS] Service Overview table lists Go as the language and chi as the framework
- [FAIL] Architecture section contains a mermaid diagram
  - Evidence: No ```mermaid block found
- [PASS] SLI Definitions table has at least 4 entries covering Latency, Traffic, Errors, and Saturation
- [PASS] Spans table includes at least one OOB category span for HTTP
- [PASS] Metrics table includes http.server.request.duration as a Histogram
- [PASS] Components section does NOT list external databases, caches, or message queues
- [PASS] Configurability section mentions OTEL_SDK_DISABLED
- [PASS] All Status columns in signal tables are blank since this is a fresh audit

#### Eval 2: express-basic

| | With Skill | Baseline |
|---|---|---|
| Pass rate | 8/8 (100%) | 8/8 (100%) |
| Time | 125s | 154s |
| Tokens | 10,535 | 11,932 |

**Assertions (with skill):**

- [PASS] inventory.md file exists in the app .observe/ directory
- [PASS] Service Overview identifies Node.js as the language and Express as the framework
- [PASS] Components section does NOT list external databases, caches, or message queues
- [PASS] Fault Domains table includes HTTP Server entries for connectivity, latency, errors, and capacity
- [PASS] Spans table includes at least one OOB category span for HTTP
- [PASS] Metrics table includes at least 3 metric entries
- [PASS] Logs table has at least 1 log signal entry
- [PASS] Alerts and Dashboard Recommendations sections are present

#### Eval 3: fastapi-celery

| | With Skill | Baseline |
|---|---|---|
| Pass rate | 6/6 (100%) | 6/6 (100%) |
| Time | 151s | 184s |
| Tokens | 18,273 | 10,655 |

**Assertions (with skill):**

- [PASS] inventory.md file exists and was updated (not created from scratch)
- [PASS] New SLI entries related to cancellation or refund are present in the SLI Definitions table
- [PASS] New signal entries with blank Status appear for the cancellation/refund domain
- [PASS] A last-updated date or changelog comment is present
- [PASS] Redis component is still listed in the Components table
- [PASS] Celery component is still listed in the Components table

---

### splunk-instrument

#### Eval 1: flask-basic

| | With Skill | Baseline |
|---|---|---|
| Pass rate | 3/5 (60%) | 3/5 (60%) |
| Time | 265s | 138s |
| Tokens | 18,181 | 4,180 |

**Assertions (with skill):**

- [PASS] An otel_setup.py or similar OTel initialization file is created
- [PASS] opentelemetry packages are added to pyproject.toml or requirements.txt
- [FAIL] Auto-instrumentation for Flask HTTP is configured
  - Evidence: Could not verify assertion programmatically
- [FAIL] At least one custom metric (Counter, Histogram, or Gauge) is added in application code
  - Evidence: Could not verify assertion programmatically
- [PASS] inventory.md Status column is updated to OK for instrumented signals

**Baseline failures:**

- [FAIL] Auto-instrumentation for Flask HTTP is configured
  - Evidence: Could not verify assertion programmatically
- [FAIL] At least one custom metric (Counter, Histogram, or Gauge) is added in application code
  - Evidence: Could not verify assertion programmatically

#### Eval 2: kvstore

| | With Skill | Baseline |
|---|---|---|
| Pass rate | 5/6 (83%) | 5/6 (83%) |
| Time | 466s | 138s |
| Tokens | 39,515 | 13,158 |

**Assertions (with skill):**

- [PASS] go.opentelemetry.io dependencies are added to go.mod
- [PASS] An OTel SDK initialization function is created or added to main
- [FAIL] otelhttp or otelchi middleware is wired into the HTTP server
  - Evidence: Could not verify assertion programmatically
- [PASS] Custom spans are added for store operations (get, set, delete, or search)
- [PASS] At least one custom metric instrument is created (Counter, Histogram, or Gauge)
- [PASS] inventory.md Status column is updated to OK for instrumented signals

**Baseline failures:**

- [FAIL] otelhttp or otelchi middleware is wired into the HTTP server
  - Evidence: Could not verify assertion programmatically

---

### splunk-observe

#### Eval 1: express-basic

| | With Skill | Baseline |
|---|---|---|
| Pass rate | 3/5 (60%) | 3/5 (60%) |
| Time | 546s | 245s |
| Tokens | 52,945 | 13,902 |

**Assertions (with skill):**

- [PASS] .observe/inventory.md is created with signal tables
- [PASS] OpenTelemetry packages are added to package.json
- [PASS] An OTel setup or instrumentation file is created
- [FAIL] The skill progresses through at least audit and instrument phases
  - Evidence: Could not verify assertion programmatically
- [FAIL] inventory.md Status column has at least some OK entries after instrumentation
  - Evidence: Could not verify assertion programmatically

**Baseline failures:**

- [FAIL] The skill progresses through at least audit and instrument phases
  - Evidence: Could not verify assertion programmatically
- [FAIL] inventory.md Status column has at least some OK entries after instrumentation
  - Evidence: Could not verify assertion programmatically

---

### splunk-provision

#### Eval 1: flask-basic

| | With Skill | Baseline |
|---|---|---|
| Pass rate | 3/6 (50%) | 4/6 (67%) |
| Time | 12s | 144s |
| Tokens | 501 | 9,180 |

**Assertions (with skill):**

- [FAIL] At least one .tf file is created in .observe/terraform/
  - Evidence: No .tf files found in .observe/terraform/
- [FAIL] Terraform files reference SignalFx or Splunk Observability provider
  - Evidence: Could not verify assertion programmatically
- [FAIL] A dashboard resource is defined with charts for HTTP latency, error rate, or throughput
  - Evidence: Could not verify assertion programmatically
- [PASS] Alert rule definitions are created in .observe/alerts/
- [PASS] inventory.md Alerts section is populated with at least one alert entry
- [PASS] inventory.md Dashboard Recommendations section is updated

**Baseline failures:**

- [FAIL] Terraform files reference SignalFx or Splunk Observability provider
  - Evidence: Could not verify assertion programmatically
- [FAIL] A dashboard resource is defined with charts for HTTP latency, error rate, or throughput
  - Evidence: Could not verify assertion programmatically

#### Eval 2: kvstore

| | With Skill | Baseline |
|---|---|---|
| Pass rate | 3/4 (75%) | 3/4 (75%) |
| Time | 391s | 429s |
| Tokens | 33,461 | 30,054 |

**Assertions (with skill):**

- [FAIL] Terraform files are created in .observe/terraform/
  - Evidence: Could not verify assertion programmatically
- [PASS] Dashboard includes panels for KV store-specific metrics (store operations, evictions, or persist duration)
- [PASS] Alert rules include at least one critical and one warning severity
- [PASS] inventory.md Alerts section is populated

**Baseline failures:**

- [FAIL] Terraform files are created in .observe/terraform/
  - Evidence: Could not verify assertion programmatically

---

### splunk-verify

#### Eval 1: flask-basic

| | With Skill | Baseline |
|---|---|---|
| Pass rate | 2/5 (40%) | 2/5 (40%) |
| Time | 279s | 198s |
| Tokens | 16,734 | 9,851 |

**Assertions (with skill):**

- [PASS] The skill attempts to start or connect to the Observer collector
- [FAIL] HTTP endpoints of the service are exercised (GET, POST, or similar requests)
  - Evidence: Could not verify assertion programmatically
- [FAIL] Trace data is queried or checked from the collector
  - Evidence: Could not verify assertion programmatically
- [FAIL] Metric data is queried or checked from the collector
  - Evidence: Could not verify assertion programmatically
- [PASS] inventory.md Verified column is updated to OK for confirmed signals

**Baseline failures:**

- [FAIL] HTTP endpoints of the service are exercised (GET, POST, or similar requests)
  - Evidence: Could not verify assertion programmatically
- [FAIL] Trace data is queried or checked from the collector
  - Evidence: Could not verify assertion programmatically
- [FAIL] Metric data is queried or checked from the collector
  - Evidence: Could not verify assertion programmatically

#### Eval 2: kvstore

| | With Skill | Baseline |
|---|---|---|
| Pass rate | 2/4 (50%) | 2/4 (50%) |
| Time | 229s | 198s |
| Tokens | 18,433 | 6,192 |

**Assertions (with skill):**

- [FAIL] The skill attempts to build and run the Go service
  - Evidence: Could not verify assertion programmatically
- [PASS] KV store endpoints are exercised (PUT, GET, DELETE operations)
- [PASS] Trace or metric data is checked from the collector
- [FAIL] A coverage summary is reported showing verified vs total signals
  - Evidence: Could not verify assertion programmatically

**Baseline failures:**

- [FAIL] The skill attempts to build and run the Go service
  - Evidence: Could not verify assertion programmatically
- [FAIL] A coverage summary is reported showing verified vs total signals
  - Evidence: Could not verify assertion programmatically

---

*5 skills, 10 evals, 20 total runs.*