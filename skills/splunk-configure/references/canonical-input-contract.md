# Canonical Configure Input Contract

Read this file completely only after input preflight reports `audit_only` or
`canonical`.

## Contents

- Authority and binding
- Audit-only source acceptance
- Bound overlay proof
- Readiness and prerequisites
- Stop conditions

## Authority and binding

Use `.observe/otel-audit.json` as the audit authority. Canonical readable HTML
is a human review surface, never input authority. Do not open or read an audit
Markdown report.

The canonical chain is:

1. `.observe/otel-audit.json`
2. `.observe/otel-selection.json`
3. `.observe/otel-instrumentation.json`
4. `.observe/otel-verify.json`

Require every overlay's `audit_id` and `audit_sha256` to match the normalized
audit. Require instrumentation `selection_sha256` to match the exact normalized
selection and verification `instrumentation_sha256` to match the exact
normalized instrumentation. A matching finding list is not sufficient.

If any overlay is stale, malformed, unreadable, non-regular, or only partially
present, stop. Do not switch audit formats, omit the invalid overlay, or repair
provenance in prose.

## Audit-only source acceptance

An audit with no selection, instrumentation, or verification overlays may
authorize an exact pre-existing metric only when both conditions hold:

- the exact name appears in `current_instrumentation.metrics`; and
- the user explicitly accepts that exact metric as source-only for this run.

Pass each accepted name to the validator with
`--allow-source-only-metric <exact-name>`. This records scope acceptance; it
does not claim runtime emission, product visibility, or a successful detector
compile.

Once any downstream overlay exists, audit-only acceptance is unavailable. The
complete bound selection -> instrumentation -> verification chain is required.
A source-only exception cannot fill a missing selected result.

## Bound overlay proof

Read service identity and candidate pre-existing metrics from `meta` and
`current_instrumentation.metrics`. Read telemetry gaps and readiness from
`findings`, `current_instrumentation.incident_readiness`, and
`genai_readiness`.

Use selection `approved_ids` as the only implementation scope. Never infer
approval from priority, report prose, HTML state, or an instrumentation row.
Preserve unselected findings as audit context, not implemented work.

For each selected finding:

1. Read exact added or modified metrics from instrumentation
   `telemetry_changes`, preserving stable item ID, type, name, source, unit,
   required attributes, and product view.
2. Join verification by finding ID and stable telemetry item ID.
3. Treat the metric as proven only when the matching verification
   `item_results` row is `working`, every required mapped scenario has direct
   evidence, and the observed exact name, unit, and required dimensions agree.
4. Do not infer proof from a finding-level status, aggregate count, similarly
   named metric, expected telemetry, or source code alone.

Put a selected metric that is `not_working`, `not_proven`, or
`not_configured` in skipped metrics or prerequisites with its exact next
action. Never silently demote it to audit-only source acceptance.

## Readiness and prerequisites

Consume every telemetry-scoped row in
`current_instrumentation.incident_readiness`. Reconcile each `partial`,
`missing`, or `owner_mapped` row through its matching source finding. Preserve
the human-readable area, exact required signals, owner, evidence, and
detection/localization impact.

Consume every independently actionable `genai_readiness` surface. Keep these
ownership surfaces separate when the audit separates them:

- provider/model
- workflow/agent
- tool/function
- token/context and stream/session
- retrieval and memory/context
- evaluation/data export and content governance
- privacy/cardinality
- model/config and cost ownership

Do not merge distinct readiness surfaces. Missing or partial GenAI areas become
instrumentation prerequisites unless exact equivalent metrics are source-backed
and proven. Missing or partial GenAI areas become instrumentation prerequisites.
generate detectors only for implemented or proven signals. Do not imply complete
coverage while `remaining_signals` is non-empty.

Treat detector reliability evidence such as missed, flapping, auto-resolved,
or no-data alerts as alert-coverage input. Create an application
instrumentation prerequisite only when the missing signal is application-owned.

## Stop conditions

If there are no accepted/proven metrics, continue processing gaps and readiness sections.
When actionable rows exist, create prerequisites-only reports; do not generate detector or dashboard resources.

If the audit contains neither usable metrics nor actionable telemetry
readiness, stop with:

> The audit report contains no detector-ready metrics or telemetry
> prerequisites. Review `.observe/otel.html`, approve applicable findings, run
> `$otel-instrument`, and then run `$otel-verify`.

Do not create placeholder detectors for expected, absent, unsafe, or
owner-mapped signals.
