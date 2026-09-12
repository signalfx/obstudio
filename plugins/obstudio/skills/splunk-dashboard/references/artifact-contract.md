# Dashboard Artifact Contract

After metric classification, keep Terraform, Splunk Observability Studio
preview, report, and final response aligned to one panel inventory.

## Contents

- [Terraform files](#terraform-files)
- [Splunk Observability Studio preview](#splunk-observability-studio-preview)
- [Human report](#human-report)
- [Validation and handoff](#validation-and-handoff)

## Terraform files

Write `.observe/terraform/dashboards.tf` using the group, dashboard, chart, and
SignalFlow shapes in `dashboard-templates.md`. A normal service has one overview
group and one RED dashboard; add a separate GenAI group/dashboard only when
source-backed GenAI metrics exist. Every panel is a separate `signalfx_*_chart`
resource referenced exactly once from its dashboard's `chart {}` blocks.

Write `.observe/terraform/variables.tf` with this secret-safe shape:

```hcl
variable "realm" {
  description = "Splunk Observability Cloud realm (e.g. us1, eu0)"
  type        = string
}

variable "api_token" {
  description = "Splunk Observability Cloud API token"
  type        = string
  sensitive   = true
}

variable "service_name" {
  description = "Service name for dashboard naming and chart filters"
  type        = string
  default     = "<audited-service-name>"
}
```

`sensitive = true` is mandatory. Never place a real token in Terraform, the
preview, the report, command output, or source control.

Write `.observe/terraform/terraform.tfvars.example`:

```hcl
realm        = ""   # e.g. us1, eu0, lab0
api_token    = ""   # Splunk O11y API token (org-level, dashboard write)
service_name = "<audited-service-name>"
```

## Splunk Observability Studio preview

Write `.observe/dashboards.preview.json` as JSON, not JSONC:

```json
{
  "schemaVersion": 1,
  "generatedAt": "<RFC3339 timestamp>",
  "groups": [{
    "name": "<service> Overview",
    "description": "RED + saturation dashboard for <service>",
    "dashboards": [{
      "name": "<service> RED",
      "description": "Rate, errors, duration",
      "charts": [{
        "label": "p99_latency",
        "title": "P99 Latency",
        "chartType": "time_series",
        "programText": "A = data('http.server.request.duration', filter=filter('service.name', '<service>')).percentile(pct=99).publish(label='P99 Latency')",
        "text": null,
        "layout": {"column": 0, "row": 0, "width": 6, "height": 3}
      }]
    }]
  }]
}
```

Allowed `chartType` values are `time_series`, `single_value`, `list`, `heatmap`,
`text`, and `table`. For a text panel, set `programText` to `null` and put its
Markdown in `text`. For every other panel, dedent the HCL heredoc and resolve the
standard `${var.service_name}` to the audited service name. If another
`${var.*}` occurs, load `../../references/terraform-normalization.md` and apply
its complete precedence rules. No unresolved interpolation may remain.

The preview is a one-to-one resolved projection of `dashboards.tf`: preserve
each chart's label, type, SignalFlow query, and grid placement. Splunk Observability Studio does
not parse HCL. Each layout must satisfy the 12-column constraints and match the
corresponding dashboard `chart {}` block exactly.

Quote and escape the audited service name safely in every SignalFlow filter. If
it cannot be represented as a safe string literal, stop instead of emitting an
invalid or injectable query.

## Human report

Write `.observe/dashboards.md` with:

1. title, audited service/language/framework/date, input path, and Terraform
   output path;
2. a summary table of dashboard, group, panel count, and chart types;
3. a panel table containing panel, source metric, chart type, grid tuple, and
   classification rationale;
4. a 12-column grid map;
5. every skipped metric with a concrete reason;
6. missing GenAI signals as instrumentation prerequisites when applicable; and
7. next steps to copy the tfvars example, set realm/token, preview in Splunk
   Observability Studio, then explicitly choose `$splunk-dashboard-publish` or
   `terraform apply`.

Never describe a finding or expected signal as a generated panel. Never expose
a token. Do not claim that Terraform was initialized/applied or that Splunk was
contacted.

## Validation and handoff

Validate all five artifacts locally. Parse the preview as JSON; compare its
panels and layouts against the Terraform; check grid bounds/overlap, chart
references, `sensitive = true`, unresolved variables, and detector-only
SignalFlow tails. Do not call a network endpoint and do not run Terraform.

The final response names generated dashboards/panels and all five artifact
paths, then points to Splunk Observability Studio's **Dashboards** tab. Present publishing or
`terraform apply` only as user-controlled follow-up actions.
