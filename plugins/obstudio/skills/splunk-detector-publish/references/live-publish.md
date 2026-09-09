# Live Detector Publish

Read this reference only for a live Splunk Observability Cloud comparison. It
governs auth, fresh-state classification, confirmation, sequential create, and
the resumable ledger.

Before the first live call, read `../../references/splunk-api.md`; it is the sole
authority for `SPLUNK_ACCESS_TOKEN`, realm resolution, token secrecy,
skip-on-500 pagination, and HTTP response handling. Also read
`coverage-model.md`, `../../references/terraform-normalization.md`, and—before
the first mutation—`../../references/ledger-template.md`. The local coverage
model already incorporates `../../references/coverage-decision-tree.md`, so do
not load that shared decision tree separately.

## Resolve Auth Without Exposing Secrets

Read the token only from `SPLUNK_ACCESS_TOKEN` and send it only in the
`X-SF-Token` header. Never print it or copy it to a prompt, command output,
report, ledger, or file. Resolve realm from non-empty `SPLUNK_REALM` first, then
the connected Observer's realm-only lookup. Observer never supplies the token.
Stop if either prerequisite is absent.

## Fetch And Classify Fresh State

Use the shared bounded pagination contract for `GET /v2/detector`, collecting
`id`, `name`, `programText`, `detectorOrigin`, and `rules` while deduplicating by
ID. Fetch `GET /v2/detector/{id}` only when a candidate's `programText` is absent
or truncated. Avoid per-detector reads otherwise.

Skip only intermittent HTTP 500 pages. Surface 401, 403, parse, transport, JSON,
and other errors. Continuous 500s or any incomplete inventory makes every
affected local verdict UNCERTAIN and ends the run without POST. Only a successful
empty list proves that no live detector exists and can classify valid local
specs GAP.

Apply `coverage-model.md` to normalized local programs and the fresh live list:

- COVERED requires one live Standard detector with both the same metric and the
  same resolved `service.name` or equivalent `sf_service` filter.
- GAP requires a complete successful inventory with no such match.
- UNCERTAIN covers partial/ambiguous matches or unusable live `programText` and
  is never created automatically.
- `detectorOrigin == "AutoDetect"` is recorded in the advisory section only and
  never satisfies service-scoped coverage.

Record every criterion that fired and a concrete non-empty Reason for every
verdict.

## Fresh Confirmation Gate

Show the complete detector diff and AutoDetect advisory before any POST. Include
the resolved realm and whether it came from `SPLUNK_REALM` or Observer, exact GAP
count, sequential operation order, normalized payload identity, all UNCERTAIN
rows, and concrete reasons/IDs for COVERED rows. Require explicit current yes/no.
On no or ambiguity, stop.

That confirmation authorizes one exact mutation set only. It expires if local
Terraform, normalization inputs, realm, live inventory, GAP membership/order,
or payloads change. If there is intervening work or any reason to suspect stale
state before the first POST, re-fetch and recompute. A changed diff must be shown
and confirmed again. Never extend a confirmation to newly discovered GAPs or a
later rerun. A 409 during creation closes the remaining diff/create race by
GET/reuse rather than duplicate creation.

## Create Confirmed GAPs Sequentially

For each confirmed GAP, in the displayed order, POST
`https://api.${realm}.signalfx.com/v2/detector` with:

```python
body = {
    "name": resolved_name,
    "programText": normalized_program_text,
    "rules": [
        {
            "severity": rule["severity"],
            "detectLabel": rule["detect_label"],
            "notifications": rule.get("notifications", []),
            "disabled": rule["disabled"] if "disabled" in rule else False,
        }
        for rule in rules
    ],
    "description": f"Created by splunk-detector-publish from {hcl_label}",
    "tags": ["obstudio"],
}
```

Never send raw HCL `program_text`, an unresolved `${var.*}`, or snake_case
`detect_label`. Preserve explicit `disabled = true` and `disabled = false` from
each Terraform rule; default to `false` only when `disabled` is absent, and stop
if a present value cannot be resolved to a boolean. Never update/delete a
detector or POST a COVERED/UNCERTAIN row. Keep writes sequential so each response
is attributable.

Apply the shared status contract:

- POST 200/201: record returned ID, name, and detector deep link.
- POST 409/duplicate: GET the existing detector, reuse its ID, and record
  COVERED.
- POST 400: distinguish camelCase wire-field failure from SignalFlow
  normalization;
  never blindly retry the same request.
- POST 401/403 stops the mutation set without retry or further POSTs.
- other failure: record the detector and exact error; continue only with an
  independent remaining confirmed GAP when the shared API contract permits it.

## Ledger And Final Response

Write or overwrite `.observe/detector-sync.md` after every live run: success,
partial failure, zero-gap all-COVERED no-op, or unresolved UNCERTAIN result. Use
the shared ledger template and include summary counts plus one row per local
spec with metric, final status, detector ID/link when known, and a concrete
Reason. Add AutoDetect advisories without treating them as verdicts. Never store
the token or auth header.

The response reports already-covered, created, failed, and uncertain counts;
the ledger path; every failed operation; and the exact next action. A rerun
always fetches and reclassifies current live state—ledger verdicts are history,
not authorization or proof.
