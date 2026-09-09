# Dashboard Publish Chart Wire Contract

Read this reference whenever parsing a chart type or planning/building a
`POST /v2/chart` body. It is self-contained so publish runs do not need to load
the dashboard-generation templates.

## Type Mapping

| HCL resource | Local type | REST `options.type` |
|---|---|---|
| `signalfx_time_chart` | `time_series` | `TimeSeriesChart` |
| `signalfx_single_value_chart` | `single_value` | `SingleValue` |
| `signalfx_list_chart` | `list` | `List` |
| `signalfx_heatmap_chart` | `heatmap` | `Heatmap` |
| `signalfx_text_chart` | `text` | `Text` |
| `signalfx_table_chart` | `table` | `TableChart` |

The generator's broader reference is
`../../splunk-dashboard/references/dashboard-templates.md`, but do not load it
for publish: this local contract owns the publish-time wire mapping and body.

## Chart Body

```python
CHART_TYPE_MAP = {
    "time_series": "TimeSeriesChart",
    "single_value": "SingleValue",
    "list": "List",
    "heatmap": "Heatmap",
    "text": "Text",
    "table": "TableChart",
}

rest_type = CHART_TYPE_MAP.get(chart_type, chart_type)
options = {"type": rest_type, "colorBy": "Dimension"}
if rest_type == "TimeSeriesChart":
    options["defaultPlotType"] = "LineChart"

body = {
    "name": chart_name,
    "programText": normalized_program_text,
    "options": options,
    "packageSpecifications": "signalfx",
}
```

Only `TimeSeriesChart` accepts `defaultPlotType`. `SingleValue`, `List`,
`Heatmap`, `Text`, and `TableChart` reject it with HTTP 400.

A `Text` chart omits `programText`; put its content in
`options: {"type": "Text", "markdown": "..."}`. Never send unresolved
`${var.*}`, heredoc indentation, or no-argument `.last()`. Use an explicit
window for `.last()` or the appropriate `.mean()` gauge aggregation.

HCL uses `program_text`, `chart_id`, and `dashboard_group`; REST bodies use
`programText`, `chartId`, and `groupId`.
