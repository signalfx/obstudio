### 8. Produce Verification Artifacts

In canonical flow, write `.observe/otel-verify.json` using
`./references/json-approval-handoff.md`. Preserve exact selected finding,
scenario, and instrumentation-item order; bind it to the exact normalized
instrumentation digest; validate the flow; and refresh
`.observe/otel-instrumentation.html`. Leave `.observe/otel.html` as the audit
and scope surface.

When a project/user-supplied correctness contract is available, read
`references/correctness-evaluations.md` and reconcile its per-finding scenarios
through the optional `observer_skill_correctness_evaluate` tool. Preserve
independent expectations; skill-reported success is not correctness evidence.
Keep unavailable/unknown scores separate from existing app verification proof.

## Reader Report

Write this order:

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

Read this table left to right as: what was added, whether it works, how it was
tested, and the proof.

| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|

## Not Working Or Not Proven

| Item | State | Why | What is needed next |
|---|---|---|---|

Use `None` when every in-scope item is proven. Use `Not working` only when an
executed check failed. Use `Not proven` when a scenario was not run or a
prerequisite was unavailable.

## Proof

| Proof type | What it proves | Evidence |
|---|---|---|

## Technical Details

### Commands Run

| Command | Result | Evidence |
|---|---|---|

### Coverage And Diagnostics

<Include only the runtime, build, signal, path, topology, and explorer rows
needed to substantiate the result or explain gaps.>
```

Report requirements:

- For GenAI, include all three **Required GenAI Report Evidence** tables from
  `../references/genai-readiness.md` in the requested review/report. Even a
  captured-fixture review must map fresh-agent boundaries to exact actual or
  proposed creators: supported SDK methods or the justified per-operation
  public OTel exception. Record chosen package/public API source and applicable
  example revision, preserve existing creators, assess ordinary
  helpers as GenAI N/A, and include explicit cancellation/teardown evidence
  rows. Missing runtime evidence is Not proven; generic SDK recommendations
  cannot substitute for the producer receipt or lifecycle assessment.
- Follow `../references/report-flow-contract.md`. The first screen must let a
  reader answer what changed, whether it was tested, whether it works, what
  proves it, and why anything remains unproven.
- Keep `Bottom line` to one sentence. Do not use coverage counts alone as the
  bottom line.
- In `What Changed`, group related signals by behavior or component instead of
  listing every span in prose.
- In `Tested And Working`, include every individual item from the reconciled
  Changed Telemetry Inventory. Do not group independently instrumented or tested
  route spans, operation call sites, metrics, logs, or exporters into one row.
  When the same span name is emitted by multiple modified call sites, identify
  the call site in `OTel item` and give each call site its own row.
- Put `Individual result: <working>/<total> working` immediately above the
  table, followed by counts by signal type. Derive the counts from the table.
- Use only `Working`, `Not working`, `Not proven`, or `Not configured` in the
  `Working status` column. `Working` requires direct test or runtime evidence.
- State exactly how each item was tested: application test, actual full
  runtime, temporary app-code harness, OTLP query, or static configuration
  validation. Do not write only `tested`, `verified`, or a suite name.
- Put a direct file path, report, assertion, or saved collector response in
  every `Evidence` cell. Source code presence alone is not evidence that an
  OTel item works.
- Repeat non-working, unproven, and unconfigured rows under
  `Not Working Or Not Proven` with the reason and next action. Write `None`
  there only when every per-OTel row is `Working`.
- In `Proof`, explain the strength of evidence in plain language. Distinguish
  application tests, temporary app-code harnesses, OTLP collector acceptance,
  and source/config checks. Never present source presence as runtime proof.
- Put commands, runtime selection, trace IDs, full path matrices, signal
  inventories, and topology diagnostics under `Technical Details`. Omit
  diagnostic tables that merely repeat evidence already shown above.
- Use exact signal names and source/test paths.
- Do not claim a signal is verified unless command output, test assertion, or
  collector or Splunk Observability Studio evidence proves it.
- If only fake/in-memory telemetry was used, say it is not explorer-visible.
- If any inventory row is unverified, set `Result: Partial`, `Blocked`, or
  `Fail`.
- Set `Result: Fail` when project-configured source viability fails because of
  instrumentation changes, or when an executed scenario omits or violates
  expected telemetry. Use `Partial` for environmental blockers or unexecuted
  rows when meaningful proof passed and no executed assertion failed. Use
  `Blocked` when no meaningful proof can run because a concrete prerequisite
  is unavailable.
- Include runtime dependency and build/import details under `Technical Details`
  when they affect the result. A failed gate must map to every blocked signal
  and path that depends on it.
- Use only `instrumentation-introduced`, `pre-existing`, `environment`,
  `unknown`, or `not applicable` in the failure-ownership column. Include
  compiler/import locations or prerequisite evidence for every non-passing row.
- Always summarize added, modified, or removed telemetry in `What Changed` when
  a source instrumentation artifact exists or the user asks what changed.
- Preserve per-path verification in the working inventory whenever workflows,
  routes, jobs, startup, streaming, tools, retrieval, redaction, GenAI, or
  runtime paths are in scope. Publish detailed rows only for gaps, failures, or
  materially different proof.
- Generated SDK contracts may appear in evidence but must not satisfy the
  `App code proof` column.
- The reconciled working inventories are the verification source of truth.
  The report's `What Changed`, `Tested And Working`, and
  `Not Working Or Not Proven` sections are the reader-facing projection of
  those inventories.
- Include summary counts, for example:

```markdown
**Changed signal coverage:** Overall 37/42; spans 8/9; metrics 29/33; logs 0/0.
**Path coverage:** 8/12 verified; 2 source-only; 2 blocked.
**Unit export coverage:** unit+OTLP 12; unit-only 3; OTLP-only 2; blocked 1.
```

If no logs/events were changed, include one `Not applicable` row for
logs/events. If OTLP logs were requested but no log exporter or bridge exists,
mark them `Not configured` and state the implementation required. Do not use
`Not proven` for an absent implementation.

Never expose raw trace IDs or span IDs in generated HTML. Say **the generated
trace** and name the span or signal. Preserve exact identifiers only in
canonical `trace_ids`, durable evidence, and Markdown `Technical Details`.

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
gap-mirroring error and rerun until the validator passes. Do not finalize an
unvalidated report.

For canonical flow, then follow `Validate And Render` in
`json-approval-handoff.md`. Refresh `.observe/otel-instrumentation.html`; never
write verification state into `.observe/otel.html`. The instrumentation HTML
starts with one verification-state heading and one proof-and-delivery sentence,
then each selected finding exactly once. Keep technical ledgers in JSON and
Markdown, not duplicate HTML statistic cards or proof tables.

### 9. Final Response

Mirror the reader-first report in the command response. Use these exact headings
in this exact order; do not replace them with generic headings such as
`Outcome`, `Summary`, or `Validation`:

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

Keep technical diagnostics out of the command response, but do not shorten it
by omitting per-OTel rows. It is the user's primary result, not merely a pointer
to the file. Always include `Tested And Working`, even when verification fails
or is partial; the `Working status` column makes mixed results explicit.
Always include `Not Working Or Not Proven`; write `None` only when every
in-scope inventory row is proven.

Use the loopback links returned by `render-instrumentation-html` for both HTML
reports. Do not open either report automatically. Keep the Markdown and JSON
report links as absolute local-file paths.

Name `$otel-instrument` as the repair path for instrumentation-introduced
source failures; do not imply that rerunning verification will repair
application code. In canonical flow, state the audit ID and approved IDs and
confirm unselected findings were excluded.

For demo-oriented runs, include:

`Splunk Observability Studio can verify the instrumentation contract locally: it runs deterministic checks, can hold open a real OTLP contract process, and writes a report proving which OTel signals are emitted and visible.`
