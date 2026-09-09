---
name: otel-verify
description: >-
  Deterministically verify existing OpenTelemetry spans, metrics, logs,
  approved audit IDs, GenAI traces, per-path coverage, and local OTLP emission,
  then write verification reports. Use for $otel-verify, instrumentation tests,
  and emission proof. Read-only for application code; use $otel-instrument for
  changes and modify tests only when requested.
---

# OTel Verify

Prove existing OpenTelemetry instrumentation with deterministic application
execution and direct evidence. Write `.observe/otel-verify.md`; in canonical
flow also write `.observe/otel-verify.json` and refresh
`.observe/otel-instrumentation.html`.

Before writing verification artifacts, read
`../references/report-flow-contract.md`, but load only its
`## Verification Report Contract` section and stop before
`## Splunk Configure Contract`; the preceding audit and instrumentation
contracts are not verification instructions. Then read
`references/verification-report.md`.

When `.observe/otel-audit.json` exists or the user supplies finding IDs, also
read `./references/json-approval-handoff.md`; it owns canonical scope, schema,
digest binding, status rollup, and HTML refresh.

Resolve paths in this entrypoint from the skill directory. Inside a loaded
reference, resolve relative paths from that reference's directory. Use each
routed contract as its single authority; never resolve skill references from
the service cwd or probe alternate copies unless a required file is missing.

## Contract

- Canonical inputs are `.observe/otel-audit.json`, its bound
  `.observe/otel-selection.json`, and `.observe/otel-instrumentation.json`.
  JSON is authoritative; Markdown is reader detail. Without a canonical audit,
  stop and ask for `$otel-audit`. Never fabricate canonical state.
- Verify exactly the selection's dependency-closed `approved_ids`, in audit
  order, their referenced scenarios, and every bound instrumentation item.
  Bind proof to the normalized instrumentation overlay through
  `instrumentation_sha256`; matching IDs alone do not prove freshness.
- Default behavior is read-only for application code. Do not add or repair
  instrumentation; route that work to `$otel-instrument`. Do not change tests
  unless the user explicitly asks to add, repair, persist, or write them.
- Verification is application-code-first. Generated SDK telemetry can prove an
  exporter/schema contract only and never proves that application code emits.
- Build exact working inventories for every declared or changed span,
  metric, log/event, runtime/exporter behavior, and telemetry-distinct path.
  One representative trace cannot close a larger inventory.
- Run a project-runtime build/import viability gate before new telemetry
  harnesses. Use the repository-configured runtime and do not install missing
  app dependencies globally, edit manifests, or refresh lockfiles.
- Direct proof must establish each signal's required name/shape, attributes or
  dimensions, status/error behavior, topology or correlation, and relevant
  path. Source presence is not emission proof.
- Keep credentials, production endpoints, raw prompts/content, and user,
  session, request, trace, or span IDs out of unsafe output and metric
  dimensions. Prefer deterministic fakes and local-only OTLP.
- `Pass` requires every in-scope item and path to have its required proof.
  Use `Fail` for executed telemetry violations or instrumentation-introduced
  viability failures, `Partial` when meaningful proof passed but gaps remain,
  `Blocked` when a concrete prerequisite prevents all meaningful proof, and
  `Not run` only when nothing executed and no structured blocker applies.
- The report and final response must answer, per individual telemetry item:
  what changed, whether it was tested, whether it works, the direct proof, and
  why anything remains unproven plus its next action.

## Progressive Disclosure

Load only the references required by the selected mode:

| Condition | Read | Authority |
|---|---|---|
| Canonical audit exists or exact IDs are supplied | `references/json-approval-handoff.md` | Bound selection, verification JSON, digest/status rules, validation, HTML refresh |
| New compile/import/test/harness/startup/OTLP proof is needed | `references/direct-verification.md` | Inventories, proof order, source viability, signal/path/runtime proof |
| Any verification command will run | `references/project-runtime-resolution.md` (routed from direct verification) | Project runtime discovery and reporting |
| Routes, workflows, jobs, startup, streaming, tools, retrieval, redaction, or error paths are in scope | `references/path-scenario-coverage.md` (routed from direct verification) | Scenario derivation, path execution, matrices |
| Auto-instrumentation/runtime-only behavior is claimed | `../references/full-runtime-acceptance.md` (routed from direct verification) | Real-process acceptance gate |
| Local explorer visibility is claimed | `references/explorer-witness.md` (routed from direct verification) | Source lifecycle, query evidence, visibility states |
| User explicitly requests permanent tests | `references/app-code-test-authoring.md` (routed from direct verification) | App-code test requirements |
| Markdown report or final response is written | `references/verification-report.md` | Reader order, status projection, validation, response shape |

Do not read `references/direct-verification.md` for a request that only validates and
renders a complete, already-bound durable proof packet. Do not skip it when
new verification evidence must be executed.

## Workflow

### 1. Discover The Verification Inputs

#### Canonical Scope Gate

When `.observe/otel-audit.json` exists or exact IDs were supplied, read and
follow `./references/json-approval-handoff.md` before choosing commands.
Validate the audit and bound selection first. Require the instrumentation
overlay to match its exact `selection_sha256`, and require saved verification
to match the normalized instrumentation digest; verify exactly the approved
findings in audit order and their referenced scenarios. Unselected findings are
outside this result and must not make it partial.

If canonical audit/selection exists but instrumentation JSON is absent, do not
write verification JSON or infer IDs from instrumentation Markdown. Perform
only a clearly incomplete read-only check and route the missing bound handoff
to `$otel-instrument`. Without canonical audit, stop and ask for `$otel-audit`.

Reconcile saved commands, source paths, runtimes, expected signals, and proof
against current source. Never trust stale paths or invent missing evidence.

### 2. Choose The Verification Mode

#### Existing Durable Proof Packet

Use this mode only when the request is to validate, preserve, or render an
existing complete `.observe/otel-verify.json` packet and no new runtime claim
is requested.

1. Validate the complete audit -> selection -> instrumentation -> verification
   chain with the shared validator from `references/json-approval-handoff.md`.
2. Preserve supplied evidence, finding/scenario/item order, proof modes,
   visibility, and trace IDs. Do not rerun the application, replace direct
   proof with source inspection, invent a removed signal, or broaden scope.
3. Write the compatibility Markdown from the bound proof and run the reader
   validator. Refresh instrumentation HTML only through the bound render flow.

This mode does not load `references/direct-verification.md`, project-runtime, path,
full-runtime, explorer, or test-authoring references unless the request also
requires new evidence.

#### New Or Incomplete Verification

Read and follow `references/direct-verification.md`. It owns inventory
construction, existing-test discovery, runtime/build gates, proof strength,
detailed statuses, path execution, optional local OTLP, and artifact handoff.
Load only the conditional references it routes to.

Keep these invariants visible while executing:

- Every changed telemetry item and referenced scenario must have a distinct
  result. Shared helper proof cannot close unexecuted named operations.
- Runtime-only auto-instrumentation claims require the real process and the
  full-runtime acceptance gate.
- Unresolved dependencies are `Blocked`, not `Source only`; an absent requested
  exporter or bridge is `Not configured`, not `Not proven`.
- Any meaningful unverified row prevents `Pass`.

### 3. Produce And Validate Artifacts

In canonical flow, write `.observe/otel-verify.json` exactly as
`references/json-approval-handoff.md` specifies, preserving selected finding, scenario,
and instrumentation-item order and exact digest bindings. Then write
`.observe/otel-verify.md` through `references/verification-report.md`.

Always run the reader validator. In canonical mode include audit, selection,
instrumentation, and verification JSON arguments; then validate the complete
flow and render `.observe/otel-instrumentation.html`. Leave
`.observe/otel.html` as the audit and scope-planning surface.

## Reader Report

The Markdown report and command response begin with these question-led
sections before diagnostics:

```markdown
## What Changed
## Tested And Working
**Individual result:** <working>/<total> working: <counts by signal type>.
## Not Working Or Not Proven
## Proof
```

Use one row per exact canonical item in `Tested And Working`, direct evidence
for every working claim, and a mirrored reason/next action for every incomplete
item. Detailed report shape, status projection, privacy rules, and validation
belong to `references/verification-report.md`.

Always validate the Markdown with:

```bash
python3 -I "<directory-containing-loaded-SKILL.md>/scripts/validate_reader_report.py" \
  "<service-root>/.observe/otel-verify.md"
```

Never expose raw trace IDs or span IDs in generated HTML. Say **the generated
trace** and name the span or signal; keep exact identifiers only in canonical
JSON, durable evidence, and Markdown technical detail.

### 9. Final Response

Use the exact heading order from `references/verification-report.md` and include the
individual result table rather than only linking to the file. In canonical
flow, use these link forms:

```markdown
**Report:** [otel-verify.md](<absolute path>)
**Machine report:** [otel-verify.json](<absolute path>)
**Instrumentation report:** [otel-instrumentation.html](http://127.0.0.1:<port>/<token>/otel-instrumentation.html)
**Audit report:** [otel.html](http://127.0.0.1:<port>/<token>/otel.html)
```

Use the loopback links returned by `render-instrumentation-html`; do not open
either report automatically. Keep the Markdown and JSON report links as
absolute local-file paths. State the audit ID and approved IDs, confirm unselected
findings were excluded, and route instrumentation-introduced repairs to
`$otel-instrument`.

For demo-oriented runs, include:

`Obstudio can verify the instrumentation contract locally: it runs deterministic checks, can hold open a real OTLP contract process, and writes a report proving which OTel signals are emitted and visible.`
