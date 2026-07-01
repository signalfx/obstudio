# Coverage Model — splunk-detector-publish

How `splunk-detector-publish` determines whether a local `signalfx_detector` spec
is already covered by a live Splunk Observability Cloud detector. Builds on the
shared `../../references/coverage-decision-tree.md` (the COVERED / GAP /
UNCERTAIN vocabulary and the record-every-criterion-that-fired rule).

## The Matching Rule

A local spec is **COVERED** only when ALL of the following are true for a single
live Standard detector:

1. **Same metric name** — the OTel metric extracted from the local spec's
   `program_text` (the first `data('metric.name', ...)` argument) also appears in
   the live detector's `programText`.
2. **Same service filter** — the local spec's `filter('service.name', '${var.service_name}')`
   (resolved to the actual service name string) also appears in the live
   detector's `programText`, either as `filter('service.name', '<value>')` or
   `filter('sf_service', '<value>')` — both dimension keys are equivalent for
   this check.
3. **Standard origin** — the live detector has `detectorOrigin != "AutoDetect"`.
   Org-wide AutoDetect detectors never qualify as COVERED (see AutoDetect section).

If ANY condition is not met, the spec is NOT COVERED.

## Why Name Matching Was Rejected

Searching by detector name is unreliable:
- The live search API returns thousands of org-wide results for a single term
  (observed: 4429 results in mon0 for one common keyword).
- Name strings vary freely across teams; a detector named "My Service Latency"
  may or may not cover `http.server.request.duration` for a specific service.
- Name-based matches produce false positives (different service, same metric
  family) and false negatives (same coverage, different naming convention).

The metric-name + service-filter rule is deterministic and verifiable from the
live `programText`.

## Status Definitions

### COVERED
A live Standard detector's `programText` contains:
- the same OTel metric name as the local spec's `data(...)` call, AND
- a `filter('service.name', '<service>')` or `filter('sf_service', '<service>')` 
  call with the resolved service name value.

**Action:** skip — no create needed.

### GAP
No live Standard detector matches on both metric name AND service filter.

**Action:** create via `POST /v2/detector` (Splunk REST API). Only the confirmed
gaps are created; existing detectors are never modified. See
`../../references/splunk-api.md` for the request shape. The create step is
idempotent by construction — the diff runs against the live detector set fetched
that same run, and a 409 Conflict from a concurrently-created detector is treated
as already-covered rather than an error (see Idempotency below).

### UNCERTAIN
At least one live Standard detector references the same metric name, but the
service filter is absent, uses a wildcard, uses an unrecognized dimension key,
or the filter value cannot be compared (e.g. `${var.some_var}` unexpanded).

**Action:** surface in confirmation diff; do not auto-create or auto-cover.
The user must manually inspect the live detector and decide.

Common UNCERTAIN triggers:
- Live `programText` has `data('metric.name')` with no `filter(...)` at all
- Live `programText` uses `filter('environment', ...)` instead of `service.name`
- Live `programText` filter value is a pattern or wildcard
- Local spec `${var.service_name}` could not be resolved to a concrete string

### AutoDetect Advisory

A live detector where `detectorOrigin == "AutoDetect"`.

These detectors are created by Splunk's org-wide APM AutoDetect feature. They
use `blended()` over `service.request.*` metrics aggregated across all services
and have no `service.name` filter. Because they are not scoped to a specific
service, they cannot substitute for a custom detector in this analysis.

**Action:** surface as an advisory footnote in the confirmation diff for latency
and error specs. The local spec's classification (COVERED / GAP / UNCERTAIN)
is determined solely by Standard detectors. AutoDetect status never changes that
classification.

## Idempotency

There is no server-side `if_not_exists` flag on `POST /v2/detector`; the Splunk
O11y REST API does not offer one. Idempotency is achieved locally:

1. **Diff before create.** Every local spec is classified against the live
   detector set fetched at the start of the run. Only specs classified as GAP are
   sent to `POST /v2/detector`; COVERED and UNCERTAIN specs are never created.
2. **409 Conflict tolerance.** If a detector with the same name/scope was created
   concurrently (another run, another user) between the diff and the create, the
   API returns HTTP 409. Treat that 409 as "already covered" — record it in the
   ledger as COVERED-on-conflict rather than surfacing it as a failure.
3. **Resumable ledger.** `.observe/detector-sync.md` records each spec's verdict
   and create result, so a re-run skips already-created detectors and only
   retries genuine failures.

This diff + 409 approach gives the same "create only the confirmed gaps" behavior
that a hypothetical `if_not_exists` flag would, without depending on an API
feature that does not exist.

## Worked Examples

### Example 1 — COVERED

Local spec `program_text`:
```
A = data('http.server.request.duration', filter=filter('service.name', 'orders-api')).percentile(pct=99).publish(label='P99')
detect(when(A > threshold(1.0))).publish('P99 Too High')
```

Live detector `programText`:
```
A = data('http.server.request.duration', filter=filter('service.name', 'orders-api')).percentile(pct=99).publish(label='P99 Latency')
detect(when(A > 1.5)).publish('High Latency')
```

Match: metric `http.server.request.duration` ✓ + filter `service.name=orders-api` ✓ + Standard origin ✓
→ **COVERED** (thresholds may differ — that is intentional, existing config is respected)

### Example 2 — UNCERTAIN (metric matches, service filter absent)

Local spec `program_text`:
```
A = data('orders.errors.total', filter=filter('service.name', 'orders-api')).sum(over='5m').publish(label='Error Rate')
```

Live detector `programText`:
```
A = data('orders.errors.total').sum(over='5m').publish(label='Error Rate')
```

Match: metric `orders.errors.total` ✓ + filter `service.name=orders-api` ✗ (no filter in live)
→ **UNCERTAIN** (metric matches, service scope missing — cannot confirm coverage)

### Example 3 — GAP (no matching live detector at all)

Local spec metric: `db.pool.connections.active` for service `orders-api`

Live detectors: none reference `db.pool.connections.active` in their `programText`
→ **GAP** — create this detector

### Example 4 — AutoDetect Advisory (not COVERED)

Local spec: latency detector for `service.request.duration` (or similar) for `orders-api`

Live detector: `detectorOrigin == "AutoDetect"`, `programText` uses `blended()` over
`service.request.*` with no `filter('service.name', ...)`.

→ Local spec classification determined by Standard detectors only.
   AutoDetect detector is noted as advisory: "org-wide AutoDetect APM detector
   exists; does not substitute for a service-scoped custom detector."

## Field Name Normalization

The local HCL uses `program_text` (snake_case). The live API returns `programText`
(camelCase). Treat both as the same field when comparing.

Similarly, `service.name` (OTel semantic convention) and `sf_service` (legacy
SignalFx dimension) are equivalent for the service filter check.
