# Verification Report And Handoff

Load this reference once after execution and proof classification are complete.
It owns `.observe/otel-verify.md`, reader validation, canonical HTML refresh,
and the standalone or instrumentation-child handoff. Canonical machine schema
and bindings remain owned by `json-approval-handoff.md`.

## Reader Report

Write this order:

```markdown
# OTel Verification Report: <service>

**Result:** Pass | Fail | Partial | Blocked | Not run
**Bottom line:** <one plain-language sentence saying what works and what does not>
**Source audit:** `.observe/otel-audit.json` | direct user scope
**Approved selection:** `.observe/otel-selection.json` | direct user scope
**Source instrumentation:** `.observe/otel-instrumentation.json` | `.observe/otel-instrumentation.md` direct | not found

## What Changed

| Area | Added or modified | Status |
|---|---|---|

## Tested And Working

**Individual result:** <working>/<total> working: <counts by signal type>.

| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|

## Not Working Or Not Proven

| Item | State | Why | What is needed next |
|---|---|---|---|

## Proof

| Proof type | What it proves | Evidence |
|---|---|---|

## Technical Details

### Commands Run

| Command | Result | Evidence |
|---|---|---|

### Coverage And Diagnostics
```

Keep `Bottom line` to one sentence and do not use counts alone. Group related
signals in `What Changed`, but put every exact added or modified item/call site
in `Tested And Working`; do not group independently verified routes, spans,
metrics, logs, exporters, or repeated span names from different call sites.
Use only `Working`, `Not working`, `Not proven`, or `Not configured` in that
table. Put a direct assertion, report, saved collector response, or file path in
every evidence cell; source presence is not working proof.

For canonical rows, preserve instrumentation item order and project the two
proof columns deterministically:

- `How it was tested` = `proof_mode=<mode>; scenarios=<comma-separated ids>`;
  use `scenarios=none` when empty.
- `Product result / visibility` = semicolon-joined product validation followed
  by `visibility=<enum>`.

Do not substitute observed telemetry for proof mode or omit visibility. If the
bound instrumentation inventory has no telemetry changes, retain the header,
write `Individual result: 0/0 working`, and add exactly `No telemetry items.
Selected findings are proof-first verification scope.`

Repeat every non-working, unproven, and unconfigured item under `Not Working Or
Not Proven`; write `None` only when all in-scope items work. Explain evidence
strength in `Proof`. Keep commands, runtime candidates, path matrices, trace
IDs, inventories, and topology diagnostics under `Technical Details`, and omit
diagnostic tables that merely repeat reader evidence.

Never expose raw trace IDs or span IDs in generated HTML. Say **the generated
trace** and name the span or signal. Preserve exact identifiers only in
canonical `trace_ids`, durable evidence, and Markdown `Technical Details`.

## Reader Validation

Escape every literal `|` inside Markdown table cells as `\|`; backticks do not
make it safe. Then always run:

```bash
python3 -I "<directory-containing-loaded-SKILL.md>/scripts/validate_reader_report.py" \
  "<service-root>/.observe/otel-verify.md"
```

In canonical mode add all four bindings:

```text
--instrumentation-json <service-root>/.observe/otel-instrumentation.json
--verify-json <service-root>/.observe/otel-verify.json
--audit-json <service-root>/.observe/otel-audit.json
--selection-json <service-root>/.observe/otel-selection.json
```

Only on the direct path add
`--expected-items-file .observe/tmp/otel-verify-expected-items.txt`. Repair
every structural, item-coverage, status, count, projection, or gap-mirroring
error and rerun until the validator passes. Do not finalize an unvalidated
report.

For canonical flow, then follow `Validate And Render` in
`json-approval-handoff.md`. Refresh `.observe/otel-instrumentation.html`; never
write verification state into `.observe/otel.html`. The instrumentation HTML
starts with one verification-state heading and one proof-and-delivery sentence,
then each selected finding exactly once. Keep technical ledgers in JSON and
Markdown, not duplicate HTML statistic cards or proof tables.

## Result And Failure Projection

Use `Fail` for a project-configured instrumentation-caused viability failure or
an executed telemetry assertion failure. Use `Partial` when meaningful proof
passed but rows remain unexecuted, blocked, or unproven and no assertion failed.
Use `Blocked` only when a concrete prerequisite prevented all meaningful proof.
Use `Not run` only when no check executed.

For `not_working`, keep finding `remaining` and top-level `next_steps` to the
concrete application code/config repair. Do not add rerun, proof capture, or
product inspection as another repair action. The failed scenario owns observed
failure evidence and the scenario map owns confirmation scope. Explain once
that `$otel-verify` is read-only and `$otel-instrument` makes the repair.

State local delivery and target-product check scope once at report level. Do
not repeat generic **Target product** or **Executed checks** lines per finding.
Preserve executed focused evidence with its real proof mode; a `not_proven`
scenario remains incomplete and appears as **Focused evidence obtained**, not a
passed scenario or request for stronger proof. Blocked coverage shows the
canonical `blocking_reason`, mapped working evidence under **Already proven**,
and `unobserved_outcome` under **Still unobserved**.

## Standalone Final Response

Use this only for a user-invoked verification. Mirror the report with these
headings in this order:

```markdown
**Result:** Pass | Fail | Partial | Blocked | Not run
**Report:** [otel-verify.md](<absolute path>)
**Machine report:** [otel-verify.json](<absolute path>) when canonical
**Instrumentation report:** [otel-instrumentation.html](<absolute path>) when canonical
**Audit report:** [otel.html](<absolute path>) when canonical

## What Changed
## Tested And Working
**Individual result:** <working>/<total> working: <counts by signal type>.
| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|
## Not Working Or Not Proven
## Proof
```

Include every exact item row; this is the primary result, not only a report
pointer. Keep diagnostics out. Write `None` under `Not Working Or Not Proven`
only when all rows work. For standalone failure name `$otel-instrument` once as
the repair workflow and explain that verification changes no application code.
State the canonical audit ID and approved IDs and confirm unselected findings
were excluded.

## Instrumentation Child Return

Do not emit the standalone response when an active `$otel-instrument` workflow
invoked verification. Write and validate the artifacts, then return the repair
packet to that workflow. A failed child remains
`meta.workflow_mode: instrumentation_child` and
`meta.lifecycle: intermediate`, with failed finding/item/scenario IDs, direct
evidence, repair-only `remaining`/`next_steps`, and any separately structured
`stop_boundaries[]`. Do not ask the user to start either workflow again. The
parent owns code mutation and automatically invokes affected checks after a
repair; the next child must bind the updated `instrumentation_sha256`.
