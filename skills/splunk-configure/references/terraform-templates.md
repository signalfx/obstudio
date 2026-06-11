# Terraform Templates for Detector Categories

SignalFlow + HCL templates for each detector category. The agent uses these
templates to generate `.observe/terraform/detectors.tf` resources.

## SignalFlow Guardrails

- Do not equate the provider/API `realm` variable with telemetry. `realm` is
  only for the Splunk Observability Cloud provider/API endpoint. Use `sfx_realm`
  or other proven telemetry dimensions in dashboard variables only when the
  audit shows they exist and are low-cardinality.
- For dashboard variables, use `apply_if_exist = true` for optional dimensions
  that may be missing on some metrics. Use `apply_if_exist = false` only for
  required filters backed by every chart metric.
- For pre-aggregated percentile metrics, do not average or percentile again.
  In a known-traffic window, run a value sanity check and mark ambiguous units
  as unverified in `.observe/dashboards.md`.
- Do not keep a stale `configId` parameter from copied dashboard code unless
  the audit proves it is still emitted.
- Do not combine mixed-unit signals. Use separate panels for latency, rate,
  count, percentage, freshness age, and capacity utilization.
- Treat provider-derived or stale/unowned evidence as a prerequisite, not proof.
  Only claim source-backed coverage from a source-backed emitter inspected in
  the current run.
- Convert cumulative counters and cumulative timers to rates or deltas before
  alerting. Use `rollup='rate'` when producing rate charts from cumulative
  counters.
- For source-backed CPU utilization, generate a CPU saturation detector only
  from normalized CPU utilization when available. Do not use thread count,
  goroutine count, or worker count as CPU saturation. If only cumulative CPU time
  exists, use it as a diagnostic rate with `rollup='rate'` and list
  normalized CPU utilization as a prerequisite.

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
`references/detector-classification.md`. Generate concrete HCL with the same
`signalfx_detector` resource shape used above.

| Category | SignalFlow Method | Default | Severity | Detect Label |
|---|---|---|---|---|
| freshness | Static threshold on age/lag gauge or histogram p99 | 300 seconds | Critical | Freshness Lag Too High |
| backpressure | Static threshold on lag/depth/oldest age; sudden-change for rebalance count | 85 for depth/lag, 3 stddev for rebalances | Major | Backpressure Too High |
| dependency | P99 latency threshold for duration, sudden-change above baseline for errors/timeouts/retries | 1.0s or 3 stddev | Major | Dependency Health Degraded |
| customer-impact | P99 workflow latency threshold and error/degraded/timeout rate above baseline | 1.0s or 3 stddev | Critical | Customer Workflow Degraded |
| impact-classification | Static threshold or sudden-change on unavailable/degraded impact by workflow/region | 1 unavailable event or 3 stddev degraded events | Critical | Customer Impact Classified |
| auth-edge | P99 login/edge latency, error/timeout/expiry above baseline, certificate/TLS expiry static threshold | 1.0s, 3 stddev, or 14 days for cert expiry | Critical | Auth Edge Degraded |
| capacity-saturation | Static threshold on utilization/quota, sudden-change for throttles/restarts | 85%, 3 stddev, or 1 restart/crash-loop event | Major | Capacity Saturation Too High |
| genai-latency | P99 model/provider/workflow duration and streaming first-chunk or chunk latency | 5.0s workflow, 2.0s first chunk, or 3 stddev | Major | GenAI Latency Degraded |
| genai-token-pressure | P95/P99 input, output, total, cached, prompt, completion, and context token volume | 3 stddev above baseline or service-specific token limit | Major | GenAI Token Pressure High |
| genai-provider | Provider/model timeout, throttle, rate-limit, unavailable, retry, fallback, or deployment error rate | 1 timeout/unavailable event or 3 stddev error increase | Critical | GenAI Provider Degraded |
| genai-tool | Tool execution error/timeout rate, p99 tool latency, and tool-call count per workflow | 1.0s, 1 timeout/error, or 3 stddev fanout increase | Major | GenAI Tool Degraded |
| genai-model-config | Model/deployment readiness failure, model resolution failure, requested-vs-response mismatch, config/canary failure | 1 readiness or mismatch failure | Critical | GenAI Model Config Degraded |
| genai-workflow-fanout | LLM-call count, tool-call count, nested-agent count, workflow timeout, and workflow outcome rate | 3 stddev fanout increase or 1 timeout/unavailable event | Major | GenAI Workflow Fanout High |
| genai-retrieval | Retrieval/RAG latency, error/no-result/stale-result rate, vector search dependency health | 1.0s, 3 stddev error/no-result increase, or freshness threshold | Major | GenAI Retrieval Degraded |

When a readiness area is missing in `.observe/otel.md`, do not generate a
detector placeholder. Add it to `.observe/detectors.md` as an instrumentation
prerequisite and recommend `$otel-instrument`.

## Dashboard Terraform Shape

Use Splunk Observability Cloud dashboard resources when metric evidence exists:

```hcl
resource "signalfx_dashboard_group" "service" {
  name = "${var.service_name} Observability"
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
- Decision or delivery workflow
- Multi-region blast radius
- Capacity saturation
- Release/config/canary correlation
- GenAI workflow latency and fanout
- GenAI provider/model health and fallback
- GenAI tool execution and retrieval health
- GenAI token/context pressure

Each row must say whether coverage is generated, existing, missing, or blocked
by missing instrumentation. Do not claim coverage from a missing signal.

## Impact and Blast-Radius Dashboards

For impact-classification and blast-radius coverage, include dashboard panels or
specifications that roll up by low-cardinality dimensions already present in the
metrics:

- `service.name`
- `deployment.environment`
- region or environment when available
- workflow name/type when available
- impact class or outcome when available
- dependency name/operation when available
- deployment version, config version, canary, or rollout batch when available

The dashboard should make these questions answerable quickly:

1. Is the whole app down, or is one workflow degraded?
2. Is impact limited to one region/environment or multi-region?
3. Is the symptom API, workflow, auth, ingest, or delivery specific?
4. Did impact start near a deploy, config change, canary, or dependency failure?
5. For GenAI workflows, is impact provider, model/config, retrieval, tool, token
   pressure, fallback, or agent fanout specific?

## terraform.tfvars.example

Generated alongside the `.tf` files so users know exactly which values to provide.

```hcl
realm                = ""   # Splunk Observability Cloud API realm
api_token            = ""   # Splunk O11y API token (org-level, detector write)
service_name         = "<service-name>"
notification_channel = ""   # e.g. "Email,team@example.com" or PagerDuty routing key
```

Includes `realm`, `api_token`, and `notification_channel` (no defaults) plus
`service_name` for convenience (has a default from the report but commonly overridden).
Per-detector threshold overrides are omitted -- they have sensible defaults in
`variables.tf` and users add overrides only when tuning.

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
