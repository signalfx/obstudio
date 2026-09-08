---
name: splunk-configure
description: >-
  Generate Splunk Observability Cloud detector and dashboard Terraform from
  canonical .observe audit, approved instrumentation, and verification
  evidence. Use for $splunk-configure, detectors, dashboards, alert-coverage
  audits, app-down versus degraded impact, blast-radius views, MTTD or incident
  localization, and GenAI/LLM coverage. Generate only from proven or explicitly
  accepted metrics; report readiness gaps instead of inventing signals.
metadata:
  author: otel-studio
  version: 0.2.0
  category: observability
---

# Detect -- Splunk O11y Detector and Dashboard Terraform from Observability Reports

## Overview

Read existing `.observe/` observability reports, classify detector-ready metrics
into generic, incident-readiness, and GenAI categories, and generate Terraform
configuration for Splunk Observability Cloud detectors and dashboards. Generate
resources only from source-backed metrics that are verified or explicitly
accepted as source-only inputs. Report missing or unverified readiness coverage
as instrumentation prerequisites instead of inventing alerts from absent data.

Before writing outputs, read only the tail of
`../references/report-flow-contract.md` starting at
`## Splunk Configure Contract`; it contains both the Splunk Configure Contract
and Splunk Configure Verification. Do not load the preceding audit,
instrumentation, or verification sections unless resolving a concrete contract
conflict.

When a prompt mentions MTTD, faster incident detection, better alerts, easier
incident debugging, or blast-radius visibility, generate detectors and
dashboards that make customer impact, affected workflow, likely fault domain,
blast radius, and release/config correlation faster to detect and localize.

When incident evidence mentions missed, flapping, auto-resolved, or no-data
alerts, treat that as detector reliability evidence. Do not ask app instrumentation
to emit alert lifecycle metrics unless the app owns those events; audit the
detector, dashboard, data quality, and alert coverage behavior in
`alert-coverage-audit` output.

When the audit report contains `genai_readiness[]`, GenAI findings, or source
evidence that maps signals to an LLM/GenAI workflow, classify available GenAI
metrics first and report missing or unverified GenAI signals as instrumentation
prerequisites instead of inventing detectors from absent data.

## When to Use

- After running `$otel-audit` to generate `.observe/otel-audit.json`
- After `$otel-instrument` and `$otel-verify` when the user wants detectors for
  newly implemented signals
- When the user wants alerting/detection Terraform for their service
- When creating monitors for latency, errors, throughput, saturation, runtime,
  dependency, customer-impact, or incident-readiness metrics
- When creating dashboards for API workflows, dependencies, freshness,
  queue/backpressure, customer impact, or release context
- When auditing whether existing or desired alerts cover app-down,
  primary workflow degradation, auth degradation, ingest lag/drops,
  critical workflow delay, dependency failure, blast radius, or capacity
  saturation
- When creating GenAI/LLM detectors from audit output containing `gen_ai.*`
  metrics, provider/model/tool/retrieval spans, memory/context, evaluation
  quality, token pressure, content governance, cost, fallback, model/config
  readiness, or workflow fanout gaps

**When NOT to use:** If no audit report exists yet, instruct the user to run
`$otel-audit` first.

## Process

### Supported Modes

Use the default detector/dashboard generation path unless the user asks for a
specific mode. Modes share the same observability reports and should be
implemented as report sections or Terraform output, not as separate skills.

| Mode | Trigger | Output |
|---|---|---|
| `generate` | Generate detectors/dashboards from audit metrics | `.observe/terraform/`, `.observe/detectors.md`, `.observe/dashboards.md` |
| `alert-coverage-audit` | Audit existing or desired alerts/dashboards for incident detection/localization gaps | Coverage matrix comparing readiness areas to detectors/dashboards, including detector reliability evidence for missed, flapping, auto-resolved, or no-data alerts; missing app-owned signals become instrumentation prerequisites |
| `impact-classify` | Distinguish app down from degraded API, workflow, auth, ingest, or workflow-specific impact | Impact detectors/dashboard sections grouped by workflow, outcome, region/environment, dependency, and release context |
| `blast-radius` | Detect region-wide or multi-workflow incidents earlier | Region/environment/workflow rollups and dashboards that show single-service, single-region, multi-region, or all-region blast radius |

If existing Splunk detectors or dashboards are not available in the repository
or through an approved API/source, do not claim they were audited. Generate the
desired-state coverage matrix and clearly label it as based on
`.observe/otel-audit.json` and local Terraform/config evidence only.

### Step 1 -- Locate Source Reports

Look for `.observe/otel-audit.json` in the repository root.

- If the file exists, proceed to Step 2.
- If the file is missing, stop and respond:

> No audit report found at `.observe/otel-audit.json`. Please run `$otel-audit` first
> to generate the observability coverage report.

Also look for optional downstream reports:

- `.observe/otel-instrumentation.md` for implemented signal changes and
  detector handoff.
- `.observe/otel-verify.md` for emitted metric proof, OTLP evidence, and
  unverified rows.

### Step 2 -- Parse Metadata, Metrics, Verification, and Readiness Coverage

Extract from `.observe/otel-audit.json`:

1. **Service metadata** from `meta.service_name`, `meta.language`, and
   `meta.framework`.

2. **Existing metrics** from `current_instrumentation.metrics`.
   - Each metric object provides the metric name, source, type, and attributes
     when known.
   - Record only source-backed existing metrics as detector candidates for Step
     3.

3. **Findings** from `findings`.
   - Treat each finding as an instrumentation prerequisite candidate unless it
     is already resolved by source-backed or downstream-proven metrics.
   - Preserve its priority, required fix, owner or instrument mode, and
     `verification_scenarios`.
   - Use `expected_telemetry` only to describe missing desired signals; do not
     generate detectors from desired telemetry that is not already present or
     proven.

4. **Incident readiness** from `current_instrumentation.incident_readiness`.
   - Preserve each readiness area, status, evidence, required signal or gap,
     and detection/localization impact.
   - Join partial or missing rows to findings with the same area when possible.
   - Treat missing or partial rows as prerequisites unless matching metrics are
     source-backed and proven. Never imply complete coverage while required
     signals remain missing.

5. **Implemented signal changes** from `.observe/otel-instrumentation.md` when
   present:
   - `Signals Changed`
   - `Audit Gap Closure`
   - `Verification Handoff / Results`
   - `Detector Handoff / Results`
   Use this to identify newly implemented metrics and remaining prerequisites.

7. **Verified signal proof** from `.observe/otel-verify.md` when present:
   - `Tested And Working`
   - `Not Working Or Not Proven`
   - any signal inventory, path coverage, or Explorer-visible OTLP evidence
   A metric is proof-ready only when its exact metric row is `Working`, emitted
   datapoints are proven with the expected unit/dimensions, and source evidence
   exists, unless the user explicitly accepts source-only detector generation.
   Do not infer proof from an aggregate coverage count or from a similarly
   named metric.

8. **GenAI Readiness** from canonical `genai_readiness[]`, GenAI findings, and
   source evidence when present:
   - Read every independently actionable surface row and its exact required
     signals, owner/source files, and acceptance criteria.
   - Keep provider/model, workflow/agent, tool/function, token/context,
     stream/session, retrieval, memory/context, evaluation/data export,
     content governance, privacy/cardinality, model/config, and cost ownership
     as separate detector prerequisites when the audit separates them.
   - Do not merge distinct readiness surfaces into a generic prerequisite.
   Missing or partial GenAI areas become instrumentation prerequisites unless
   matching metrics are source-backed and proven.

9. **GenAI Readiness Closure** from the bound instrumentation and verification
   JSON overlays when present:
   - Parse selected GenAI findings and their exact telemetry-change and
     item-result rows.
   - Treat any selected GenAI surface with remaining signals, non-working
     status, or missing item proof as an instrumentation prerequisite unless
     matching metrics are proven.
   - Generate detectors only for implemented or proven GenAI signals. Do not
     imply complete token/context, provider/model, tool, stream, retrieval, or
     model/config coverage while required signals remain missing.

10. **Detector reliability evidence** from gaps, readiness sections, local alert
   config, or incident evidence:
   - missed, flapping, auto-resolved, or no-data alerts
   - detectors that cannot distinguish no traffic from no telemetry
   - dashboard or detector group-by keys that hide workflow, region,
     environment, dependency, or release blast radius
   Record these in `alert-coverage-audit` output. Only turn them into
   instrumentation prerequisites when the missing data is app-owned and absent.

If the audit has no metrics and downstream reports contain no implemented or
verified metrics, continue processing gaps and readiness sections. If none are
present, stop and respond:

> The audit report contains no metrics. Detectors require metric data.
> Run `$otel-instrument` to add instrumentation, then re-run `$otel-audit`.

If there are no detector-ready metrics but gap, incident-readiness, or GenAI
readiness sections exist, do not generate detector or dashboard resources.
Create `.observe/detectors.md` and `.observe/splunk-configure-verify.md` with the
applicable instrumentation prerequisites and alert coverage matrix. Create
`.observe/dashboards.md` only when the user requested a desired-state dashboard
specification. Recommend `$otel-instrument` for missing signals and
`$otel-verify` for implemented signals that lack proof.

For `alert-coverage-audit` mode, load the Alert Coverage Audit Output section in
`references/terraform-templates.md` even when no detector-ready metric exists;
it owns the required matrix rows independently of Terraform generation.

### Step 3 -- Classify Metrics into Detector Categories

When candidate metrics exist, load `references/detector-classification.md` and
apply the classification rules to each metric from Step 2.

Before classifying individual metrics, apply Route-Level De-duplication from
`references/detector-classification.md`: group candidate metrics that share
the same `service.name` and route/operation dimension, and merge into that
histogram's route group instead of classifying as a second, independently
tracked metric: an error/status counter that only restates an outcome
already carried as an attribute on a same-route duration histogram, or a
throughput counter whose count is derivable from that histogram's own
observation count for the route (no matching histogram attribute is
required for the throughput case). One route should produce at most one
Latency, one Error, and one Throughput detector, each reading dimensions
off the smallest set of metrics the route actually emits -- not one
detector per candidate metric.

Only classify metrics that are present in source evidence and either verified
by `.observe/otel-verify.md` or explicitly accepted by the user as source-only
detector inputs. Put unverified metrics in `Skipped Metrics` with the reason
`unverified metric emission` and the next step `$otel-verify`.

Assign each accepted metric to exactly one category. Apply GenAI-specific rules
first when canonical `genai_readiness[]`, GenAI findings, or source evidence
maps the signal to an LLM/GenAI workflow, or when metric names or dimensions
explicitly indicate LLM/GenAI ownership: `gen_ai.*`, LLM, inference,
embedding, model provider/deployment, agent, tool/function calling, retrieval,
prompt/completion/context token usage, fallback, or model/config readiness. Do
not classify generic `model`, `workflow`, `tool`, `config`, `canary`, `token`,
`session`, `chat`, `memory`, `context`, `evaluation`, `evaluator`, `quality`,
`cost`, or `billing` metrics as GenAI unless audit evidence shows they belong to
a GenAI/LLM path.

After GenAI rules, apply incident-readiness categories before generic latency,
error, throughput, or saturation so customer-impact, dependency, freshness,
backpressure, auth/edge, capacity, and release/config signals do not collapse
into generic RED buckets.

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
- **freshness** -- gauges/histograms for event age, ingest lag, processing lag
- **backpressure** -- queue depth, consumer lag, oldest-message age, rebalance
  count, paused/blocked consumer gauges
- **dependency** -- dependency error, timeout, retry, rate-limit, throttle,
  circuit-breaker, endpoint health, target health, availability, unhealthy
  target count, or operation-duration metrics
- **customer-impact** -- workflow success/error/degraded/timeout counters or
  duration histograms for rendering, transaction, auth, notification, or other
  user-visible workflows
- **impact-classification** -- app/workflow availability, synthetic probe/client telemetry,
  degraded/unavailable impact, or customer-impact summary metrics used to
  distinguish app down from degraded API, workflow, auth, ingest, or
  workflow-specific impact
- **auth-edge** -- login, identity provider, domain routing, token/session, DNS, TLS,
  certificate, gateway, or edge workflow metrics
- **capacity-saturation** -- memory, CPU, disk/filesystem, JVM,
  worker/thread-pool utilization, inflight/concurrency, queue saturation,
  quota, throttling, crash-loop/restart, desired-vs-healthy,
  startup/readiness/healthcheck failure, HPA/ASG, pod, task, process, or node
  capacity metrics
- **release-context** -- `service.version`, `deployment.environment.name`,
  `cloud.region`, `cloud.platform`, `container.image.name`,
  `container.image.tags`, artifact version, config/canary/rollout metadata, or
  source-backed custom aliases used as dashboard filters and detector
  dimensions, not as standalone alert metrics
- **latency** -- duration histograms
- **error** -- counters with failure/error/invalid keywords
- **throughput** -- counters without error keywords
- **saturation** -- gauges for connections, buffers, queues, lag,
  disk/filesystem, and resource utilization
Skip metrics that match the exclusion rules (auto-instrumented library metrics
that duplicate custom signals).

For every `findings[]` entry that is still missing a metric, add an entry to the
generated report's "Instrumentation Prerequisites" section. Do not generate a
detector for a missing or unverified signal. Recommend `$otel-instrument` with
the specific coverage area when instrumentation is absent, `$otel-verify` when
implementation exists without emission proof, or name the external owner when
the signal belongs to platform/provider telemetry.

For partial closure, generate detectors only for implemented or proven signals.
Do not imply complete coverage from a partially closed audit gap. If
instrumentation or verification overlays include `remaining` or equivalent
remaining signal fields, list those signals under `Instrumentation
Prerequisites` and avoid detector names or dashboard headings that claim the
whole readiness area is covered.

For every incident-readiness area with status `missing` or `partial`, add a
prerequisite unless equivalent metrics are source-backed and proven. Do not
generate detectors from desired impact, dependency, freshness, backpressure,
auth/edge, capacity, or release/config rows unless accepted metric evidence
contains the corresponding signal.

For every `genai_readiness[]` row or GenAI finding that is still missing or has
unverified metric, trace attribute, span event, or owner-mapped external signal
evidence, add an entry to the generated report's "GenAI Instrumentation
Prerequisites" section. Do not generate a detector for a missing or unverified
signal. Recommend `$otel-instrument` with the specific human-readable GenAI
surface when instrumentation is absent, and `$otel-verify` when instrumentation
exists but emitted metric proof is missing.

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

For each detector-eligible classified metric, emit a `signalfx_detector`
resource block. Do not emit standalone detectors for release-context-only
metadata or categories that the classification reference marks as prerequisite
or dashboard evidence only. Do not emit a detector for a counter that
Route-Level De-duplication merged into a histogram's route group -- that
outcome is already covered by an Error detector reading the same histogram
filtered to its own outcome attribute, and/or a Throughput detector reading
the same histogram's observation count for the route with no outcome filter.
Two detectors legitimately reading the same metric name with different
aggregations or filters (for example a Latency detector with no filter, an
Error detector filtered to `error.type`, and a Throughput detector with only
the route filter) are not duplicates and are all expected.

Use the exact provider, detector, SignalFlow, rule, and threshold-variable
shapes in `references/terraform-templates.md`; that reference owns the HCL
examples and category defaults.

Sanitize metric names for HCL identifiers: replace dots and hyphens with
underscores, strip leading digits.

#### `.observe/terraform/variables.tf`

Follow the variable shapes in `references/terraform-templates.md`. Declare
`realm`, sensitive `api_token`, `service_name`, `notification_channel`, and one
defaulted threshold variable per detector.

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

Every dashboard must include a `service.name` filter. Include
`deployment.environment.name`, `cloud.region`, `cloud.platform`,
`service.version`, `container.image.name`, `container.image.tags`, artifact
version, config version, and rollout/canary filters only when verification
evidence or an explicitly accepted source proves those dimensions exist and
are low-cardinality. Recognize existing `deployment.environment`,
`deployment.region`, `deployment.platform`, and `container.image.tag`
dimensions, but do not generate or require those custom aliases when a
standard attribute is available. Always use the exact attribute name proven by
the audit or metric metadata; do not create duplicate filters.
Dashboard variables that apply globally across multiple charts must use
`apply_if_exist = true`. This is required for optional dimensions such as
environment, region, namespace, platform, version, image tag, config version,
rollout, dependency, and custom realm, because not every chart metric has every
dimension. Never generate wildcard variables for optional
dimensions with `apply_if_exist = false`; they can silently filter all data out
of charts whose metric lacks that dimension.
Keep the Splunk Observability Cloud API `realm` variable separate from service
telemetry dimensions. Do not use `var.realm` as a SignalFlow filter for
`sfx_realm`, `cloud.region`, `deployment.region`, or any application/runtime
dimension unless live metric metadata or the audit proves that exact dimension
and value. Prefer dashboard variables for dimensions such as environment,
region, namespace, platform, version, image tag, and custom realm so users can
select the active stream. If a chart needs a fixed dimension value, the value
must come from proven metric metadata or an explicit user choice, not from the
provider/API realm.
Before writing chart `program_text`, verify every filter and group-by dimension
against audit evidence, local metric metadata, or approved Splunk API metadata.
If a dimension is not present on the target metric, omit the filter/group-by and
document the missing dimension in `.observe/dashboards.md`. Never group by a
dimension solely because instrumentation code intended to emit it.
Only generate a dashboard panel for a metric name that is source-backed and
either `Working` in `.observe/otel-verify.md` or explicitly accepted by the user
as a source-only or approved external input. If using a provider-derived,
precomputed, or transformed metric name instead of the audited OTel name,
record its live metadata provenance and acceptance in `.observe/dashboards.md`.
Live metric metadata alone is not enough to claim source-backed coverage when
the repository does not contain the emitter. If the metric is found only in
build output, generated artifacts, `target/`, `build/`, `.class`, jar, coverage,
or stale runtime files, treat it as stale/unowned evidence: do not generate the
panel by default, and list it as a verification issue or cleanup prerequisite.
Use source files, checked-in IaC/config, audited instrumentation evidence, or an
explicit user-approved external source as provenance.
Do not combine mixed-unit signals on one chart. Split boolean readiness,
availability, ratios/percentages, bytes, counts, rates, cumulative counters,
and durations into separate panels unless the dashboard type has explicit
per-series units or axes and the report documents the unit handling. For
example, database readiness and connection-pool utilization should be separate
panels, not one shared-axis time chart.
For runtime capacity, generate separate dashboard panels and detectors for each
source-backed resource class instead of substituting adjacent runtime metrics.
When source-backed CPU utilization metrics such as `process.cpu.utilization`,
`process.runtime.*.cpu.utilization`, `jvm.cpu.recent_utilization`, or a
runtime-specific equivalent are present, generate a CPU utilization panel and
a CPU saturation detector. Memory/heap usage, thread/goroutine/worker count, GC
pressure, concurrency, disk, and quota signals belong in separate panels with
their own units. Do not use thread count, heap usage, or GC metrics as a CPU
proxy. If only cumulative CPU time is available, chart it as a diagnostic rate
with `rollup='rate'` or equivalent and list normalized CPU utilization as a
missing signal before creating a CPU saturation detector.
For pre-aggregated percentile metrics, including names such as `.p99`, `.p95`,
`p50`, `quantile`, or metrics marked as already-quantized, do not average
series for the headline chart. Use `max()` for current worst-case values and
`max(by=[...])` for breakdowns. Use `.percentile(pct=99)` only for raw
duration/histogram distributions. Match units to metric names and metadata:
convert nanoseconds to seconds or milliseconds, convert ratios to percent only
when the metric is a ratio, and label bytes/counts/rates honestly.
For cumulative counters or cumulative timers, including names that end in
`.total`, `.count`, `.time`, or metrics whose metadata shows cumulative
temporality, do not chart the raw cumulative value as current health. Use
`rollup='rate'`, a delta/rate transform, or a true duration histogram/summary.
If neither is available, label the chart as cumulative and mark it unverified
instead of presenting it as a latency, utilization, or health-rate panel.
After generating dashboard Terraform, run a value sanity check when a Splunk API
token or local metric query path is available. Execute each chart's SignalFlow
over a recent window with known traffic or a representative historical window
and confirm it returns non-empty series with plausible magnitude and expected
dimensions. If live verification is unavailable, mark the dashboard report as
unverified and call out the exact metric names, filters, units, and group-bys
that still need validation before `terraform apply`. When validating in the UI
after an update, reload the dashboard URL without a stale `configId` parameter
or reset saved dashboard overrides so the browser uses the updated dashboard
definition.

#### `.observe/terraform/terraform.tfvars.example`

Generate the exact `.tfvars.example` shape from
`references/terraform-templates.md` for the user to copy and fill in before an
apply.

Do NOT include per-detector threshold variables in this file -- they already have
sensible defaults in `variables.tf`. Include `realm`, `api_token`, and
`notification_channel` (which have no defaults) plus `service_name` for
convenience (it has a default from the report but users often override it).

### Step 5 -- Generate Detectors and Dashboards Report

Always create `.observe/detectors.md`. Create `.observe/dashboards.md` when
dashboard resources or a desired-state dashboard specification are generated.
The detector report owns the configure result, every detector's classification
rationale, skipped metrics, instrumentation prerequisites, and alert coverage.
The dashboard document is a subordinate inventory of panels, filters,
dimensions, units, and evidence; it must not define a separate result or
duplicate the report-flow contract. `.observe/splunk-configure-verify.md`
remains the authoritative proof report.

Use the Splunk Configure Contract in
`../references/report-flow-contract.md` for status semantics and evidence
ownership. Keep the detector report deterministic with this reader order:
`Executive Summary`, `Flow`, `Summary`, applicable detector categories,
`Skipped Metrics`, conditional `Instrumentation Prerequisites`, conditional
`Alert Coverage Matrix`, conditional `GenAI Instrumentation Prerequisites`,
`Classification Rules Applied`, `Terraform Output`, and `Next Steps`.
Start with `# Detectors Report: <service-name>` and record the exact `Result`,
language, framework, date, source audit, instrumentation, verification, and
output path. Use `Category | Count | Severity | Detection Method` for the
summary and `File | Contents` for the Terraform inventory. Set `Flow` to
`audit -> instrument -> verify -> configure -> configure-verify`.

The summary and category names come from
`references/detector-classification.md`; detector methods, defaults, and
severities come from `references/terraform-templates.md`. Do not copy those
authorities into the report. Each generated detector row must retain category,
metric, source, threshold variable, and default. Each skipped row must state a
reason. Use these compact prerequisite schemas:

- instrumentation: `Area | Audit Status | Missing Signal | Why No Detector Was Generated | Next Step`
- GenAI: `Surface | Audit Status | Missing Signal | Why No Detector Was Generated | Next Step`
- alert coverage: `Incident Pattern | Existing/Generated Coverage | Missing Signal or Dashboard | Detection/Localization Risk | Next Step`

Include source artifact paths, the `.observe/terraform/` inventory, exact
configure result, and publish/apply next steps. Never report an unproven metric
as covered.
### Step 6 -- Validate Configure Output

Always create `.observe/splunk-configure-verify.md` for a completed configure
run. Follow
`../references/report-flow-contract.md` Splunk Configure Verification.

Validation requirements:

1. Confirm generated files exist:
   - `.observe/terraform/detectors.tf`
   - `.observe/terraform/variables.tf`
   - `.observe/terraform/terraform.tfvars.example`
   - `.observe/terraform/.gitignore` excluding `.terraform/`, local state, and
     `terraform.tfvars`
   - `.observe/detectors.md`
   - `.observe/terraform/dashboards.tf` and `.observe/dashboards.md` when
     dashboard resources were generated
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
   - when dashboards are generated, `Pass` also requires the value sanity check
     from Step 4 for every chart. If live chart evaluation is unavailable,
     report `Partial` and name dashboard values, dimensions, and units as
     unproven.
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
   - generated dashboard charts map to accepted metrics and proven dimensions
   - skipped metrics explain whether they are missing, unverified, duplicate,
     unsafe, or owner-mapped
   - prerequisites point to `$otel-instrument` for missing instrumentation and
     `$otel-verify` for missing emission proof

After the checks above, always run the bundled dependency-free validator for
runs that generated Terraform:

```bash
python3 <splunk-configure-skill-dir>/scripts/validate_configure_output.py \
  --terraform-dir .observe/terraform \
  --detectors-report .observe/detectors.md \
  --configure-verify-report .observe/splunk-configure-verify.md \
  --verify-report .observe/otel-verify.md
```

For every metric the user explicitly accepted as source-only, append
`--allow-source-only-metric <exact-metric-name>`. Never use that option merely
because `.observe/otel-verify.md` is absent.

Treat validator failure as configure failure and repair the generated files.
The script validates file presence, HCL resource/variable references,
provider credential/endpoint wiring, SignalFlow labels and service filters,
sensitive identifiers, local-state ignore rules, reader-first heading order,
matching configure statuses, and exact metric reconciliation against
reader-first `Working` metric rows. `.observe/detectors.md` must inherit the
result from `.observe/splunk-configure-verify.md`; the plan and its verification
must never disagree. The script does not replace `terraform validate`; run both
when Terraform is available. The bundled script validates detector resources,
not dashboard resources; use the explicit dashboard evidence checks above and
do not attribute dashboard proof to the script.

Use the exact report shape and heading order under Splunk Configure
Verification in `../references/report-flow-contract.md`; it owns the result
semantics, authenticated-plan gate, headings, and order. Populate those
sections with concrete evidence from the validation requirements above.
Under `What Was Added`, list every detector as
`Resource Label | Metric | Detect Condition | Severity`; do not replace the
per-detector inventory with an aggregate summary.

For a prerequisites-only run with no detector-ready metrics, still write the
configure verification report, record that Terraform validation was not run,
and use `Blocked` when no meaningful output validation can execute. Do not run
the file validator against intentionally absent Terraform files and do not mark
the run `Pass`.

### Step 7 -- Chat Summary

After generating and validating outputs, summarize category counts from
`references/detector-classification.md`, the `.observe/terraform/` path, files
actually written, the exact configure verification result, unproven work, and
the next review, credential, plan, and publish/apply actions. Do not paste HCL
or empty category tables into chat; `references/terraform-templates.md` owns
the output shapes.

## Warning Signs

- Audit report has no metrics section
- All metrics are auto-instrumented library duplicates (nothing to detect on)
- Service name contains characters invalid for SignalFlow filter values
