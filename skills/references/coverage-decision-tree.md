# Coverage decision tree — COVERED / GAP / UNCERTAIN

Shared meta-pattern for how every sync skill decides whether a local Terraform
spec is already covered by a live Splunk Observability Cloud object. The
object-specific matching criteria live in each skill's own `references/`
(`splunk-detector-publish/references/coverage-model.md` for detectors;
`splunk-dashboard-publish/references/dashboard-coverage-model.md` for dashboards,
charts, and groups). This file defines the shared verdict vocabulary and the
**record-every-criterion-that-fired** rule those models build on.

## Why not match by name

Searching by object name is unreliable: the live search API returns thousands of
org-wide results for a common term, names vary freely across teams, and
name-only matches produce both false positives (different service, same metric
family) and false negatives (same coverage, different naming convention).
Match on **structural identity** — the metric name(s), the service filter, and
the object type — read from the live object's `programText`/`charts[]`. That is
deterministic and verifiable from live state.

## The three verdicts

### COVERED
A live object matches the local spec on **all** required criteria for its type.
**Action:** skip — no create needed. Record the live object's name + id and the
exact criteria that matched.

### GAP
No live object matches on the required criteria.
**Action:** create it via the REST API (chart-first for dashboards; see the
sync skill). Record what was searched for and confirmed absent.

### UNCERTAIN
A live object partially matches — e.g. the metric name appears but the service
filter is absent, uses a different dimension key, is a wildcard, or the spec's
`${var.*}` could not be resolved to a concrete value; or a same-named container
exists but its contents differ.
**Action:** surface in the confirmation diff; do **not** auto-create and do
**not** auto-cover. The user inspects and decides. Record the specific
divergence.

## Record every criterion that fired (drives the Reason column)

The classification is multi-criterion. For each spec, evaluate each criterion
independently and **record which ones fired and what was compared** — that record
is the concrete Reason shown in the confirmation diff and persisted in the
ledger's Reason column (see `ledger-template.md`). The reason must let a human
re-derive the verdict without re-running the tool:

- COVERED → the live object name + id + each criterion that matched
  (`metric X present`, `filter service.name=Y present`, `type Z matched`).
- GAP → the criteria that were searched and the value found absent.
- UNCERTAIN → the exact criterion that diverged and why it blocks a confident
  verdict.

A never-empty Reason per verdict is a hard requirement; a deterministic eval
asserts it.

## Multi-level objects

A simple object (a detector) has one verdict. A composite object (a dashboard)
is classified at **each level** of its graph and each level records its own
reason:

- the **container** (dashboard group) — exists by name or not;
- the **object** (dashboard) — matches by name + member set or not;
- each **member** (chart/panel) — matches by metric + filter + type or not.

This is what lets a sync add one missing panel to an otherwise-covered dashboard
rather than mislabeling the whole dashboard COVERED or GAP. See the dashboard
coverage model for the concrete per-level criteria.

## Field-name equivalences

When comparing local HCL against live REST objects, treat these as the same:

- `program_text` (HCL) ≡ `programText` (REST).
- `service.name` (OTel semantic convention) ≡ `sf_service` (legacy SignalFx
  dimension) for the service-filter check — both match the same series.
