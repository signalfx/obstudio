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

## terraform.tfvars.example

Generated alongside the `.tf` files so users know exactly which values to provide.

```hcl
realm                = ""   # e.g. us1, eu0, lab0
api_token            = ""   # Splunk O11y API token (org-level, detector write)
service_name         = "<service-name>"
notification_channel = ""   # e.g. "Email,team@example.com" or PagerDuty routing key
```

Includes `realm`, `api_token`, and `notification_channel` (no defaults) plus
`service_name` for convenience (has a default from the report but commonly overridden).
Per-detector threshold overrides are omitted — they have sensible defaults in
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
| `<metric_id>` | Sanitized metric name (dots/hyphens → underscores, no leading digits) |
| `<metric_name>` | Original metric name as it appears in telemetry |
| `var.service_name` | From `variables.tf`; defaults to the service name in the audit report |
