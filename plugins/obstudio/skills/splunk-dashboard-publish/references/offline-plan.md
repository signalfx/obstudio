# Offline Dashboard Publish Plan

Read this reference when network access is unavailable, credentials are only
placeholders, or the user requests a dry-run plan without live queries. This
mode never reads environment credentials, calls the Splunk API, or creates,
updates, or deletes remote objects.

The final response is incomplete unless it includes all three: the exact
normalized per-chart `programText`, a concrete Reason on every diff row, and a
planned dashboard JSON body with the literal `"tags": ["obstudio"]` marker.

## Parse And Normalize

Parse `.observe/terraform/dashboards.tf` into a three-level graph:

1. Each `signalfx_dashboard_group`: HCL label, `name`, and `description`.
2. Each `signalfx_dashboard`: HCL label, `name`, `description`,
   `dashboard_group`, and every `chart` placement (`chart_id`, `column`, `row`,
   `width`, `height`).
3. Each `signalfx_*_chart`: HCL label, `name`, chart type, `program_text`, or
   `markdown` for text charts.

Read `../../references/terraform-normalization.md` and normalize every
`program_text`: reproduce Terraform `<<-EOF` dedent, trim blank edges, and
resolve every `${var.*}` from `terraform.tfvars`, `*.auto.tfvars`,
`terraform.tfvars.example`, then variable defaults. Ask rather than guess if a
value remains unresolved. Use the normalized text for both comparison and any
planned REST `programText`.

Read `chart-wire-contract.md` for the HCL/local/REST type mapping and planned
chart body. Do not load the dashboard-generation templates.

Fail fast on unparseable HCL or unresolved variables. Never present invalid or
placeholder SignalFlow as ready to publish.

Before the diff, render concrete normalization evidence:

```markdown
### Normalized Chart Programs
| Local chart | REST type | Exact normalized programText |
|---|---|---|
```

Include one row for every non-text chart. Print its complete resolved
SignalFlow exactly as it would appear in `programText`, with no `${var.*}`,
heredoc indentation, placeholder such as `<normalized SignalFlow>`, or ellipsis.
For a text chart, show the exact normalized markdown separately and state that
its POST body omits `programText`.

## Offline Classification

Without live state, a local object can be proven neither COVERED nor absent.
Render every local group, dashboard, and chart as `UNCERTAIN (offline plan)` or
`UNCERTAIN` with the concrete reason `no live fetch available; planned candidate
only — reclassify against live state before execution`. `GAP` is reserved for a
live search that confirms absence. Do not invent live IDs, claim absence was
queried, or carry offline verdicts into a later mutation run.

For every chart row, put the metric, resolved `service.name` filter, and chart
type inside the `Reason` cell itself; adjacent Metric and Type columns do not
satisfy this requirement. Use this exact shape:
`no live fetch available; planned candidate only — metric=<metric> + filter
service.name=<service> + type=<type> not compared; reclassify against live state
before execution`. If the local spec itself is ambiguous—for example unresolved
scope or an unsupported chart shape—also name the divergence. Every row needs
a non-empty reason.

Use this confirmation-diff shape:

```markdown
## Dashboard Publish Diff — <service-name> (offline plan)

### Dashboard Groups
| Local Group | Status | Reason |
|---|---|---|

### Dashboards
| Local Dashboard | Group | Status | Reason |
|---|---|---|---|

### Charts / Panels
| Local Chart | Metric | Type | Status | Reason |
|---|---|---|---|---|

---
N groups, N dashboards, and N charts are UNCERTAIN planned candidates.
No live state was fetched. Confirm? (yes/no)
```

The prompt is informational in offline mode: stop after it. A `yes` cannot
authorize offline mutation or convert planned candidates into live GAPs. A later
online run must fetch and reclassify fresh state, show a new diff with the
resolved realm and exact orphan deletions, and obtain confirmation again.

## Planned Creation Graph And Bodies

Describe what a later confirmed online run would do:

1. `POST /v2/dashboardgroup` for a live-confirmed GAP group and keep its ID.
2. `POST /v2/chart` for each live-confirmed GAP chart and keep each chart ID.
3. `POST /v2/dashboard` for a missing dashboard, referencing the collected
   `chartId` values with exact grid placement.
4. For confirmed chart GAPs in a COVERED dashboard, fetch current state and
   fetch-merge-`PUT /v2/dashboard/{id}` solely to attach them. Retain every
   existing `charts[]` placement and its order; append only confirmed new
   placements. Never remove/reorder existing placements, recreate or otherwise
   mutate the COVERED dashboard, or mutate UNCERTAIN. This sole permitted
   COVERED mutation does not make the dashboard a GAP.

Show the planned chart body shape from `chart-wire-contract.md`, then list the
exact `name`, REST type, and complete normalized `programText` for each planned
non-text chart. Never substitute a placeholder for the concrete per-chart
SignalFlow.

Show this planned dashboard body under a visible `### Planned Dashboard Body`
heading, including the ownership marker:

```python
body = {
    "name": dashboard_name,
    "description": dashboard_description,
    "groupId": group_id,
    "charts": [
        {"chartId": cid, "column": c, "row": r, "width": w, "height": h}
        for (cid, c, r, w, h) in placed_charts
    ],
    "tags": ["obstudio"],
}
```

Explain that chart IDs must be written incrementally to
`.observe/dashboard-sync.md`. If dashboard POST/PUT fails after chart creation,
record every still-unreferenced chart ID immediately as explicit `Orphan charts`
after either the POST failure or the PUT failure. A retry can match/reuse them,
or a future confirmed cleanup can `DELETE /v2/chart/{id}`. Never imply that
cleanup ran offline.

## Response

Return the parsed object counts, normalized chart identities, complete
three-level diff, planned bodies/order, explicit offline limitation, and the
confirmation boundary. State that no network call or remote mutation ran and
that live reclassification plus a new explicit confirmation is required. The
response must include the `Normalized Chart Programs` table rather than only a
count of unresolved variables. Before finalizing, search the response for the
literal `"tags": ["obstudio"]`; if it is absent, add the planned dashboard body.
A future-live response is incomplete unless it says: create GAPs only; the sole
COVERED mutation is this append-only PUT preserving existing chart placements
and order; never otherwise mutate COVERED or UNCERTAIN; and after dashboard
POST or PUT failure record every unreferenced chart ID under `Orphan charts`.
