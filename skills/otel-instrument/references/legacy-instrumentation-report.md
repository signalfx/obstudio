# Instrumentation Compatibility Report

Load this reference once, only when writing
`.observe/otel-instrumentation.md`. It owns the compatibility Markdown for both
canonical and legacy instrumentation runs. Canonical machine state and the
human HTML remain owned by `json-approval-handoff.md`.

## Contents

- Reader order
- Signals changed
- Incident-readiness roles
- Audit gap closure
- Validation and verification handoff

## Reader Order

Use this shape:

```markdown
# OTel Instrumentation Report: <service>

**Result:** Pass | Partial | Fail | Blocked
**Source audit:** `.observe/otel-audit.json` | `.observe/otel.md` legacy | not found
**Selected scope:** `.observe/otel-selection.json` | direct no-audit request
**Verification report:** `.observe/otel-verify.md` | not run | blocked
**Detector report:** `.observe/detectors.md` | not requested | blocked

## Executive Summary
## Flow
## Files Changed
## Signals Changed
## Audit Gap Closure
<!-- Include the next section only for a GenAI source audit. -->
## GenAI Readiness Closure
## Validation Gates
## Verification Handoff / Results
## Detector Handoff / Results
## Remaining Gaps
## Next Steps
```

When no audit report exists, still include service/runtime evidence, scoped
implementation changes, validation gates, verification results or handoff, and
explicit remaining gaps. State that the report establishes the implementation
baseline. Do not fabricate a full audit or canonical machine flow.

## Signals Changed

`Signals Changed` is the implementation-change inventory. Include:

| Signal type | Added | Modified | Removed | Product result / next product action | Evidence | Verification status |
|---|---|---|---|---|---|---|
| Traces/spans | exact span names or `None` | exact changes or `None` | exact removals or `None` | waterfall/map/filter result and follow-up | source paths + tests/harnesses | verified/partial/not run/blocked |
| Metrics | exact metric names or `None` | exact changes or `None` | exact removals or `None` | chart/dashboard/detector action | source paths + tests/harnesses | verified/partial/not run/blocked |
| Logs/events | bridge/event names or `None` | exact changes or `None` | exact removals or `None` | query/correlation result and follow-up | source paths + tests/harnesses | verified/partial/not run/blocked |
| Runtime/config | service/exporter/env/startup settings or `None` | exact changes or `None` | exact removals or `None` | service/environment/export diagnostics | startup/config paths | verified/partial/not run/blocked |
| Dependencies | OTel packages or `None` | version/package changes or `None` | removed packages or `None` | enabled runtime behavior | manifest/lockfile paths | verified/partial/not run/blocked |

Do not claim a removal unless the previous report or Git diff proves the signal
or configuration existed and current source proves it was removed. Use `None`
for empty cells. The final response must summarize added, modified, removed, and
unchanged signals by signal type and point to this report.

For canonical scope, treat every instrumentation
`findings[].telemetry_changes[]` row as the durable code-to-product mapping.
Preserve its stable item ID, concrete code/config change, exact source or call
site, signal kind, newly added attributes/dimensions, product view, audit
scenarios, and item-specific follow-up actions. A free-text finding `changes`
list is not item coverage. Preserve audit-authored keys and bounded values
exactly. Every custom metric must name the chart/dashboard or detector action
after proof; every new bounded attribute must name its filter, slice, group-by,
or breakdown. Never auto-publish without the downstream review workflow.

### Incident Readiness Signal Roles

For incident-readiness work, include this nested table even without a source
audit:

| Surface | Exact signal | Role | Detector use / reason | Proof | Remaining owner / prerequisite |
|---|---|---|---|---|---|

Use exactly `MTTD-improving`, `localization-only`,
`provider/platform-owned`, or `uncovered` in `Role`. Write one row per exact
added or proven signal; do not group metric names. Use `None` for `Exact signal`
only when owner-mapping an unavailable prerequisite, and name that owner or
prerequisite in the final column. This is a signal-role inventory, not another
gap ledger; reconcile audited surfaces through `Audit Gap Closure`.

## Audit Gap Closure

This is the reader-facing compatibility reconciliation. Stable IDs and exact
selected scope live in canonical JSON.

| Priority | Gap | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|---|
| required | exact audit `Area` value | concrete code/config change or `No code change` | scenario IDs and test mode | Working / Not working / Not proven / Not configured / Deferred | direct evidence or exact blocker |

Use one row per prioritized audit gap. Mark unselected rows `Deferred` with
`Not in selected otel-selection.json scope`; canonical instrumentation JSON
contains selected rows only. `Not working` requires an executed failed check.
`Not proven` means the required scenario did not run or lacked a prerequisite.
Use `Not configured` when requested implementation is absent and `Deferred`
only for explicit scope, owner, prerequisite, or `manual decision`. Without a
source audit write `No source audit gap table was available.`

For every selected canonical row, project `What changed`, `Tested`, and
`Evidence / reason` exactly from instrumentation JSON `changes`, `tests`, and
`evidence` arrays in source order. After verification, only `Result` comes from
the bound verify row. Do not paraphrase compatibility cells independently.

For a GenAI audit, `GenAI Readiness Closure` is the detailed signal-level
reconciliation and `Audit Gap Closure` remains the prioritized user work queue.
Neither substitutes for the other. Follow the loaded GenAI reference for its
machine closure and rollup.

Derive `**Result:**` from all applicable closure tables. Do not use `Pass` while
an audit row is `Not working`, `Not proven`, or `Not configured`, or a GenAI row
is `Partial`, `Not working`, `Not proven`, or `Not configured`. Use `Partial`
when meaningful proof passed but any such row remains. `Deferred` and
`Owner-mapped` may coexist with `Pass` only when the exact external owner or
explicit scope decision is recorded.

## Validation And Verification Handoff

When a source audit exists, run the bundle-local validator before finalizing:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/validate_gap_closure.py" \
  .observe/otel.md .observe/otel-instrumentation.md \
  --audit-json .observe/otel-audit.json \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json
```

Run the validator before reading its implementation. Use actionable failures
to repair the report or expose a missing audit row. After verification JSON
exists, rerun the same command with both the exact
`--instrumentation-json .observe/otel-instrumentation.json` and
`--verify-json .observe/otel-verify.json`; never infer the implementation
overlay from the verification file's directory. This prevents stale
pre-verification statuses or next-state results.

Maintain `## Verification Handoff / Results` using
`project-runtime-validation.md`. Record the selected runtime, exact local-safe
commands and outcomes, changed source-to-scenario mappings, the `$otel-verify`
result/report path, and blocked prerequisites. This is not proof of emitted
telemetry unless a test, harness, or collector actually observed it.

Use the canonical audit, validated selection, and selected findings' referenced
verification scenarios as the handoff contract. Use Markdown sections only on
the legacy fallback. Do not copy unrelated report sections into audit or
instrumentation reports.
