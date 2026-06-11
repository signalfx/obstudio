---
name: splunk-configure
description: >-
  Generate Splunk Observability Cloud detector and dashboard Terraform from an
  existing otel-audit report. Reads .observe/otel.md, classifies metrics and
  APM readiness coverage into detector/dashboard categories, and outputs
  ready-to-apply HCL with SignalFlow program_text. Use when the user types
  $splunk-configure, asks to "generate detectors", "create alerts from audit",
  "build Terraform for monitors", "set up Splunk detectors", "create
  dashboards", "audit alert coverage", "classify app down vs degraded impact",
  "build blast-radius dashboards", asks for GenAI/LLM detector coverage, asks
  to improve alerting or incident localization from observability gaps, or asks
  to include deployment, release, environment, Helm, GitOps, Terraform,
  serverless, VM, container, health, capacity, rollout, dependency config, or
  config context in alerts.
metadata:
  author: otel-studio
  version: 0.1.0
  category: observability
---

# Detect -- Splunk O11y Detector and Dashboard Terraform from Audit Report

## Overview

Read an existing `.observe/otel.md` audit report, classify detected metrics and
APM readiness coverage into detector categories, and generate Terraform
configuration for Splunk Observability Cloud detectors and dashboards. Use
metric detectors for available signals and report missing readiness coverage as
instrumentation prerequisites instead of inventing alerts from absent data.

When a prompt mentions MTTD, faster incident detection, better alerts, easier
incident debugging, or blast-radius visibility, generate detectors and
dashboards that make customer impact, affected workflow, likely fault domain,
blast radius, and release/config correlation faster to detect and localize.
For GenAI/LLM workflows, also make provider/model/tool/retrieval/token pressure,
fallback, model/config readiness, and agent fanout visible without a manual
trace search.
When the audit includes deployment context, use it to add safe detector and
dashboard dimensions and to report runtime, release/config, health, capacity,
and dependency-config prerequisites.

## When to Use

- After running `$otel-audit` to generate `.observe/otel.md`
- When the user wants alerting/detection Terraform for their service
- When creating monitors for RED signals or saturation metrics
- When creating dashboards for API workflows, dependencies, freshness,
  queue/backpressure, customer impact, or release context
- When auditing whether existing or desired alerts cover app-down,
  primary workflow degradation, auth degradation, ingest lag/drops,
  decision or delivery workflow delay, dependency failure, blast radius, or capacity
  saturation
- When creating GenAI/LLM dashboards or detectors from audit output containing
  `gen_ai.*` metrics, agent/tool/retrieval spans, token pressure, provider
  latency/error, model/config readiness, fallback, or workflow fanout gaps
- When deployment/runtime context should shape alert grouping, filters, or
  prerequisites for release/config, health, rollout, and capacity detection

**When NOT to use:** If no audit report exists yet, instruct the user to run
`$otel-audit` first.

## Process

### Supported Modes

Use the default detector/dashboard generation path unless the user asks for a
specific mode. Modes share the same `.observe/otel.md` input and should be
implemented as report sections or Terraform output, not as separate skills.

| Mode | Trigger | Output |
|---|---|---|
| `generate` | Generate detectors/dashboards from audit metrics | `.observe/terraform/`, `.observe/detectors.md`, `.observe/dashboards.md` |
| `alert-coverage-audit` | Audit existing or desired alerts/dashboards for incident detection/localization gaps | Coverage matrix comparing readiness areas to detectors/dashboards; missing signals become instrumentation prerequisites |
| `impact-classify` | Distinguish app down from degraded API, workflow, auth, ingest, or delivery impact | Impact detectors/dashboard sections grouped by workflow, outcome, region/environment, dependency, and release context |
| `blast-radius` | Detect region-wide or multi-workflow incidents earlier | Region/environment/workflow rollups and dashboards that show single-service, single-region, multi-region, or all-region blast radius |
| `genai-readiness` | Detect and localize GenAI/LLM workflow degradation | Provider/model/tool/retrieval/token/fallback/workflow panels plus instrumentation prerequisites for missing OTel GenAI signals |

If existing Splunk detectors or dashboards are not available in the repository
or through an approved API/source, do not claim they were audited. Generate the
desired-state coverage matrix and clearly label it as based on `.observe/otel.md`
and local Terraform/config evidence only.

### Step 1 -- Locate Audit Report

Look for `.observe/otel.md` in the repository root.

- If the file exists, proceed to Step 2.
- If the file is missing, stop and respond:

> No audit report found at `.observe/otel.md`. Please run `$otel-audit` first
> to generate the observability coverage report.

### Step 2 -- Parse Service Metadata, Metrics, and Readiness Coverage

Extract from `.observe/otel.md`:

1. **Service metadata** from the report header:
   - Service name (from the `# Observability Report: {service-name}` heading)
   - Language (from the `**Language:**` field)
   - Framework (from the `**Framework:**` field)

2. **Metrics table** from the `### Metrics` section:
   - Each row provides: metric name, source, and type (auto/custom)
   - Record all metrics for classification in Step 3

3. **Gap Ledger** from the `## Gap Ledger` section when present. This is the
   structured handoff contract from `$otel-audit` and `$otel-instrument`:
   - Parse `gap_id`, status, `required_signals`, owner, `code_surface`, and
     `acceptance_criteria`.
   - Treat any row with status `missing` or `partial` as an instrumentation
     prerequisite unless matching metrics already exist in the Metrics table.
   - For partial closure or closure matrices that include `remaining_signals`,
     generate detectors only for implemented or proven signals. Do not imply
     complete coverage in detector names, descriptions, dashboards, or coverage
     summaries while required signals remain missing, even when one matching
     metric exists.
   - List `remaining_signals` under `Instrumentation Prerequisites` with the
     owning code surface, provider, platform, deployment source, or exact
     missing source from the ledger.

4. **Gaps** from the `## Gaps` section. This is the current-main
   `$otel-audit` handoff:
   - Treat each bullet as an instrumentation prerequisite candidate.
   - Infer impact from the wording, available metric evidence, and readiness
     sections.
   - Add missing readiness signals to the generated report instead of creating
     detector placeholders for absent data.

5. **Legacy APM Readiness Coverage** from the `## APM Readiness Coverage`
   section when present. Use this only when `## Gaps` is absent:
   - Area
   - Status
   - Evidence
   - Gap
   - Detection/Localization Impact, or the legacy column name MTTD Impact

6. **Incident Readiness** from the `## Incident Readiness` section when present:
   - API/workflow impact
   - dependencies
   - freshness/backpressure
   - auth/edge/capacity/release context
   Missing or partial incident-readiness areas become instrumentation
   prerequisites unless matching metrics already exist in the Metrics table.

7. **GenAI Readiness** from the `## GenAI Readiness` section when present:
   - workflow trace shape
   - semantic-convention completeness
   - metrics and detectors
   - privacy/cardinality
   Missing or partial GenAI areas become instrumentation prerequisites unless
   matching metrics already exist in the Metrics table.

8. **Deployment Context** from `## Deployment Context`, when present:
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

If the Metrics section says "No metrics detected.", do not generate detector or
dashboard Terraform from metrics. Continue processing `## Gaps`,
`## APM Readiness Coverage`, `## Incident Readiness`, and
`## GenAI Readiness`, and `## Deployment Context` so the output still includes
`.observe/detectors.md` instrumentation/deployment prerequisites and, for
`alert-coverage-audit` mode, an alert coverage matrix. Include an alert coverage
matrix when running `alert-coverage-audit`. If there are no metrics, no gaps,
and no readiness sections, stop and respond:

> The audit report contains no metrics. Detectors require metric data.
> Run `$otel-instrument` to add instrumentation, then re-run `$otel-audit`.

### Step 3 -- Classify Metrics into Detector Categories

When metrics exist, load `references/detector-classification.md` and apply the
classification rules to each metric from Step 2.

Assign each metric to exactly one category. Apply GenAI-specific rules first
when the audit has a `## GenAI Readiness` section or when metric names or
dimensions explicitly indicate LLM/GenAI ownership: `gen_ai.*`, LLM, inference,
embedding, model provider/deployment, agent, tool/function calling, retrieval,
token, fallback, or model/config readiness. Do not classify generic `model`,
`workflow`, `tool`, `config`, or `canary` metrics as GenAI unless the audit
evidence shows they belong to a GenAI/LLM path. Use generic latency, error,
throughput, saturation, or dependency categories when no GenAI-specific category
matches.

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
- **latency** -- duration histograms
- **error** -- counters with failure/error/invalid keywords
- **throughput** -- counters without error keywords
- **saturation** -- gauges for connections, buffers, queues, lag,
  disk/filesystem, and resource utilization
- **freshness** -- gauges/histograms for event age, ingest lag, processing lag
- **backpressure** -- queue depth, consumer lag, oldest-message age, rebalance
  count, paused/blocked consumer gauges
- **dependency** -- dependency error, timeout, retry, rate-limit, throttle,
  circuit-breaker, endpoint health, target health, availability, unhealthy
  target count, or operation-duration metrics
- **customer-impact** -- workflow success/error/degraded/timeout counters or
  duration histograms for rendering, transaction, auth, decision evaluation,
  notification, or delivery workflows
- **impact-classification** -- app/workflow availability, synthetic probe/client telemetry,
  degraded/unavailable impact, or customer-impact summary metrics used to
  distinguish app down from degraded API, workflow, auth, ingest, or delivery
  impact
- **auth-edge** -- login, identity provider, domain routing, token/session, DNS, TLS,
  certificate, gateway, or edge workflow metrics
- **capacity-saturation** -- memory, CPU, disk/filesystem, JVM,
  worker/thread-pool utilization, inflight/concurrency, queue saturation,
  quota, throttling, crash-loop/restart, desired-vs-healthy,
  startup/readiness/healthcheck failure, HPA/ASG, pod, task, process, or node
  capacity metrics
- **release-context** -- `service.version`, `deployment.environment`,
  `deployment.region`, `deployment.platform`, `container.image.tag`, artifact
  version, config/canary/rollout metadata used as dashboard filters and
  detector dimensions, not as standalone alert metrics
Skip metrics that match the exclusion rules (auto-instrumented library metrics
that duplicate custom signals).

For every `## Gap Ledger` row or `## Gaps` entry that is still missing a metric,
add an entry to the generated report's "Instrumentation Prerequisites" section.
Do not generate a detector for a missing signal. Recommend `$otel-instrument`
with the specific coverage area that must be added first.

For partial closure, generate detectors only for implemented or proven signals.
Do not imply complete coverage from a partially closed audit gap. If a ledger or
instrumentation closure matrix includes `remaining_signals`, list those signals
under `Instrumentation Prerequisites` and avoid detector names or dashboard
headings that claim the whole readiness area is covered.

For legacy APM readiness rows, add prerequisites for every area with status
`missing` or `partial` when no `## Gaps` entry covers the same area.

For every incident-readiness area with status `missing` or `partial`, add a
prerequisite unless equivalent metrics are present. Do not generate detectors
from desired impact, dependency, freshness, backpressure, auth/edge, capacity,
or release/config rows unless the Metrics table contains the corresponding
metric evidence.

For every GenAI readiness area with status `missing` or `partial`, add a
prerequisite unless equivalent metrics are present. Do not invent detectors from
trace-only attributes such as conversation, session, task, user, account, tenant,
request, or trace IDs. These may be useful for trace drilldown, but they are not
safe detector group-by dimensions.

### SignalFlow and Dashboard Guardrails

- Keep the Splunk Observability Cloud API `realm` variable separate from
  telemetry dimensions. Do not use `var.realm` as a SignalFlow filter. Use
  proven telemetry dimensions such as `sfx_realm`, `deployment.environment`, or
  `cloud.region` only when they exist in the audit and are low-cardinality.
- For dashboard variables, set `apply_if_exist = true` for optional filters
  that may be absent on some metrics, and `apply_if_exist = false` only for
  required service-scoping filters backed by every chart metric.
- Before writing chart `program_text`, verify the metric type and unit. For
  pre-aggregated percentile metrics, do not average or percentile them again;
  chart the value directly and record a value sanity check in
  `.observe/dashboards.md` when units are ambiguous.
- Do not carry forward a stale `configId` parameter from an existing dashboard
  unless the audit proves it is still emitted. Treat stale/unowned evidence as a
  dashboard prerequisite, not a generated filter.
- Do not mix mixed-unit signals in one chart. Use separate panels for latency,
  count/rate, percentage, freshness age, and capacity utilization.
- Do not infer coverage from provider-derived or stale/unowned evidence. Only
  claim source-backed coverage from the metric source, trace/span source,
  runtime file, or dashboard file inspected in the current run.
- For cumulative counters and cumulative timers, use an explicit
  `rollup='rate'` or delta/rate expression before thresholding rates. Do not
  alert on ever-increasing cumulative values directly.
- For source-backed CPU utilization, generate a CPU saturation detector only
  from normalized CPU utilization when available. Do not use thread count,
  goroutine count, or worker count as CPU saturation. If only cumulative CPU time
  exists, use it as a diagnostic rate with `rollup='rate'` and list
  normalized CPU utilization as a prerequisite.

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

Generate detector Terraform using `references/terraform-templates.md`. Also
generate dashboard Terraform or, when a dashboard panel cannot be expressed
confidently from available metrics, a dashboard specification in
`.observe/dashboards.md`.
Dashboard Terraform should use `signalfx_dashboard_group`,
`signalfx_dashboard`, and chart resources such as `signalfx_time_chart`,
`signalfx_single_value_chart`, `signalfx_table_chart`, or `signalfx_list_chart`
when enough metric evidence exists.

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
  description = "Splunk Observability Cloud API realm"
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

#### `.observe/terraform/dashboards.tf`

Generate a service dashboard with sections for every detector category that has
metrics:

| Section | Charts |
|---|---|
| API workflows | request rate, p99 latency, 5xx/error rate by route/status |
| External dependencies | dependency latency, error/timeout/retry/rate-limit rate, circuit-breaker state, endpoint health, target health, availability, and unhealthy target count when present |
| Data freshness | newest event age, ingest lag, processing lag, accepted/dropped by reason |
| Queue/backpressure | queue depth, consumer lag, oldest message age, rebalance count, paused consumers |
| Customer impact | user workflow duration, success/error/degraded/timeout by workflow |
| Impact classification | app-down vs degraded workflow counts, synthetic probe/client telemetry/API/freshness/dependency correlation, impact by region/environment |
| Auth/edge workflows | auth success/error/latency, identity provider failures, domain-routing/DNS/TLS/gateway failures |
| Capacity saturation | memory/CPU/disk/runtime/thread-pool/concurrency/quota/throttle/restart, desired-vs-healthy, startup/readiness/healthcheck failure, and traffic target health where metrics exist |
| Blast radius | impacted workflows and regions over time, grouped by service, deployment region, environment, platform, release, and dependency |
| Release context | dashboard filters or event overlays for service version, deployment environment/region/platform, container image tag, artifact version, config version, and canary/rollout dimensions |
| GenAI workflow | workflow duration/outcome, agent fanout, LLM-call count, tool-call count, timeout rate by workflow/environment |
| GenAI provider/model | provider latency/error/rate-limit/timeout, requested model, response model, region/deployment, fallback |
| GenAI token pressure | input/output token histograms, context size, cache read/create tokens, token growth by workflow/model |
| GenAI tools/retrieval | tool success/error/latency by stable tool name, retrieval latency/error/no-result/stale-result |
| GenAI model/config readiness | failed model resolution, missing deployment, config version/canary/feature-flag filters |

Every dashboard must include a `service.name` filter. Include
`deployment.environment`, `deployment.region`, `deployment.platform`,
`service.version`, `container.image.tag`, artifact version, config version, and
rollout/canary filters when the metrics or audit evidence show those dimensions
exist and are low-cardinality.
Prefer exact metric/resource attribute names proven by the audit, such as
`cloud.region` or platform-provided container image attributes. Do not create
duplicate filters only to force generic alias names.
For GenAI dashboards, include provider, requested model, response model,
operation name, stable tool name, workflow name, environment/region, deployment
version, and config version only when present and low-cardinality. Never group
charts or detectors by user, account, tenant, conversation, session, task,
request, trace, raw prompt, completion, retrieved document, raw URL, or tool
argument values.

#### `.observe/terraform/terraform.tfvars.example`

Generate a `.tfvars.example` file the user copies and fills in to apply:

```hcl
realm                = ""   # Splunk Observability Cloud API realm
api_token            = ""   # Splunk O11y API token (org-level, detector write)
service_name         = "<service-name from report>"
notification_channel = ""   # e.g. "Email,team@example.com" or PagerDuty routing key
```

Do NOT include per-detector threshold variables in this file -- they already have
sensible defaults in `variables.tf`. Include `realm`, `api_token`, and
`notification_channel` (which have no defaults) plus `service_name` for
convenience (it has a default from the report but users often override it).

### Step 5 -- Generate Detectors and Dashboards Report

Create `.observe/detectors.md` and `.observe/dashboards.md` as human-readable
companions to the Terraform files. The detector report documents every detector
that was generated, its classification rationale, thresholds, and which metrics
were skipped. The dashboard report documents generated panels, filters, and any
readiness coverage that still requires `$otel-instrument`.

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
| Freshness  | N     | Critical | Static lag/age threshold |
| Backpressure | N   | Major    | Static lag/depth threshold |
| Dependency | N     | Major    | Latency/error/timeout threshold |
| Customer Impact | N | Critical | Workflow success/error/latency threshold |
| Impact Classification | N | Critical | App-down/degraded workflow rollup |
| Auth/Edge | N | Critical | Login/edge success/error/latency threshold |
| Capacity Saturation | N | Major | Resource/quota/throttle/restart threshold |
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

## Instrumentation Prerequisites

| Area | Audit Status | Missing Signal | Why No Detector Was Generated | Next Step |
|------|--------------|----------------|-------------------------------|-----------|
| Data freshness | missing | newest event age, ingest lag, dropped records by reason | No metric exists in `.observe/otel.md` | Run `$otel-instrument` to add data freshness signals |
| Dependency health | missing | endpoint health, target health, availability, timeout/rate-limit count, or unhealthy target count | No matching dependency health metric exists in `.observe/otel.md` | Run `$otel-instrument` or configure platform telemetry for dependency health signals |
| Capacity health | missing | disk saturation, desired-vs-healthy, startup/readiness/healthcheck failure, restart count, or traffic target health | No runtime/platform metric exists in `.observe/otel.md` | Run `$otel-instrument` or add platform telemetry before creating detectors |

## Deployment Prerequisites

| Area | Status | Needed Before Alerting |
|------|--------|------------------------|
| Release/config | <partial/missing/unknown> | <version/config/rollout dimensions or repo path needed> |
| Dependency config | <partial/missing/unknown> | <dependency endpoint/region/timeout/retry/circuit-breaker/config source or metric needed> |
| Dependency health | <partial/missing/unknown> | <dependency endpoint health/target health/error/timeout/rate-limit metric needed> |
| Health/capacity | <partial/missing/unknown> | <restart/readiness/desired-vs-healthy/CPU/memory/disk/throttle/quota/concurrency metrics or deployment source needed> |
| Export path | <partial/missing/unknown> | <collector/export configuration needed> |

## Alert Coverage Matrix

Use this section for `alert-coverage-audit` mode and include it in the detector
report when readiness coverage is partial or missing.

| Incident Pattern | Existing/Generated Coverage | Missing Signal or Dashboard | Detection/Localization Risk | Next Step |
|---|---|---|---|---|
| Primary workflow unavailable | {detector/dashboard or "none found"} | {workflow impact metric, dependency metric, or synthetic/client telemetry signal} | {why detection/debugging remains slow} | {configure detector or instrument signal} |
| Ingest lag/drops | {detector/dashboard or "none found"} | {freshness/drop/lag signal} | {risk} | {next step} |
| Auth/domain-routing/edge | {detector/dashboard or "none found"} | {auth/edge workflow signal} | {risk} | {next step} |
| Decision or delivery workflow | {detector/dashboard or "none found"} | {workflow delivery/evaluation outcome signal} | {risk} | {next step} |
| Multi-region blast radius | {detector/dashboard or "none found"} | {region/environment/workflow rollup} | {risk} | {next step} |
| Dependency endpoint health | {detector/dashboard or "none found"} | {endpoint health, target health, unavailable, timeout, rate-limit, or unhealthy target signal} | {risk} | {next step} |
| Capacity saturation | {detector/dashboard or "none found"} | {CPU/memory/disk/quota/throttle/concurrency/restart/readiness/desired-vs-healthy/platform signal} | {risk} | {next step} |
| Release/config correlation | {dashboard filter/event overlay or "none found"} | {service.version, deployment.region, deployment.platform, container.image.tag, artifact version, config version, or rollout/canary id} | {risk} | {next step} |

## Classification Rules Applied

<include the decision flowchart from references/detector-classification.md>

## Terraform Output

| File | Contents |
|------|----------|
| `detectors.tf` | N `signalfx_detector` resources with inline SignalFlow |
| `dashboards.tf` | dashboard group, dashboard, and panel resources for classified metrics when metric evidence exists |
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

After generating all files (Terraform + reports), present a summary:

```
## Detectors Generated

| Category    | Count |
|-------------|-------|
| Latency     | N     |
| Error       | N     |
| Saturation  | N     |
| Throughput  | N     |
| Freshness   | N     |
| Backpressure | N    |
| Dependency  | N     |
| Customer Impact | N |
| Impact Classification | N |
| Auth/Edge | N |
| Capacity Saturation | N |

**Output:** `.observe/terraform/`

Files:
- `.observe/terraform/detectors.tf` -- N detector resources
- `.observe/terraform/dashboards.tf` -- service dashboard and panel resources when metric evidence exists
- `.observe/terraform/variables.tf` -- realm, api_token, service_name, notification_channel + N threshold variables
- `.observe/terraform/terraform.tfvars.example` -- copy to `terraform.tfvars`, fill in credentials
- `.observe/detectors.md` -- full detectors report with classification details
- `.observe/dashboards.md` -- dashboard sections, filters, and readiness prerequisites

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
  description = "Splunk Observability Cloud API realm"
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
