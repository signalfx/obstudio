# Terraform Templates for Dashboards

HCL templates for `signalfx_dashboard_group`, `signalfx_dashboard`, and the
per-panel `signalfx_*_chart` resources. The chart `program_text` reuses the
shared `../../references/signalflow-patterns.md` fragment (the
`data(...).<agg>().publish(...)` body) with **no** `detect()/when()/threshold()`
tail — charts visualize, they do not alert.

## Provider + group + dashboard skeleton

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

resource "signalfx_dashboard_group" "service_overview" {
  name        = "${var.service_name} Overview"
  description = "RED + saturation dashboards for ${var.service_name}"
}

resource "signalfx_dashboard" "red" {
  name            = "${var.service_name} RED"
  description     = "Rate, errors, duration"
  dashboard_group = signalfx_dashboard_group.service_overview.id

  chart {
    chart_id = signalfx_single_value_chart.kpi_p99_latency.id
    column   = 0
    row      = 0
    width    = 3
    height   = 2
  }

  chart {
    chart_id = signalfx_time_chart.p99_latency.id
    column   = 0
    row      = 2
    width    = 6
    height   = 3
  }
}
```

`dashboard_group` is the HCL attribute; the REST create body uses `groupId`. The
`chart {}` block grid fields are `column` (0-11), `row` (≥0), `width` (1-12),
`height` (≥1).

## Time-series chart (`signalfx_time_chart`)

```hcl
resource "signalfx_time_chart" "p99_latency" {
  # telemetry-item: OTEL-001.http-duration
  name         = "P99 Latency - <metric_name>"
  plot_type    = "LineChart"   # LineChart | AreaChart | ColumnChart | Histogram

  program_text = <<-EOF
    A = data('<metric_name>', filter=filter('service.name', '${var.service_name}')).percentile(pct=99).publish(label='P99 Latency')
  EOF

  axis_left {
    label = "seconds"
  }
}
```

## Single-value chart (`signalfx_single_value_chart`)

```hcl
resource "signalfx_single_value_chart" "kpi_p99_latency" {
  # telemetry-item: OTEL-001.http-duration
  name         = "P99 Latency"
  color_by     = "Scale"

  program_text = <<-EOF
    A = data('<metric_name>', filter=filter('service.name', '${var.service_name}')).percentile(pct=99).publish(label='P99 Latency')
  EOF

  is_timestamp_hidden = true
}
```

Use `single_value` for the overview KPI row (latest value of each RED signal and
key saturation gauges).

## Error-rate and throughput panels

Same `signalfx_time_chart` shape; the `program_text` uses `.sum()` from the
shared fragment:

```hcl
program_text = <<-EOF
  A = data('<error_or_request_counter>', filter=filter('service.name', '${var.service_name}')).sum().publish(label='Error Rate')
EOF
```

## Saturation panel

```hcl
resource "signalfx_single_value_chart" "saturation_connections" {
  # telemetry-item: OTEL-005.db-connections
  name         = "Active Connections"
  program_text = <<-EOF
    A = data('db.pool.connections.active', filter=filter('service.name', '${var.service_name}')).mean().publish(label='Active Connections')
  EOF
}
```

> **SignalFlow aggregation rule for `SingleValue` charts:** always end with an explicit
> aggregation (`.mean()` for gauges, `.sum()` for counters) before `.publish()`.
> A bare `.publish()` with no preceding aggregation will show no value in the panel.
> **Do NOT use `.last()` without a window argument** — SignalFlow's `.last()` requires
> an explicit window duration (e.g. `.last('1m')`); omitting it causes a 400 API error.
> Use `.mean()` as the safe default for gauge KPI panels.

## Text panel (`signalfx_text_chart`)

```hcl
resource "signalfx_text_chart" "section_red" {
  # telemetry-item: OTEL-001.http-duration
  name     = "RED Signals"
  markdown = "## RED Signals\nRate, errors, and duration for ${var.service_name}."
}
```

A text panel has `markdown` and no `program_text`; in the preview sidecar it maps
to `chartType: "text"` with `programText: null` and the markdown in `text`.

Every chart resource carries stable provenance as `# telemetry-item:`. Use the
verified `OTEL-###.<item>` ID for implemented telemetry. For a pre-existing
metric explicitly accepted without item proof, use
`SOURCE-METRIC.<exact-metric-name>` and record the same explicit exception in
the report and validator command; never manufacture an `OTEL-###` ID. The
preview repeats that exact value in `telemetryItemId` and records the
item-specific chart/dashboard follow-up in `productAction`; these fields are
ignored by Terraform and the Observer renderer but are validated before the
report can pass.

## Other chart types

Also available from the provider when a panel needs them:
`signalfx_list_chart` (per-dimension top-N), `signalfx_heatmap_chart`
(distribution density), `signalfx_table_chart` (tabular multi-metric). Use the
same `name` + `program_text` shape; the preview `chartType` is `list`, `heatmap`,
or `table` respectively.

## Chart resource ↔ REST mapping (used by `$splunk-dashboard-publish`)

| HCL resource | preview `chartType` | REST `options.type` |
|---|---|---|
| `signalfx_time_chart` | `time_series` | `TimeSeriesChart` |
| `signalfx_single_value_chart` | `single_value` | `SingleValue` |
| `signalfx_list_chart` | `list` | `List` |
| `signalfx_heatmap_chart` | `heatmap` | `Heatmap` |
| `signalfx_text_chart` | `text` | `Text` |
| `signalfx_table_chart` | `table` | `TableChart` |

> **`SingleValue` REST constraint:** the `POST /v2/chart` body for a `SingleValue`
> chart must NOT include `defaultPlotType` in `options` — that field is only valid for
> `TimeSeriesChart` and the API returns HTTP 400 if it appears on any other type.
> Correct `options` body for `SingleValue`:
> ```json
> { "type": "SingleValue", "colorBy": "Dimension" }
> ```
> For `TimeSeriesChart` only, `defaultPlotType` is valid:
> ```json
> { "type": "TimeSeriesChart", "defaultPlotType": "LineChart", "colorBy": "Dimension" }
> ```

## terraform.tfvars.example

```hcl
realm        = ""   # e.g. us1, eu0, lab0
api_token    = ""   # Splunk O11y API token (org-level, dashboard write)
service_name = "<service-name from report>"
```

`api_token` is `sensitive = true` in `variables.tf` — never commit a real value.

## Exact preview sidecar shape

Use the object-valued `layout` below. Do not encode layout as an array and do
not use a chart title as `label`; `label` is the exact Terraform resource label.
Repeat the HCL query, human title, telemetry item ID, and product action
literally:

```json
{
  "schemaVersion": 1,
  "groups": [
    {
      "label": "service_overview",
      "name": "Service Overview",
      "dashboards": [
        {
          "label": "red",
          "name": "RED",
          "charts": [
            {
              "label": "p99_latency",
              "title": "P99 Latency",
              "chartType": "time_series",
              "telemetryItemId": "SOURCE-METRIC.http.server.request.duration",
              "productAction": "Investigate sustained route latency.",
              "programText": "A = data('http.server.request.duration', filter=filter('service.name', 'checkout')).percentile(pct=99).publish(label='p99')",
              "text": null,
              "layout": {"column": 0, "row": 0, "width": 6, "height": 3}
            }
          ]
        }
      ]
    }
  ]
}
```

Use resolved service values in preview `programText`; keep `${var.service_name}`
only in Terraform. Preserve unused groups and empty dashboards as empty arrays.

## Exact dashboard report shape

The validator owns this literal projection. Write one result line and name the
sidecar exactly:

```markdown
# Dashboards Report: <service-name>

**Result:** Partial
**Preview:** `.observe/dashboards.preview.json`

## Panels

| # | Telemetry Item ID | Panel | Metric | Chart Type | Grid (col,row,w,h) | Product action / rationale |
|---|---|---|---|---|---|---|
| 1 | SOURCE-METRIC.http.server.request.duration | P99 Latency | http.server.request.duration | time_series | 0,0,6,3 | Investigate sustained route latency. |

## Preview And Validation

| Check | Result | What it proves | Evidence / next step |
|---|---|---|---|
| Verified metric item mapping | Pass | Every chart maps to an accepted or verified exact metric item. | Validator accepted SOURCE-METRIC.http.server.request.duration. |
| Terraform ↔ preview parity | Pass | HCL and preview contain the same charts, queries, and grid. | Validator compared dashboards.tf with dashboards.preview.json. |
| Observer render | Not run | Whether Observer renders the sidecar. | Open .observe/dashboards.preview.json in Observer. |
| Live value sanity | Not run | Whether recent series return expected values. | Query a recent window after local render. |
| Publish/apply | Not run | Whether reviewed resources exist in Splunk Observability Cloud. | Run $splunk-dashboard-publish or reviewed terraform apply. |
```

For each panel row, copy preview values literally: `Telemetry Item ID` from
`telemetryItemId`, `Panel` from `title`, `Chart Type` from `chartType`, grid as
`column,row,width,height`, and `Product action / rationale` from
`productAction`. `Metric` is the unique `data(...)` metric inventory in query
order, joined by `, `, or `N/A` for text charts. Mapping and parity become
`Pass` only after the validator succeeds. Keep render/live checks `Not run`
without direct evidence and always keep publish/apply `Not run` locally.

## Placeholder reference

| Placeholder | Meaning |
|---|---|
| `<metric_name>` | Original metric name as it appears in telemetry |
| `<metric_id>` | Sanitized metric name (dots/hyphens → underscores, no leading digits) for the HCL resource label |
| `var.service_name` | From `variables.tf`; defaults to the service name in the audit report |
