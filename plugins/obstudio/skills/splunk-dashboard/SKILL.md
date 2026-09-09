---
name: splunk-dashboard
description: >-
  Generate Splunk Observability Cloud dashboard Terraform and a local Observer
  preview from .observe/otel-audit.json. Use for $splunk-dashboard, "generate a dashboard",
  "build a dashboard from an audit", "create charts for my service", or
  "visualize my metrics". Use $splunk-configure for detectors and
  $splunk-dashboard-publish for live publishing.
metadata:
  author: otel-studio
  version: 0.1.0
  category: observability
---

# Dashboard -- Splunk O11y Dashboard Terraform from Audit Report

Generate local dashboard artifacts from canonical audit evidence. This skill is
generation-only: write under `.observe/`, do not call a network service, do not
run Terraform, and do not publish. Use `$splunk-configure` for detectors and
`$splunk-dashboard-publish` for live dashboard writes.

Resolve paths in this entrypoint from the skill directory. Inside a loaded
reference, resolve relative paths from that reference's directory. Never use
the service cwd as the base or probe alternate skill copies.

## 1. Gate on the canonical audit before loading references

The first skill action after reading this entrypoint is to locate and parse
`.observe/otel-audit.json` in the project root. Do not copy or replace the audit,
create output directories, or load any reference before this parse. If an outer
test harness explicitly stages a fixture audit, treat that copy as pre-skill
setup; once staged, parse the canonical path before continuing.

Confirm that the file is valid JSON, extract service name, language, framework,
and `current_instrumentation.metrics`, and select the mode: standard dashboards,
or standard plus GenAI when source-backed GenAI metrics exist. If the file is
missing, make no files and stop with:

> No audit report found at `.observe/otel-audit.json`. Please run `$otel-audit`
> first to generate the observability coverage report.

Chart only source-backed existing metrics. Treat findings,
`expected_telemetry`, and missing GenAI readiness signals as instrumentation
prerequisites, never as panels. Existing GenAI metrics may form their own group.

If there are no source-backed existing metrics or explicitly proven downstream
metrics, make no dashboard files and stop with:

> The audit report contains no metrics. Dashboards require metric data. Run
> `$otel-instrument` to add instrumentation, then re-run `$otel-audit`.

## Reference routing after the gate

Only after confirming the audited service, non-empty metric inventory, and mode,
read each selected reference once:

1. Load `references/dashboard-classification.md` to classify source-backed
   metrics and place panels.
2. Load `references/dashboard-templates.md` before generating the three-level
   Terraform and chart SignalFlow.
3. Load `references/artifact-contract.md` before writing the variables, preview,
   report, and final handoff.
4. The local templates cover ordinary RED, saturation, and GenAI panels. Load
   `../references/signalflow-patterns.md` only for a route-group histogram or
   another advanced SignalFlow shape not covered locally. Load
   `../references/terraform-normalization.md` only when resolving variables
   beyond the standard `service_name` interpolation. Do not load publishing or
   detector references for an ordinary dashboard generation.

## 2. Classify panels

Load `references/dashboard-classification.md`. Produce the overview KPI row and
the supported latency, error, throughput, saturation, and evidenced GenAI panels.
Record every skipped metric and its reason. Never invent a metric.

## 3. Generate all artifacts

Load `references/dashboard-templates.md` and
`references/artifact-contract.md`, then create:

- `.observe/terraform/dashboards.tf`: at least one
  `signalfx_dashboard_group`, a referenced `signalfx_dashboard`, and one
  `signalfx_<type>_chart` resource per panel. Each dashboard `chart {}` block
  references its `chart_id` and supplies a non-overflowing 12-column grid
  placement. Sanitize HCL resource labels; preserve metric names in queries.
- `.observe/terraform/variables.tf`: `realm`, `service_name`, and `api_token`
  with `sensitive = true`. Never embed, log, report, or commit a real token.
- `.observe/terraform/terraform.tfvars.example`: empty realm/token values and
  the audited service name.
- `.observe/dashboards.preview.json`: valid JSON with `schemaVersion: 1` and the
  `groups -> dashboards -> charts` tree. Allowed `chartType` values are
  `time_series | single_value | list | heatmap | text | table`.
- `.observe/dashboards.md`: panel rationale, grid, skipped metrics, relevant
  GenAI prerequisites, and local preview/publish/apply next steps.

Chart `program_text` must use a service-scoped
`data(...).<aggregation>().publish(...)` visualization stream and must not add a
`detect()`, `when()`, or `threshold()` alert tail. The preview's resolved
`programText`, chart type, and layout must match each Terraform chart exactly.

## 4. Validate locally

Before finishing, verify without network or Terraform execution:

- all five required artifacts exist;
- `dashboards.tf` has the group -> dashboard -> chart hierarchy and every chart
  is referenced exactly once;
- each placement satisfies `0 <= column <= 11`, `1 <= width <= 12`,
  `column + width <= 12`, `row >= 0`, and `height >= 1`, with no overlap;
- `variables.tf` marks `api_token` sensitive and no output contains a real token;
- preview JSON parses, has no unresolved `${var.*}`, and stays in lockstep with
  the Terraform; and
- chart SignalFlow uses the correct aggregation and has no detector tail.

## 5. Hand off

Summarize dashboards and panels, list the five files, and direct the user to the
Observer **Dashboards** tab for local preview. Offer
`$splunk-dashboard-publish` or `terraform apply` as explicit next actions; do not
perform either action in this skill.
