# splunk-configure Validation

## Definition of Done

All of the following must be true before this branch is merged.

Each validation step must be run in a **new, separate agent context** that loads
the skill solely by reading `skills/splunk-configure/SKILL.md` and following its
workflow — no prior conversation context should carry over.

### 1. Skill loads

A new agent reads `skills/splunk-configure/SKILL.md` and confirms it can parse the
front matter and workflow without errors.

- [x] Skill file exists at `skills/splunk-configure/SKILL.md` with valid front matter
- [x] Symlink at `.agents/skills/splunk-configure` resolves correctly
- [x] A separate agent loaded skill, parsed workflow, and executed all 5 steps successfully

### 2. Missing report handling

A new agent reads the skill, then runs it against a repo with no `.observe/otel.md`
(e.g., `evals/go/chi-basic`).

The agent's response must mention `$otel-audit` as the prerequisite and must not generate any Terraform files.

- [x] Verified — agent responded with prescribed message mentioning `$otel-audit`; no `.observe/terraform/` created

### 3. Terraform generation

A new agent reads the skill, then runs it against `../go-agent-management`
(which has a valid `.observe/otel.md`).

Confirm the following files are created:

```
.observe/terraform/detectors.tf
.observe/terraform/variables.tf
.observe/terraform/terraform.tfvars.example
```

`detectors.tf` must contain one or more `resource "signalfx_detector"` blocks with inline `program_text` using SignalFlow.

`variables.tf` must contain `variable` blocks for at least:
- `realm`
- `api_token`
- `service_name`
- `notification_channel`
- Per-detector threshold overrides

`terraform.tfvars.example` must contain:
- `realm`, `api_token`, `service_name`, `notification_channel` placeholders
- No per-detector threshold variables (those have defaults)
- No actual credential values

- [x] Verified — 26 `signalfx_detector` resources; `variables.tf` has all required blocks; `terraform.tfvars.example` has only 4 placeholders

### 4. Detector classification

Inspect `detectors.tf` and confirm the classification rules were applied:

- Duration histogram metrics (e.g., `http.server.request.duration`) have `percentile(pct=99)` in their SignalFlow program
- Error counter metrics (e.g., `uam.server.auth.failures.total`) use `against_recent` or sudden-change logic in their SignalFlow program
- Gauge metrics (e.g., `uam.server.clients.heartbeat.buffer.lag`) use static threshold comparison (e.g., `detect(when(A > var.threshold))`)

- [x] Verified — latency (8), error (3), saturation (7), throughput (8) correctly classified per rules

### 5. No secrets

Inspect both `detectors.tf` and `variables.tf`. Neither file may contain:

- Hardcoded API tokens or bearer strings as assigned values
- Hardcoded realm strings as configured values in provider blocks or variable defaults (realm examples in description strings and comments like `# e.g. us1, eu0` are acceptable documentation)
- Hardcoded endpoint URLs as assigned values

All such values must be referenced via `var.*` or `${var.*}` expressions in configuration.

- [x] Verified — only `var.api_token`, `var.realm`, `var.service_name` references; no hardcoded values

### 6. Chat summary

The agent's chat response after generation must include:

- Count of detectors generated per category (latency, error, saturation, throughput)
- The output path `.observe/terraform/`

- [x] Verified — summary included category counts (8/3/7/8) and output path with next-steps workflow

### 7. Terraform validate

A new agent reads the skill, runs it against `../go-agent-management`, then
after generation runs:

```bash
cd ../go-agent-management/.observe/terraform
terraform init
terraform validate
```

`terraform validate` must pass without errors (provider plugin downloads automatically on init).

- [x] Verified — `terraform validate` passed (`Success! The configuration is valid.`)

### 8. Template linting

Verify that all HCL code blocks in `skills/splunk-configure/references/terraform-templates.md`
produce valid Terraform when placeholders are substituted with concrete values.

Process:
1. Extract each HCL code block from the templates file
2. Substitute placeholders (`<metric_id>` → `test_metric`, `<metric_name>` → `test.metric.duration`)
3. Combine into a single `.tf` file with required variable declarations
4. Run `terraform validate` on the rendered output

Additionally, lint for common mistakes:
- No bare `var.*` references inside `<<-EOF` heredocs (must use `${var.*}`)
- No unused imports (e.g., `from signalfx.detectors.against_recent import against_recent` without `against_recent.*` usage)
- All `${var.*}` references must have a corresponding `variable` block

- [x] Verified — rendered all 4 templates with concrete placeholders; `terraform validate` passed; no bare `var.*` in heredocs; no unused imports

### 9. Template unit tests

Render each template category with a sample metric and verify correctness:

| Category | Sample metric | Expected pattern in `program_text` |
|----------|--------------|-------------------------------------|
| Latency | `http.server.request.duration` | `percentile(pct=99)` + `threshold(${var.latency_...})` |
| Error | `auth.failures.total` | `against_recent.detector_mean_std` + `fire_num_stddev=${var.error_...}` |
| Saturation | `pool.connections.usage` | `threshold(${var.saturation_...})` |
| Throughput | `requests.total` | `against_recent.detector_mean_std` + `fire_num_stddev=${var.throughput_...}` |

Verify for each:
- `filter('service.name', '${var.service_name}')` is present (proper interpolation)
- Threshold/stddev values use `${var.*}` syntax (not bare `var.*`)
- Latency template does NOT import `against_recent`
- Error and Throughput templates DO import `against_recent`

- [x] Verified — all 4 categories pass: correct `${var.*}` interpolation, correct imports per category, `filter('service.name', '${var.service_name}')` in all 4 templates

### 10. Terraform plan/apply (live Splunk org)

A new agent reads the skill, runs it against `../go-agent-management`, then
runs `terraform plan` and `terraform apply` against a live Splunk Observability
Cloud org.

Requires credentials (ask the user before running):
- `realm` — Splunk O11y realm → **`lab1`**
- `api_token` — Splunk O11y API token with detector write permissions → **provided**
- `notification_channel` — alert target → **`Email,noop@test.local`** (placeholder for testing)

- [x] Verified — `terraform plan` succeeded (21 to add); `terraform apply` completed (21 detectors created in lab1 org)

### 11. README and repo wiring

Confirm `README.md` and `AGENTS.md` both reference `$splunk-configure`:

- `README.md` Core Skills table includes `$splunk-configure` row
- `README.md` Using The Skills section mentions `$splunk-configure`
- `README.md` Repository Layout lists `splunk-configure/` under `skills/`
- `AGENTS.md` Available Skills table includes `$splunk-configure` row

- [x] Verified — all four references confirmed in README.md and AGENTS.md

## Not Required

- Automated eval suite (separate feature spec)
- Cross-language fixture testing
