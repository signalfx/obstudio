# Dashboard classification

Apply these rules in order; the first matching signal class wins. Each eligible
metric produces a trend panel and, when it is a primary RED/saturation signal,
an overview KPI.

## Chart vocabulary

| `chartType` | Terraform resource | Purpose |
|---|---|---|
| `single_value` | `signalfx_single_value_chart` | current KPI |
| `time_series` | `signalfx_time_chart` | trend |
| `list` | `signalfx_list_chart` | dimension breakdown |
| `heatmap` | `signalfx_heatmap_chart` | distribution density |
| `text` | `signalfx_text_chart` | markdown note |
| `table` | `signalfx_table_chart` | tabular summary |

## Ordered signal rules

1. **GenAI:** Explicit GenAI metrics go in a separate GenAI dashboard group.
   Duration uses percentile; tokens use time-series or KPI; provider/tool
   errors use sums. A missing readiness signal is a prerequisite, not a panel.
2. **Latency:** A histogram whose name contains `.duration` uses
   `time_series` with `.percentile(pct=99)` plus a p99 `single_value` KPI.
3. **Error:** A counter whose name contains any error keyword uses
   `time_series` with `.sum()` plus an error KPI.
4. **Throughput:** A counter with no error keyword uses `time_series` with
   `.sum()` plus a throughput KPI.
5. **Saturation:** A gauge whose name contains `connections`, `pool`, `buffer`,
   `queue`, `lag`, `utilization`, `capacity`, `active`, `pending`, `heap`,
   `memory`, `goroutines`, or `threads` uses a `single_value` KPI and may add a
   `time_series` trend.

The counter test is name-based because the audit Type is `auto`/`custom`, not a
literal counter type. It matches suffix `.total`, `.count`, or `.processed`, or
any word in the same full error family, singular and plural alike:
`error`, `errors`, `failure`, `failures`, `failed`, `invalid`, `rejected`,
`timeout`, `timeouts`, `exception`, `exceptions`. Thus
`checkout.payment.error`, `rpc.timeout`, `auth.failure`, `worker.exception`,
`rpc.failures`, `auth.rejected`, and `db.query.timeouts` are qualifying error
counters; `checkout.orders.processed` is throughput.

Skip duplicate auto-instrumented/library metrics when a custom equivalent
exists, generic runtime/host metrics without an actionable view, and
informational-only metrics such as uptime/version. Record every skip.

## 12-column placement

- Row 0: overview KPIs left-to-right, usually `width=3,height=2`.
- Later rows: RED trends top-to-bottom, usually two `width=6` charts or one
  `width=12` chart per row; place saturation trends below them.
- Require `column` 0-11, `width` 1-12, `column + width <= 12`, `row >= 0`, and
  `height >= 1`. Never overlap chart rectangles.

Priority is GenAI -> Latency -> Error -> Throughput -> Saturation.
