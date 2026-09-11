---
name: splunk-detector-publish
description: >-
  Compare .observe/terraform/detectors.tf with live Splunk Observability Cloud
  detectors, classify COVERED/GAP/UNCERTAIN results, confirm, and create only
  GAPs with an idempotent ledger. Use for $splunk-detector-publish, "sync
  detectors", "check which detectors are missing", "create missing monitors",
  or "push detector gaps to Splunk". Requires existing $splunk-configure output.
metadata:
  author: otel-studio
  version: 0.3.2
  category: observability
---

# Detector Publish -- Splunk O11y Detector Gap Analysis And Create

Compare `$splunk-configure` Terraform with live Splunk Observability Cloud and
create only explicitly confirmed detector gaps. If
`.observe/terraform/detectors.tf` is absent, stop and ask the user to run
`$splunk-configure` first.

Resolve paths in this entrypoint from the skill directory. Inside a loaded
reference, resolve relative paths from that reference's directory. Read only
the routed references; do not scan alternate copies or load every reference.

## Always-Loaded Safety Contract

- Local parsing, offline planning, and live comparison are read-only. Before
  **every remote mutation set**, show the complete current diff, ordered GAP
  operations, resolved realm and realm source, then require explicit current
  yes/no confirmation. Credentials, a dry-run answer, a prior ledger, or an
  earlier confirmation are not consent.
- A mutation set is authorized only for the exact fresh diff shown. Every live
  run fetches and reclassifies current state; never infer state from a prior
  ledger. If local specs, normalized payloads, realm, or live results change
  after confirmation, discard it, re-fetch, reclassify, show the new diff, and
  confirm again.
- Create only rows currently classified `GAP` and included in that confirmation.
  Skip `COVERED`; never create `UNCERTAIN`. This skill never updates or deletes
  detectors. A missing or incomplete live inventory proves no GAP: classify
  every affected local spec `UNCERTAIN` and stop before mutation.
- Live auth uses `SPLUNK_ACCESS_TOKEN` from the environment as `X-SF-Token`.
  Never echo, log, print, persist, or place it in prompt/report context. Never
  write it to `.observe/detector-sync.md` or a Terraform example. Resolve the
  realm from non-empty `SPLUNK_REALM` first, then the connected Splunk Observability Studio's
  realm-only lookup; Splunk Observability Studio is never a token source. Missing live token or
  realm is a blocker, not an invitation to guess.
- Offline/no-network/placeholder-credential mode never reads environment
  credentials and never calls the Splunk API. Its verdicts are `UNCERTAIN`, not
  provisional live GAPs. Its informational diff or answer cannot authorize a
  later write; a later online run must fetch, classify, show, and confirm again.
- Live pagination skips only HTTP 500 pages. Never swallow 401, 403, parse,
  transport, JSON, or other failures; an incomplete fetch cannot become an
  empty successful list. Continuous 500s are a blocker. A successful empty list
  may yield GAPs.
- Mutations are sequential. POST 200/201 records the returned ID; 409/duplicate
  requires a GET and reuse of the existing ID as COVERED; HTTP 400 requires
  field-casing versus SignalFlow-normalization diagnosis; 401/403 stops without
  retry; other per-detector failures are recorded and reported.
- Every verdict and ledger row has a concrete, non-empty `Reason` naming the
  metric, resolved `service.name` (or equivalent `sf_service`) filter, and live
  comparison result. `detectorOrigin == "AutoDetect"` is advisory only and can
  never make a service-specific local spec COVERED.
- Normalize before comparison or any planned/live POST. HCL `program_text` maps
  to REST `programText`, `detect_label` maps to `detectLabel`, and every create
  body includes the literal ownership marker `"tags": ["obstudio"]`.

## Reference Router

| Condition | Read | Authority |
|---|---|---|
| Offline/no-network, placeholder credentials, preview, or dry-run-only | `references/offline-plan.md` | Local parse, normalized planned payloads/order, UNCERTAIN diff, offline stop |
| Any `program_text` is parsed | `../references/terraform-normalization.md` | `<<-EOF` dedent, every `${var.*}` resolution, HTTP 400 prevention |
| Live comparison or mutation | `references/live-publish.md` | Fresh fetch, structural classification, confirmation, sequential create, ledger |
| Live API access | `../references/splunk-api.md` (routed by live publish) | Auth, realm, skip-on-500 pagination, response/error handling |
| Live classification | `references/coverage-model.md` (routed by live publish) | Detector match, AutoDetect advisory, idempotency |
| Ledger will be written | `../references/ledger-template.md` (routed by live publish) | `.observe/detector-sync.md` structure and concrete reasons |

`references/coverage-model.md` incorporates the verdict vocabulary and reason
rules from `../references/coverage-decision-tree.md`; do not load that shared
decision tree separately. Offline mode must not load `references/live-publish.md`,
`references/coverage-model.md`, `../references/splunk-api.md`,
`../references/coverage-decision-tree.md`, or
`../references/ledger-template.md`.

## Process

### 1. Locate, Parse, And Normalize Local Specs

Require `.observe/terraform/detectors.tf`; optionally read
`.observe/detectors.md` for rationale. Parse every `signalfx_detector` resource:

1. HCL label and resolved `name`;
2. raw `program_text`;
3. every rule's `severity`, `detect_label`, and `notifications`;
4. first `data('metric.name', ...)` metric; and
5. resolved `filter('service.name', '...')` value, recognizing `sf_service` as
   the equivalent live dimension.

Read `../references/terraform-normalization.md`. Reproduce `<<-EOF` dedent,
trim blank edges, and resolve every `${var.*}` from `terraform.tfvars`, then
`*.auto.tfvars`, `terraform.tfvars.example`, then `variables.tf` defaults. This
includes threshold, stddev, and window variables, not only service name. Ask
rather than guess if any value is unresolved. Carry the one normalized string
into both comparison and `programText`; unresolved interpolation or leading
indentation causes an HTTP 400 SignalFlow parse failure.

Fail fast on malformed HCL. Avoid repeated full repository inventories: inspect
the named Terraform inputs and only the supporting files required to resolve a
specific field.

### 2. Select Offline Or Live Mode

When the request forbids network, credentials are placeholders, network is
unavailable, or the user asks only for a preview/dry run, read
`references/offline-plan.md`. Do not probe credentials or connectivity. Show
exact normalized programs and planned REST bodies/order, classify every local
spec `UNCERTAIN` because no live comparison occurred, include an AutoDetect
advisory, and stop without remote mutation.

Otherwise, read `references/live-publish.md` before reading credentials or
making the first API call. It routes to the API, coverage, normalization, and
ledger references. Fetch the current detector inventory, classify structurally,
show the diff, obtain confirmation, and create only its confirmed GAPs.

### 3. Show A Complete Diff

For either mode, show one row per local detector with a non-empty Reason:

```markdown
## Detector Publish Diff — <service-name> [offline plan when applicable]

| Local Spec | Metric | Severity | Status | Live Detector | Reason |
|---|---|---|---|---|---|

### AutoDetect Advisory
<advisory rows, or an explicit no-live-inventory/no-advisory statement>

---
N GAPs are eligible for this live mutation set; N UNCERTAIN require review.
Confirm? (yes/no)
```

An offline `Confirm?` is informational only and must say that no answer can
authorize a write. In live mode, list the exact sequential POST order and realm
source. Zero GAPs means no mutation; a live all-COVERED run still writes the
ledger.

### 4. Execute Only A Confirmed Live Mutation Set

After a current live `yes`, follow `references/live-publish.md`. POST only the
confirmed GAP rows to `/v2/detector`, sequentially, with normalized
`programText`, camelCase `detectLabel`, rule severity/notifications, and
`"tags": ["obstudio"]`. Never POST an offline or UNCERTAIN row. If the diff
becomes stale, re-fetch and reconfirm before continuing.

### 5. Ledger And Response

For a live success, partial failure, or all-COVERED no-op, write
`.observe/detector-sync.md` from `../references/ledger-template.md`. Include
summary counts, each local spec, metric, final status, live/created ID and link,
and a concrete Reason. Never persist the token.

Return covered, created, failed, and uncertain counts; the ledger path; every
failure; and the exact next action. Offline responses instead state that no
credentials, network call, ledger-backed live verdict, or remote mutation was
used, and require a new online fetch/diff/confirmation.

## Red Flags

- Missing `detectors.tf`: run `$splunk-configure`.
- Unresolved `${var.*}` or indented SignalFlow: do not compare or POST.
- Missing/incomplete live inventory: UNCERTAIN, never GAP.
- AutoDetect-only overlap: advisory, never COVERED.
- Missing token/realm, 401/403, or continuous 500s: stop with the exact blocker.
- HTTP 400: distinguish REST casing (`programText`, `detectLabel`) from
  unnormalized SignalFlow.
- Changed state or payload after confirmation: re-fetch, re-diff, reconfirm.
