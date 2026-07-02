# Coverage Model — splunk-dashboard-publish

How `splunk-dashboard-publish` decides whether a local dashboard Terraform spec is
already covered by live Splunk Observability Cloud objects. Builds on the shared
`../../references/coverage-decision-tree.md` (the COVERED / GAP / UNCERTAIN
vocabulary and the record-every-criterion-that-fired rule). A dashboard is a
three-level object, so it is classified at **three levels**, each with its own
verdict and its own concrete reason.

## Why structural matching, not name-only

Matching dashboards by name alone is unreliable (the live search returns many
org-wide results; names vary across teams). Match on **structural identity**: the
group name, the dashboard name + its panel-metric set, and per-chart
`{ metric, filters, chartType }` read from the live `programText`/`charts[]`.

## Level 1 — Dashboard group

A local `signalfx_dashboard_group` is:

- **COVERED** when a live group has the same `name`. Reason:
  `matched live dashboard group "<name>" (id G-123): name match`.
- **GAP** when no live group has that name. Reason:
  `no live dashboard group named "<name>"; will create before its dashboards`.

Groups are created first (a dashboard's `groupId` must reference an existing
group).

## Level 2 — Dashboard

A local `signalfx_dashboard` is:

- **COVERED** when a live dashboard matches by `name` (within the matched group),
  AND its panel-metric set matches the local panel-metric set. Reason:
  `matched live dashboard "<name>" (id D-123): name match + N/N panel metrics present`.
- **GAP** when no live dashboard with that name exists in the group. Reason:
  `no live dashboard named "<name>" in group "<group>"; will create`.
- **COVERED (with chart-level GAPs)** when a same-named live dashboard exists
  and every live panel title/label matches a local panel, but the live dashboard
  has **fewer panels** than the local spec (i.e. the live panel set is a strict
  subset of the local panel set). Classify the dashboard as COVERED and emit a
  chart-level GAP entry for each panel present locally but absent in the live
  dashboard. This enables the chart-level GAP repair path: create only the
  missing charts and append them to the existing dashboard via
  `PUT /v2/dashboard/{id}` — do **not** recreate the whole dashboard. Reason
  example:
  `live dashboard "<name>" (D-123): name match; live panels are a strict subset — local has p99_latency + error_rate + throughput; live has p99_latency + error_rate only; throughput chart is a GAP`.
- **UNCERTAIN** when a same-named live dashboard exists and the live dashboard
  contains panels that do not correspond to any local panel (genuinely different
  content, not just missing panels). Reason names the divergence:
  `live dashboard "<name>" exists but panels differ: local has p99_latency + error_rate; live has p50_latency only — needs human review`.
  Do not auto-create and do not auto-cover; surface for manual review.

## Level 3 — Chart / panel

Within a matched (COVERED) dashboard, each local chart is classified against the
live dashboard's `charts[]` (fetch each live chart's `programText` and type via
`GET /v2/chart/{id}`):

A local chart is **COVERED** only when ALL hold for a single live chart:

1. **Same metric name** — the OTel metric in the local chart's `program_text`
   (the first `data('metric.name', ...)` argument) also appears in the live
   chart's `programText`.
2. **Same service filter** — the local `filter('service.name', '<value>')`
   (resolved) also appears in the live `programText` as
   `filter('service.name', '<value>')` or `filter('sf_service', '<value>')` —
   both dimension keys are equivalent.
3. **Same chart type** — the local chart type (`time_series`, `single_value`,
   etc.) matches the live chart's `options.type`.

Reason (COVERED):
`chart COVERED: metric http.server.request.duration + filter service.name=<svc> + type time_series all matched live chart C-456`.

A local chart is **GAP** when no live chart in the matched dashboard satisfies all
three. Reason:
`panel GAP: no live chart with metric=<m> + filter service.name=<svc> + type <t> in dashboard D-123; will create and add`.

A local chart is **UNCERTAIN** when the metric matches a live chart but the
service filter is absent / uses a different dimension key / is a wildcard, or the
chart type differs, or the local `${var.*}` could not be resolved. Reason names
the specific divergence, e.g.
`chart UNCERTAIN: metric matches live chart C-456 but its programText has no service.name/sf_service filter — cannot confirm scope`.

This three-level scheme is what lets sync **add one missing panel** to an
otherwise-covered dashboard: the dashboard is COVERED, but a chart inside it is a
GAP, so only that chart is created and added.

## Worked examples

### Example 1 — dashboard COVERED, all charts COVERED

Local: dashboard "Checkout RED" in group "Checkout Overview" with charts
`p99_latency` (http.server.request.duration), `error_rate` (http.server.errors.total).

Live: group "Checkout Overview" (G-1) exists; dashboard "Checkout RED" (D-2)
exists in it with two charts whose `programText` reference the same two metrics +
`filter('service.name','checkout')` and matching types.

→ group COVERED (name match), dashboard COVERED (name + 2/2 metrics), each chart
COVERED (metric + filter + type). Nothing created.

### Example 2 — dashboard COVERED, one chart GAP

Local: same dashboard plus a new `throughput` panel (http.server.requests.total).

Live: "Checkout RED" (D-2) has latency + error charts but no throughput chart.

→ dashboard COVERED; `throughput` chart GAP (`no live chart with
metric=http.server.requests.total + filter service.name=checkout + type
time_series in D-2`). Create only the throughput chart via `POST /v2/chart`,
then `PUT /v2/dashboard/D-2` with the existing `charts[]` plus the new
`{"chartId": <new_id>, ...}` entry. Do **not** recreate the whole dashboard —
that produces a duplicate. See `../../references/splunk-api.md` for the PUT
fetch-merge-update pattern.

### Example 3 — dashboard GAP (whole dashboard missing)

Local: dashboard "Checkout GenAI" in a GenAI group.

Live: no group or dashboard by those names.

→ group GAP, dashboard GAP, every chart GAP. Create group, then charts, then the
dashboard referencing them.

### Example 4 — dashboard COVERED (subset), chart GAPs

Local: "Checkout RED" with p99_latency + error_rate + throughput.

Live: a same-named "Checkout RED" exists with p99_latency + error_rate but no
throughput chart (every live panel matches a local panel; the live set is a
strict subset of the local set).

→ dashboard COVERED (`live panels are a strict subset`); throughput chart is a
GAP. Create only the throughput chart via `POST /v2/chart`, then
`PUT /v2/dashboard/{id}` appending it to the existing charts[]. Do not recreate
the whole dashboard.

### Example 5 — dashboard UNCERTAIN

Local: "Checkout RED" with p99_latency + error_rate.

Live: a same-named "Checkout RED" exists but contains only a single p50 latency
chart and an unrelated metric (the live dashboard has panels that don't
correspond to any local panel).

→ dashboard UNCERTAIN (`panels differ`); do not auto-create. Surface for the user
to reconcile.

## Field-name normalization

- `program_text` (HCL) ≡ `programText` (REST).
- `dashboard_group` (HCL attr) ≡ `groupId` (REST create body).
- `chart_id` (HCL) ≡ `chartId` (REST).
- `service.name` (OTel) ≡ `sf_service` (legacy SignalFx) for the filter check.
