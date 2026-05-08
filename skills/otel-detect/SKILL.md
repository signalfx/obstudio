---
name: otel-detect
description: >-
  Generate Splunk Observability Cloud detector Terraform from an existing
  otel-audit report. Reads .observe/otel.md, classifies metrics into
  detector categories, and outputs ready-to-apply HCL with SignalFlow
  program_text. Use when the user types $otel-detect, asks to "generate
  detectors", "create alerts from audit", "build Terraform for monitors",
  or "set up Splunk detectors".
metadata:
  author: otel-studio
  version: 0.1.0
  category: observability
---

# Detect -- Splunk O11y Detector Terraform from Audit Report

## Overview

Read an existing `.observe/otel.md` audit report, classify detected metrics
into detector categories (latency, error, saturation, throughput), and generate
Terraform configuration for Splunk Observability Cloud `signalfx_detector`
resources with inline SignalFlow programs.

## When to Use

- After running `$otel-audit` to generate `.observe/otel.md`
- When the user wants alerting/detection Terraform for their service
- When creating monitors for RED signals or saturation metrics

**When NOT to use:** If no audit report exists yet, instruct the user to run
`$otel-audit` first.

## Process

### Step 1 -- Locate Audit Report

Look for `.observe/otel.md` in the repository root.

- If the file exists, proceed to Step 2.
- If the file is missing, stop and respond:

> No audit report found at `.observe/otel.md`. Please run `$otel-audit` first
> to generate the observability coverage report.

### Step 2 -- Parse Service Metadata and Metrics

Extract from `.observe/otel.md`:

1. **Service metadata** from the report header:
   - Service name (from the `# Observability Report: {service-name}` heading)
   - Language (from the `**Language:**` field)
   - Framework (from the `**Framework:**` field)

2. **Metrics table** from the `### Metrics` section:
   - Each row provides: metric name, source, and type (auto/custom)
   - Record all metrics for classification in Step 3

If the Metrics section says "No metrics detected.", stop and respond:

> The audit report contains no metrics. Detectors require metric data.
> Run `$otel-instrument` to add instrumentation, then re-run `$otel-audit`.

### Step 3 -- Classify Metrics into Detector Categories

Load `references/detector-classification.md` and apply the classification rules
to each metric from Step 2.

Assign each metric to exactly one category:
- **latency** -- duration histograms
- **error** -- counters with failure/error/invalid keywords
- **throughput** -- counters without error keywords
- **saturation** -- gauges for connections, buffers, queues, lag

Skip metrics that match the exclusion rules (auto-instrumented library metrics
that duplicate custom signals).

### Step 4 -- Generate Terraform

Create the output directory `.observe/terraform/` if it does not exist.

Generate three files using the templates from `references/terraform-templates.md`:

#### `.observe/terraform/detectors.tf`

For each classified metric, emit a `signalfx_detector` resource block:

```hcl
resource "signalfx_detector" "<category>_<sanitized_metric_name>" {
  name        = "${var.service_name} <Category> - <metric_name>"
  description = "Detects <category> anomalies for <metric_name>"

  program_text = <<-EOF
    <SignalFlow program from template>
  EOF

  rule {
    description  = "<Category> threshold breached"
    severity     = "<severity from template>"
    detect_label = "<label from template>"

    notifications = [var.notification_channel]
  }
}
```

Sanitize metric names for HCL identifiers: replace dots and hyphens with
underscores, strip leading digits.

#### `.observe/terraform/variables.tf`

```hcl
variable "realm" {
  description = "Splunk Observability Cloud realm (e.g. us1, eu0)"
  type        = string
}

variable "api_token" {
  description = "Splunk Observability Cloud API token"
  type        = string
  sensitive   = true
}

variable "service_name" {
  description = "Service name for detector naming"
  type        = string
  default     = "<service-name from report>"
}

variable "notification_channel" {
  description = "Notification target for detector alerts"
  type        = string
}

# Per-detector threshold overrides
<one variable block per detector with its default threshold>
```

#### `.observe/terraform/terraform.tfvars.example`

Generate a `.tfvars.example` file the user copies and fills in to apply:

```hcl
realm                = ""   # e.g. us1, eu0, lab0
api_token            = ""   # Splunk O11y API token (org-level, detector write)
service_name         = "<service-name from report>"
notification_channel = ""   # e.g. "Email,team@example.com" or PagerDuty routing key
```

Do NOT include per-detector threshold variables in this file — they already have
sensible defaults in `variables.tf`. Only include the four required variables
that have no defaults.

### Step 5 -- Chat Summary

After generating the files, present a summary:

```
## Detectors Generated

| Category    | Count |
|-------------|-------|
| Latency     | N     |
| Error       | N     |
| Saturation  | N     |
| Throughput  | N     |

**Output:** `.observe/terraform/`

Files:
- `.observe/terraform/detectors.tf` — N detector resources
- `.observe/terraform/variables.tf` — realm, api_token, service_name, notification_channel + N threshold variables
- `.observe/terraform/terraform.tfvars.example` — copy to `terraform.tfvars`, fill in credentials

Next:
1. `cp .observe/terraform/terraform.tfvars.example .observe/terraform/terraform.tfvars`
2. Fill in `realm`, `api_token`, and `notification_channel` in `terraform.tfvars`
3. `cd .observe/terraform && terraform init && terraform plan`
4. `terraform apply`
```

## Output Templates

### detectors.tf Shape

```hcl
terraform {
  required_providers {
    signalfx = {
      source  = "splunk-terraform/signalfx"
      version = "~> 9.0"
    }
  }
}

provider "signalfx" {
  auth_token = var.api_token
  api_url    = "https://api.${var.realm}.signalfx.com"
}

resource "signalfx_detector" "latency_http_server_request_duration" {
  name        = "${var.service_name} Latency - http.server.request.duration"
  description = "Detects high p99 latency for http.server.request.duration"

  program_text = <<-EOF
    from signalfx.detectors.against_recent import against_recent
    A = data('http.server.request.duration', filter=filter('service.name', '${var.service_name}')).percentile(pct=99).publish(label='P99 Latency')
    detect(when(A > threshold(var.latency_http_server_request_duration_threshold))).publish('P99 Latency Too High')
  EOF

  rule {
    description  = "P99 latency exceeds threshold"
    severity     = "Warning"
    detect_label = "P99 Latency Too High"

    notifications = [var.notification_channel]
  }
}
```

### variables.tf Shape

```hcl
variable "realm" {
  description = "Splunk Observability Cloud realm (e.g. us1, eu0)"
  type        = string
}

variable "api_token" {
  description = "Splunk Observability Cloud API token"
  type        = string
  sensitive   = true
}

variable "service_name" {
  description = "Service name for detector naming"
  type        = string
  default     = "my-service"
}

variable "notification_channel" {
  description = "Notification target for detector alerts"
  type        = string
}

variable "latency_http_server_request_duration_threshold" {
  description = "P99 latency threshold in seconds for http.server.request.duration"
  type        = number
  default     = 1.0
}
```

## Red Flags

- Audit report has no metrics section
- All metrics are auto-instrumented library duplicates (nothing to detect on)
- Service name contains characters invalid for SignalFlow filter values
