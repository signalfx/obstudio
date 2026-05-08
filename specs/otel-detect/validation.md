# otel-detect Validation

## Definition of Done

All of the following must be true before this branch is merged.

Each validation step must be run in a **new, separate agent context** that loads
the skill solely by reading `skills/otel-detect/SKILL.md` and following its
workflow — no prior conversation context should carry over.

### 1. Skill loads

A new agent reads `skills/otel-detect/SKILL.md` and confirms it can parse the
front matter and workflow without errors.

- [x] Skill file exists at `skills/otel-detect/SKILL.md` with valid front matter
- [x] Symlink at `.agents/skills/otel-detect` resolves correctly
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

- [x] Verified — 20 `signalfx_detector` resources; `variables.tf` has all required blocks; `terraform.tfvars.example` has only 4 placeholders

### 4. Detector classification

Inspect `detectors.tf` and confirm the classification rules were applied:

- Duration histogram metrics (e.g., `http.server.request.duration`) have `percentile(pct=99)` in their SignalFlow program
- Error counter metrics (e.g., `uam.server.auth.failures.total`) use `against_recent` or sudden-change logic in their SignalFlow program
- Gauge metrics (e.g., `uam.server.clients.heartbeat.buffer.lag`) use static threshold comparison (e.g., `detect(when(A > var.threshold))`)

- [x] Verified — latency (6), error (3), saturation (3), throughput (8) correctly classified per rules

### 5. No secrets

Inspect both `detectors.tf` and `variables.tf`. Neither file may contain:

- Hardcoded API tokens or bearer strings
- Hardcoded realm strings (e.g., `us0`, `us1`, `eu0`)
- Hardcoded endpoint URLs

All such values must be referenced via `var.*` expressions.

- [x] Verified — only `var.api_token`, `var.realm`, `var.service_name` references; no hardcoded values

### 6. Chat summary

The agent's chat response after generation must include:

- Count of detectors generated per category (latency, error, saturation, throughput)
- The output path `.observe/terraform/`

- [x] Verified — summary included category counts (6/3/3/8) and output path with next-steps workflow

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

### 8. Terraform plan/apply (live Splunk org)

A new agent reads the skill, runs it against `../go-agent-management`, then
runs `terraform plan` and `terraform apply` against a live Splunk Observability
Cloud org.

Requires credentials (ask the user before running):
- `realm` — Splunk O11y realm → **`lab0`**
- `api_token` — Splunk O11y API token with detector write permissions → **awaiting**
- `notification_channel` — alert target (e.g. email or Slack webhook) → **awaiting**

**Status:** Blocked — awaiting `api_token` and `notification_channel`

### 9. README and repo wiring

Confirm `README.md` and `AGENTS.md` both reference `$otel-detect`:

- `README.md` Core Skills table includes `$otel-detect` row
- `README.md` Using The Skills section mentions `$otel-detect`
- `README.md` Repository Layout lists `otel-detect/` under `skills/`
- `AGENTS.md` Available Skills table includes `$otel-detect` row

- [x] Verified — all four references confirmed in README.md and AGENTS.md

## Not Required

- Automated eval suite (separate feature spec)
- Cross-language fixture testing
