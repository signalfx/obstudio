# splunk-configure Requirements

## Scope

Read `.observe/otel.md` (produced by `$otel-audit`) and generate Splunk Observability Cloud detector definitions as Terraform files: `.observe/terraform/detectors.tf` and `.observe/terraform/variables.tf`.

## Out of Scope

- No Splunk API JSON output — Terraform is the only output format
- No threshold prompting — defaults are baked in, overridable via Terraform variables
- No `terraform plan`/`apply` execution — the skill generates files only; user applies via `terraform.tfvars`
- No automated pytest evals — covered by a separate feature spec
- No calibration from production data — teams tune thresholds post-deployment

## Decisions

### One detector per classified metric

Each metric from the audit report that matches a classification rule gets its own `signalfx_detector` resource. Users remove detectors they do not need rather than requesting them one by one.

### Classification by metric name pattern

The skill classifies metrics automatically using name patterns — no user input required:

- `*.duration` histograms → latency detector (P99 static threshold, default 1s)
- `*.total` with failure/error/invalid in the name → error detector (sudden change, 3 stddev)
- `*.total` without error keywords → throughput detector (sudden change, 3 stddev)
- Gauge metrics for connections/buffer/lag → saturation detector (static threshold, default 85%)

### Default thresholds

| Category | Condition | Default |
|----------|-----------|---------|
| Latency | P99 static threshold | 1s |
| Error | Sudden change (mean + N stddev) | 3 stddev |
| Throughput | Sudden change (mean + N stddev) | 3 stddev |
| Saturation | Static threshold | 85% |

### Thresholds as Terraform variables

Every threshold is a Terraform variable so teams can override without editing detector logic. Per-detector variables follow the pattern `<detector_name>_threshold`.

### User apply workflow via `.tfvars.example`

The skill generates a `terraform.tfvars.example` alongside the `.tf` files containing the four required variables (`realm`, `api_token`, `service_name`, `notification_channel`). Users copy it to `terraform.tfvars`, fill in credentials, and run `terraform apply -var-file=terraform.tfvars`. This keeps secrets out of version control and gives users a clear path from generation to deployment.

### SignalFlow filtering

All SignalFlow programs filter by service name using `filter('service.name', '${var.service_name}')` (Terraform interpolation embeds the variable value into the SignalFlow string). This scopes detectors to a single service.

## Context

### Prerequisite

`$otel-audit` must have run and produced `.observe/otel.md`. If the file is missing, the skill instructs the user to run `$otel-audit` first.

### Token budget

SKILL.md must stay under 300 lines. Reference files (`terraform-templates.md`, `detector-classification.md`) are loaded only during the generation step to keep context lean.

### Skill patterns

Follows existing skill conventions from `otel-audit` and `otel-instrument`:
- YAML front matter with `name`, `description`, `metadata` (author, version, category)
- Step-by-step workflow in the body
- Output template showing exact file structure
- Chat summary format at the end
- Cross-reference to `$otel-audit` using the exact token
