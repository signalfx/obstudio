---
name: splunk-dashboard
description: >-
  Generate Splunk Observability Cloud dashboard Terraform from an existing
  otel-audit report. Reads .observe/otel.md, groups metrics into dashboard
  panels, and outputs ready-to-apply HCL (signalfx_dashboard_group +
  signalfx_dashboard + per-panel signalfx_*_chart resources) plus a sidecar
  preview model for the local Observer. Use when the user types
  $splunk-dashboard, asks to "generate a dashboard", "build a dashboard from
  the audit", "create charts for my service", or "visualize my metrics".
metadata:
  author: otel-studio
  version: 0.1.0
  category: observability
---

# Dashboard -- Splunk O11y Dashboard Terraform from Audit Report

## Overview

Read an existing `.observe/otel.md` audit report, group detected metrics into
dashboard panels (RED-style layout), and generate Terraform for Splunk
Observability Cloud `signalfx_dashboard_group`, `signalfx_dashboard`, and
per-panel `signalfx_*_chart` resources with inline SignalFlow `program_text`.
Also emit a sidecar `.observe/dashboards.preview.json` that the local Observer's
**Dashboards** tab renders against live OTLP data as an approximate preview.

This is the visualization analogue of `$splunk-configure` (which generates
detectors). It shares its parsing rules and SignalFlow fragments; it differs in
that a dashboard is a three-level object — group → dashboard → charts[] — where
each chart is a separate resource placed on a 12-column grid.

## When to Use

- After running `$otel-audit` to generate `.observe/otel.md`
- When the user wants a dashboard / charts / a visual overview for their service
- When the user wants to preview a dashboard layout locally before pushing it to
  Splunk (the Observer Dashboards tab reads the preview sidecar this skill writes)

**When NOT to use:** If no audit report exists yet, instruct the user to run
`$otel-audit` first. For alerting/detection Terraform, use `$splunk-configure`.
To push the generated dashboards to a live org, use `$splunk-dashboard-sync`.

## Process

### Step 1 -- Locate Audit Report

Look for `.observe/otel.md` in the repository root.

- If the file exists, proceed to Step 2.
- If the file is missing, stop and respond:

> No audit report found at `.observe/otel.md`. Please run `$otel-audit` first
> to generate the observability coverage report.

### Step 2 -- Parse Service Metadata, Metrics, and GenAI Coverage

Extract from `.observe/otel.md`, using the same parsing rules `$splunk-configure`
documents:

1. **Service metadata** from the report header: service name (from the
   `# Observability Report: {service-name}` heading), language, framework.
2. **Metrics table** from the `### Metrics` section: each row gives metric name,
   source, and type (auto/custom). Record all metrics for grouping in Step 3.
3. **GenAI Readiness** from the `## GenAI Readiness` section when present. GenAI
   metrics that exist become their own dashboard group; missing GenAI areas
   become preview/instrumentation prerequisites, not invented panels.

If the Metrics section says "No metrics detected." and there are no GenAI
readiness sections, stop and respond:

> The audit report contains no metrics. Dashboards require metric data.
> Run `$otel-instrument` to add instrumentation, then re-run `$otel-audit`.

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
- Each chart is placed via the dashboard's `chart { chart_id = ...; column; row;
  width; height }` block on the 12-wide grid: `column` 0-11, `width` 1-12,
  `row` ≥0, `height` ≥1.

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
              "programText": "data('http.server.request.duration', filter=filter('service.name','<service>')).percentile(pct=99).publish(label='P99 Latency')",
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
- `programText` carries the resolved SignalFlow (no `${var.*}`, dedented). For a
  `text` panel, set `programText: null` and put the markdown in `text`.
- `layout` mirrors the HCL `chart {}` block exactly: `column` 0-11, `row` ≥0,
  `width` 1-12, `height` ≥1. The grid is 12 columns wide.

Keep the preview sidecar in lockstep with `dashboards.tf`: every chart in the HCL
appears exactly once in the sidecar with the same label, type, resolved query,
and grid placement.

### Step 6 -- Generate Report

Create `.observe/dashboards.md` as a human-readable companion:

```markdown
# Dashboards Report: <service-name>

**Language:** <lang> | **Framework:** <framework> | **Date:** <YYYY-MM-DD>
**Source:** `.observe/otel.md` | **Output:** `.observe/terraform/`

## Summary

| Dashboard | Group | Panels | Chart Types |
|-----------|-------|--------|-------------|
| <service> RED | <service> Overview | N | single_value, time_series |

## Panels

| # | Panel | Metric | Chart Type | Grid (col,row,w,h) | Rationale |
|---|-------|--------|------------|--------------------|-----------|
| 1 | P99 Latency | http.server.request.duration | time_series | 0,0,6,3 | latency histogram → percentile time series |

## Grid Map

<ASCII or table sketch of the 12-column placement per dashboard>

## Skipped Metrics

| Metric | Reason |
|--------|--------|

## GenAI Instrumentation Prerequisites

<when GenAI Readiness exists and a required signal is missing>

## Next Steps

1. `cp .observe/terraform/terraform.tfvars.example .observe/terraform/terraform.tfvars`
2. Fill in `realm` and `api_token`
3. Preview locally: open the Observer **Dashboards** tab (localhost:3000)
4. Push to Splunk: `$splunk-dashboard-sync` (REST-direct, creates only gaps)
   or `cd .observe/terraform && terraform init && terraform apply`

---
*Generated by splunk-dashboard on <YYYY-MM-DD>*
```

### Step 7 -- Chat Summary

After all files are written, present a concise summary: the dashboards/panels
generated, the files written (`dashboards.tf`, `variables.tf`,
`terraform.tfvars.example`, `.observe/dashboards.md`,
`.observe/dashboards.preview.json`), and the next steps — preview in the Observer
Dashboards tab, then `$splunk-dashboard-sync` or `terraform apply`.

## Red Flags

- Audit report has no metrics section and no GenAI readiness — nothing to chart.
- A chart's resolved `programText` still contains a literal `${var.*}` — the
  preview sidecar and any future POST will fail; resolve every variable per
  `../references/terraform-normalization.md` before writing.
- A panel's grid placement overflows the 12-column grid (`column + width > 12`)
  — clamp or re-place it; the Observer preview clamps defensively but the HCL
  should be correct.
- Service name contains characters invalid for a SignalFlow filter value.
