# Terraform Templates for Detector Categories

SignalFlow + HCL templates for each detector category. The agent uses these
templates to generate `.observe/terraform/detectors.tf` resources.

## Latency Detector

Monitors p99 latency using a static threshold on histogram percentile data.

**Default threshold:** 1.0 (seconds)
**Severity:** Warning

```hcl
resource "signalfx_detector" "latency_<metric_id>" {
  name        = "${var.service_name} Latency - <metric_name>"
  description = "Detects high p99 latency for <metric_name>"

  program_text = <<-EOF
    A = data('<metric_name>', filter=filter('service.name', '${var.service_name}')).percentile(pct=99).publish(label='P99 Latency')
    detect(when(A > threshold(${var.latency_<metric_id>_threshold}))).publish('P99 Latency Too High')
  EOF

  rule {
    description  = "P99 latency exceeds threshold"
    severity     = "Warning"
    detect_label = "P99 Latency Too High"

    notifications = [var.notification_channel]
  }
}
```

**Variable:**

```hcl
variable "latency_<metric_id>_threshold" {
  description = "P99 latency threshold in seconds for <metric_name>"
  type        = number
  default     = 1.0
}
```

## Error Detector

Monitors error rates using sudden-change detection against recent history.

**Default sensitivity:** 3 standard deviations
**Severity:** Critical

```hcl
resource "signalfx_detector" "error_<metric_id>" {
  name        = "${var.service_name} Error - <metric_name>"
  description = "Detects sudden error rate increase for <metric_name>"

  program_text = <<-EOF
    from signalfx.detectors.against_recent import against_recent
    A = data('<metric_name>', filter=filter('service.name', '${var.service_name}')).sum().publish(label='Error Rate')
    against_recent.detector_mean_std(stream=A, current_window='5m', historical_window='1h', fire_num_stddev=${var.error_<metric_id>_stddev}, clear_num_stddev=2.5, orientation='above', ignore_extremes=True, calculation_mode='vanilla').publish('Error Rate Anomaly')
  EOF

  rule {
    description  = "Error rate deviates from recent baseline"
    severity     = "Critical"
    detect_label = "Error Rate Anomaly"

    notifications = [var.notification_channel]
  }
}
```

**Variable:**

```hcl
variable "error_<metric_id>_stddev" {
  description = "Number of standard deviations for error detection on <metric_name>"
  type        = number
  default     = 3.0
}
```

## Saturation Detector

Monitors resource saturation using a static threshold on gauge values.

**Default threshold:** 85 (percent)
**Severity:** Warning

```hcl
resource "signalfx_detector" "saturation_<metric_id>" {
  name        = "${var.service_name} Saturation - <metric_name>"
  description = "Detects high saturation for <metric_name>"

  program_text = <<-EOF
    A = data('<metric_name>', filter=filter('service.name', '${var.service_name}')).publish(label='Saturation')
    detect(when(A > threshold(${var.saturation_<metric_id>_threshold}))).publish('Saturation Too High')
  EOF

  rule {
    description  = "Saturation exceeds threshold"
    severity     = "Warning"
    detect_label = "Saturation Too High"

    notifications = [var.notification_channel]
  }
}
```

**Variable:**

```hcl
variable "saturation_<metric_id>_threshold" {
  description = "Saturation threshold (percent) for <metric_name>"
  type        = number
  default     = 85.0
}
```

## Throughput Detector

Monitors request throughput using sudden-change detection against recent history.

**Default sensitivity:** 3 standard deviations
**Severity:** Major

```hcl
resource "signalfx_detector" "throughput_<metric_id>" {
  name        = "${var.service_name} Throughput - <metric_name>"
  description = "Detects sudden throughput change for <metric_name>"

  program_text = <<-EOF
    from signalfx.detectors.against_recent import against_recent
    A = data('<metric_name>', filter=filter('service.name', '${var.service_name}')).sum().publish(label='Throughput')
    against_recent.detector_mean_std(stream=A, current_window='5m', historical_window='1h', fire_num_stddev=${var.throughput_<metric_id>_stddev}, clear_num_stddev=2.5, orientation='out_of_band', ignore_extremes=True, calculation_mode='vanilla').publish('Throughput Anomaly')
  EOF

  rule {
    description  = "Throughput deviates from recent baseline"
    severity     = "Major"
    detect_label = "Throughput Anomaly"

    notifications = [var.notification_channel]
  }
}
```

**Variable:**

```hcl
variable "throughput_<metric_id>_stddev" {
  description = "Number of standard deviations for throughput detection on <metric_name>"
  type        = number
  default     = 3.0
}
```

## Incident-Readiness Detector Defaults

Use these defaults for APM readiness categories from
`detector-classification.md`. Generate concrete HCL with the same
`signalfx_detector` resource shape used above.

| Category | SignalFlow Method | Default | Severity | Detect Label |
|---|---|---|---|---|
| freshness | Static threshold on age/lag gauge or histogram p99 | 300 seconds | Critical | Freshness Lag Too High |
| backpressure | Static threshold on lag/depth/oldest age when a source-backed SLO/capacity exists; otherwise a proven baseline; sudden-change for rebalance count | 85% only for normalized saturation, service-specific for counts, or 3 stddev for rebalances | Major | Backpressure Too High |
| dependency | P99 latency threshold for duration, sudden-change above baseline for errors/timeouts/retries | 1.0s or 3 stddev | Major | Dependency Health Degraded |
| customer-impact | P99 workflow latency threshold and error/degraded/timeout rate above baseline | 1.0s or 3 stddev | Critical | Customer Workflow Degraded |
| impact-classification | Static threshold or sudden-change on unavailable/degraded impact by workflow/region | 1 unavailable event or 3 stddev degraded events | Critical | Customer Impact Classified |
| auth-edge | P99 login/edge latency, error/timeout/expiry above baseline, certificate/TLS expiry static threshold | 1.0s, 3 stddev, or 14 days for cert expiry | Critical | Auth Edge Degraded |
| capacity-saturation | Static threshold on utilization/quota, sudden-change for throttles/restarts | 85%, 3 stddev, or 1 restart/crash-loop event | Major | Capacity Saturation Too High |

When a readiness area is missing in `.observe/otel.md`, do not generate a
detector placeholder. Add it to `.observe/detectors.md` as an instrumentation
prerequisite and recommend `$otel-instrument`.

When incident evidence mentions missed, flapping, auto-resolved, or no-data
alerts, document detector reliability evidence in the alert coverage matrix.
Do not generate service metric Terraform for alert lifecycle behavior unless
the audit proves an app-owned metric already exists or is a required missing
signal.

## GenAI Detector Defaults

Use these defaults for GenAI categories from
`detector-classification.md`. Generate concrete HCL with the same
`signalfx_detector` resource shape used above.

| Category | SignalFlow Method | Default | Severity | Detect Label |
|---|---|---|---|---|
| genai-latency | P99 model/provider/workflow duration and streaming first-chunk or chunk latency | 5.0s workflow, 2.0s first chunk, or 3 stddev | Major | GenAI Latency Degraded |
| genai-token-pressure | P95/P99 input, output, total, cached, prompt, completion, and context token volume | 3 stddev above baseline or service-specific token limit | Major | GenAI Token Pressure High |
| genai-provider | Provider/model timeout, throttle, rate-limit, unavailable, retry, fallback, or deployment error rate | 1 timeout/unavailable event or 3 stddev error increase | Critical | GenAI Provider Degraded |
| genai-tool | Tool execution error/timeout rate, p99 tool latency, and tool-call count per workflow | 1.0s, 1 timeout/error, or 3 stddev fanout increase | Major | GenAI Tool Degraded |
| genai-model-config | Model/deployment readiness failure, model resolution failure, requested-vs-response mismatch, config/canary failure | 1 readiness or mismatch failure | Critical | GenAI Model Config Degraded |
| genai-workflow-fanout | LLM-call count, tool-call count, nested-agent count, workflow timeout, and workflow outcome rate | 3 stddev fanout increase or 1 timeout/unavailable event | Major | GenAI Workflow Fanout High |
| genai-retrieval | Retrieval/RAG latency, error/no-result/stale-result rate, vector search dependency health | 1.0s, 3 stddev error/no-result increase, or freshness threshold | Major | GenAI Retrieval Degraded |
| genai-memory-context | Memory/context latency, error, hit/miss, stale/missing context, source/version, or permission failure | 1.0s, 1 permission failure, or freshness threshold | Major | GenAI Memory Context Degraded |
| genai-evaluation-quality | Evaluation score distribution, pass/fail or violation count, evaluator error/no-data, sample rate/count, freshness | 3 stddev score drop, 1 critical violation, or no-data threshold | Major | GenAI Evaluation Quality Degraded |
| genai-content-governance | Content capture mode, redaction/truncation outcome, unsafe capture, policy rejection, access/retention owner evidence | 1 unsafe capture or policy failure | Critical | GenAI Content Governance Risk |
| genai-cost | App-computed cost, budget/quota consumption, billing export freshness, or cost calculation failure | 3 stddev cost spike or budget threshold | Major | GenAI Cost Spike |

When a GenAI readiness area is missing in `.observe/otel.md`, do not generate a
detector placeholder. Add it to `.observe/detectors.md` as a GenAI
instrumentation prerequisite and recommend `$otel-instrument`.

## Dashboard Terraform Shape

Use Splunk Observability Cloud dashboard resources when metric evidence exists:

```hcl
resource "signalfx_dashboard_group" "service" {
  name        = "${var.service_name} Observability"
  description = "Service health dashboards for ${var.service_name}"
}

resource "signalfx_dashboard" "service" {
  name            = "${var.service_name} Service Health"
  dashboard_group = signalfx_dashboard_group.service.id
  time_range      = "-1h"

  filter {
    property = "service.name"
    values   = [var.service_name]
  }
}
```

Add Splunk dashboard chart resources for classified metrics and attach them to
the dashboard.
Prefer time charts for rates, latency, freshness, backpressure, and dependency
health; use single-value charts for current lag/age and list/table charts for
route, dependency, or workflow breakdowns when dimensions are present.
Dashboard-wide variables for optional dimensions must set
`apply_if_exist = true`; otherwise a wildcard variable for a dimension that one
metric lacks can hide valid chart data. Apply this to optional context such as
environment, region, namespace, platform, version, image tag, config version,
rollout, provider, model, dependency, and custom realm:

```hcl
variable {
  property       = "deployment.environment.name"
  alias          = "Environment"
  values         = ["*"]
  apply_if_exist = true
}
```

Never generate optional wildcard variables with `apply_if_exist = false`.
Use the exact proven telemetry dimension. Accept the deprecated
`deployment.environment` key only when existing metric metadata actually uses
it; newly instrumented services should emit `deployment.environment.name`.
Before writing chart SignalFlow, confirm every metric name, filter, group-by,
and unit from audit evidence, local metric metadata, or approved Splunk API
metadata. Do not equate the provider/API `realm` variable with telemetry
dimensions such as `sfx_realm`, `deployment.region`, or `cloud.region`; expose
those dimensions as dashboard variables when they are proven low-cardinality,
and only hard-code a dimension value when the audit or user explicitly provides
that telemetry value.
Only generate charts for metric names present in the audit or verified through
live metric metadata. If a provider-derived, precomputed, or transformed metric
name is used instead of the audited OTel name, document the live metadata
provenance and verification result in `.observe/dashboards.md`.
Live metric metadata alone is not sufficient when the repository has no
source-backed emitter for the metric. If a metric appears only in build output,
generated artifacts, `target/`, `build/`, `.class`, jar, coverage, or stale
runtime files, treat it as stale/unowned evidence: skip the panel by default and
record a verification issue or cleanup prerequisite instead.
Do not combine mixed-unit signals on one chart. Split boolean readiness,
availability, ratios/percentages, bytes, counts, rates, cumulative counters,
and durations into separate panels unless the chart type explicitly supports
per-series units or axes and the dashboard report documents the unit handling.
For example, database readiness and connection-pool utilization belong in
separate panels.
Runtime capacity dashboards must preserve the resource class represented by
each metric. When source-backed CPU utilization is present, create a CPU panel
and CPU saturation detector from that CPU metric, for example
`process.cpu.utilization`, `process.runtime.*.cpu.utilization`,
`jvm.cpu.recent_utilization`, or the runtime-specific equivalent. Do not satisfy
CPU coverage with thread, heap, memory, GC, or worker-count charts. Do not use thread count
as a CPU proxy. Memory/heap, thread or goroutine count, GC
pressure, concurrency, disk/filesystem, quota, and CPU should be separate panels
because their units and thresholds differ.
If only cumulative CPU time is available, chart it as a diagnostic rate with
`rollup='rate'` or an equivalent delta/rate transform and record normalized CPU utilization
as a missing prerequisite before creating a CPU saturation detector.
If a metric is pre-aggregated, already quantized, or named like `.p99`, `.p95`,
`p50`, or `quantile`, do not average it for p99 charts. Use `max()` for a
current worst-case value or `max(by=[...])` for a split chart. Use
`.percentile(pct=99)` only with raw duration/histogram metrics. Convert units
explicitly when the metric name or metadata indicates nanoseconds,
milliseconds, bytes, ratios, or rates.
For cumulative counters or cumulative timers, including names that end in
`.total`, `.count`, `.time`, or metrics whose metadata shows cumulative
temporality, do not chart the raw cumulative value as current health. Use
`rollup='rate'`, a delta/rate transform, or a true duration histogram/summary.
If neither is available, label the chart as cumulative and mark it unverified.
When a token or local query path is available, run each generated chart program
over a recent known-traffic window before applying Terraform. If the chart
returns no series, uses an absent dimension, or has implausible units, fix the
program or document the panel as unverified in `.observe/dashboards.md`.
When validating a dashboard in the Splunk UI after Terraform updates, reload
the canonical dashboard URL without a stale `configId` parameter or reset saved
dashboard overrides before deciding the chart still has no data.

## Alert Coverage Audit Output

When `splunk-configure` runs in alert-coverage-audit mode, produce a coverage
matrix even if no Terraform can be generated. Use existing local Terraform,
dashboard specs, or approved Splunk API results as evidence when available.
If existing alert inventory is unavailable, label the matrix as desired-state
coverage derived from `.observe/otel.md`.

Required rows:

- Primary workflow availability
- API error/latency
- Ingest lag/drops/freshness
- Queue/backpressure
- Dependency health
- Auth/domain-routing/edge
- Critical business workflow
- Multi-region blast radius
- Capacity saturation
- Release/config/canary correlation

Each row must say whether coverage is generated, existing, missing, or blocked
by missing instrumentation. Do not claim coverage from a missing signal.

## Impact and Blast-Radius Dashboards

For impact-classification and blast-radius coverage, include dashboard panels or
specifications that roll up by low-cardinality dimensions already present in the
metrics:

- `service.name`
- `deployment.environment.name` (or a proven existing legacy/custom alias)
- region or environment when available
- workflow name/type when available
- impact class or outcome when available
- dependency name/operation when available
- deployment version, config version, canary, or rollout batch when available

The dashboard should make these questions answerable quickly:

1. Is the whole app down, or is one workflow degraded?
2. Is impact limited to one region/environment or multi-region?
3. Is the symptom API, workflow, auth, ingest, or workflow specific?
4. Did impact start near a deploy, config change, canary, or dependency failure?
5. Is the impact tied to dependency health, capacity, release/config, or
   backpressure?

## terraform.tfvars.example

Generated alongside the `.tf` files so users know exactly which values to provide.

```hcl
realm                = ""   # Splunk Observability Cloud realm
api_token            = ""   # Splunk O11y API token (org-level, detector write)
service_name         = "<service-name>"
notification_channel = ""   # e.g. "Email,team@example.com" or PagerDuty routing key
```

Includes `realm`, `api_token`, and `notification_channel` (no defaults) plus
`service_name` for convenience (has a default from the report but commonly overridden).
Per-detector threshold overrides are omitted -- they have sensible defaults in
`variables.tf` and users add overrides only when tuning.

Generate `.gitignore` beside these files:

```gitignore
.terraform/
*.tfstate
*.tfstate.*
terraform.tfvars
```

Keep `.terraform.lock.hcl` after a successful `terraform init`; it pins the
resolved provider build without containing credentials.

The user workflow is:
1. `cp terraform.tfvars.example terraform.tfvars`
2. Fill in credentials
3. `terraform init && terraform plan`
4. `terraform apply`

## Placeholder Reference

| Placeholder | Meaning |
|---|---|
| `<metric_id>` | Sanitized metric name (dots/hyphens to underscores, no leading digits) |
| `<metric_name>` | Original metric name as it appears in telemetry |
| `var.service_name` | From `variables.tf`; defaults to the service name in the audit report |
