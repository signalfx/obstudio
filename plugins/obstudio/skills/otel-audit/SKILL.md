---
name: otel-audit
description: >-
  Scan a codebase for existing OpenTelemetry instrumentation and report
  on observability coverage gaps. Read-only for application code -- writes
  audit artifacts under .observe/ including .observe/otel-audit.json
  and .observe/otel.html, but does not modify service code.
  Use when the user types $otel-audit, asks about observability gaps,
  wants to assess instrumentation coverage, says "what signals am I
  missing", "scan this service for observability", asks about
  "observability readiness", asks whether instrumentation can make incidents
  faster to detect or localize, or asks whether GenAI/LLM workflows follow
  OpenTelemetry semantic conventions. Do NOT use for implementing code changes
  -- use $otel-instrument instead.
allowed-tools: Read Grep Glob Write
---

# Audit -- Observability Coverage Scan

## Overview

Scan a service repository to detect its language, framework, dependencies,
and existing OpenTelemetry instrumentation. Report what is instrumented,
what is missing, and any anti-patterns. This skill is read-only for application
code: it writes `.observe/otel-audit.json` and `.observe/otel.html` but does
not modify service code, dependencies, configuration, or tests.

Resolve every reference and script path from the directory containing the
loaded `otel-audit/SKILL.md`. Here, `../references/<file>` means the shared
sibling under the parent skills directory, while `references/<file>` and
`scripts/<file>` are local to `otel-audit`. Never probe the service root or
repository root for these paths.

Before writing the report artifacts, read
`../references/report-flow-contract.md` and follow the Audit Contract plus the
Reader-First Report Order.

Before classifying any local OTLP endpoint, read
`../references/local-otlp-receiver.md`. Treat Splunk Observability Studio as a
configurable local receiver and optional cloud-compatible AO gateway. Receiver
receipt alone is not project/stream configuration or cloud delivery evidence.

## Stage workflow

Read `../references/skill-workflow-observability.md` before starting. Follow the
stages below in order, loading each linked reference before its affected work.
These references retain the complete workflow requirements; they are not optional
summaries. Resolve all paths in stage references from this skill directory,
including existing `./references/` and sibling `../references/` paths.

- [discover](references/stages/discover.md): Read before discovery; record `discover` with the detected language branch.
- [assess](references/stages/assess.md): Read before assessment; record `assess` with `fresh`, `incremental`, or `mixed`.
- [libraries](references/stages/libraries.md): Read the warnings and the detected language library map before recommending instrumentation.
- [report](references/stages/report.md): Read before writing artifacts or finalizing the report; record `report` after the canonical artifacts validate.

Record only stages actually reached. If blocked, record the reason and finish
`partial` or `failed`; leave unreached stages unobserved. A recorder failure must
not interrupt the primary workflow. Preserve the existing final response contract.
