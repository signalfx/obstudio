# Readiness and Dashboard Report Addendum

Read only when the output contains incident/GenAI readiness, alert coverage,
dashboards, or prerequisites without detector-ready metrics.

## Prerequisites and coverage

Under `Instrumentation Prerequisites`, preserve one row per actionable gap:
area, current status, exact missing signal, owner, why no detector was
generated, and next step. Never collapse different owners.

For incomplete readiness, add `## Alert Coverage Matrix` and distinguish
generated, existing, desired-state, missing, and blocked coverage for:

- app/primary-workflow availability and customer impact;
- API latency/errors and critical business workflows;
- dependency health and auth/domain-routing/edge;
- ingest freshness/drops and queue/backpressure;
- capacity saturation and multi-region blast radius; and
- release/config/canary correlation.

Missed, flapping, auto-resolved, and no-data alert evidence describes detector
reliability; it does not prove app telemetry or live detector coverage.

## GenAI surfaces

Consume every independently actionable surface and use these display
categories without merging them:

- GenAI Latency
- GenAI Token Pressure
- GenAI Provider
- GenAI Tool
- GenAI Model Config
- GenAI Workflow Fanout
- GenAI Retrieval
- GenAI Memory Context
- GenAI Evaluation Quality
- GenAI Content Governance
- GenAI Cost

For missing/partial areas add `## GenAI Instrumentation Prerequisites` with:

```markdown
| Surface | Audit Status | Missing Signal | Why No Detector Was Generated | Next Step |
|---|---|---|---|---|
```

Missing or partial GenAI areas become instrumentation prerequisites. Do not
merge distinct readiness surfaces or emit placeholders.

## Dashboard report

When dashboards exist, `.observe/dashboards.md` is a subordinate inventory that
inherits the configure result. Include reader summary/flow, dashboard/group
variables and filters, canonical `## Panels` provenance, exact metric/unit/
dimensions/SignalFlow purpose/layout, skipped panels/prerequisites, and
`## Preview And Validation` with separate parity, render, live-value, and
publish states. Do not duplicate the configure proof ledger or calculate a
second verdict. The exact preview/report parity fields remain owned by
`dashboard-output-contract.md`.

## Prerequisites-only output

When the audit has no detector-ready metrics but has gaps/readiness rows, still
write `.observe/detectors.md` and `.observe/splunk-configure-verify.md`. State
that no Terraform detector was generated, preserve the actionable readiness
matrix, and point to `$otel-instrument`/`$otel-verify`. If neither metrics nor
actionable readiness exists, stop before output generation and explain that the
audit has no usable configure input.
