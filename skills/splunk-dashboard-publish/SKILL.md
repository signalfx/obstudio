---
name: splunk-dashboard-publish
description: >-
  Compare .observe/terraform/dashboards.tf with live Splunk Observability Cloud
  groups, dashboards, and charts; classify COVERED/GAP/UNCERTAIN results,
  confirm, and create only GAPs chart-first with a resumable ledger. Use for
  $splunk-dashboard-publish, "sync dashboards", "check which dashboards are missing",
  "create missing dashboards", or "push dashboard gaps to Splunk".
metadata:
  author: otel-studio
  version: 0.1.2
  category: observability
---

# Dashboard Publish -- Splunk O11y Dashboard Gap Analysis And Create

Compare `$splunk-dashboard` Terraform with live Splunk Observability Cloud at
group, dashboard, and chart levels; create only confirmed GAPs. Charts must
exist before dashboards use their `chartId` values. Keep a ledger for
idempotent reruns and orphan-chart recovery.

Without `.observe/terraform/dashboards.tf`, stop and request
`$splunk-dashboard` first.

Resolve paths in this entrypoint from the skill directory. Inside a loaded
reference, resolve its relative paths from that reference's directory. Never
resolve skill references from the service cwd or probe alternate copies unless
a required file is missing. Read only the references routed by the selected mode.

## Always-Loaded Safety Contract

- Local planning and live comparison are read-only. Before any remote create,
  update, or delete, show the complete diff and require explicit current
  yes/no confirmation. Credentials, a prior run, or earlier confirmation are
  not consent. A changed diff requires confirmation again.
- Create only GAPs. On a COVERED dashboard, append only confirmed chart GAPs.
  Never mutate UNCERTAIN objects.
- Live REST auth uses `SPLUNK_ACCESS_TOKEN` from the environment as
  `X-SF-Token`. Never log it, echo it, write it to
  `.observe/dashboard-sync.md`, put it in prompt/report context, or persist a
  real value in Terraform examples.
- Resolve realm from non-empty `SPLUNK_REALM` first, then the connected
  Splunk Observability Studio's realm-only lookup. That lookup is never a token source. If token
  or realm is missing for a live run, stop with the exact prerequisite.
- Fetch and reclassify live state on every run; the prior ledger is not proof
  that an object remains COVERED or GAP. Use prior rows only for audit history
  and orphan recovery.
- Only HTTP 500 pages in paginated GET are skipped. Never swallow 401, 403,
  parsing, transport, or other errors with a bare `except Exception`; an
  incomplete fetch cannot become an empty list and false GAPs.
- Writes are sequential. POST 200/201 records the returned ID; 409 requires a
  GET and reuse of the existing ID; 400 requires casing/SignalFlow diagnosis;
  401/403 stops without retry. Detailed PUT/race handling belongs to the live
  reference.
- Record every successful chart POST immediately in the ledger before the
  dashboard write. If POST/PUT dashboard fails, keep every unreferenced chart
  ID under `Orphan charts`. Reuse exact matches or `DELETE /v2/chart/{id}` only
  when that cleanup was listed in the current confirmation diff.
- Never expose or invent live IDs. Every group/dashboard/chart verdict and
  ledger row has a concrete, non-empty Reason naming the criteria and values
  compared.

## Reference Router

| Condition | Read | Authority |
|---|---|---|
| Explicit no-network request, unavailable network, or placeholder credentials | `references/offline-plan.md` | Local parsing, UNCERTAIN candidates, planned payloads/order, offline stop |
| Any `program_text` is parsed | `../references/terraform-normalization.md` | `<<-EOF` dedent and every `${var.*}` resolution |
| Chart wire type is needed | `references/chart-wire-contract.md` | HCL/local/REST type mapping and chart body |
| Connected dry-run, live comparison, or mutation | `references/live-publish.md` | Fresh fetch, confirmation, dry-run stop or ordered mutation, orphan recovery, ledger |
| Live API access | `../references/splunk-api.md` (routed by live publish) | Auth, realm, pagination, HTTP status, dashboard PUT |
| Live classification | `references/dashboard-coverage-model.md` (routed by live publish) | Three-level structural match and reason criteria |
| Ledger will be written | `../references/ledger-template.md` (routed by live publish) | Resumable ledger and incremental chart-ID writes |

The local coverage model incorporates the shared
`../references/coverage-decision-tree.md`; do not load the shared decision tree
separately. Offline mode must not load `splunk-api.md`, `live-publish.md`, the
live coverage model, or the ledger template.

The generator source `../splunk-dashboard/references/dashboard-templates.md`
contains the same type vocabulary, but do not load it during publish; the
local chart wire contract is self-contained.

## Process

### 1. Locate And Parse Local Specs

Require `.observe/terraform/dashboards.tf`. Optionally read
`.observe/dashboards.md` for panel rationale and
`.observe/dashboard-sync.md` for prior orphan IDs.

Parse a three-level graph:

1. `signalfx_dashboard_group`: HCL label, `name`, `description`.
2. `signalfx_dashboard`: HCL label, `name`, `description`,
   `dashboard_group`, and every chart placement (`chart_id`, `column`, `row`,
   `width`, `height`).
3. Each `signalfx_*_chart`: HCL label, `name`, chart type, and normalized
   `program_text`; text charts carry `markdown` instead.

Read `../references/terraform-normalization.md`. Dedent every indented
`<<-EOF` heredoc and resolve every `${var.*}` from tfvars/defaults before
comparison or planned POST. For offline plans, show each non-text chart's exact
normalized `programText`; a placeholder or ellipsis is not proof of
normalization. Fail rather than guess unresolved variables. HCL
uses `program_text`, `chart_id`, and `dashboard_group`; REST uses
`programText`, `chartId`, and `groupId`.

Read `references/chart-wire-contract.md`. The publish path must recognize
`TimeSeriesChart` and `SingleValue` as well as the remaining mapped types.
`packageSpecifications` belongs in chart bodies.

### 2. Select Offline Or Live Mode

If network is unavailable, credentials are placeholders, or the user explicitly
requires no network, read `references/offline-plan.md`. Do not read credentials
or make a network call. Produce the complete local plan with every unqueried
object marked `UNCERTAIN`, describe chart-first creation and orphan recovery,
show exact normalized SignalFlow for every non-text chart, and print a planned
dashboard body containing the literal `"tags": ["obstudio"]`. Then stop at the
informational confirmation gate without creating, updating, or deleting.

A dry-run request with usable live access is not offline: read
`references/live-publish.md`, perform the read-only live fetch and structural
classification, show real COVERED/GAP/UNCERTAIN results, and stop before every
mutation even if the user answers yes. A later non-dry-run must re-fetch, show
the diff, and obtain a new confirmation.

Otherwise read `references/live-publish.md` before the first API call. It
routes to the shared API, live coverage, and ledger contracts. Fetch groups and
dashboards, then only the charts needed for candidate comparison. A successful
empty list means all local objects are GAP; a failed fetch does not.

### 3. Classify At Three Levels

Live mode applies `references/dashboard-coverage-model.md`:

- Group: name match is COVERED; absence is GAP.
- Dashboard: match within group by name and panel set. A same-name live strict
  subset is COVERED with chart-level GAPs; divergent extra/different content is
  UNCERTAIN.
- Chart: COVERED only when one live chart matches metric, resolved service
  filter (`service.name` or equivalent `sf_service`), and chart type. Partial
  matches are UNCERTAIN; absence of a complete match is GAP.

Record every criterion that fired. A valid chart reason can say
`metric http.server.request.duration + filter service.name=checkout + type
time_series all matched live chart C-456`. Reject a generic note such as
`matched live dashboard`.

### 4. Show The Confirmation Diff

Before any write, show separate Dashboard Groups, Dashboards, and Charts /
Panels tables with a non-empty Reason on every row. Include
resolved realm/source for live mode, exact operation counts, every UNCERTAIN
row, and proposed orphan deletions.

```markdown
## Dashboard Publish Diff — <service-name>

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
N groups, N dashboards, and N charts will be created or updated.
N UNCERTAIN require review; N orphan charts are proposed for deletion.
Confirm? (yes/no)
```

With zero GAPs and UNCERTAINs, do no remote mutation. Write the all-COVERED
ledger only in non-dry-run live mode; a connected dry run never writes one.
Offline mode stops after its informational diff. A later online run must fetch,
reclassify, show a new diff, and confirm again.

### 5. Execute Confirmed Live GAPs

Only after `yes`, follow `references/live-publish.md`:

1. Ensure each GAP group exists with `POST /v2/dashboardgroup`.
2. Reuse an exact matching orphan or create each GAP chart with
   `POST /v2/chart`; persist every returned ID immediately.
3. Create a missing dashboard with `POST /v2/dashboard`, referencing placed
   chart IDs and including `"tags": ["obstudio"]`.
4. For chart GAPs in a COVERED dashboard, fetch-merge-`PUT /v2/dashboard/{id}`;
   never recreate the dashboard.
5. Clear referenced orphan IDs and delete only still-unmatched, explicitly
   confirmed orphans via `DELETE /v2/chart/{id}`.

Build chart bodies exactly as `references/chart-wire-contract.md` specifies.

### 6. Write The Resumable Ledger And Summary

For non-dry-run live runs, write `.observe/dashboard-sync.md` after success,
partial failure, or an all-COVERED no-op with `../references/ledger-template.md`.
Keep separate group/dashboard/chart
tables, summary counts, IDs/deep links, concrete reasons, failures, and any
remaining `Orphan charts`. Never write the access token.

Summarize covered, created, failed, and uncertain counts at each level; link the
ledger; list every failure and orphan ID; and give the exact next action.
Reruns always re-fetch live state and reuse persisted orphan IDs rather than
creating duplicates.

## Red Flags

- Missing dashboard Terraform: run `$splunk-dashboard`.
- Missing live token or realm: stop; do not guess or use Splunk Observability Studio as a token
  source.
- Unresolved `${var.*}` or leading heredoc indentation: do not compare or POST.
- Dashboard write before chart IDs exist: invalid order.
- Dashboard failure after chart creation without an incremental orphan ledger:
  unsafe and non-resumable.
- 401/403: stop without retry. 400: distinguish REST casing from SignalFlow
  normalization. Continuous 500s: treat as a likely auth/service problem, not
  an empty live inventory.
