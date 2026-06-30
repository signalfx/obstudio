# SignalFlow `program_text` fragments

Shared reference for the SignalFlow body shared by Splunk detectors and dashboard
charts. Detectors append a `detect()/when()/threshold()` tail; dashboard charts
stop at `.publish(...)`. Both start from the same `data(...).<agg>().publish(...)`
fragment, so it lives here once and is reused by `splunk-configure` (detectors)
and `splunk-dashboard` (charts).

## Base fragment

```
A = data('<metric_name>', filter=filter('service.name', '${var.service_name}')).<agg>().publish(label='<Label>')
```

- `<metric_name>` — the OTel metric name exactly as it appears in telemetry.
- `filter('service.name', '${var.service_name}')` — scope to one service. The
  dimension key is `service.name` (OTel semantic convention); `sf_service` is the
  equivalent legacy SignalFx key and matches the same series.
- `<agg>` — the aggregation method (see table).
- `.publish(label='...')` — names the plot/stream. Required for both charts and
  detectors. A chart's `program_text` ends here.

## Aggregation by signal type

| Signal type | Metric shape | Aggregation method | Example tail |
|---|---|---|---|
| Latency / duration | histogram | `.percentile(pct=99)` | `.percentile(pct=99).publish(label='P99 Latency')` |
| Error rate | counter (error/failure/invalid) | `.sum()` | `.sum().publish(label='Error Rate')` |
| Throughput | counter (no error keyword) | `.sum()` | `.sum().publish(label='Throughput')` |
| Saturation | gauge (connections, queues, buffers, lag) | raw / `.mean()` / `.last()` | `.publish(label='Saturation')` |

For a single-value KPI panel, prefer the latest value: `.mean()` or `.last()`
over a short window. For a time-series panel, publish the stream directly and let
the chart's `plot_type` render it.

## Worked fragments

Latency (P99 of a histogram):
```
A = data('http.server.request.duration', filter=filter('service.name', '${var.service_name}')).percentile(pct=99).publish(label='P99 Latency')
```

Error rate (sum of an error counter):
```
A = data('http.server.request.errors', filter=filter('service.name', '${var.service_name}')).sum().publish(label='Error Rate')
```

Saturation (raw gauge):
```
A = data('db.pool.connections.active', filter=filter('service.name', '${var.service_name}')).publish(label='Active Connections')
```

## Detector tail vs chart tail

- **Detector** (`signalfx_detector`) appends a detection clause after the
  `.publish(...)`: `detect(when(A > threshold(${var.<id>_threshold}))).publish('<Alert Label>')`
  or an `against_recent.detector_mean_std(...)` block for sudden-change detection.
  See `splunk-configure/references/terraform-templates.md`.
- **Chart** (`signalfx_*_chart`) has **no** `detect()/when()/threshold()` tail —
  the panel just visualizes the published stream. The dashboard chart
  `program_text` is exactly the base fragment above.

## Placeholders

| Placeholder | Meaning |
|---|---|
| `<metric_name>` | Original metric name as it appears in telemetry |
| `<metric_id>` | Sanitized metric name (dots/hyphens → underscores, no leading digits) for HCL identifiers |
| `${var.service_name}` | From `variables.tf`; defaults to the service name in the audit report |
