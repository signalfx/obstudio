# Dashboard Classification Rules

Rules for grouping metrics from an otel-audit report into dashboard panels. The
dashboard analogue of `splunk-configure/references/detector-classification.md` —
same metric taxonomy, but each metric maps to a **panel** (chart type + grid
placement) instead of a detector. Apply in order; the first match wins.

## Chart-type vocabulary

| chartType | Terraform resource | Use for |
|---|---|---|
| `single_value` | `signalfx_single_value_chart` | a current-value KPI (latest p99, error rate, saturation gauge) |
| `time_series` | `signalfx_time_chart` | a trend over time (latency, error rate, throughput, saturation trend) |
| `list` | `signalfx_list_chart` | per-dimension breakdown (top-N by endpoint, by status) |
| `heatmap` | `signalfx_heatmap_chart` | distribution density (latency heatmap) |
| `text` | `signalfx_text_chart` | a markdown note / section header |
| `table` | `signalfx_table_chart` | tabular multi-metric summary |

## Panel grouping rules

### Overview KPI row (top of the primary dashboard)

Emit a row of `single_value` panels at `row = 0`, one per RED signal that exists,
left to right:

- p99 latency (from a duration histogram) → `single_value`
- error rate (from an error counter) → `single_value`
- throughput (from a non-error counter) → `single_value`
- one or two key saturation gauges → `single_value`

Each KPI panel is narrow (e.g. `width = 3`, `height = 2`) so several fit across
the 12-column grid in one row.

### Latency

A metric is a **latency time-series panel** candidate when its name contains
`.duration` and its type is histogram (`http.server.request.duration`,
`rpc.server.duration`, `db.client.operation.duration`). Chart type
`time_series`; aggregation `.percentile(pct=99)`.

### Error

A metric is an **error time-series panel** candidate when its name ends in
`.total`/`.count` AND contains an error keyword (`error`, `errors`, `failure`,
`failures`, `failed`, `invalid`, `rejected`, `timeout`, `exception`). Chart type
`time_series`; aggregation `.sum()`.

### Throughput

A metric is a **throughput time-series panel** candidate when its name ends in
`.total`/`.count` AND contains no error keyword (`http.server.requests.total`,
`orders.processed.count`). Chart type `time_series`; aggregation `.sum()`.

### Saturation

A metric is a **saturation panel** candidate when its type is gauge and its name
contains one of `connections`, `pool`, `buffer`, `queue`, `lag`, `utilization`,
`capacity`, `active`, `pending`, `heap`, `memory`, `goroutines`, `threads`. Emit
a `single_value` panel (current saturation) and optionally a `time_series` trend.

### GenAI

When the audit has a `## GenAI Readiness` section and GenAI metrics exist, group
them into their **own** `signalfx_dashboard` inside a separate GenAI dashboard
group. Mirror the GenAI categories from
`splunk-configure/references/detector-classification.md` (genai-latency,
genai-token-pressure, genai-provider, genai-tool, etc.) but render each as a
panel: latency/duration → `time_series` percentile; token usage → `time_series`
or `single_value`; provider/tool error counts → `time_series`. A missing GenAI
signal is a preview/instrumentation prerequisite — never an invented panel.

## Exclusion rules

Skip a metric (no panel) when it matches the detector skill's exclusion rules:
auto-instrumented library duplicates when a custom equivalent exists, generic
runtime/host metrics without an actionable view, and informational-only metrics
(`process.uptime`, version gauges). Record each skipped metric with a reason.

## Grid placement (12-column)

The dashboard grid is 12 columns wide. Each panel's `chart {}` block sets:

- `column` — left edge, 0-11.
- `width` — span, 1-12; `column + width` must be ≤ 12 (no horizontal overflow).
- `row` — top edge, ≥0.
- `height` — span, ≥1.

Layout convention:

1. **Row 0** — the overview KPI `single_value` row (narrow panels, e.g.
   `width = 3` each, four across).
2. **Following rows** — the RED `time_series` panels, typically `width = 6`
   (two per row) or `width = 12` (full width), increasing `row` as you go down.
3. Saturation trends below RED.

Place panels top-to-bottom, left-to-right; never overlap two panels on the same
`column`/`row` span; never let `column + width` exceed 12.

## Decision flowchart

```
metric has GenAI context (gen_ai.* or GenAI Readiness + explicit keyword)?
  -> YES -> GenAI panel in the GenAI dashboard group
  -> NO

metric name contains ".duration" (histogram)?
  -> YES -> time_series percentile panel (+ single_value KPI in overview row)
  -> NO

metric name ends with ".total"/".count"?
  -> YES -> error keyword?
    -> YES -> error-rate time_series panel (+ single_value KPI)
    -> NO  -> throughput time_series panel (+ single_value KPI)
  -> NO

metric type is gauge AND name matches saturation keywords?
  -> YES -> saturation single_value panel (+ optional time_series trend)
  -> NO  -> skip (no panel)
```

## Priority order

When a metric could match multiple categories, use the same priority as the
detector skill: GenAI → Latency → Error → Throughput → Saturation.
