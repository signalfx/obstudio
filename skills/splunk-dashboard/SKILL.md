---
name: splunk-dashboard
description: >-
  Generate Splunk Observability Cloud dashboard Terraform from canonical OTel
  audit JSON and its approved instrumentation and verification overlays. Groups proven or
  explicitly accepted metrics into dashboard panels and outputs ready-to-apply
  HCL (signalfx_dashboard_group + signalfx_dashboard + per-panel
  signalfx_*_chart resources) plus a sidecar preview model for the local
  Observer. Use when the user types $splunk-dashboard, asks to "generate a dashboard",
  "build a dashboard from the audit", "create charts for my service", or
  "visualize my metrics".
metadata:
  author: otel-studio
  version: 0.1.0
  category: observability
---

# Splunk dashboard

Generate local dashboard Terraform, an Observer preview, and a concise report
from one authoritative audit flow. This skill does not publish live resources;
use `$splunk-dashboard-publish` only after review.

## Workflow

### 1. Validate Canonical Input Before Loading References

Require `.observe/otel-audit.json`, then read
`references/canonical-input-contract.md` completely. Never open or read an audit
Markdown report. Do not load `../references/report-flow-contract.md` as an
up-front dashboard dependency; the local contract is complete. If canonical
audit JSON is absent, stop and ask the user to run `$otel-audit` first.

### 2. Select dashboard-ready metrics

Follow the canonical input contract. Preserve exact service metadata,
metric names, types, sources, stable telemetry item IDs, and direct proof.
Generate panels only for exact verified metrics or explicitly accepted
source-only metrics. Missing GenAI readiness signals are instrumentation
prerequisites, not invented panels. Put every exclusion and its concrete next
step in `Skipped Metrics`.

If the audit has no metrics and no GenAI readiness section, stop: tell the user
to review `.observe/otel.html`, approve applicable findings, run
`$otel-instrument`, and then run `$otel-verify`.

### 3. Classify and generate

Read these two references completely:

- `references/dashboard-classification.md` for deterministic RED, saturation,
  GenAI, exclusion, and 12-column placement rules.
- `references/dashboard-templates.md` for HCL resource shapes, standard
  SignalFlow, and chart-type mappings.

The templates cover normal RED and saturation charts. Do not load the longer
`../references/signalflow-patterns.md` unless a proven metric needs a query
shape absent from the dashboard templates. Do not load
`../references/terraform-normalization.md` unless a nonstandard heredoc or an
unresolved `${var.*}` remains; normally resolve variables from tfvars/defaults
and dedent `<<-` heredocs directly.

Write exactly:

- `.observe/terraform/dashboards.tf`: one or more
  `signalfx_dashboard_group` -> `signalfx_dashboard` -> per-panel
  `signalfx_*_chart` resources.
- `.observe/terraform/variables.tf`: `realm`, `service_name`, and `api_token`;
  `api_token` must contain `sensitive = true` and never a real token.
- `.observe/terraform/terraform.tfvars.example`: empty realm/token and the
  audited service name.
- `.observe/dashboards.preview.json`: the fully resolved Observer preview.
- `.observe/dashboards.md`: the human-readable companion report.

For every chart, keep one exact provenance ID across the HCL
`# telemetry-item:` comment, preview `telemetryItemId`, and report:

- `OTEL-###.<item>` for an implemented, directly verified metric.
- `SOURCE-METRIC.<exact-metric-name>` only for an explicitly accepted existing
  metric. Never invent an `OTEL-###` ID.

The preview has integer `schemaVersion: 1` and the hierarchy
`groups[].dashboards[].charts[]`. Every chart requires `label`, `title`,
`chartType`, `telemetryItemId`, `productAction`, `programText` or text, and
integer layout `column,row,width,height`. Allowed `chartType` values are
`time_series | single_value | list | heatmap | text | table`. Its resolved query,
type, hierarchy, and 12-column grid placement must match HCL exactly. Include
unused groups and empty dashboards; never claim the preview rendered or
returned live values without direct evidence.

Keep the report literal too: copy each panel label without paraphrasing, make
its Product action / rationale cell exactly equal the preview chart's
`productAction`, and enumerate the exact `OTEL-###.<item>` or
`SOURCE-METRIC.<exact-metric-name>` IDs in mapping evidence. These are parity
fields, not prose summaries. The Panels table header is exactly:

```markdown
| # | Telemetry Item ID | Panel | Metric | Chart Type | Grid (col,row,w,h) | Product action / rationale |
```

For `Metric`, list the unique `data(...)` metric names in query order separated
by `, `; use `N/A` for text-only charts. The `Preview And Validation` table must
use these exact row labels:

- `Verified metric item mapping`
- `Terraform ↔ preview parity`
- `Observer render`
- `Live value sanity`
- `Publish/apply`

Set overall `Result: Pass` only when the first four checks pass; `Publish/apply`
is a handoff status and may remain `Not run`. Use `Partial` when deterministic
mapping/parity passes but local render or live values were not proven. Use
`Blocked` when meaningful generation or deterministic validation cannot run.

### 4. Validate once, then repair named errors

Run the dependency-free `python3 scripts/validate_dashboard_output.py` command
from the canonical input contract with `--terraform`, `--preview`, `--report`,
and its proof arguments.

Treat the validator as an opaque executable; do not inspect its source or tests
during normal generation. Repair only the artifact or binding named by compact
JSON errors, then rerun. Do not create a synthetic audit or weaken a claim to
make validation pass. A zero exit proves mapping and artifact parity, not
Observer rendering, live values, or publication.

### 5. Hand off

Summarize the dashboards and panels, five written outputs, exact validation
result, and remaining unproven checks. Next steps are local Observer preview,
then `$splunk-dashboard-publish` or reviewed `terraform apply`; never apply or
publish as part of this skill.

## Stop conditions

- Invalid/stale canonical JSON or digest binding: stop; never switch audit
  formats or merge states.
- Newly implemented metric without direct item proof or explicit source-only
  acceptance: skip it.
- Missing service filter, unresolved variable, invalid/overlapping grid,
  missing provenance/product action, report-preview drift, or non-sensitive
  token variable: repair the generated artifact and revalidate.
