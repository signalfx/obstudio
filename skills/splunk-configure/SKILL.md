---
name: splunk-configure
description: >-
  Generate Splunk Observability Cloud detector Terraform from an existing
  otel-audit report. Reads .observe/otel.md, classifies metrics into
  detector categories, and outputs ready-to-apply HCL with SignalFlow
  program_text. Use when the user types $splunk-configure, asks to "generate
  detectors", "create alerts from audit", "build Terraform for monitors",
  "set up Splunk detectors", or asks for GenAI/LLM detector coverage from an
  otel-audit report.
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

When the audit report contains `## GenAI Readiness`, classify available GenAI
metrics first and report missing GenAI signals as instrumentation prerequisites
instead of inventing detectors from absent data.

## When to Use

- After running `$otel-audit` to generate `.observe/otel.md`
- When the user wants alerting/detection Terraform for their service
- When creating monitors for RED signals or saturation metrics
- When creating GenAI/LLM detectors from audit output containing `gen_ai.*`
  metrics, provider/model/tool/retrieval spans, memory/context, evaluation
  quality, token pressure, content governance, cost, fallback, model/config
  readiness, or workflow fanout gaps

**When NOT to use:** If no audit report exists yet, instruct the user to run
`$otel-audit` first.

## Process

### Step 1 -- Locate Audit Report

Look for `.observe/otel.md` in the repository root.

- If the file exists, proceed to Step 2.
- If the file is missing, stop and respond:

> No audit report found at `.observe/otel.md`. Please run `$otel-audit` first
> to generate the observability coverage report.

### Step 2 -- Parse Service Metadata, Metrics, and GenAI Coverage

Extract from `.observe/otel.md`:

1. **Service metadata** from the report header:
   - Service name (from the `# Observability Report: {service-name}` heading)
   - Language (from the `**Language:**` field)
   - Framework (from the `**Framework:**` field)

2. **Metrics table** from the `### Metrics` section:
   - Each row provides: metric name, source, and type (auto/custom)
   - Record all metrics for classification in Step 3

3. **GenAI Readiness** from the `## GenAI Readiness` section when present:
   - workflow trace shape
   - semantic-convention completeness
   - metrics and detectors
   - AI pathway surfaces
   - memory/context
   - evaluation quality
   - content governance and privacy/cardinality
   - cost source or owner mapping
   Missing or partial GenAI areas become instrumentation prerequisites unless
   matching metrics already exist in the Metrics table.

4. **Legacy GenAI gap-contract input** when present:
   - Treat older machine-oriented GenAI gap contracts as legacy audit input.
     Normalize each row into the human-readable `## GenAI Readiness` surface
     model before producing detector prerequisites.
   - Parse surface/status, `required_signals`, owner/source files, and
     `acceptance_criteria`; do not require or display opaque row IDs.
   - Treat any GenAI surface with status `missing` or `partial` as an
     instrumentation prerequisite unless matching metrics already exist in the
     Metrics table.
   - Generate detectors only for implemented or proven GenAI signals. Do not
     imply complete token/context, provider/model, tool, stream, retrieval, or
     model/config coverage while required signals remain missing.

If the Metrics section says "No metrics detected." and there are no GenAI
readiness sections or legacy GenAI gap-contract inputs, stop and respond:

> The audit report contains no metrics. Detectors require metric data.
> Run `$otel-instrument` to add instrumentation, then re-run `$otel-audit`.

If the Metrics section says "No metrics detected." but GenAI readiness sections
or legacy GenAI gap-contract inputs exist, do not generate detector Terraform. Create
`.observe/detectors.md` with GenAI instrumentation prerequisites and recommend
`$otel-instrument` for the specific missing signals.

### Step 3 -- Classify Metrics into Detector Categories

Load `references/detector-classification.md` and apply the classification rules
to each metric from Step 2.

Assign each metric to exactly one category. Apply GenAI-specific rules first
when the audit has a `## GenAI Readiness` section or when metric names or
dimensions explicitly indicate LLM/GenAI ownership: `gen_ai.*`, LLM, inference,
embedding, model provider/deployment, agent, tool/function calling, retrieval,
prompt/completion/context token usage, fallback, or model/config readiness. Do
not classify generic `model`, `workflow`, `tool`, `config`, `canary`, `token`,
`session`, `chat`, `memory`, `context`, `evaluation`, `evaluator`, `quality`,
`cost`, or `billing` metrics as GenAI unless the audit evidence shows they
belong to a GenAI/LLM path. Use generic latency, error, throughput, or
saturation categories when no GenAI-specific category matches.

- **genai-latency** -- `gen_ai.client.operation.duration`, model/provider
  request duration, workflow duration, streaming first-chunk/time-per-chunk
- **genai-token-pressure** -- `gen_ai.client.token.usage`, prompt/context/token
  size, cache read/create tokens, input/output token histograms
- **genai-provider** -- provider/model timeout, rate-limit, throttle, 5xx,
  unavailable, fallback selected/failed, region/deployment errors
- **genai-tool** -- `execute_tool` success/error/latency, stable tool name,
  tool failure class, tool-call count per workflow
- **genai-model-config** -- requested vs response model, model/deployment
  readiness, failed model resolution, config version/canary/feature flag
- **genai-workflow-fanout** -- LLM-call count, tool-call count, nested
  agent/workflow count, workflow outcome and timeout by surface/environment
- **genai-retrieval** -- retrieval duration/error/no-result/stale-result
  signals when retrieval/RAG code exists
- **genai-memory-context** -- memory/context duration/outcome/error,
  hit/miss, stale/missing context, source/version, and permission/auth failure
- **genai-evaluation-quality** -- `gen_ai.evaluation.result` derived or
  app-owned score distribution, pass/fail or violation count, evaluator
  error/timeout/no-data, sample rate/count, and freshness
- **genai-content-governance** -- content capture mode, redaction/truncation
  outcome, unsafe capture/policy rejection, and access/retention owner evidence;
  use mostly as a prerequisite/dashboard category, never raw content
- **genai-cost** -- app-computed request/model/provider cost, budget/quota
  consumption, billing export freshness, or cost calculation failure. If the app
  does not own an accurate pricing map, owner-map the billing/provider source
  instead of generating an approximate cost detector
- **latency** -- duration histograms
- **error** -- counters with failure/error/invalid keywords
- **throughput** -- counters without error keywords
- **saturation** -- gauges for connections, buffers, queues, lag

Skip metrics that match the exclusion rules (auto-instrumented library metrics
that duplicate custom signals).

For every `## GenAI Readiness` row or GenAI `## Gaps` entry that is still
missing a metric, trace attribute, span event, or owner-mapped external signal,
add an entry to the generated report's "GenAI Instrumentation Prerequisites"
section. Do not generate a detector for a missing signal. Recommend
`$otel-instrument` with the specific human-readable GenAI surface and coverage
area that must be added first.

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
| GenAI Latency | N | Major | P99 or sudden change |
| GenAI Token Pressure | N | Major | Token/context threshold or baseline |
| GenAI Provider | N | Critical | Error/timeout/rate-limit/fallback |
| GenAI Tool | N | Major | Tool error/latency/fanout |
| GenAI Model Config | N | Critical | Readiness/mismatch failure |
| GenAI Workflow Fanout | N | Major | LLM/tool call fanout |
| GenAI Retrieval | N | Major | Retrieval error/latency/staleness |
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

## GenAI Instrumentation Prerequisites

Include this section when `## GenAI Readiness` or a legacy GenAI gap-contract input exists
and any required GenAI signal is missing or partial.

| Surface | Audit Status | Missing Signal | Why No Detector Was Generated | Next Step |
|---------|--------------|----------------|-------------------------------|-----------|
| Token/context pressure | partial | truncation rate, token-limit errors, prompt/tool schema size, LLM-call fanout | Matching metrics are absent or only token usage exists | Run `$otel-instrument` to close the named GenAI signals or owner-map them |

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
| GenAI Latency | N |
| GenAI Token Pressure | N |
| GenAI Provider | N |
| GenAI Tool | N |
| GenAI Model Config | N |
| GenAI Workflow Fanout | N |
| GenAI Retrieval | N |

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
