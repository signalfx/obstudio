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
| Saturation | gauge (connections, queues, buffers, lag) | raw / `.mean()` | `.mean().publish(label='Saturation')` |

For a single-value KPI panel, prefer `.mean()` as the safe no-argument
aggregation. Do **not** use bare `.last()` — SignalFlow's `.last()` requires an
explicit window duration (e.g. `.last('1m')`), and a windowless `.last()` is
rejected with an HTTP 400 at chart-create time (see
`splunk-dashboard/references/dashboard-templates.md` and
`splunk-dashboard-publish/SKILL.md`). For a time-series panel, publish the stream
directly and let the chart's `plot_type` render it.

## Worked fragments

Latency (P99 of a histogram):
```
A = data('http.server.request.duration', filter=filter('service.name', '${var.service_name}')).percentile(pct=99).publish(label='P99 Latency')
```

Error rate (sum of an error counter):
```
A = data('http.server.request.errors', filter=filter('service.name', '${var.service_name}')).sum().publish(label='Error Rate')
```

Saturation (gauge, mean):
```
A = data('db.pool.connections.active', filter=filter('service.name', '${var.service_name}')).mean().publish(label='Active Connections')
```

## Filtering a merged route-group metric on more than `service.name`

When `splunk-configure`'s Route-Level De-duplication merges an error or
throughput counter into a same-route duration histogram (see
`splunk-configure/references/detector-classification.md`), express the merged
Error and Throughput detectors by adding the route/operation dimension
(`http.route`, `rpc.method`, `db.operation.name`, or equivalent) as a second
`filter(...)` rather than reading a second metric. Error and Throughput are
distinct patterns — do not filter Throughput to the error attribute, or it
reports only failed-request volume for the route instead of total volume:

Error (route-scoped, filtered to the histogram's own outcome attribute):
```
A = data('http.server.request.duration', filter=filter('service.name', '${var.service_name}') and filter('http.route', '/payment') and filter('error.type', '*'), rollup='count').sum(by=['error.type']).publish(label='Error Rate')
```

Throughput (route-scoped, no outcome/error filter — counts every request for the route):
```
A = data('http.server.request.duration', filter=filter('service.name', '${var.service_name}') and filter('http.route', '/payment'), rollup='count').sum().publish(label='Throughput')
```

- Combine filters with `and filter(...)`; each additional filter narrows the
  same series, it does not add a second metric.
- Always include the route/operation filter so a counter for one route is not
  silently replaced by a service-wide stream.
- For Error, filter the histogram's proven outcome attribute. An `error.type`
  existence wildcard is valid; for `http.response.status_code`,
  `rpc.response.status_code`, or `db.response.status_code`, select only the
  failing value(s) evidenced by the audit and never use `*`. For Throughput,
  omit the outcome filter entirely so the count includes every outcome.
- `.count()` (as an aggregation method) counts the number of *time series*
  reporting data, not the observations inside them -- for a low-cardinality
  route metric that is close to constant, not a request-volume proxy. To read
  request/failure volume off a duration histogram, select the histogram's
  count rollup with `data(..., rollup='count')` (the total number of data
  points recorded in the interval) and aggregate the remaining series with
  `.sum(by=['error.type'])` for the grouped error case or `.sum()` for
  throughput. `.sum()` on a histogram's default (non-count) rollup sums the
  observed *values* (total duration), which is wrong here; `.sum()` is only
  correct once `rollup='count'` has already converted each series to an
  event count. `.percentile()` remains the correct aggregation for the
  Latency detector on the same metric.

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
