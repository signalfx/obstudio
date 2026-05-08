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
    detect(when(A > threshold(var.latency_<metric_id>_threshold))).publish('P99 Latency Too High')
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
    against_recent.detector_mean_std(stream=A, current_window='5m', historical_window='1h', fire_num_stddev=var.error_<metric_id>_stddev, clear_num_stddev=2.5, orientation='above', ignore_extremes=True, calculation_mode='vanilla').publish('Error Rate Anomaly')
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
    detect(when(A > threshold(var.saturation_<metric_id>_threshold))).publish('Saturation Too High')
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
    against_recent.detector_mean_std(stream=A, current_window='5m', historical_window='1h', fire_num_stddev=var.throughput_<metric_id>_stddev, clear_num_stddev=2.5, orientation='out_of_band', ignore_extremes=True, calculation_mode='vanilla').publish('Throughput Anomaly')
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

## terraform.tfvars.example

Generated alongside the `.tf` files so users know exactly which values to provide.

```hcl
realm                = ""   # e.g. us1, eu0, lab0
api_token            = ""   # Splunk O11y API token (org-level, detector write)
service_name         = "<service-name>"
notification_channel = ""   # e.g. "Email,team@example.com" or PagerDuty routing key
```

Only the four required variables (those without defaults) are included.
Per-detector threshold overrides are omitted — they have sensible defaults in
`variables.tf` and users add overrides only when tuning.

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
