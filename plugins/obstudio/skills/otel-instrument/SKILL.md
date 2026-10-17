---
name: otel-instrument
description: >-
  Add OpenTelemetry traces, metrics, and local application logs using
  auto-instrumentation and optional custom signals, write separate instrumentation Markdown
  and HTML reports,
  and run verification unless explicitly skipped or blocked. Use when the user
  types $otel-instrument, asks to "add OTel", "add tracing", "add metrics",
  "implement observability", "wire up telemetry", "instrument this service",
  passes selected executable audit finding IDs with --ids, supplies
  .observe/otel-selection.json,
  asks to add a specific custom signal like "add a metric to track queue
  depth", "add a span for payment processing", "track error rate for X", or
  asks to add signals that make incidents faster to detect or localize, or asks
  to instrument GenAI/LLM workflows with OpenTelemetry semantic conventions.
---

# Instrument

Add OpenTelemetry observability to applications using auto-instrumentation,
default local application-log export, and optional custom spans or metrics.

Prefer the application's current runtime shape. If the project already uses Docker/Compose or Kubernetes, fit instrumentation into that path. If the user does not have Docker or does not want Docker, do not introduce containers just for observability; use the host/native runtime patterns.

Before editing application code, read `../references/report-flow-contract.md`
and follow the Instrumentation Contract plus Reader-First Report Order. When
`.observe/otel-audit.json` exists, also read
`./references/json-approval-handoff.md` before editing; it owns canonical
selection, instrumentation JSON, and human HTML. The technical Markdown report contract is defined in `references/stages/report.md`.
On an incremental run, read the existing bound `.observe/otel-verify.json`
before editing or regenerating reports. Carry each selected failed scenario
and its evidence into the repair plan; rerun its actual check after repair
before replacing that failure with a passing result. Older passing probes for
other assertions do not supersede it. `validate-flow` proves artifact shape
and binding, not semantic correctness or successful verification.
When any selected finding uses
`finding_group: splunk-agent-observability`, or the repository contains a
`splunk_ao` dependency/import, also read
`../references/splunk-agent-observability.md` before editing.
For a fresh Python runtime with no existing telemetry instrumentation, or
uncovered functions on an existing Splunk AO producer path, read that reference
and complete its per-function producer decision gate before selecting creators.
An existing OTel/Galileo trace, metric, log or export-only pipeline stays on its
current stack; fill missing GenAI operations with OTel and supported hooks.
Record each native SDK `@log`, justified application-owned function-decorator,
or preserved-producer decision in existing plan/report evidence; a manual
context-manager scope alone does not instrument a fresh function by this gate.
Always read `../references/local-otlp-receiver.md` before choosing exporter
endpoints. Resolve the active local receiver once during instrumentation and
persist standard OTel receiver configuration and supported AO SDK endpoint/auth
configuration in the application/deployment environment; generated
application startup must not query Studio-specific discovery APIs. Normal AO
SDK calls to a configured cloud-compatible endpoint are allowed.


## Credential Safety

When the project uses or introduces env files:

1. **Ensure `.env` is gitignored before writing secrets**: Check `.gitignore` for `.env`. If it is missing, add it. Never allow a `.env` with access tokens to be committed.
2. **Create or update `.env.example` with safe placeholders**: Do this whenever the instrumentation introduces env vars. `.env.example` must never contain real tokens.
3. **Verify no tokens in tracked files**: Search tracked config files for access tokens and confirm no real token values appear in files that would be committed.

## Scope

- **New apps**: Full scaffold matching the current runtime shape: instrumentation, SDK init, env var config
- **Existing apps**: Incremental -- detect what's already present, add only what's missing

## Stage workflow

Read `../references/skill-workflow-observability.md` before starting. Follow the
stages below in order, loading each linked reference before its affected work.
These references retain the complete workflow requirements; they are not optional
summaries. Resolve all paths in stage references from this skill directory,
including existing `./references/` and sibling `../references/` paths.

- [preflight](references/stages/preflight.md): Read before any edit; record `preflight`, then `scope` with `explicit`, `saved`, `all`, or `blocked` after resolving authorization.
- [plan](references/stages/plan.md): Read before choosing or implementing signals; record `plan` with `fresh`, `incremental`, or `targeted`.
- [apply](references/stages/apply.md): Read before dependency or application changes; record `apply` after implementing the authorized changes.
- [verify](references/stages/verify.md): Read before validation; record `verify` with `focused`, `full_runtime`, or `blocked` based on actual checks.
- [debug](references/stages/debug.md): Read only if enabling the supported VS Code debugging path.
- [report](references/stages/report.md): Read before producing instrumentation artifacts.
- [finalize](references/stages/finalize.md): Read before handoff or the final response; record `report` after artifact validation.

Record only stages actually reached. If blocked, record the reason and finish
`partial` or `failed`; leave unreached stages unobserved. A recorder failure must
not interrupt the primary workflow. Preserve the existing final response contract.
