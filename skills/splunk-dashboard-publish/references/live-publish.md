# Live Dashboard Publish

Read this reference only when live Splunk Observability Cloud comparison is
possible. It governs fresh-state classification and, after explicit
confirmation, sequential create/update/orphan-cleanup operations.

Before any API call, read `../../references/splunk-api.md`. It is the sole
authority for `SPLUNK_ACCESS_TOKEN`, realm resolution, token secrecy,
skip-on-500 pagination, create/update statuses, and dashboard fetch-merge-PUT.
Also read `dashboard-coverage-model.md`; it owns group, dashboard, and chart
matching. Do not separately load `../../references/coverage-decision-tree.md`
because the local coverage model incorporates its verdict and reason rules.

Read `../../references/terraform-normalization.md` before comparing or sending
SignalFlow and `chart-wire-contract.md` before building chart bodies. Read
`../../references/ledger-template.md` before the first mutation because chart
IDs must be persisted immediately.

## Fetch Fresh State

Use the shared skip-on-500 pagination rules for:

- `GET /v2/dashboardgroup` for `id`, `name`;
- `GET /v2/dashboard` for `id`, `name`, `groupId`, and placed `charts[]`;
- `GET /v2/chart/{id}` only for charts in candidate-matched dashboards whose
  `programText` and `options.type` are needed.

An empty successful live list means local objects are GAPs. Do not turn a
failed/incomplete fetch into an empty list or false GAP. Only HTTP 500 pages are
skipped; 401/403, parsing, and transport errors remain visible.

Classify fresh state at all three levels through
`dashboard-coverage-model.md`. `service.name` and `sf_service` are equivalent
only for the service-filter comparison. Record every criterion and a concrete,
non-empty reason for every COVERED, GAP, and UNCERTAIN verdict.

## Confirmation Gate

Show the complete group/dashboard/chart diff before any remote write. Include:

- resolved realm and whether it came from `SPLUNK_REALM` or the connected
  Splunk Observability Studio realm-only lookup;
- every object to create or update;
- every unmatched orphan chart proposed for deletion;
- exact non-empty reasons and identifiers for COVERED objects;
- all UNCERTAIN objects, which remain non-mutating; and
- ordered operation counts.

Require explicit yes/no. Credentials, an earlier confirmation, or a prior
ledger do not count. A changed live diff invalidates an earlier confirmation.
On `no` or ambiguity, stop without writes.

For an explicit dry run with usable live access, the fresh GETs and structural
classification still run, but the displayed confirmation is informational.
Stop before every create, update, ledger write, or orphan deletion regardless
of the answer. A later non-dry-run must fetch and classify current state again,
show its exact mutation set, and obtain a new confirmation.

## Prepare Chart Bodies

Use `chart-wire-contract.md` exactly. It owns HCL-to-REST type mapping,
`options`, `programText`, `packageSpecifications`, text-chart behavior, and the
`defaultPlotType` restriction.

## Create Confirmed GAPs And Attach Chart GAPs Sequentially

Create only `GAP` objects from the confirmed diff. The sole permitted mutation
of a `COVERED` object is the containing-dashboard PUT required to attach
confirmed chart-level `GAP` rows; this exception does not reclassify the
dashboard itself as GAP. Execute in this order:

1. Create each GAP group with `POST /v2/dashboardgroup` body
   `{name, description}`; reuse the ID of a COVERED group.
2. Reuse a matching saved orphan ID when its name plus normalized
   `programText` fingerprint or metric+filter+type matches exactly. Otherwise
   create the GAP chart with `POST /v2/chart`.
3. Immediately after each chart POST, write/rewrite the in-progress
   `.observe/dashboard-sync.md` ledger with that chart ID under `Orphan charts`.
   Do not wait until the final report.
4. For a GAP dashboard, `POST /v2/dashboard` with `name`, `description`,
   `groupId`, placed `charts[]`, and `"tags": ["obstudio"]`.
5. For a COVERED dashboard with chart GAPs, fetch its current object and
   `PUT /v2/dashboard/{id}` with every existing `charts[]` placement retained
   and only the confirmed new chart placements appended. Build the accepted PUT
   body from current live values and change only `charts[]`; never remove or
   reorder an existing placement, recreate the dashboard, or update it for any
   other reason.
6. Once a created/reused chart is successfully referenced, remove it from the
   orphan list. Delete only unmatched orphan IDs included in the confirmed diff
   via `DELETE /v2/chart/{id}`.

Never create an UNCERTAIN object. Never create in parallel: sequential writes
make attribution and incremental recovery deterministic.

## Status And Race Handling

Use the shared API contract exactly:

- POST 200/201: persist returned ID, name, and app link.
- POST 409/duplicate: GET the existing object's ID, reclassify COVERED, and
  reuse it. A chart ID must be recovered before dashboard reference.
- POST/PUT 400: distinguish camelCase field errors from unnormalized
  SignalFlow; repair only the local request representation.
- POST/PUT 401 or 403: stop; do not retry or continue mutation.
- PUT 200: updated. PUT 404: re-fetch/reclassify because the dashboard changed
  after diff; do not create under stale confirmation.
- Unexpected per-object failure: record it and continue only where the shared
  contract allows independent safe work.

If dashboard POST/PUT fails after charts exist, persist every unreferenced ID
as an orphan before continuing or stopping. Never silently leave or discard
the IDs.

## Ledger And Summary

For a non-dry-run live run, write `.observe/dashboard-sync.md` after success,
partial failure, or an all-COVERED no-op. A connected dry run never writes a
ledger. Use the shared ledger template, with separate group, dashboard,
and chart tables and a concrete non-empty `Reason` cell per row. Add an
`Orphan charts` section whenever IDs remain unreferenced.

Deep links use
`https://app.${realm}.signalfx.com/#/dashboard/{id}`. Never include the access
token, auth header, raw secret, or real Terraform token value.

The final summary states covered, created, failed, and uncertain counts at all
three levels; the ledger path; every failed operation; and all remaining orphan
IDs with the exact reuse/cleanup next action. A subsequent run always re-fetches
and reclassifies live state instead of trusting prior COVERED/GAP verdicts.
