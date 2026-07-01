---
name: splunk-configure
description: >-
  Generate Splunk Observability Cloud detector Terraform from existing
  observability reports. Reads .observe/otel.md plus instrumentation and
  verification reports when available, classifies proven or accepted metrics
  into detector categories, outputs HCL with SignalFlow program_text, and
  writes local configure verification. Use when the user types
  $splunk-configure, asks to "generate detectors", "create alerts from audit",
  "build Terraform for monitors", "set up Splunk detectors", "create
  dashboards", or asks for GenAI/LLM detector coverage from observability
  reports.
metadata:
  author: otel-studio
  version: 0.1.0
  category: observability
---

# Detect -- Splunk O11y Detector Terraform from Audit Report

## Overview

Read existing `.observe/` observability reports, classify detector-ready
metrics into categories (latency, error, saturation, throughput, GenAI-specific
categories), and generate Terraform configuration for Splunk Observability
Cloud `signalfx_detector` resources with inline SignalFlow programs.

Before writing outputs, read `../references/report-flow-contract.md` and follow
the Splunk Configure Contract plus Splunk Configure Verification.

When the audit report contains `## GenAI Readiness`, classify available GenAI
metrics first and report missing or unverified GenAI signals as
instrumentation prerequisites instead of inventing detectors from absent data.

## When to Use

- After running `$otel-audit` to generate `.observe/otel.md`
- After `$otel-instrument` and `$otel-verify` when the user wants detectors for
  newly implemented signals
- When the user wants alerting/detection Terraform for their service
- When creating monitors for latency, errors, throughput, saturation, runtime,
  dependency, or GenAI readiness metrics
- When creating GenAI/LLM detectors from audit output containing `gen_ai.*`
  metrics, provider/model/tool/retrieval spans, memory/context, evaluation
  quality, token pressure, content governance, cost, fallback, model/config
  readiness, or workflow fanout gaps

**When NOT to use:** If no audit report exists yet, instruct the user to run
`$otel-audit` first.

## Process

### Step 1 -- Locate Source Reports

Look for `.observe/otel.md` in the repository root.

- If the file exists, proceed to Step 2.
- If the file is missing, stop and respond:

> No audit report found at `.observe/otel.md`. Please run `$otel-audit` first
> to generate the observability coverage report.

Also look for optional downstream reports:

- `.observe/otel-instrumentation.md` for implemented signal changes and
  detector handoff.
- `.observe/otel-verify.md` for emitted metric proof, OTLP evidence, and
  unverified rows.

### Step 2 -- Parse Metadata, Metrics, Verification, and GenAI Coverage

Extract from `.observe/otel.md`:

1. **Service metadata** from the report header:
   - Service name (from the `# Observability Report: {service-name}` heading)
   - Language (from the `**Language:**` field)
   - Framework (from the `**Framework:**` field)

2. **Metrics table** from the `### Metrics` section:
   - Each row provides: metric name, source, and type (auto/custom)
   - Record all metrics as detector candidates for Step 3

3. **Implemented signal changes** from `.observe/otel-instrumentation.md` when
   present:
   - `Signals Changed`
   - `Verification Handoff / Results`
   - `Detector Handoff / Results`
   Use this to identify newly implemented metrics and remaining prerequisites.

4. **Verified signal proof** from `.observe/otel-verify.md` when present:
   - `Signals Verified`
   - `Added Signal Verification Matrix`
   - `Signal Inventory Coverage`
   - `Explorer-Visible OTLP Evidence`
   A metric is proof-ready only when its exact metric row is `Working`, emitted
   datapoints are proven with the expected unit/dimensions, and source evidence
   exists, unless the user explicitly accepts source-only detector generation.
   Do not infer proof from an aggregate coverage count or from a similarly
   named metric.

5. **GenAI Readiness** from the `## GenAI Readiness` section when present:
   - Read every independently actionable surface row and its exact required
     signals, owner/source files, and acceptance criteria.
   - Keep provider/model, workflow/agent, tool/function, token/context,
     stream/session, retrieval, memory/context, evaluation/data export,
     content governance, privacy/cardinality, model/config, and cost ownership
     as separate detector prerequisites when the audit separates them.
   - Do not merge distinct readiness surfaces into a generic prerequisite.
   Missing or partial GenAI areas become instrumentation prerequisites unless
   matching metrics already exist in the Metrics table.

6. **GenAI Readiness Closure** from the instrumentation report when present:
   - Parse each `Surface`, `Required signals`, `Implemented / proven`, `Tests`,
     `Remaining signals`, and `Result` cell.
   - Treat any surface with remaining signals or a non-working result as an
     instrumentation prerequisite unless matching metrics are proven.
   - Generate detectors only for implemented or proven GenAI signals. Do not
     imply complete token/context, provider/model, tool, stream, retrieval, or
     model/config coverage while required signals remain missing.

If the Metrics section says "No metrics detected." and there are no implemented
or verified metrics in downstream reports, and there are no GenAI
readiness or readiness-closure sections, stop and respond:

> The audit report contains no metrics. Detectors require metric data.
> Run `$otel-instrument` to add instrumentation, then re-run `$otel-audit`.

If the Metrics section says "No metrics detected." but GenAI readiness or
readiness-closure sections exist, do not generate detector Terraform.
Create `.observe/detectors.md` and `.observe/splunk-configure-verify.md` with
GenAI instrumentation prerequisites and recommend `$otel-instrument` for the
specific missing signals.

### Step 3 -- Classify Metrics into Detector Categories

Load `references/detector-classification.md` and apply the classification rules
to each metric from Step 2.

Only classify metrics that are present in source evidence and either verified
by `.observe/otel-verify.md` or explicitly accepted by the user as source-only
detector inputs. Put unverified metrics in `Skipped Metrics` with the reason
`unverified metric emission` and the next step `$otel-verify`.

Assign each accepted metric to exactly one category. Apply GenAI-specific rules first
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
missing or has unverified metric, trace attribute, span event, or owner-mapped
external signal evidence, add an entry to the generated report's
"GenAI Instrumentation Prerequisites" section. Do not generate a detector for a
missing or unverified signal. Recommend `$otel-instrument` with the specific
human-readable GenAI surface when instrumentation is absent, and `$otel-verify`
when instrumentation exists but emitted metric proof is missing.

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
**Result:** Pass | Partial | Fail | Blocked
**Source audit:** `.observe/otel.md`
**Source instrumentation:** `.observe/otel-instrumentation.md` | not found
**Source verification:** `.observe/otel-verify.md` | not found
**Output:** `.observe/terraform/`

## Executive Summary
- <detectors generated count and most important covered category>
- <metrics skipped because missing/unverified>
- <configuration validation result>
- <next action>

## Flow
`audit -> instrument -> verify -> configure -> configure-verify`

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
| GenAI Memory Context | N | Major | Memory/context latency, error, freshness, or permission failure |
| GenAI Evaluation Quality | N | Major | Evaluation score, violation, error, no-data, or freshness |
| GenAI Content Governance | N | Critical | Unsafe capture, redaction, truncation, or policy failure |
| GenAI Cost | N | Major | Cost spike, budget/quota pressure, or billing freshness |
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

Include this section when `## GenAI Readiness` or
`## GenAI Readiness Closure` exists and any required GenAI signal is missing or
partial.

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

### Step 6 -- Validate Configure Output

Always create `.observe/splunk-configure-verify.md` after generating
`.observe/detectors.md` and Terraform files. Follow
`../references/report-flow-contract.md` Splunk Configure Verification.

Validation requirements:

1. Confirm generated files exist:
   - `.observe/terraform/detectors.tf`
   - `.observe/terraform/variables.tf`
   - `.observe/terraform/terraform.tfvars.example`
   - `.observe/terraform/.gitignore` excluding `.terraform/`, local state, and
     `terraform.tfvars`
   - `.observe/detectors.md`
2. If Terraform is installed, run:
   - `terraform fmt -check -recursive .observe/terraform`
   - `terraform -chdir=.observe/terraform init -backend=false -input=false`
   - `terraform -chdir=.observe/terraform validate -json`
   - preserve the generated `.terraform.lock.hcl`
   - surface validation warnings separately from errors; a provider warning is
     not proof of generated-HCL failure, but it must be recorded in the report
   - when init fails because a user-level Terraform CLI configuration forces a
     private provider mirror, inspect that configuration without exposing
     credentials and do not modify it. If public-registry access is allowed,
     rerun only the local validation with `TF_CLI_CONFIG_FILE=/dev/null` and
     record the bypass. Otherwise mark native validation `Blocked`.
   - if real, approved Splunk credentials are already available, run
     `terraform -chdir=.observe/terraform plan -refresh=false -input=false`
     without saving or applying a plan. The SignalFx provider sends each
     `program_text` to `/v2/detector/validate`, so this is the authoritative
     SignalFlow compile test.
   - never use a fake token for the plan and never print credentials. A plan
     without a valid detector-capable token fails with 401 and proves only the
     authentication boundary, not the detector programs.
   - `Pass` requires both local validation and an authenticated plan that
     accepts every generated detector. When local validation passes but no
     approved token is available, report `Partial` and name remote SignalFlow
     compilation as the one unproven check. Applying resources is not required
     for configure verification.
3. If Terraform is unavailable, record Terraform validation as `Skipped` or
   `Blocked` with the missing prerequisite. Do not mark it `Pass`.
4. Validate SignalFlow shape without contacting Splunk:
   - every generated metric appears in audit, instrumentation, or verify
     evidence
   - every detector filters by `service.name`
   - every threshold variable referenced in `detectors.tf` is declared in
     `variables.tf`
   - the provider uses `var.api_token` and a realm-derived `api_url`; do not
     hard-code either value
   - every rule `detect_label` matches a published detect label in
     `program_text`
   - no user/session/request/trace IDs, raw prompts, raw content, API tokens,
     or secrets appear in filters, group-bys, or example variables
   - the exact set of metrics referenced by `data(...)` is a subset of the
     `Working` metric rows in `.observe/otel-verify.md`, unless a source-only
     exception was explicitly accepted and recorded
   - metric names, units, and required dimensions used by detector logic match
     verification evidence; do not silently substitute an alternate
     semantic-convention name
5. Validate coverage:
   - generated detectors map to accepted metrics
   - skipped metrics explain whether they are missing, unverified, duplicate,
     unsafe, or owner-mapped
   - prerequisites point to `$otel-instrument` for missing instrumentation and
     `$otel-verify` for missing emission proof

After the checks above, always run the bundled dependency-free validator:

```bash
python3 <splunk-configure-skill-dir>/scripts/validate_configure_output.py \
  --terraform-dir .observe/terraform \
  --detectors-report .observe/detectors.md \
  --configure-verify-report .observe/splunk-configure-verify.md \
  --verify-report .observe/otel-verify.md
```

Treat validator failure as configure failure and repair the generated files.
The script validates file presence, HCL resource/variable references,
provider credential/endpoint wiring, SignalFlow labels and service filters,
sensitive identifiers, local-state ignore rules, reader-first heading order,
matching configure statuses, and exact metric reconciliation against
reader-first `Working` metric rows. `.observe/detectors.md` must inherit the
result from `.observe/splunk-configure-verify.md`; the plan and its verification
must never disagree. The script does not replace `terraform validate`; run both
when Terraform is available.

Use this report shape:

```markdown
# Splunk Configure Verification: <service-name>

**Result:** Pass | Partial | Fail | Blocked
**Source:** `.observe/detectors.md`
**Terraform:** `.observe/terraform/`

## Executive Summary

<1-2 sentence overall verdict>

## What Was Added

| Resource Label | Metric | Detect Condition | Severity |
|----------------|--------|-----------------|----------|
| latency_<id> | <metric_name> | P99 > threshold | Warning |
| error_<id> | <metric_name> | rate anomaly (mean+stddev) | Critical |
| saturation_<id> | <metric_name> | mean > threshold | Warning |
| throughput_<id> | <metric_name> | rate anomaly (out-of-band) | Major |

## Tested And Working
## Not Yet Proven
## Validation Notes
## Next Steps
```

### Step 7 -- Chat Summary

After generating all files and configure verification, present a summary:

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
| GenAI Memory Context | N |
| GenAI Evaluation Quality | N |
| GenAI Content Governance | N |
| GenAI Cost | N |

**Output:** `.observe/terraform/`

Files:
- `.observe/terraform/detectors.tf` — N detector resources
- `.observe/terraform/variables.tf` — realm, api_token, service_name, notification_channel + N threshold variables
- `.observe/terraform/terraform.tfvars.example` — copy to `terraform.tfvars`, fill in credentials
- `.observe/terraform/.gitignore` — excludes provider cache, local state, and credential tfvars
- `.observe/terraform/.terraform.lock.hcl` — provider selection produced by successful init
- `.observe/detectors.md` — full detectors report with classification details
- `.observe/splunk-configure-verify.md` — Terraform/SignalFlow/coverage/safety validation

**Configure verification:** Pass | Partial | Fail | Blocked

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

## Warning Signs

- Audit report has no metrics section
- All metrics are auto-instrumented library duplicates (nothing to detect on)
- Service name contains characters invalid for SignalFlow filter values
