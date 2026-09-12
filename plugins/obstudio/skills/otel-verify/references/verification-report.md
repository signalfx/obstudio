# Verification Report And Response

Read this reference before writing `.observe/otel-verify.md` or the final
response. Keep the full inventories as working data, but publish only the rows
needed to show whether each telemetry change works, reproduce a failure, or
identify an uncovered path.

## Reader Report

Write `.observe/otel-verify.md` in this order:

```markdown
# OTel Verification Report: <service>

**Result:** Pass | Fail | Partial | Blocked | Not run
**Bottom line:** <one plain-language sentence saying what works and what does not>
**Source audit:** `.observe/otel-audit.json`
**Approved selection:** `.observe/otel-selection.json`
**Source instrumentation:** `.observe/otel-instrumentation.json` | not found

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

<Only runtime, build, signal, path, topology, and explorer rows needed to
support the result or explain gaps.>
```

The first screen must answer, in order: what changed; whether each change was
tested; whether it works; the direct proof; and why anything remains unproven
plus what is needed next. Keep `Bottom line` to one sentence, not a coverage
count.

Use `What Changed` to group related behavior, but put every reconciled
telemetry change in `Tested And Working`: one row per exact route/server span,
custom span call site, metric, log pipeline/category, and runtime/exporter
behavior. Separate modified call sites even when they emit the same name. Do
not make the reader correlate separate change and test ledgers.

Immediately above the table, derive `Individual result` and per-signal counts
from its rows. Use only `Working`, `Not working`, `Not proven`, or
`Not configured` in `Working status`:

- `Working` requires direct test/runtime evidence and an exact description of
  whether an application test, full runtime, temporary app-code harness, OTLP
  query, or static configuration validation ran.
- `Not working` requires an executed failed check or absent/invalid expected
  telemetry.
- `Not proven` means the scenario did not run or a prerequisite was
  unavailable.
- `Not configured` means the requested implementation or runtime pipeline is
  absent; stdout trace fields do not prove an OTLP log exporter.

Every `Evidence` cell must cite a direct file, report, assertion, or saved
collector response. Source presence alone is not working proof. State product
or local visibility exactly as supported by the bound overlay. Repeat every
non-working, unproven, or unconfigured item under `Not Working Or Not Proven`,
with reason and next action; write `None` only when all item rows work.

In `Proof`, distinguish application tests, temporary app-code harnesses, OTLP
acceptance/explorer evidence, and source/config checks. Put runtime selection,
commands, trace IDs, full path/signal matrices, and topology diagnostics under
`Technical Details`; omit ledgers that merely repeat reader rows. Include
runtime/build detail there when it changes the result, and map each failed gate
to every dependent signal/path.

When routes, workflows, jobs, startup, streaming, tools, retrieval, redaction,
GenAI, or runtime paths are in scope, preserve per-path results in the working
inventory and publish detailed rows for gaps, failures, or materially distinct
proof. Generated SDK contracts may support contract evidence but cannot satisfy
application-code proof.

Use only `instrumentation-introduced`, `pre-existing`, `environment`,
`unknown`, or `not applicable` for failure ownership, with source locations or
prerequisite evidence. Set the aggregate result as follows:

- `Pass`: every in-scope item and path has required proof.
- `Fail`: an executed scenario omitted or violated expected telemetry, or
  instrumentation-introduced source viability failed.
- `Partial`: meaningful proof passed but environmental blockers, source-only,
  unexecuted, or otherwise unproven rows remain.
- `Blocked`: no meaningful proof could run because a concrete prerequisite was
  unavailable.
- `Not run`: no scenario or item has executed proof and there is no structured
  blocker result.

If no logs/events changed, include one `Not applicable` logs/events row. If
OTLP logs were requested but no bridge/exporter exists, use `Not configured`
and name the implementation needed.

Optional coverage summaries must derive from the inventories, for example:

```markdown
**Changed signal coverage:** Overall 37/42; spans 8/9; metrics 29/33; logs 0/0.
**Path coverage:** 8/12 verified; 2 source-only; 2 blocked.
**Unit export coverage:** unit+OTLP 12; unit-only 3; OTLP-only 2; blocked 1.
```

Never expose raw trace IDs or span IDs in generated HTML. Say **the generated
trace** and name the span/signal. Preserve exact identifiers only in canonical
`trace_ids`, durable evidence, and Markdown `Technical Details`.

## Reader Validation

Escape every literal `|` inside Markdown table cells as `\|`; backticks do not
make it safe. Always run:

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

Repair every structural, item-coverage, status, count, projection, or
gap-mirroring error and rerun until validation passes. Then run `Validate And
Render` in `json-approval-handoff.md`. Refresh
`.observe/otel-instrumentation.html`, never `.observe/otel.html`.

The human instrumentation HTML starts with one verification-state heading and
one proof-and-delivery sentence, then each selected finding exactly once. Keep
technical ledgers in JSON/Markdown rather than duplicate HTML statistic cards
or proof tables.

### 9. Final Response

Mirror the report in the command response with these exact headings and order:

```markdown
**Result:** Pass | Fail | Partial | Blocked | Not run
**Report:** [otel-verify.md](<absolute path>)
**Machine report:** [otel-verify.json](<absolute path>) when canonical
**Instrumentation report:** [otel-instrumentation.html](http://127.0.0.1:<port>/<token>/otel-instrumentation.html) when canonical
**Audit report:** [otel.html](http://127.0.0.1:<port>/<token>/otel.html) when canonical

## What Changed
## Tested And Working
**Individual result:** <working>/<total> working: <counts by signal type>.
| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|
## Not Working Or Not Proven
## Proof
```

Use the loopback links returned by `render-instrumentation-html` for both HTML
reports. Do not open either report automatically. Markdown and JSON report
links are absolute local-file paths.

Do not omit or group per-OTel rows from the response. Always include both
`Tested And Working` and `Not Working Or Not Proven`, even for failed or partial
runs; write `None` only when every item works. Keep diagnostics out of the
response. In canonical flow state the audit ID and approved IDs and confirm
unselected findings were excluded.

Name `$otel-instrument` as the repair path for instrumentation-introduced
source failures; rerunning verification does not repair application code.

For demo-oriented runs, include:

`Splunk Observability Studio can verify the instrumentation contract locally: it runs deterministic checks, can hold open a real OTLP contract process, and writes a report proving which OTel signals are emitted and visible.`
