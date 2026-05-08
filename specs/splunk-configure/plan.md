# splunk-configure Plan

## Group 1 — Skill Structure

- [x] 1. Create `skills/splunk-configure/SKILL.md` with front matter (`name: splunk-configure`, `version: 0.1.0`, `author: otel-studio`, `category: observability`)
- [x] 2. Define the 5-step workflow in SKILL.md:
   - Step 1: Locate `.observe/otel.md`; if missing, instruct the user to run `$otel-audit` first
   - Step 2: Parse the Metrics table (name, source, type) and service metadata (service name, language, framework) from the report header
   - Step 3: Classify each metric into a detector category by name pattern (see `references/detector-classification.md`)
   - Step 4: Generate `.observe/terraform/detectors.tf` and `.observe/terraform/variables.tf` using the templates in `references/terraform-templates.md`
   - Step 5: Summarize what was generated in chat
- [x] 3. Add the output template for `.observe/terraform/detectors.tf` showing the expected `signalfx_detector` resource shape with inline SignalFlow `program_text`
- [x] 4. Add the output template for `.observe/terraform/variables.tf` showing variable blocks for `realm`, `api_token`, `service_name`, `notification_channel`, and per-detector threshold overrides
- [x] 5. Add the chat summary format: detector count per category (latency, error, saturation, throughput) and the output path `.observe/terraform/`
- [x] 5b. Generate `.observe/terraform/terraform.tfvars.example` with the four required variables for user to copy and fill in

## Group 2 — Reference Files

- [x] 6. Create `skills/splunk-configure/references/terraform-templates.md` with SignalFlow + HCL templates for four detector categories:
   - Latency: `signalfx_detector` with `data().percentile(pct=99)` and static threshold (default 1s)
   - Error: `signalfx_detector` with `against_recent.detector_mean_std` for sudden-change detection (default 3 stddev)
   - Saturation: `signalfx_detector` with `data()` and static threshold comparison (default 85%)
   - Throughput: `signalfx_detector` with `against_recent.detector_mean_std` for sudden-change detection (default 3 stddev)
- [x] 7. Create `skills/splunk-configure/references/detector-classification.md` with classification rules:
   - `*.duration` histograms → latency detector
   - `*.total` with failure/error/invalid in name → error detector
   - `*.total` without error keywords → throughput detector
   - Gauge metrics for connections/buffer/lag → saturation detector
   - Skip auto-instrumented library metrics (e.g. `redisotel`, `otelhttp`) that duplicate custom metrics

## Group 3 — Repo Wiring

- [x] 8. Add symlink `.agents/skills/splunk-configure -> ../../skills/splunk-configure`
- [x] 9. Update `AGENTS.md` Available Skills table with a `$splunk-configure` row: "Generate Splunk O11y detector Terraform from audit report"
- [x] 10. Stage a copy of the skill in `observer/cmd/obstudio/_skills/splunk-configure/` for CLI embedding

## Group 4 — Examples

- [x] 15. Add a "Detect -- Generate Alerts" section to `docs/examples.md` with prompts such as:
   - Generate detectors from audit: "Generate Splunk detectors from my audit report"
   - Targeted category: "Create latency detectors for this service"
   - Post-instrument workflow: "I just instrumented the service -- now set up alerts"
   - Threshold tuning context: "Generate detectors with a 2s latency threshold"
   - Full pipeline: "Audit this service, then generate detector Terraform"

## Grounding Evidence

Terraform templates and SignalFlow programs are based on the official Splunk Observability Cloud provider documentation:

- [Terraform Provider: splunk-terraform/signalfx](https://registry.terraform.io/providers/splunk-terraform/signalfx/latest/docs) — provider configuration (`realm`, `api_url`, `auth_token`)
- [`signalfx_detector` resource](https://registry.terraform.io/providers/splunk-terraform/signalfx/latest/docs/resources/detector) — `program_text`, `rule` blocks, severity levels, notification routing
- [SignalFlow library: `against_recent`](https://github.com/splunk-terraform/terraform-provider-signalfx/blob/main/docs/resources/detector.md) — sudden-change detection functions used in error/throughput detectors

## Validation

See `specs/splunk-configure/validation.md` for the full definition of done.
