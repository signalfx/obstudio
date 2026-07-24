# JSON Selection Handoff

Use this reference when `.observe/otel-audit.json` exists or the user supplies
finding IDs. It defines the deterministic executable-scope gate and machine handoff.
For that canonical JSON flow, this file is the scoped instrumentation and
reader-report authority. Do not also load `../../references/report-flow-contract.md`
unless a conditional downstream workflow explicitly requires an additional
field or rollup rule from it.

## Selection Gate

Before any application-code, dependency, runtime-config, or test edit:

1. Validate the audit:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate .observe/otel-audit.json
   ```

2. Accept finding IDs from one of these sources, in order:
   the user's current `$otel-instrument --ids OTEL-001,OTEL-002` request;
   otherwise the newest valid bound state found by `adopt-selection` across an
   existing `.observe/otel-selection.json`, embedded
   `.observe/otel-audit.json.review_selection`, or saved
   `otel-audit*.json`/`otel-selection*.json`; or, only for a bare/broad
   instrumentation request with no saved scope, deterministic `select --all`.
   Accept manual answers only from that bound handoff's `decision_answers` or
   the user's current repeatable `--decision OTEL-###=option-id` arguments; do
   not infer an answer from prose or from an executable ID. Do not infer
   selected scope from priority, severity, or an earlier request after a saved
   selection exists.
3. Unless Step 4 writes a fresh selection from current `--ids`, run
   `adopt-selection` before reporting a missing selection. Step 4a writes a
   fresh selection from `--all` only after adoption finds no saved scope for a
   bare or broad instrumentation request. The command is
   idempotent: it validates an existing `.observe/otel-selection.json`,
   extracts `review_selection` from `.observe/otel-audit.json`, or adopts the
   newest saved/downloaded audit or selection bound to the current audit ID and
   SHA-256 digest:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" adopt-selection \
     .observe/otel-audit.json \
     -o .observe/otel-selection.json \
     --scoped-out .observe/tmp/otel-selected-findings.json
   ```

   On a bare or broad instrumentation request, add `--all-if-empty` to this
   command. It preserves a nonempty saved selection; if the saved audit contains
   only decision answers, it uses those answers to select every now-eligible
   executable finding. If the required decision answer is still missing, it
   prints the same explicit `--decision OTEL-###=option-id` choices as
   `select --all` and still stops before edits.

   The helper searches the audit directory, the output directory, and
   `~/Downloads` for `otel-audit*.json` and `otel-selection*.json`, including
   browser-generated names such as `otel-audit (3).json` and
   `otel-selection (3).json`. It must validate the canonical audit before
   materializing `.observe/otel-selection.json`. If it prints `PASS:` or
   `wrote`, immediately run Step 5 and continue the same instrumentation run.
   Do not ask the user to move a download, save again, or rerun instrumentation
   after a successful adoption. If it reports that the audit is invalid, the
   blocker is the canonical audit, not missing selection; rerun or repair
   `$otel-audit` instead of bypassing the JSON gate. If it reports no matching
   saved audit state or selection, continue to Step 4a only when the current
   request is bare or broad instrumentation. Otherwise stop before edits, point
   the user to `.observe/otel.html`, summarize the selectable findings, and ask
   which IDs to include.
4. For user-provided IDs, create the selection and scoped input:

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
4a. For a bare or broad instrumentation request with no saved scope, create the
    selection from every currently eligible executable finding:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" select \
     .observe/otel-audit.json \
     --all \
     --decision OTEL-003=application-owned \
     -o .observe/otel-selection.json \
     --scoped-out .observe/tmp/otel-selected-findings.json
   ```

   Include repeatable `--decision` arguments only when they were supplied by the
   current user request or already existed in the bound audit/selection. If
   `select --all` exits with manual-decision options, stop before edits and show
   those exact `--decision OTEL-###=option-id` choices to the user. Do not choose
   between mutually exclusive telemetry owners, providers, propagation paths,
   or signal shapes. A `select --all` result with empty executable IDs does not
   authorize code or configuration edits.
5. Validate the bound selection:

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
6. Use only the scoped executable findings, dependencies, and referenced
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
  "next_steps": ["Review the route trace in the configured telemetry explorer after proof is available."]
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

Give every telemetry change a stable item ID beginning with its finding ID, for
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

Keep verification proof and remaining runtime work in the separately bound
`.observe/otel-verify.json`; do not duplicate them as new instrumentation
schema fields. Before creating the child overlay, author instrumentation
`next_steps` and finding `follow_up_actions` as durable implementation or
product actions, not an instruction to run `$otel-verify`. Once a child report
exists, the terminal `finalize-instrumentation` command rejects any stale
pending-verification CTA in those instrumentation fields. Repair that stale
parent handoff and rerun the child so its digest binds the corrected overlay;
never hand-edit the child digest.
The human instrumentation HTML must also avoid presenting `$otel-verify` as the
next user action. If child proof is absent, `Not run`, or blocked, say the
instrumentation run has not completed internal verification and name the
concrete prerequisite, repair, or product evidence gap. Do not claim rerunning
`$otel-verify` will repair or advance the instrumentation result; verification
is invoked inside `$otel-instrument` after the repair or prerequisite is
available.

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

Require item-specific evidence. Aggregate receiver counts, a differently named
signal, or a shared helper that never invokes the exact item are context only;
keep that item `not_proven`, render it as **Not proven** rather than
**Observed**, and say that the exact item was not directly observed. A
`not_proven` scenario with useful executed evidence remains incomplete; group
its trigger as **Focused evidence obtained** in coverage details, never as a
passed scenario or a request for “stronger proof.”

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
`render-instrumentation-html` with both the exact
`--instrumentation-json .observe/otel-instrumentation.json` and
`--verify-json .observe/otel-verify.json` paths. Do not infer the implementation
overlay from the verification file's directory.
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
Do not run `instrumentation-final-gate`, fixed-Go cleanup, or the final response
from this Step 5 reference. When the current child overlay has no executed
failures, it may become the candidate `lifecycle: final` overlay, but the parent
`SKILL.md` owns the actual gate only after mandatory Steps 6 and 7, applicable
Credential Safety work, requested downstream work, final review, and all other
validation finish. A child with `not_working` remains `lifecycle: intermediate`
until repaired or until the parent workflow records an evidenced stop boundary.
If the user explicitly opted out or a concrete prerequisite prevented a child
verify overlay, do not fabricate one and do not run
`instrumentation-final-gate`, which requires it. Preserve the overall result
derivation: when compile/focused implementation proof passed, keep
`meta.result: Partial` and the affected findings `not_proven`; do not set the
overall result to `Blocked` or `Not run` solely because child verification is
absent. Record `Verification: Not run` or `Verification: Blocked` plus the exact
reason in finding evidence, `next_steps`, and compatibility Markdown, then rerun the
`validate-flow` and `render-instrumentation-html` commands above without
`--verify-json`. This is preliminary Step 5 validation. The parent terminal
sequence reruns the applicable validation after every later report, safety,
review, and downstream requirement is complete.

When a child contains `not_working` and the repair loop reaches an evidenced
unselected-work, material-decision, new-authority, or external-prerequisite
boundary, preserve the child as `lifecycle: intermediate` and preserve the
executed failure. Keep finding `remaining` and top-level `next_steps`
repair-only. Record the boundary separately in top-level `stop_boundaries[]`:
use the affected failed `finding_ids`, one `kind` from `unselected_work`,
`material_decision`, `new_authority`, or `external_prerequisite`, a declarative
`reason`, the user or external `required_action`, and durable `evidence`. Keep
instrumentation `meta.result: Fail` and the affected finding `not_working`; do
not relabel observed failure as `Blocked` or `not_proven`. Validate and render
that stopped state with
`--verify-json`, then continue to the parent terminal sequence. This is a
stopped-failure handoff, not a completed or verified instrumentation result.
Leave `.observe/otel.html` as the audit and scope-planning surface; never render the
instrumentation or verification overlays into it.
