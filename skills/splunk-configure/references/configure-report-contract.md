# Detector Report Contract

Read after detector resources and skipped/prerequisite sets are final. This
core owns detector-only reports and the final response.

## One status authority

`.observe/splunk-configure-verify.md` is authoritative; every other configure
report inherits its exact `Result`:

- `Pass`: local checks passed and an authenticated detector-capable Terraform
  plan accepted every SignalFlow program;
- `Partial`: useful local output passed, but authenticated compile or another
  required proof was not run;
- `Fail`: an executed validation/compile failed;
- `Blocked`: a prerequisite prevents meaningful output or validation.

A `Pass` cannot contain substantive `Not Yet Proven` content. Skipped checks
never become passes.

## `.observe/detectors.md`

Use this reader-first order:

```markdown
# Detectors Report: <service>
**Result:** Pass | Partial | Fail | Blocked
**Language:** <language> | **Framework:** <framework> | **Date:** <YYYY-MM-DD>
**Source audit:** <path/mode>
**Selection:** <path/scope>
**Source instrumentation:** <path or not found>
**Source verification:** <path or not found>
**Output:** `.observe/terraform/`

## Executive Summary
## Flow
## Summary
## <Non-empty Category> Detectors
## Skipped Metrics
## Instrumentation Prerequisites
## Classification Rules Applied
## Terraform Output
## Next Steps
```

The summary counts each generated category. Each detector row names resource
label, exact metric, condition, severity, bounded dimensions, rationale, proof
source, and threshold/baseline owner. Omit empty category tables.

`Skipped Metrics` labels each item missing, unverified, unsafe, duplicate,
partial, owner-mapped, or uncategorized and gives one exact next action.
`Instrumentation Prerequisites` preserves independently actionable owners and
missing signals. Report every route merge and why no standalone resource was
generated.

If incident/GenAI readiness, an alert-coverage matrix, dashboards, or a
prerequisites-only run is present, also read `readiness-report-contract.md`.

## `.observe/splunk-configure-verify.md`

Always write it when configure produces reports or Terraform, with exactly:

```markdown
# Splunk Configure Verification: <service>
**Result:** Pass | Partial | Fail | Blocked
**Source:** `.observe/detectors.md`
**Terraform:** `.observe/terraform/`

## Executive Summary
## What Was Added
## Tested And Working
## Not Yet Proven
## Validation Notes
## Next Steps
```

`What Was Added` has one row per detector:

```markdown
| Resource Label | Metric | Detect Condition | Severity |
|---|---|---|---|
```

`Tested And Working` uses `| Check | Result | Evidence |`. Record preflight,
the bundled validator, Terraform fmt/init/validate, and authenticated plan as
separate executed checks. Claim authenticated SignalFlow compile only when
`terraform plan -refresh=false -input=false` actually accepted every generated
detector through `/v2/detector/validate`. Local shape or `terraform validate`
does not prove SignalFlow compile. Put unavailable required proof in `Not Yet
Proven`; evidence names the command/artifact and observed result.

```markdown
| Authenticated detector SignalFlow compile | Pass | Authenticated plan accepted all <N> generated detectors through `/v2/detector/validate`. |
```

For prerequisites-only output, say no detector was generated and why; do not
run a file validator against intentionally absent Terraform.

## Final response

Lead with category/count, exact configure result, output files/path, important
route merges and skipped/prerequisite counts, validation levels actually
passed, and one current next action. Hand reviewed detector output to
`$splunk-detector-publish`; mention `$splunk-dashboard-publish` only when a
dashboard exists. Do not narrate internal generation steps.
