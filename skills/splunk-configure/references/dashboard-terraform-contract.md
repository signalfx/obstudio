# Configure Dashboard Terraform Contract

Read only when dashboard generation was requested and accepted metric evidence
supports it. `dashboard-output-contract.md` owns the preview and report shapes.

Create a `signalfx_dashboard_group` with a non-empty `description`, a
`signalfx_dashboard` filtered by `service.name`, and chart resources attached to
that dashboard. Use time charts for rates/latency/freshness/backpressure and
single-value or list charts only where the unit and dimensions fit.

Optional dashboard variables must use the exact proven dimension and
`apply_if_exist = true`; never use optional wildcard variables with
`apply_if_exist = false`. This applies to environment, region, namespace,
platform, version/image/config/rollout, provider/model, dependency, and custom
realm dimensions. Keep the Splunk Observability Cloud API `realm` variable
separate. Do not equate the provider/API `realm` variable with telemetry such
as `sfx_realm`, `deployment.region`, or `cloud.region`, and do not use
`var.realm` as a SignalFlow filter.
Newly instrumented services should emit `deployment.environment.name`; use a
legacy environment key only when the metric metadata proves it.

```hcl
resource "signalfx_dashboard_group" "service" {
  name        = "${var.service_name} Observability"
  description = "Service health dashboards for ${var.service_name}"
}

variable {
  property       = "deployment.environment.name"
  alias          = "Environment"
  values         = ["*"]
  apply_if_exist = true
}
```

Before writing chart `program_text`, verify exact metric name, filter, group-by,
unit, temporality, and source-backed emitter. Provider-derived/precomputed names
need approved live metadata provenance plus a source owner. Build output,
generated artifacts, jars/classes, coverage, or stale runtime files are
stale/unowned evidence, not source-backed coverage.

Do not combine mixed-unit signals; use separate panels for booleans,
percentages/ratios, bytes, counts/rates, cumulative counters, cumulative timers,
and durations. For pre-aggregated percentile metrics (`.p99`, `.p95`,
quantile), do not average or use `.percentile()`; use max/worst-case treatment
with documented units.
Raw histograms may use `.percentile(pct=99)`. Cumulative counters/timers need
`rollup='rate'` or another proven delta/rate transform. Cumulative CPU time is a
diagnostic rate; CPU saturation needs source-backed normalized utilization.
Do not use thread count as a CPU proxy.

When a query path is available, use a known-traffic window for a value sanity
check. No series, absent dimensions, or implausible units remain unverified in
`.observe/dashboards.md`. After Terraform updates, reload the canonical
dashboard without a stale `configId` parameter before judging live data.

For `alert-coverage-audit`, prerequisites, impact, or blast-radius output, load
`readiness-report-contract.md`; do not claim live coverage from desired-state
evidence.
