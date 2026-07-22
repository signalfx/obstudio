---
name: splunk-dashboard
description: >-
  Generate Splunk Observability Cloud dashboard Terraform from canonical OTel
  audit JSON and its approved instrumentation and verification overlays, with
  legacy .observe/otel.md fallback only when JSON is absent. Groups proven or
  explicitly accepted metrics into dashboard panels and outputs ready-to-apply
  HCL (signalfx_dashboard_group + signalfx_dashboard + per-panel
  signalfx_*_chart resources) plus a sidecar preview model for the local
  Observer. Use when the user types
  $splunk-dashboard, asks to "generate a dashboard", "build a dashboard from
  the audit", "create charts for my service", or "visualize my metrics".
metadata:
  author: otel-studio
  version: 0.1.0
  category: observability
---

# Dashboard -- Splunk O11y Dashboard Terraform from Audit Report

## Overview

Prefer `.observe/otel-audit.json` plus matching selection, instrumentation, and
verification overlays. Group proven or explicitly accepted source-only metrics
into dashboard panels (RED-style layout), and generate Terraform for Splunk
Observability Cloud `signalfx_dashboard_group`, `signalfx_dashboard`, and
per-panel `signalfx_*_chart` resources with inline SignalFlow `program_text`.
Also emit a sidecar `.observe/dashboards.preview.json` that the local Observer's
**Dashboards** tab renders against live OTLP data as an approximate preview.

Before parsing inputs, read `../references/report-flow-contract.md`. Follow its
canonical chain and precedence:

`audit JSON -> HTML approval -> selection JSON -> instrumentation JSON -> verify JSON -> dashboard Terraform -> $splunk-dashboard-publish`

This is the visualization analogue of `$splunk-configure` (which generates
detectors). It shares its parsing rules and SignalFlow fragments; it differs in
that a dashboard is a three-level object — group → dashboard → charts[] — where
each chart is a separate resource placed on a 12-column grid.

## When to Use

- After `$otel-audit` generated `.observe/otel-audit.json` and the user reviewed
  `.observe/otel.html`
- After `$otel-instrument` and `$otel-verify` when newly approved metrics should
  appear in dashboards
- When the user wants a dashboard / charts / a visual overview for their service
- When the user wants to preview a dashboard layout locally before pushing it to
  Splunk (the Observer Dashboards tab reads the preview sidecar this skill writes)

**When NOT to use:** If no audit report exists yet, instruct the user to run
`$otel-audit` first. For alerting/detection Terraform, use `$splunk-configure`.
To push the generated dashboards to a live org, use `$splunk-dashboard-publish`.

## Process

### Step 1 -- Locate Canonical Inputs

Look for `.observe/otel-audit.json` in the repository root.

- If it exists, validate and use it as the audit authority. Also load
  `.observe/otel-selection.json`, `.observe/otel-instrumentation.json`, and
  `.observe/otel-verify.json` when present. Require each overlay's `audit_id` and
  `audit_sha256` to match the canonical audit. A stale or invalid JSON artifact
  is an error; do not fall back to Markdown or fill missing JSON fields from it.
- Only when `.observe/otel-audit.json` is absent, fall back to the legacy
  `.observe/otel.md` audit and its Markdown instrumentation/verification reports.
  Do not combine legacy Markdown inputs with JSON overlays.
- If neither audit artifact exists, stop and respond:

> No audit report found at `.observe/otel-audit.json` or legacy
> `.observe/otel.md`. Please run `$otel-audit` first.

### Step 2 -- Parse Metadata, Approved Metrics, Proof, and GenAI Coverage

In canonical JSON mode:

1. Read service name, language, and framework from `meta`.
2. Read existing source-backed candidates from
   `current_instrumentation.metrics`; preserve each exact `name`, `source`, and
   `type`.
3. Read findings and `genai_readiness`. Missing readiness signals become
   instrumentation prerequisites, not invented panels.
4. Use `.observe/otel-selection.json` to scope downstream finding IDs. Use
   `.observe/otel-instrumentation.json` `telemetry_changes` only for those
   approved IDs, preserving exact metric names and provenance.
5. Join `.observe/otel-verify.json` by finding ID. A newly implemented metric is
   proof-ready only when its stable instrumentation telemetry item ID has a
   matching `working` verification `item_results` row and the mapped scenario
   evidence proves the exact emitted metric name, unit, and required dimensions.
   The bound instrumentation item must itself have `type: metric`, and its
   exact `name` must equal the SignalFlow `data()` metric.
   Do not infer proof from an aggregate count, finding-level status, or a
   similarly named signal.

In legacy fallback mode, extract service metadata, the `### Metrics` table,
gaps, and `## GenAI Readiness` from `.observe/otel.md`; extract implemented
signals from `.observe/otel-instrumentation.md` and exact `Working` proof from
`.observe/otel-verify.md` when present.

Generate panels only for metrics that are source-backed and either verified by
the authoritative verification overlay or explicitly accepted by the user as
source-only inputs. Record every other metric in `Skipped Metrics` with the
reason and `$otel-verify` as the next step. Record the exact source-only
acceptance in `.observe/dashboards.md`.

If the Metrics section says "No metrics detected." and there are no GenAI
readiness sections, stop and respond:

> The audit contains no dashboard-ready metrics. Review `.observe/otel.html`,
> approve applicable findings, run `$otel-instrument`, then run `$otel-verify`.

### Step 3 -- Group Metrics into Panels

Load `references/dashboard-classification.md` and apply its grouping rules to
each metric from Step 2. Each metric maps to a panel with a chart type and a grid
placement:

- **Overview KPI row (top):** a row of `single_value` panels — one per RED
  signal that exists (p99 latency, error rate, throughput) plus key saturation
  gauges — giving an at-a-glance service summary.
- **Latency** (duration histograms) → a `time_series` percentile panel.
- **Error** (counters whose name carries an error keyword — e.g.
  `checkout.payment.errors`, `http.server.errors.total` — keyed on counter-ness,
  not a required `.total`/`.count` suffix) → a `time_series` error-rate panel.
- **Throughput** (non-error counters — e.g. `checkout.orders.processed`,
  `http.server.requests.total` — same counter test, no error keyword) → a
  `time_series` rate panel.
- **Saturation** (gauges: connections, queues, buffers, lag) → a `single_value`
  panel (and optionally a `time_series` trend panel).
- **GenAI** metrics (when present) → their own `signalfx_dashboard` inside a
  GenAI dashboard group, with latency/token/provider/tool panels.

Skip metrics that match the exclusion rules (auto-instrumented library
duplicates, informational-only gauges). Record skipped metrics with a reason for
the report.

### Step 4 -- Generate Terraform

Create the output directory `.observe/terraform/` if it does not exist. Generate
three files using `references/dashboard-templates.md` plus the shared
`../references/signalflow-patterns.md` for chart `program_text`:

#### `.observe/terraform/dashboards.tf`

- One `signalfx_dashboard_group` (plus a second GenAI group when GenAI metrics
  exist).
- One or more `signalfx_dashboard` referencing the group.
- One `signalfx_<type>_chart` per panel (`signalfx_time_chart`,
  `signalfx_single_value_chart`, etc.), with SignalFlow `program_text` built from
  the shared `signalflow-patterns.md` fragment (no `detect()/when()/threshold()`
  tail — charts only visualize).
- Give every chart a globally unique HCL resource label and put its exact stable
  signal provenance inside the resource as `# telemetry-item:`. Use
  `OTEL-###.<item>` for an implemented and verified telemetry item. For a
  pre-existing metric that the user explicitly accepted without item proof, use
  `SOURCE-METRIC.<exact-metric-name>`; never invent an `OTEL-###` ID. This
  comment is machine-readable provenance; finding-level status or a free-text
  metric description is not a substitute.
- Each chart is placed via the dashboard's `chart { chart_id = ...; column; row;
  width; height }` block on the 12-wide grid: `column` 0-11, `width` 1-12,
  `row` ≥0, `height` ≥1.

Sanitize metric names for HCL identifiers: replace dots and hyphens with
underscores, strip leading digits.

#### `.observe/terraform/variables.tf`

> **REQUIRED: `sensitive = true` on `api_token` — no exceptions.**
> The `api_token` variable MUST include `sensitive   = true`. Omitting it is a
> hard failure: Terraform will log the value in plaintext. Copy the block below
> exactly; do not remove `sensitive = true`.

```hcl
variable "realm" {
  description = "Splunk Observability Cloud realm (e.g. us1, eu0)"
  type        = string
}

variable "api_token" {
  description = "Splunk Observability Cloud API token"
  type        = string
  sensitive   = true   # REQUIRED — must always be present
}

variable "service_name" {
  description = "Service name for dashboard naming and chart filters"
  type        = string
  default     = "<service-name from report>"
}
```

`api_token` is always `sensitive = true` — it is a secret and must never be
logged, written into a report, or committed with a real value.

#### `.observe/terraform/terraform.tfvars.example`

```hcl
realm        = ""   # e.g. us1, eu0, lab0
api_token    = ""   # Splunk O11y API token (org-level, dashboard write)
service_name = "<service-name from report>"
```

### Step 5 -- Emit the Observer Preview Sidecar

Write `.observe/dashboards.preview.json` for the local Observer Dashboards tab.
Because this skill already resolves `${var.*}` and dedents the `<<-EOF` heredocs
while writing HCL (per `../references/terraform-normalization.md`), write the
**fully-resolved** `programText` here — the Observer does no HCL parsing.

```jsonc
{
  "schemaVersion": 1,
  "generatedAt": "<RFC3339 timestamp>",
  "groups": [
    {
      "name": "<service-name> Overview",
      "description": "RED + saturation dashboard for <service-name>",
      "dashboards": [
        {
          "name": "<service-name> RED",
          "description": "Rate, errors, duration",
          "charts": [
            {
              "label": "p99_latency",
              "title": "P99 Latency",
              "chartType": "time_series",
              "telemetryItemId": "OTEL-001.http-duration",
              "productAction": "Add the verified latency metric to the RED dashboard.",
              "programText": "A = data('http.server.request.duration', filter=filter('service.name','<service>')).percentile(pct=99).publish(label='P99 Latency')",
              "text": null,
              "layout": { "column": 0, "row": 0, "width": 6, "height": 3 }
            }
          ]
        }
      ]
    }
  ]
}
```

- `chartType` ∈ `time_series | single_value | list | heatmap | text | table`.
- `programText` carries the resolved SignalFlow (no `${var.*}`), normalized by
  heredoc form: dedent `<<-TAG`, but preserve content indentation for `<<TAG`.
  For a `text` panel, set `programText: null` and put the markdown in `text`.
- `telemetryItemId` must equal the chart resource's `# telemetry-item:` comment:
  the exact stable ID from the instrumentation and verification overlays, or
  `SOURCE-METRIC.<exact-metric-name>` for an explicitly accepted pre-existing
  metric. `productAction` is the item-specific chart or dashboard follow-up;
  both fields are required on every chart.
- `layout` mirrors the HCL `chart {}` block exactly: `column` 0-11, `row` ≥0,
  `width` 1-12, `height` ≥1. The grid is 12 columns wide.

Keep the preview sidecar in lockstep with `dashboards.tf`: every chart in the HCL
appears exactly once in the sidecar with the same label, type, resolved query,
and grid placement.

Validate this parity deterministically before reporting success. Also validate
that every preview chart maps back to a verified telemetry item ID and its
item-specific chart/dashboard follow-up. Generating the JSON file proves only
the preview contract; it does not prove that the Observer rendered it or that a
live SignalFlow query returned plausible data.

Run the dependency-free validator from the skill directory (it uses only the
Python standard library):

```bash
python3 scripts/validate_dashboard_output.py \
  --terraform <repo>/.observe/terraform/dashboards.tf \
  --preview <repo>/.observe/dashboards.preview.json \
  --report <repo>/.observe/dashboards.md \
  --verification <repo>/.observe/otel-verify.json \
  --audit <repo>/.observe/otel-audit.json \
  --selection <repo>/.observe/otel-selection.json \
  --instrumentation <repo>/.observe/otel-instrumentation.json
```

The validator resolves defaults from the sibling `variables.tf` automatically.
Pass `--tfvars <path>` only when the generated queries intentionally use
non-secret overrides. In a legacy or explicitly accepted source-only flow, use
`SOURCE-METRIC.<exact-metric-name>` in the chart and pass the same value with
`--allow-source-only-item`; record that acceptance in `.observe/dashboards.md`.
Never invent an `OTEL-###` item or use the exception for a new metric that
should have verification proof. The validator fails on missing/extra
charts, group/dashboard/chart hierarchy drift, query/type/layout drift,
unresolved variables, missing service filters, invalid or overlapping grid
cells, an absent `api_token` variable or one without `sensitive = true`, item
IDs absent from direct Working verification proof, chart metric names absent
from the item's `observed_telemetry`, missing stable item provenance, and
report claims that contradict the preview evidence. In canonical JSON mode it
also requires the verification overlay's schema, audit/instrumentation binding
fields, finding/item join, direct-assertion boolean, direct executed item proof
mode, and exact metric type/name mapping. Every canonical `OTEL-###.<item>`
chart requires the complete audit, selection, instrumentation, and verification
chain; the validator runs the shared canonical `validate-flow` check and rejects
missing companions, stale digests, or inventory drift. Use
`--audit`, `--selection`, and `--instrumentation` to name nonstandard locations.
Run the upstream `validate-flow` command first as the workflow gate; the
dashboard validator also fails closed when required binding fields are absent
or malformed. Do not mark deterministic mapping or parity `Pass` unless this
command exits zero.

### Step 6 -- Generate Report

Create `.observe/dashboards.md` as a human-readable companion:

```markdown
# Dashboards Report: <service-name>

**Result:** Pass | Partial | Blocked
**Language:** <lang> | **Framework:** <framework> | **Date:** <YYYY-MM-DD>
**Source audit:** `.observe/otel-audit.json` | legacy `.observe/otel.md`
**Selection:** `.observe/otel-selection.json` | legacy audit scope | not found
**Instrumentation:** `.observe/otel-instrumentation.json` | legacy Markdown | not found
**Verification:** `.observe/otel-verify.json` | legacy Markdown | not found
**Output:** `.observe/terraform/`
**Preview:** `.observe/dashboards.preview.json`

## Summary

| Dashboard | Group | Panels | Chart Types |
|-----------|-------|--------|-------------|
| <service> RED | <service> Overview | N | single_value, time_series |

## Panels

| # | Telemetry Item ID | Panel | Metric | Chart Type | Grid (col,row,w,h) | Product action / rationale |
|---|-------------------|-------|--------|------------|--------------------|----------------------------|
| 1 | OTEL-001.http-duration | P99 Latency | http.server.request.duration | time_series | 0,0,6,3 | verified metric → route latency chart |

## Grid Map

<ASCII or table sketch of the 12-column placement per dashboard>

## Preview And Validation

| Check | Result | What it proves | Evidence / next step |
|-------|--------|----------------|----------------------|
| Verified metric item mapping | Pass/Fail | Every chart comes from an exact working telemetry item | item IDs and verify evidence |
| Terraform ↔ preview parity | Pass/Fail | Same chart labels, types, resolved queries, and grid placement | dashboards.tf + dashboards.preview.json |
| Observer render | Pass/Not run/Blocked | The local UI accepted and rendered the preview | Observer screenshot/API evidence or exact prerequisite |
| Live value sanity | Pass/Not run/Blocked | Queries return plausible values, units, and dimensions | saved query evidence or exact prerequisite |
| Publish/apply | Not run | Review remains local; no live resource was created | run only after human approval |

## Skipped Metrics

| Metric | Reason |
|--------|--------|

## GenAI Instrumentation Prerequisites

<when GenAI Readiness exists and a required signal is missing>

## Next Steps

1. `cp .observe/terraform/terraform.tfvars.example .observe/terraform/terraform.tfvars`
2. Fill in `realm` and `api_token`
3. Preview locally: open the Observer **Dashboards** tab (localhost:3000)
4. Push to Splunk: `$splunk-dashboard-publish` (REST-direct, creates only gaps)
   or `cd .observe/terraform && terraform init && terraform apply`

---
*Generated by splunk-dashboard on <YYYY-MM-DD>*
```

Set `Result: Pass` only when metric-item mapping, HCL/sidecar parity, Observer
rendering, and live value sanity all pass. Use `Partial` when deterministic
mapping/parity passes but Observer rendering or live values were not proven.
Use `Blocked` when no meaningful dashboard or preview validation can run. Never
describe a generated sidecar as a rendered or live-validated dashboard without
direct evidence.

The `Metric` cell for each panel must exactly list the unique `data(...)`
metric names in query order, separated by `, ` when a chart uses more than one;
use `N/A` for a text-only chart. The validator compares this column as part of
report-to-preview parity.

### Step 7 -- Chat Summary

After all files are written, present a concise summary: the dashboards/panels
generated, the files written (`dashboards.tf`, `variables.tf`,
`terraform.tfvars.example`, `.observe/dashboards.md`,
`.observe/dashboards.preview.json`), the exact preview/validation result and
what remains unproven, and the next steps — preview in the Observer Dashboards
tab, then `$splunk-dashboard-publish` or `terraform apply`.

## Red Flags

- `api_token` variable in `variables.tf` is missing `sensitive = true` — this is a hard requirement; the token is a secret and must never be logged or committed as plaintext.
- Audit report has no metrics section and no GenAI readiness — nothing to chart.
- Canonical audit JSON exists but is invalid, or an overlay's `audit_id` or
  `audit_sha256` is stale — stop and repair the JSON chain; never fall back to
  Markdown.
- Canonical JSON and generated Markdown disagree — treat JSON as authoritative
  and regenerate the Markdown; never merge their state.
- A newly implemented metric lacks a matching `working` verification finding
  and exact scenario evidence, and the user did not explicitly accept it as
  source-only — skip it rather than inventing a panel.
- A chart's resolved `programText` still contains a literal `${var.*}` — the
  preview sidecar and any future POST will fail; resolve every variable per
  `../references/terraform-normalization.md` before writing.
- A chart lacks an exact `# telemetry-item:` comment using either a proven
  `OTEL-###.<item>` or explicitly accepted `SOURCE-METRIC.<exact-metric-name>`,
  `telemetryItemId`, or item-specific `productAction` — provenance is not
  deterministic, so validation fails.
- A panel's grid placement overflows the 12-column grid (`column + width > 12`)
  — clamp or re-place it; the Observer preview clamps defensively but the HCL
  should be correct.
- Service name contains characters invalid for a SignalFlow filter value.
