# JSON Selection Handoff

Use this reference when `.observe/otel-audit.json` exists or the user supplies
finding IDs. It defines the deterministic executable-scope gate and machine handoff.

## Selection Gate

Before any application-code, dependency, runtime-config, or test edit:

1. Validate the audit:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate .observe/otel-audit.json
   ```

2. Accept finding IDs only from the user's current
   `$otel-instrument --ids OTEL-001,OTEL-002` request or an existing bound
   `.observe/otel-selection.json`. Accept manual answers only from that bound
   handoff's `decision_answers` or the user's current repeatable
   `--decision OTEL-###=option-id` arguments; do not infer an answer from prose
   or from an executable ID. If neither source of executable scope exists, stop before
   edits, point the user to `.observe/otel.html`, summarize the selectable
   findings, and ask which IDs to include. Do not infer selected scope from
   priority, severity, or a previous broad request.
3. For user-provided IDs, create the selection and scoped input:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" select \
     .observe/otel-audit.json \
     --ids OTEL-001,OTEL-002 \
     --decision OTEL-003=application-owned \
     -o .observe/otel-selection.json \
     --scoped-out .observe/tmp/otel-selected-findings.json
   ```

   Use the exact requested IDs. Let the tool add dependencies and preserve
   audit order. Do not hand-edit or merge selections.
4. Validate the bound selection:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate-flow \
     .observe/otel-audit.json \
     --selection-json .observe/otel-selection.json
   ```

   A missing, stale, unknown, or dependency-incomplete selection is a hard
   stop. A handoff with an authored answer whose option unlocks no work may
   validly have empty executable ID lists. Repair invalid state through the
   planning flow; never bypass the validator.
   Instrumentation must later copy the validator-computed digest of this exact
   normalized selection into `selection_sha256`. Do not hash a hand-authored or
   partially normalized object.
5. Use only the scoped executable findings, dependencies, and referenced
   verification scenarios. `manual decision` and `external follow-up` findings
   cannot appear in either selection ID list. `decision_answers` is separate
   from `requested_ids` and `approved_ids`; it is a canonical-audit-order list
   of `{"finding_id":"OTEL-###","option_id":"stable-option-id"}` entries. An
   answer never auto-selects work. Only executable
   findings listed in that option's `unlocks` may enter requested or approved
   scope; every nonmatching branch remains blocked. Reject an unanswered manual
   dependency, an unknown answer, mismatched executable work, or any unresolved
   external follow-up. Return to `.observe/otel.html` to record or change the
   answer and explicitly add matching work.
   An unresolved dependency without a valid matching answer remains a hard
   stop; do not infer or bypass it.

Refresh the selected-scope human view:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" render-html \
  .observe/otel-audit.json \
  -o .observe/otel.html \
  --selection-json .observe/otel-selection.json
```

## Instrumentation JSON

Write `.observe/otel-instrumentation.json` with this shape:

```json
{
  "schema_version": 1,
  "kind": "otel-instrumentation",
  "audit_id": "audit-id-from-selection",
  "audit_sha256": "audit-sha256-from-selection",
  "selection_sha256": "sha256-of-exact-normalized-selection",
  "meta": {
    "service_name": "example-service",
    "date": "2026-07-17",
    "result": "Partial"
  },
  "findings": [
    {
      "id": "OTEL-001",
      "status": "not_proven",
      "changes": ["Added HTTP server instrumentation."],
      "telemetry_changes": [
        {
          "id": "OTEL-001.http-server-span",
          "change_kind": "added",
          "change": "Wrapped the HTTP handler with route-aware server instrumentation.",
          "type": "span",
          "name": "GET /health",
          "source": "main.go:42",
          "added_attributes": ["http.route=/health"],
          "product_view": "Trace waterfall shows route latency and errors.",
          "follow_up_actions": ["Filter the trace waterfall by http.route after verification."],
          "verification_scenarios": ["http.health.success"]
        }
      ],
      "tests": ["go test ./..."],
      "evidence": ["main.go:42"],
      "follow_up_actions": ["Confirm the route span in the trace waterfall after verification."],
      "resolved_commit": null
    }
  ],
  "next_steps": ["Continue the active instrumentation workflow through verification."]
}
```

Copy `audit_id` and `audit_sha256` from the selection. Compute
`selection_sha256` from the exact normalized selection returned by the shared
validator, including `requested_ids`, dependency-closed `approved_ids`,
`decision_answers`, and approval metadata. A changed answer invalidates older
instrumentation even when the executable IDs remain unchanged. Use only `Pass`,
`Partial`, `Fail`, `Blocked`, or `Not run` for `meta.result`; `working`,
`not_working`, `not_proven`, `not_configured`, or `deferred` for finding status;
and `span`, `metric`, `log`, `resource`, or `configuration` for telemetry type.
Findings must exactly equal the dependency-closed selected IDs (`approved_ids`)
in audit order. Every selected finding requires a nonempty `changes` record:
name the concrete correction or explicitly explain why it is proof-only. A
`working` finding requires nonempty `tests` and `evidence`. Keep unselected findings
out of this JSON. Use `resolved_commit: null` without commit proof.

Give every telemetry change a stable ID beginning with its finding ID, for
example `OTEL-001.http-server-span`. Use `added`, `modified`, or `removed` for
`change_kind`; describe the concrete code/config change; preserve the exact
source/call site; list only newly added attributes or dimensions; and map the
item to the audit scenarios that prove it. Every item requires at least one
product follow-up. For a metric, name the chart/dashboard or detector action it
enables. Preserve each audit-authored attribute exactly: a key-only promise
stays key-only, while `key=value` keeps that exact bounded value. When
`added_attributes` is nonempty, name the filter, slice, group-by,
or breakdown it enables. These item IDs are the deterministic inventory that
verification must cover exactly; a free-text `changes` list is not a substitute.
Never use filler such as "Added/modified `<name>` for the selected bounded
telemetry contract." State the actual behavior: ownership removed or retained,
exception/status handling, lifecycle closure, bounded attributes, provider
wiring, propagation, flush/shutdown behavior, or another source-backed
correction. The validator rejects generic selected-contract wording.

Write concise, reader-facing `changes`, `product_view`, and `next_steps`
because each selected-finding HTML card uses them directly. Each selected finding should
have at least one short `changes` sentence that says what changed in code or
configuration, and each telemetry item should say the operator-visible OTel
improvement it enables. Keep runtime/product proof out of this wording unless
verification has direct evidence. If a selected finding intentionally adds no
application telemetry and exists only to prove an auto-instrumented or
platform-owned signal, record an empty `telemetry_changes` list and state that
proof-first reason in `changes`; do not fabricate a custom signal.

Keep exporter ownership distinct from delivery capability. “No
application-owned exporter was added” may coexist with an agent-owned OTLP
path; “no OTLP pipeline/export path exists” may not coexist with later
`otlp_accepted` or `explorer_visible` proof. Write `product_view` so verification
can strengthen its evidence without contradicting the implemented topology.

Render every selected finding once in the instrumentation HTML. Show all of its
finding-level `changes` values and use the bound audit finding's
`product_outcome` for **How it improves observability**. Do not keep only the
first N findings, collapse findings into themes, or substitute a component
summary. Keep a proof-first finding in this list even when its
`telemetry_changes` is empty.

Keep the human HTML concise. Start with one verification-state heading and one
proof-and-delivery sentence, followed immediately by every selected finding.
When verification is `Partial` with no `not_working` finding, use
**Verification incomplete — no observed failures** and state **X of Y telemetry
changes are proven**. State separately whether local OTLP delivery and Splunk
Observability Cloud were checked. Render canonical `not_proven` as
**verification incomplete** while preserving the machine value. Do not infer
merge readiness from these overlays without an explicit merge policy.

Do not render aggregate statistic cards or global code-to-telemetry mappings,
finding-level closure rows, scenario proof, or item-level proof ledgers in the
HTML. Preserve those complete technical records in
`.observe/otel-instrumentation.json`, `.observe/otel-instrumentation.md`,
`.observe/otel-verify.json`, and `.observe/otel-verify.md`. Removing those
duplicate HTML sections must not remove or weaken any canonical field,
validation rule, digest binding, or downstream proof handoff.

Do not render raw trace IDs or span IDs in the human HTML, even when they occur
inside `observed_telemetry`. Use **the generated trace** and a named span or
signal in reader prose. Preserve the exact identifier in verification
`trace_ids`, durable evidence, and Markdown `Technical Details` when needed.

One direct successful unit, application, or runtime observation proves the
specific telemetry item it exercised. Mark its `item_results` row `working`;
keep unexercised scenario coverage independent, so the finding may remain
`not_proven`. Do not infer success from source/config presence or an unbounded
or ambiguous absence. A bounded expected-absence assertion for a removed item
is governed by the direct-assertion rule below.

Every child verification item row carries the required boolean
`direct_assertion_passed`. Compute it before finding/scenario rollup and set it
`true` exactly for a passed assertion against the exact item or call site;
otherwise set it `false`. A removed item needs a bounded executed capture that
proves both the removed signal's absence and the intended replacement owner's
presence. The item status is `working` exactly when this boolean is `true`.

On each finding card, show one plain verification status and a **Telemetry
change / What was observed / Status** table. State local delivery and
target-product check scope once in the report-level status sentence; do not
repeat it on each card or add generic **Target product** / **Executed checks**
lines. Use **Verification incomplete** on an incomplete finding; reserve **no
observed failures** for the report-level heading. Use the audit scenario's
`trigger` in one collapsed **Coverage details**
disclosure, grouped as running service, focused check, not exercised, blocked,
failed, or not configured. Do not render per-finding `x/y` ratios, a
stronger-proof group, or a completion checklist. Keep stable IDs, commands,
and exact counts in the canonical JSON and generated Markdown proof ledgers.

Each verification scenario with `status: blocked` must carry nonempty
`blocking_reason` and `unobserved_outcome` strings. The first names the exact
prerequisite failure supported by the scenario's command/evidence; the second
names the exact runtime, OTLP-delivery, or product observation that could not
be captured. Omit both fields for non-blocked scenarios. Before **Coverage
details**, render **Runtime verification unavailable**, followed by **Why
runtime verification is unavailable**, mapped working item evidence under
**Already proven**, and the scenario outcomes under **Still unobserved**. Do
not infer a blocker from finding `remaining`, which owns remediation rather
than cause.

When current verification is `Fail`, render **Verification failures and
remaining proof**, not pending language. A failed finding shows **What
verification found** from scenario evidence followed by **Code repair
required** from its repair-only `remaining` actions, then **How the repair is
confirmed**. For a standalone verification label the primary action **Next
repair steps**; for an instrumentation child label it **Active repair loop**.
Explain that
`$otel-verify` never changes application code: `$otel-instrument` applies the
repair and automatically invokes the affected checks afterward only to confirm
the result. Do not render that automatic recheck as a second repair bullet or
user action. A `not_proven` finding keeps its incomplete coverage in the neutral
**Coverage details** disclosure; keep exact scenario IDs and counts in canonical
proof artifacts and do not add a per-finding action list.

## Validate And Render Instrumentation

After writing instrumentation JSON, run:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate-flow \
  .observe/otel-audit.json \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json

python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" render-instrumentation-html \
  .observe/otel-audit.json \
  -o .observe/otel-instrumentation.html \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json
```

After `$otel-verify` writes `.observe/otel-verify.json`, rerun validation and
`render-instrumentation-html` with `--verify-json .observe/otel-verify.json`.
The verify overlay must carry `instrumentation_sha256` for the exact normalized
instrumentation overlay, which includes the bound `selection_sha256`, plus
`meta.workflow_mode: instrumentation_child`.
Repair every binding, digest, ID order, status, or evidence error before finalizing.
When executed verification reports `not_working`, do not treat successful JSON
validation or HTML rendering as completion. Apply the pre-finalization repair
gate from `SKILL.md`: classify every failure, make a concrete repair for each
safe in-scope instrumentation-owned failure, update the
instrumentation change/test/evidence rows, and automatically re-run the
affected verification scenarios. The failed overlay is an intermediate
artifact until the repair loop passes or reaches an evidenced stop boundary.
After a repair passes, replace every superseded failure status, repair action,
trace ID, and run-level next step in the final overlays. Retain prior attempts
only as explicitly superseded technical evidence under `.observe/evidence/`;
never leave them in the current reader summary or next action.
After the current child overlay has no executed failures and is marked
`lifecycle: final`, run:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" instrumentation-final-gate \
  .observe/otel-audit.json \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json \
  --verify-json .observe/otel-verify.json
```

This gate may pass a `Partial` proof result with zero executed failures; it
rejects missing/stale instrumentation binding, standalone mode, intermediate
child state, or any `not_working` result. Do not finalize until it passes.
Leave `.observe/otel.html` as the audit and scope-planning surface; never render the
instrumentation or verification overlays into it.
