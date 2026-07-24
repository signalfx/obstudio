---
name: splunk-configure
description: >-
  Generate proof-aware Splunk Observability Cloud detector and dashboard
  Terraform from canonical .observe/otel-audit.json plus bound selection,
  instrumentation, and verification overlays. Use for $splunk-configure, detector or
  dashboard generation, alert-coverage audits, MTTD and incident-localization
  improvements, blast-radius views, and GenAI/LLM detector coverage.
---

# Splunk Configure

Generate reviewed local Terraform and reader-facing reports. Do not modify
application code. Do not publish, apply, or contact Splunk unless the user
explicitly requests that separate action.

## Non-negotiable guarantees

- Require canonical JSON and validate its complete digest-bound handoff. Never
  open or read an audit Markdown report.
- Generate a detector or chart only from an exact source-backed metric that is
  proven by its bound verification item, or from an exact source-only metric
  the user explicitly accepted.
- Keep missing, unsafe, unverified, partial closure, and owner-mapped signals in
  `Skipped Metrics`, `Instrumentation Prerequisites`, or the alert coverage
  matrix. Do not generate a detector for a missing or unverified signal.
- Preserve Route-Level De-duplication: one route may have distinct latency,
  error, and throughput detectors reading the smallest emitted metric set, but
  a duplicate counter does not get a second resource merely because its metric
  name differs.
- Keep detector, dashboard, preview, and verification statuses consistent.
- Preserve this handoff:
  `audit -> approve -> instrument -> verify -> configure -> publish`.

## Project-root invariant

Resolve the project root once. Run every command with that directory as its
working directory, and interpret every `.observe/...` path relative to it.
Never prepend the project root again after setting the working directory.

If the user explicitly provides an audit or selection at another fixture path,
copy only those requested input artifacts into the project-root `.observe/`
before preflight. This input staging is not configure output generation.

## Workflow

### 1. Run input preflight first

Run this command before creating `.observe/terraform/`, detector/dashboard
reports, previews, or configure verification output. Do not read
classification, Terraform, dashboard, or report references first:

```bash
python3 <splunk-configure-skill-dir>/scripts/validate_configure_output.py \
  --input-preflight \
  --terraform-dir .observe/terraform
```

The preflight determines the input mode and validates canonical artifact
presence and binding. A source-only acceptance cannot override that incomplete
chain.

If preflight fails, stop without writing configure outputs. Preserve every
input, report the exact error, and direct the user to complete the missing
`$otel-instrument` or `$otel-verify` handoff. Do not delete an overlay, switch
audit formats, or add a source-only override.

After a successful `audit_only` or `canonical` preflight, read
`references/canonical-input-contract.md` completely.

Do not load the shared `../references/report-flow-contract.md`; the local
contracts contain the configure-specific subset.

### 2. Resolve candidate metrics and prerequisites

Use the chosen input contract to produce three internal sets:

1. exact accepted/proven metric items;
2. skipped metrics with a concrete reason and next action;
3. independently actionable instrumentation or owner prerequisites.

When candidate metrics exist, read
`references/detector-classification.md` completely. It is the compact generic
RED core and owns Route-Level De-duplication. Its route table decides whether
either specialized reference is relevant:

- read `references/incident-detector-classification.md` only for an explicit
  incident/readiness mode, readiness evidence, or listed incident marker;
- read `references/genai-detector-classification.md` only for explicit GenAI
  ownership/readiness/context.

Do not load a specialized reference merely because it exists. Loaded GenAI and
incident categories precede generic RED categories. Assign every accepted
resource one category and retain exact route/operation, outcome, unit, and
bounded-dimension evidence.

When no detector-ready metric exists but gaps or readiness rows do, generate
prerequisites-only reader reports, not placeholder Terraform. When neither
metrics nor actionable readiness evidence exists, stop and explain that the
audit contains no usable detector input.

Supported output modes are:

| Mode | Output |
|---|---|
| `generate` | Detector Terraform and, when requested and evidenced, dashboard Terraform |
| `alert-coverage-audit` | Desired-state coverage matrix; never claim live resources were audited without an approved source |
| `impact-classify` | App-down versus degraded workflow/auth/dependency impact |
| `blast-radius` | Workflow, environment, region, dependency, and release/config rollups |

Treat missed, flapping, auto-resolved, and no-data alerts as detector
reliability evidence. Do not ask app instrumentation to emit alert lifecycle
metrics unless the application owns those events.

### 3. Generate local Terraform

Read `references/terraform-templates.md` completely before writing detector
Terraform. It is self-contained for generic RED SignalFlow; do not load the
shared `../references/signalflow-patterns.md` on this path. Read
`references/readiness-detector-templates.md` only when an incident or GenAI
classification reference was loaded.

Always generate, when detector resources exist:

- `.observe/terraform/detectors.tf`
- `.observe/terraform/variables.tf`
- `.observe/terraform/terraform.tfvars.example`
- `.observe/terraform/.gitignore`

Every detector must:

- contain one exact `data('<metric>', ...)` input;
- filter by `service.name` and any source-backed route/outcome dimensions
  required to distinguish the detector;
- aggregate and publish a bounded signal;
- contain real threshold or baseline detection logic and one matching
  `detect_label`;
- use declared variables, including sensitive `api_token` and a provider API
  `realm` that is never reused as a telemetry filter;
- exclude raw prompts/content, secrets, and user/session/request/trace IDs from
  filters and group-bys.

If dashboard resources are requested and supported by accepted metric evidence,
read `references/dashboard-terraform-contract.md` and
`references/dashboard-output-contract.md` completely before creating
`.observe/terraform/dashboards.tf`, `.observe/dashboards.md`, or
`.observe/dashboards.preview.json`. Do not load either reference for a
detector-only run.

### 4. Generate reader reports

Read `references/configure-report-contract.md` completely immediately before
writing reports. It owns detector-only structures and status rules for:

- `.observe/detectors.md`
- `.observe/splunk-configure-verify.md`
- `.observe/dashboards.md` when dashboards exist
- the final chat summary

Read `references/readiness-report-contract.md` only when output includes
incident/GenAI readiness, alert coverage, dashboards, or prerequisites without
detector-ready metrics.

Keep technical ledgers in the generated artifacts. The final response should
lead with detector/dashboard counts, the configure result, the output path,
and the next user action.

### 5. Validate without weakening the checker

Treat bundled validators as opaque deterministic tools. Use the direct paths
above; in a normal run do not run `wc`, broad `find`, `rg --files`, `git
status`, skill-cache inventories, or output-directory inventories. Do not
re-read already loaded references. Run only the documented validation CLI. Do
not inspect validator source or tests; do not search installed skill caches,
substitute another installed version, create validator symlinks, or
monkeypatch/import validator internals. If the command fails unexpectedly,
report its exact error as a skill/package defect.

For generated detector Terraform, run:

```bash
python3 <splunk-configure-skill-dir>/scripts/validate_configure_output.py \
  --terraform-dir .observe/terraform \
  --detectors-report .observe/detectors.md \
  --configure-verify-report .observe/splunk-configure-verify.md
```

In canonical mode, the validator discovers the canonical artifacts relative to
`.observe/terraform`. Pass explicit `--audit-json`, `--selection-json`,
`--instrumentation-json`, or `--verification-json` only when the authoritative
files are intentionally elsewhere.

For every explicitly accepted pre-existing dashboard item, use
`SOURCE-METRIC.<exact-metric-name>` and append the same value with
`--allow-source-only-item`. Implemented items retain their exact
`OTEL-###.<item>` IDs.

When dashboard Terraform exists, the configure validator automatically loads
and delegates exact projection checks to
`validate_dashboard_output.py`. Run that dashboard validator directly only to
isolate a reported dashboard failure.

Finalize Terraform and both reports before validation, including the intended
bundled-validation row. Run the documented validator once. If it passes, stop
validation: do not run it again, inventory outputs, or rewrite proof text. Only
a failure permits repairing generated artifacts and re-running the same
validator; repair artifacts, never the validator.

When the user allows Terraform execution and Terraform is available, also run
`fmt`, backend-disabled `init`, and `validate`. An authenticated
`terraform plan -refresh=false -input=false` is the authoritative detector
SignalFlow compile check, but run it only with already-approved real
credentials and never apply. Without that plan, a locally valid configure run
is `Partial`, not `Pass`.

### 6. Hand off reviewed output

Use `$splunk-detector-publish` to diff and publish confirmed detector gaps and
`$splunk-dashboard-publish` for confirmed dashboard gaps. Terraform apply is an
alternative only when the user chooses Terraform ownership. Configure itself
does not publish.

## Warning signs

- Preflight did not run from the resolved project root.
- Audit HTML or a reader report influenced canonical scope.
- A partial canonical overlay chain was treated as source-only.
- A detector references an absent or merely expected metric.
- Two resources have the same metric, aggregation, and attribute filters.
- A dashboard sidecar is described as rendered, live, or value-validated
  without separate evidence.
- A validator was read, replaced, patched, or bypassed instead of executed.
