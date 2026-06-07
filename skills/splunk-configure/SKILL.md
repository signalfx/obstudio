---
name: splunk-configure
description: >-
  Generate Splunk Observability Cloud detector Terraform from an existing
  otel-audit report. Reads .observe/otel.md, classifies metrics into
  detector categories, and outputs ready-to-apply HCL with SignalFlow
  program_text. Use when the user types $splunk-configure, asks to "generate
  detectors", "create alerts from audit", "build Terraform for monitors",
  "set up Splunk detectors", or asks to include deployment, release,
  environment, Helm, GitOps, Terraform, serverless, VM, container, health,
  capacity, rollout, dependency config, or config context in alerts.
metadata:
  author: otel-studio
  version: 0.1.1
  category: observability
---

# Detect -- Splunk O11y Detector Terraform from Audit Report

## Overview

Read an existing `.observe/otel.md` audit report, classify detected metrics
into detector categories (latency, error, saturation, throughput), and generate
Terraform configuration for Splunk Observability Cloud `signalfx_detector`
resources with inline SignalFlow programs. When the audit includes deployment
context, use it to add safe detector dimensions and to report runtime,
release/config, health, and capacity prerequisites.

## When to Use

- After running `$otel-audit` to generate `.observe/otel.md`
- When the user wants alerting/detection Terraform for their service
- When creating monitors for RED signals or saturation metrics
- When deployment/runtime context should shape alert grouping, filters, or
  prerequisites for release/config, health, rollout, and capacity detection

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

3. **Deployment Context** from `## Deployment Context`, when present:
   - Platform/source
   - Service identity
   - Release/config
   - Dependency config
   - Dependency health
   - Health/capacity
   - Export path
   Load `../references/deployment-context-readiness.md` when this section exists.
   Treat rows with `unknown` as missing repository context, not missing telemetry.
   Treat `referenced but not inspected` evidence as missing repository context:
   document the referenced source path or URL as a prerequisite, but do not use
   its dimensions, values, or metrics in detector Terraform.
   Add rows with `missing` or `partial` to the detector report's prerequisites
   unless matching metrics or dimensions exist.

If the Metrics section says "No metrics detected." and there is no Deployment
Context section, stop and respond:

> The audit report contains no metrics. Detectors require metric data.
> Run `$otel-instrument` to add instrumentation, then re-run `$otel-audit`.

If the Metrics section says "No metrics detected." but Deployment Context is
present, do not generate detector Terraform from absent metrics. Continue to
create `.observe/detectors.md` with Deployment Prerequisites and clearly state
that detectors require instrumentation or platform metrics first.

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

If deployment context is present:

- Add `service.name` filters when available.
- Add environment, region, cluster, namespace, task, function, image tag,
  service version, config version, rollout, or canary dimensions only when the
  audit proves they exist and they are low-cardinality.
- Treat `deployment.region`, `deployment.platform`, `container.image.tag`, and
  artifact version as aliases for deployment-aware filters only when they are
  proven and low-cardinality.
- Prefer exact metric/resource attribute names proven by the audit, such as
  `cloud.region` or platform-provided container image attributes. Do not create
  duplicate filters only to force generic alias names.
- Add dependency filters or dashboard dimensions only when the audit proves they
  exist and they are low-cardinality, such as dependency type/name, sanitized
  endpoint alias, provider region/deployment, gateway, timeout tier, retry
  policy name, circuit breaker name, or config version. Do not use full URLs,
  credentials, raw hosts with user/tenant data, request payloads, or secret
  values.
- If deployment files reference another chart, values, GitOps, IaC, env, secret,
  or runtime config source that was not inspected, leave affected filters and
  group-bys service-scoped and list that source under Deployment Prerequisites.
- Do not group detectors by raw pod, container, request, user, tenant, session,
  trace, or raw URL values.
- Do not create release/config, health, capacity, rollout, or platform detectors
  from absent metrics. Record them as prerequisites instead.
- Do not create dependency endpoint, retry, timeout, circuit breaker, provider,
  or config-version detectors from absent metrics. Record the missing source or
  metric as a prerequisite instead.
- Create dependency endpoint-health detectors only from available dependency or
  platform health metrics. If only dependency config is present, document the
  missing health metric prerequisite instead.

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

For deployment-aware output, include only safe proven filters or dimensions in
SignalFlow. Examples: `service.name`, `deployment.environment`, `service.version`,
`k8s.namespace.name`, `cloud.region`, `container.image.tag`, `faas.name`, or
`deployment.rollout.id`. Also accept proven low-cardinality aliases such as
`deployment.region`, `deployment.platform`, and artifact version. Dependency
examples include `dependency.type`, `dependency.name`,
`dependency.endpoint.alias`, `cloud.region`, `deployment.config.version`, or
`deployment.rollout.id` when proven. When those dimensions are `unknown`, leave
the detector service-scoped and document the missing deployment context in
`.observe/detectors.md`.
Keep the Splunk Observability Cloud API `realm` variable separate from service
telemetry dimensions. Do not use `var.realm` as a SignalFlow filter for
`sfx_realm`, `deployment.region`, `cloud.region`, or any application/runtime
dimension unless live metric metadata or the audit proves that exact dimension
and value. If a dimension exists but its current value is unknown, leave the
detector service-scoped or make the dimension a dashboard/filter candidate
instead of hard-coding it.
Before writing SignalFlow, verify every filter and group-by dimension against
the audit, local metric metadata, or approved Splunk API metadata. If a
dimension is absent from the target metric, omit it and document the missing
dimension as a prerequisite. Never use a dimension solely because referenced
deployment files, uninspected values, or intended instrumentation imply it may
exist.
For percentile metrics that are already aggregated, including names such as
`.p99`, `.p95`, `p50`, `quantile`, or metrics marked as already-quantized, do
not use `.percentile(pct=99)` or average streams. Use raw histograms for
percentile calculations, or use `max()`/`max(by=[...])` for precomputed
percentile series. Match units to metric names and metadata before choosing
threshold defaults.

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
realm                = ""   # e.g. us1, eu0
api_token            = ""   # Splunk O11y API token (org-level, detector write)
service_name         = "<service-name from report>"
notification_channel = ""   # e.g. "Email,team@example.com" or PagerDuty routing key
```

Do NOT include per-detector threshold variables in this file — they already have
sensible defaults in `variables.tf`. Include `realm`, `api_token`, and
`notification_channel` (which have no defaults) plus `service_name` for
convenience (it has a default from the report but users often override it).

### Step 5 -- Generate Detectors Report

Create `.observe/detectors.md` as a human-readable companion to the Terraform
files. This report documents every detector that was generated, its
classification rationale, thresholds, and which metrics were skipped.

Use the following structure:

```markdown
# Detectors Report: <service-name>

**Language:** <lang> | **Framework:** <framework> | **Date:** <YYYY-MM-DD>
**Source:** `.observe/otel.md` | **Output:** `.observe/terraform/`

## Summary

| Category   | Count | Severity | Detection Method |
|------------|-------|----------|------------------|
| Latency    | N     | Warning  | P99 static threshold |
| Error      | N     | Critical | Sudden change (mean + stddev) |
| Saturation | N     | Warning  | Static threshold |
| Throughput | N     | Major    | Sudden change (mean + stddev) |
| **Total**  | **N** | | |

## Latency Detectors

P99 percentile against a static threshold. Default: **1.0s**.

| # | Detector | Metric | Source | Threshold Variable | Default |
|---|----------|--------|--------|-------------------|---------|
| 1 | `latency_<id>` | `<metric>` | <source> | `latency_<id>_threshold` | 1.0 |

## Error Detectors

Sudden-change detection using `against_recent.detector_mean_std` (above baseline).
Default: **3.0 stddev**, 5m current window vs 1h history.

| # | Detector | Metric | Source | Threshold Variable | Default |
|---|----------|--------|--------|-------------------|---------|
| 1 | `error_<id>` | `<metric>` | <source> | `error_<id>_stddev` | 3.0 |

## Saturation Detectors

Gauge value against a static threshold. Default: **85.0**.

| # | Detector | Metric | Source | Threshold Variable | Default |
|---|----------|--------|--------|-------------------|---------|
| 1 | `saturation_<id>` | `<metric>` | <source> | `saturation_<id>_threshold` | 85.0 |

## Throughput Detectors

Sudden-change detection using `against_recent.detector_mean_std` (out-of-band).
Default: **3.0 stddev**, 5m current window vs 1h history.

| # | Detector | Metric | Source | Threshold Variable | Default |
|---|----------|--------|--------|-------------------|---------|
| 1 | `throughput_<id>` | `<metric>` | <source> | `throughput_<id>_stddev` | 3.0 |

## Skipped Metrics

| Metric | Reason |
|--------|--------|
| `<metric>` | <why it was not classified> |

## Deployment Prerequisites

| Area | Status | Needed Before Alerting |
|------|--------|------------------------|
| Release/config | <partial/missing/unknown> | <version/config/rollout dimensions or repo path needed> |
| Dependency config | <partial/missing/unknown> | <dependency endpoint/region/timeout/retry/circuit-breaker/config source or metric needed> |
| Dependency health | <partial/missing/unknown> | <dependency endpoint health/target health/error/timeout/rate-limit metric needed> |
| Health/capacity | <partial/missing/unknown> | <restart/readiness/desired-vs-healthy/CPU/memory/disk/throttle/quota/concurrency metrics or deployment source needed> |
| Export path | <partial/missing/unknown> | <collector/export configuration needed> |

## Classification Rules Applied

<include the decision flowchart from references/detector-classification.md>

## Terraform Output

| File | Contents |
|------|----------|
| `detectors.tf` | N `signalfx_detector` resources with inline SignalFlow |
| `variables.tf` | 4 required + N threshold variables |
| `terraform.tfvars.example` | Template for required variables |

## Next Steps

1. Copy and fill in credentials
2. Review threshold defaults and override as needed
3. `cd .observe/terraform && terraform init && terraform plan && terraform apply`
4. Tune thresholds based on production baselines

---
*Generated by splunk-configure on <YYYY-MM-DD>*
```

### Step 6 -- Chat Summary

After generating all files (Terraform + report), present a summary:

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
- `.observe/detectors.md` — full detectors report with classification details

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
    A = data('http.server.request.duration', filter=filter('service.name', '${var.service_name}')).percentile(pct=99).publish(label='P99 Latency')
    detect(when(A > threshold(${var.latency_http_server_request_duration_threshold}))).publish('P99 Latency Too High')
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
