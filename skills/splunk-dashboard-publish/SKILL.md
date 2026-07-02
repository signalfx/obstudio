---
name: splunk-dashboard-publish
description: >-
  Diff local splunk-dashboard Terraform against live Splunk Observability Cloud
  dashboards and create only the confirmed gaps. Reads
  .observe/terraform/dashboards.tf, fetches live dashboards, dashboard groups,
  and charts via the Splunk O11y REST API, classifies each group / dashboard /
  chart as COVERED / GAP / UNCERTAIN with an explicit reason, shows a
  confirmation diff, and creates gaps chart-first (POST /v2/chart then
  POST /v2/dashboard). Writes .observe/dashboard-sync.md as a resumable ledger.
  Use when the user types $splunk-dashboard-publish, asks to "sync dashboards",
  "check which dashboards are missing", "create missing dashboards", or "push
  dashboard gaps to Splunk".
metadata:
  author: otel-studio
  version: 0.1.0
  category: observability
---

# Dashboard Publish -- Splunk O11y Dashboard Gap Analysis and Create

## Overview

Compare locally-generated dashboard Terraform (from `$splunk-dashboard`) against
**live** Splunk Observability Cloud dashboards for the same service. Create only
the genuine gaps — chart-first, then the dashboard that references them — and
skip anything already covered. Write a persistent ledger so re-runs are
idempotent and auditable, with an explicit reason for every verdict.

This is the dashboard analogue of `$splunk-detector-publish` (detector publish). The key
structural difference: a dashboard is a three-level object — group → dashboard →
charts[] — and each chart is a **separate** REST object that must be created
**before** the dashboard that references it by `chartId`.

## When to Use

- After `$splunk-dashboard` has produced `.observe/terraform/dashboards.tf`
- When the user wants to push only the missing dashboards/charts to Splunk O11y
  without duplicating dashboards that already exist
- When auditing which dashboards are already live vs. still missing

**When NOT to use:** If no local dashboard spec exists, instruct the user to run
`$splunk-dashboard` first.

## Auth and API

> Shared reference: `../references/splunk-api.md` is the single source of truth
> for auth (`SPLUNK_ACCESS_TOKEN` → `X-SF-Token`, `SPLUNK_REALM`, base
> `https://api.${SPLUNK_REALM}.signalfx.com`), the **skip-on-500 paginated GET**
> loop, and HTTP-status handling (200 ok; 409 → COVERED; 403/401 → stop; 400 →
> casing/SignalFlow check; only 500 skipped, never a bare `except Exception`).

All Splunk O11y calls use the **Splunk REST API** directly — no MCP tool
required. If `SPLUNK_ACCESS_TOKEN` or `SPLUNK_REALM` is missing, stop and tell
the user. Treat the token as a secret — never log it or write it to the ledger.

## Process

### Step 1 -- Locate Local Specs

Look for `.observe/terraform/dashboards.tf` in the repository root.

- If it exists, proceed to Step 2.
- If it is missing, stop and respond:

> No local dashboard spec found at `.observe/terraform/dashboards.tf`. Please run
> `$splunk-dashboard` first to generate the dashboard Terraform.

Also read `.observe/dashboards.md` if present for the panel rationale that helps
resolve ambiguous UNCERTAIN cases.

### Step 2 -- Parse Local Specs

Parse each block in `dashboards.tf`:

1. **`signalfx_dashboard_group`** — `name`, `description`.
2. **`signalfx_dashboard`** — `name`, `dashboard_group` reference, and each
   `chart { chart_id; column; row; width; height }` block (grid placement).
3. **`signalfx_*_chart`** — for each chart resource: HCL label, `name`,
   `program_text`, and the chart type (from the resource type —
   `signalfx_time_chart` → `time_series`, `signalfx_single_value_chart` →
   `single_value`, etc.; see `splunk-dashboard/references/dashboard-templates.md`
   for the full mapping).

**Normalize every chart `program_text` before any POST or comparison** per
`../references/terraform-normalization.md`: `textwrap.dedent` the `<<-EOF`
heredoc and resolve **every** `${var.*}` (service name and any per-panel knob).
A literal `${var...}` or a leading-whitespace line makes the SignalFlow parser
reject the create with **HTTP 400**. HCL field names are snake_case
(`program_text`, `chart_id`, `dashboard_group`); the REST API uses camelCase
(`programText`, `chartId`, `groupId`) — normalize when building bodies.

Fail fast if the file is not parseable and tell the user.

### Step 3 -- Fetch Live Dashboards, Groups, and Charts

Using the skip-on-500 paginated GET loop from `../references/splunk-api.md`:

- `GET /v2/dashboardgroup` — live groups (`id`, `name`).
- `GET /v2/dashboard` — live dashboards (`id`, `name`, `groupId`, `charts[]`,
  each `{ chartId, column, row, width, height }`).
- `GET /v2/chart/{id}` — fetch a referenced chart's `programText` and type only
  when needed to compare a candidate-matched dashboard's panels.

If the org has zero dashboards, every local dashboard is a GAP — proceed with an
empty live list.

### Step 4 -- Classify Each Local Spec (group / dashboard / chart)

Apply `references/dashboard-coverage-model.md` (built on the shared
`../references/coverage-decision-tree.md`). Classify at **three levels**, and for
**every** verdict record the concrete reason it fired (see "Explicit coverage
rationale" below):

- **Dashboard group** — COVERED if a live group with the same name exists;
  otherwise GAP (it is created before its dashboards).
- **Dashboard** — COVERED if a live dashboard matches by name (or by group +
  panel-metric set); GAP if none matches; UNCERTAIN if a same-named dashboard
  exists but its panel set / metrics differ.
- **Chart / panel** — within a matched dashboard, each local chart is
  COVERED / GAP / UNCERTAIN against the live `charts[]` by `{ metric, filters,
  chartType }` (the live chart's `programText` fetched per Step 3). This is what
  lets sync add a missing panel to an otherwise-covered dashboard rather than
  mislabeling the whole dashboard.

The `service.name` and `sf_service` dimension keys are equivalent for the filter
check; `program_text` (HCL) and `programText` (REST) are the same field.

### Step 5 -- Confirmation Diff

Print a structured diff before any writes, **with a non-empty Reason on every
row**. Do not proceed until the user explicitly confirms (yes/no). Offer a dry
run via `POST /v2/dashboard/validate` + `POST /v2/chart/validate`.

**When network is unavailable (offline):** still produce the full confirmation
diff and describe the creation plan you would execute. Explicitly state:
1. Chart-first ordering — `POST /v2/chart` for each GAP chart to collect chart
   IDs, then `POST /v2/dashboard` referencing those `chartId` values with grid
   placement, then `POST /v2/dashboardgroup` if the group is also a GAP.
2. Orphan-chart recovery — if the dashboard POST fails after charts were
   already created, those charts exist but reference nothing; record their IDs
   in the ledger so a re-run can reuse or delete them via `DELETE /v2/chart/{id}`
   before recreating, never silently leaving orphans.

```
## Dashboard Publish Diff — <service-name>

### Dashboard Groups
| Local Group | Status | Reason |
|-------------|--------|--------|
| <service> Overview | GAP | no live dashboard group named "<service> Overview"; will create |

### Dashboards
| Local Dashboard | Group | Status | Reason |
|-----------------|-------|--------|--------|
| <service> RED | <service> Overview | GAP | no live dashboard named "<service> RED" in group; will create |

### Charts / Panels
| Local Chart | Metric | Type | Status | Reason |
|-------------|--------|------|--------|--------|
| p99_latency | http.server.request.duration | time_series | GAP | no live chart with metric=http.server.request.duration + filter service.name=<svc> + type time_series in dashboard |

---
N groups, N dashboards, N charts will be created. N UNCERTAIN need manual review.
Confirm? (yes/no)
```

If there are zero GAPs and zero UNCERTAINs, report all-COVERED, skip to Step 7,
and write the ledger.

### Step 6 -- Create GAPs (chart-first ordering)

After the user confirms, create in this order (the critical difference from
detector publish — a dashboard cannot be created before the charts it references):

1. **Ensure the dashboard group exists.** For each GAP group,
   `POST /v2/dashboardgroup` with `{ name, description }`; collect the returned
   `id`. For a COVERED group, reuse the live `id`.
2. **Create each GAP chart first.** For each GAP panel,
   `POST /v2/chart` with:
   ```python
   # options body is TYPE-DEPENDENT — see constraints below
   if chart_type == "TimeSeriesChart":
       options = {"type": "TimeSeriesChart", "defaultPlotType": "LineChart", "colorBy": "Dimension"}
   else:
       # SingleValue, List, Heatmap, Text, TableChart: do NOT include defaultPlotType
       options = {"type": chart_type, "colorBy": "Dimension"}

   body = {
       "name": chart_name,
       "programText": program_text,   # NORMALIZED per terraform-normalization.md
       "options": options,
       "packageSpecifications": "signalfx",
   }
   ```

   > **Chart API field notes:**
   > - `signalfx_text_chart` (chart type `Text`) uses `options.markdown` for its
   >   content — **not** `programText` or `program_text`. The `programText` field is
   >   ignored for text charts; always put the markdown body in `options: {type: "Text",
   >   markdown: "..."}`. Do not include `programText` in the POST body for a text chart.
   > - `TimeSeriesChart` is the **only** chart type that accepts `defaultPlotType`.
   >   All other types (`SingleValue`, `List`, `Heatmap`, `Text`, `TableChart`) reject
   >   `defaultPlotType` with HTTP 400.

   **RED FLAGS on chart create (HTTP 400):**
   - `defaultPlotType` in `options` for any non-`TimeSeriesChart` type → API rejects with 400.
     Only `TimeSeriesChart` accepts `defaultPlotType`. Remove it for `SingleValue`, `List`,
     `Heatmap`, `Text`, and `TableChart`.
   - `.last()` in `programText` with no window argument → SignalFlow rejects with 400.
     `.last()` requires an explicit window duration (e.g. `.last('1m')`). For gauge KPI panels
     use `.mean()` instead — it is the safe no-argument aggregation.

   Collect each returned chart `id`. Record every created chart id **immediately
   after each successful POST** by appending a row to the in-progress ledger
   file (write or rewrite `.observe/dashboard-sync.md` after each chart, not
   only at Step 7). This incremental write ensures that if the run aborts
   between chart creation and the final Step 7 ledger write, the chart IDs are
   still persisted and can be reused or cleaned up on the next run rather than
   left as silent orphans.
3. **Create the dashboard or update an existing one.**

   - **If the dashboard is GAP (does not exist):** `POST /v2/dashboard` with:
     ```python
     body = {
         "name": dashboard_name,
         "description": dashboard_description,
         "groupId": group_id,            # from step 1
         "charts": [
             {"chartId": cid, "column": c, "row": r, "width": w, "height": h}
             for (cid, c, r, w, h) in placed_charts
         ],
     }
     ```

   - **If the dashboard is COVERED but has chart-level GAPs:** use
     `PUT /v2/dashboard/{id}` to add only the new charts to the existing
     dashboard, per `../references/splunk-api.md` ("Updating an existing
     dashboard"). Fetch the live dashboard's current `charts[]`, append the
     new `{"chartId": cid, ...}` entries, and PUT the merged array. Do **not**
     recreate the whole dashboard — that would produce a duplicate.

Status handling per `../references/splunk-api.md`: 200/201 → record id + app
link; 409/duplicate → reclassify COVERED; 403 → token lacks dashboard-write
scope, stop; 400 → field-casing or SignalFlow-normalization check. Create
sequentially so progress is visible and failures are attributable.

**Orphan-chart recovery:** if the dashboard POST fails after charts were created,
the charts already exist but reference nothing. Record their ids in the ledger so
a re-run can either reuse them (match by metric+filter+type) or delete them
(`DELETE /v2/chart/{id}`) before recreating — never silently leave orphans.

### Step 7 -- Write Ledger

> Shared reference: `../references/ledger-template.md` defines the resumable
> ledger shape with the required non-empty **Reason** column.

Write or overwrite `.observe/dashboard-sync.md` after every run (success,
partial failure, or zero-gap no-op):

```markdown
# Dashboard Publish Ledger: <service-name>

**Date:** <YYYY-MM-DD>
**Local spec:** `.observe/terraform/dashboards.tf`
**Service filter resolved to:** `<service_name_value>`

## Summary

| Status | Count |
|--------|-------|
| COVERED | N |
| GAP → Created | N |
| GAP → Failed | N |
| UNCERTAIN | N |

## Dashboard Group Status

| Local Group | Status | Group ID | Link | Reason |
|-------------|--------|----------|------|--------|

## Dashboard Status

| Local Dashboard | Group | Status | Dashboard ID | Link | Reason |
|-----------------|-------|--------|--------------|------|--------|

## Chart Status

| Local Chart | Metric | Type | Status | Chart ID | Reason |
|-------------|--------|------|--------|----------|--------|

---
*Generated by splunk-dashboard-publish on <YYYY-MM-DD>*
```

Every row's **Reason** must be non-empty and concrete (name the live object + the
match basis for COVERED; what was searched and found absent for GAP; the specific
divergence for UNCERTAIN). Deep links use
`https://app.${SPLUNK_REALM}.signalfx.com/#/dashboard/{id}`.

### Step 8 -- Chat Summary

Present a concise summary: groups/dashboards/charts already covered, created, and
uncertain; the ledger path; and — if any creates failed — list them explicitly
with the error and any orphaned chart ids to clean up. If UNCERTAIN specs remain,
recommend re-running after the user reviews the diverging live dashboards.

## Explicit Coverage Rationale (required)

For **every** group, dashboard, and chart verdict, record the concrete reason it
was classified COVERED / GAP / UNCERTAIN — which criteria fired and what was
compared. This reason appears in the confirmation diff (Step 5) and is persisted
in the ledger's **Reason** column (Step 7). A generic note ("matched live
dashboard") is not acceptable.

- **COVERED** → name the live object + the exact match basis, e.g.
  `matched live dashboard "Checkout RED" (D-123): name match + 4/4 panel metrics present`
  or `chart COVERED: metric http.server.request.duration + filter service.name=checkout + type time_series all matched live chart C-456`.
- **GAP** → state what was searched and found absent, e.g.
  `no live dashboard named "Checkout RED" in group "checkout"; will create` or
  `panel GAP: no live chart with metric=... + filter=... found in dashboard D-123`.
- **UNCERTAIN** → state the specific divergence, e.g.
  `live dashboard "Checkout RED" exists but panels differ: local has p99_latency + error_rate; live has p50_latency only — not auto-creating, needs human review`.

See `references/dashboard-coverage-model.md` for the per-criterion reason text
and `../references/coverage-decision-tree.md` for the shared rule.

## Red Flags

- `.observe/terraform/dashboards.tf` missing — run `$splunk-dashboard` first.
- `SPLUNK_ACCESS_TOKEN` / `SPLUNK_REALM` unset — stop and tell the user.
- A chart `programText` still has a literal `${var.*}` or a leading-whitespace
  line — it will 400 on create; re-normalize per
  `../references/terraform-normalization.md`.
- Dashboard POST attempted before its charts exist — wrong ordering; charts must
  be POSTed first and referenced by `chartId`.
- A dashboard POST fails after charts were created — orphaned charts; record
  their ids and reuse or delete them on the next run.
- POST returns 403 — token lacks dashboard-write scope; stop.
