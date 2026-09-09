# Chart Wire Contract

HCL: `signalfx_time_chart`, `signalfx_single_value_chart`, and list, heatmap,
text, or table `signalfx_*_chart` resources. Preserve options; default only
when absent.

```python
CHART_TYPE_MAP = {
    "time": "TimeSeriesChart",
    "time_series": "TimeSeriesChart",
    "single_value": "SingleValue",
    "list": "List",
    "heatmap": "Heatmap",
    "text": "Text",
    "table": "TableChart",
}

PLOT_TYPES = {"LineChart", "AreaChart", "ColumnChart", "Histogram"}
COLORS = {"Dimension", "Scale", "Metric"}
COLOR_BY_TYPES = {
    "TimeSeriesChart": ("Dimension", COLORS),
    "SingleValue": ("Metric", COLORS),
    "List": ("Dimension", COLORS),
}


def chart_options(chart_type, *, plot_type=None, color_by=None):
    local_type = chart_type.removeprefix("signalfx_").removesuffix("_chart")
    rest_type = CHART_TYPE_MAP.get(local_type, chart_type)
    if rest_type not in CHART_TYPE_MAP.values():
        raise ValueError("unsupported chart type")
    color_config = COLOR_BY_TYPES.get(rest_type)
    if color_by is not None:
        if color_config is None or color_by not in color_config[1]:
            raise ValueError("unsupported color_by")
    elif color_config is not None:
        color_by = color_config[0]

    if rest_type == "TimeSeriesChart":
        plot_type = "LineChart" if plot_type is None else plot_type
        if plot_type not in PLOT_TYPES:
            raise ValueError("unsupported plot_type")
    elif plot_type is not None:
        raise ValueError("plot_type is unsupported")

    options = {"type": rest_type}
    if color_by is not None:
        options["colorBy"] = color_by
    if plot_type is not None:
        options["defaultPlotType"] = plot_type
    return options
```

Body: `{name, programText, options, packageSpecifications: "signalfx"}`. Plans
show exact per-chart `options` and state unsupported values stop, never default.
`defaultPlotType` is `TimeSeriesChart`-only.

`Text` puts `markdown` in options, not `programText`. Reject `${var.*}`, indented
heredocs, or bare `.last()`. Dashboard groups use `groupId`.
