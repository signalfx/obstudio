# Configure Dashboard Output Contract

Read this file completely only when accepted metric evidence supports dashboard
Terraform and the user requested dashboards as part of configure.

## Contents

- Evidence boundary
- SignalFlow and chart safety
- Provenance and preview parity
- Validation states

## Evidence boundary

Generate a panel only for an exact metric that is accepted under the active
canonical or legacy input contract. Preserve its proven unit and dimensions.
If a useful filter or group-by dimension is absent, document the missing
dimension rather than inventing it.

Provider-derived, precomputed, or transformed metrics require explicit live
metadata provenance and acceptance. Never silently substitute them for the
audited OTel name. Treat stale/unowned evidence as a prerequisite, not
source-backed coverage.

Keep the Splunk Observability Cloud API `realm` variable separate from
telemetry. Do not use `var.realm` as a SignalFlow filter. Use a proven telemetry
dimension such as `deployment.environment.name`, `cloud.region`, or an existing
legacy `sfx_realm` only when source evidence proves it. Preserve supported
dashboard variables and set `apply_if_exist = true` only when the underlying
dimension is proven; otherwise omit the variable or use `apply_if_exist =
false` as specified by the Terraform template.

## SignalFlow and chart safety

Before writing chart `program_text`, establish the exact metric type, unit,
monotonicity, and aggregation semantics.

- Use `timeseries` for trends, `single_value` for current KPI summaries,
  `heatmap` for raw histograms, and `list` or `table` only for ranked bounded
  series.
- Do not combine mixed-unit signals. Use separate panels for latency, counts,
  percentages, bytes, and boolean readiness.
- For pre-aggregated percentile metrics or quantile series, do not average
  percentiles. Preserve the documented percentile/quantile semantics.
- For cumulative counters and cumulative timers, use a rate/delta projection;
  use `rollup='rate'` where required by the template. Never chart cumulative
  growth as current throughput or latency.
- Generate a CPU saturation detector or chart only from source-backed CPU
  utilization. Do not use thread count, heap, GC, or cumulative CPU time as CPU
  saturation. A cumulative CPU time rate may be a diagnostic rate, while
  normalized CPU utilization is a saturation signal.
- Keep readiness, dependency health, connection-pool utilization, traffic
  target health, and resource saturation on separate panels when their units or
  fault domains differ.
- For every chart, define a value sanity check over a known-traffic window:
  confirm values exist, units are plausible, and filter/group dimensions are
  present. If that check was not executed, mark it unverified in
  `.observe/dashboards.md`.

Never claim a stale browser dashboard is current. After a local update, reload
without a stale `configId` parameter or reset saved overrides before recording
a UI witness.

## Provenance and preview parity

Generate these artifacts together:

- `.observe/terraform/dashboards.tf`
- `.observe/dashboards.preview.json`
- `.observe/dashboards.md`

The preview uses schema version 1 and the same resolved group -> dashboard ->
charts model as `$splunk-dashboard`, with supported chart type, fully resolved
`programText`, and 12-column layout.

Maintain exact one-to-one mapping across accepted signal, Terraform chart,
preview chart, and the canonical `## Panels` report row:

- Put `# telemetry-item: <id>` in every chart resource.
- Repeat that exact value as preview `telemetryItemId`.
- Record the item-specific next product step as preview `productAction`.
- Use `OTEL-###.<item>` only for a real bound instrumentation telemetry item.
- Use `SOURCE-METRIC.<exact-metric-name>` only for a user-accepted pre-existing
  metric; never manufacture an OTel finding/item ID.
- Preserve chart label, type, resolved query, row/column, width/height, metric,
  unit, and dimensions exactly across all three projections.

## Validation states

Keep these states separate:

1. Terraform/preview contract generated.
2. `validate_dashboard_output.py` proves exact HCL/query/type/layout/item parity.
3. Observer successfully renders the preview.
4. A known-traffic value sanity check proves live values, units, and dimensions.
5. A live publish/apply action succeeds.

A sidecar on disk proves only state 1. Never imply the UI rendered it, values
were plausible, or a live dashboard exists without direct evidence.

The configure validator delegates state 2 automatically when dashboards exist
and requires the dashboard report result to inherit the configure result. It
forwards canonical artifact paths and exact source-only item approvals. A
delegated failure is a configure failure.

Run the dashboard validator directly only to isolate a delegated error:

```bash
python3 <splunk-dashboard-skill-dir>/scripts/validate_dashboard_output.py \
  --terraform .observe/terraform/dashboards.tf \
  --preview .observe/dashboards.preview.json \
  --report .observe/dashboards.md \
  --verification .observe/otel-verify.json
```

Do not pass or discover `terraform.tfvars` implicitly. Use a reviewed non-secret
file only through the explicit dashboard tfvars option.
