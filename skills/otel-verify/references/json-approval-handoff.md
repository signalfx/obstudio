# JSON Approval Handoff

Use this reference when `.observe/otel-audit.json` exists or the user supplies
finding IDs. It binds verification to the approved instrumentation scope.
For that canonical JSON flow, this file is the scoped verification and
reader-report authority. Do not also load `../../references/report-flow-contract.md`
unless a conditional downstream workflow explicitly requires an additional
field or rollup rule from it.

## Scope Gate

1. Validate `.observe/otel-audit.json`:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate .observe/otel-audit.json
   ```

2. Use `.observe/otel-selection.json` or exact IDs from the user's current
   `$otel-verify --ids OTEL-001,OTEL-002` request. For user-provided IDs, run:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" select \
     .observe/otel-audit.json \
     --ids OTEL-001,OTEL-002 \
     -o .observe/otel-selection.json \
     --scoped-out .observe/tmp/otel-selected-findings.json
   ```

   Do not hand-edit or merge selections. If neither IDs nor a selection exists,
   stop and ask the user to approve findings in `.observe/otel.html`.
3. Require `.observe/otel-instrumentation.json` from the same selection and
   validate the available flow:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate-flow \
     .observe/otel-audit.json \
     --selection-json .observe/otel-selection.json \
     --instrumentation-json .observe/otel-instrumentation.json
   ```

   Selection-only validation can guide a legacy read-only run when the
   instrumentation JSON is absent, but do not write `.observe/otel-verify.json`
   or claim a complete canonical flow. Route the user to `$otel-instrument` for
   the bound machine handoff.
   The instrumentation overlay's `selection_sha256` must match the exact
   normalized selection. A changed `decision_answers` entry is stale even when
   `approved_ids` is unchanged.
4. Verify exactly the approved findings in audit order, their expected
   telemetry, and referenced scenarios. Unselected findings are outside this
   result and must not make it partial.

## Verification JSON

Write `.observe/otel-verify.json` with this shape:

```json
{
  "schema_version": 1,
  "kind": "otel-verify",
  "audit_id": "audit-id-from-selection",
  "audit_sha256": "audit-sha256-from-selection",
  "instrumentation_sha256": "sha256-of-normalized-instrumentation-overlay",
  "meta": {
    "service_name": "example-service",
    "date": "2026-07-17",
    "result": "Partial",
    "workflow_mode": "standalone",
    "lifecycle": "final"
  },
  "findings": [
    {
      "id": "OTEL-001",
      "status": "working",
      "scenarios": [
        {
          "id": "http.health.success",
          "status": "working",
          "commands": ["go test ./..."],
          "evidence": [".observe/evidence/http-health.json"],
          "observed_telemetry": ["span GET /health with http.route=/health"],
          "trace_ids": ["4bf92f3577b34da6a3ce929d0e0e4736"],
          "product_validation": ["Trace waterfall shows route latency."],
          "proof_mode": "full_runtime",
          "visibility": "explorer_visible"
        }
      ],
      "item_results": [
        {
          "id": "OTEL-001.http-server-span",
          "status": "working",
          "direct_assertion_passed": true,
          "scenarios": ["http.health.success"],
          "proof_mode": "full_runtime",
          "visibility": "explorer_visible",
          "evidence": [".observe/evidence/http-health.json"],
          "observed_telemetry": ["span GET /health with http.route=/health"],
          "product_validation": ["Trace waterfall shows route latency."]
        }
      ],
      "remaining": []
    }
  ],
  "stop_boundaries": [],
  "next_steps": []
}
```

Copy `audit_id` and `audit_sha256` from the selection. Obtain the canonical
`instrumentation_sha256` exactly once from the active bundle:

```bash
python3 -I "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" instrumentation-digest \
  .observe/otel-audit.json \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json
```

Copy only that command's digest into the verification overlay. Never import
report-helper internals, search for another helper installation, or calculate
or repair the digest manually. The command normalizes the exact instrumentation
overlay used to derive expected items and proof. Any material instrumentation change,
including change text, source, tests, or evidence, invalidates prior
verification even when item IDs are unchanged. The instrumentation digest also
contains `selection_sha256`, so verification is transitively bound to the exact
normalized selection without a redundant second selection hash.

Use `meta.workflow_mode: standalone` for a user-invoked verification and
`instrumentation_child` when an active `$otel-instrument` workflow invoked it.
Use `meta.lifecycle: intermediate` only for a failed child repair packet; all
standalone artifacts and the post-repair child artifact use `final`. A failed
child artifact cannot be final.

Use only `Pass`,
`Partial`, `Fail`, `Blocked`, or `Not run` for `meta.result`; `working`,
`not_working`, `not_proven`, `not_configured`, or `deferred` for finding status;
and `working`, `not_working`, `not_proven`, `not_configured`, or `blocked` for
scenario status. Findings must exactly equal approved IDs in audit order.
Any `not_working` finding, scenario, or item requires top-level `Fail`; a
`Fail` result requires at least one `not_working` finding. An executed nested
failure also makes its finding `not_working`, and a `not_working` finding must
contain at least one executed failed scenario or item with direct evidence.
When every mapped child is working and no work remains, the finding and
top-level result must be `working` and `Pass`; do not author an all-working
`Partial`. Use `Blocked` only for a concrete
unavailable prerequisite, not for an instrumentation-owned compile, startup,
or telemetry failure. Derive the aggregate from both scenario and item proof:
`Partial` when any meaningful check ran and unresolved work remains, `Blocked`
only when no meaningful check ran and a structured blocker prevented it, and
`Not run` only when neither scenarios nor telemetry items contain executed
proof.
Include one scenario object for every scenario referenced by each finding. A
`working` finding must list exactly the audit's scenario IDs, all required
scenarios must be working, and `remaining` must be empty. A working scenario
requires direct evidence, observed telemetry, product validation, an executed
`proof_mode`, and an explicit visibility state. Preserve empty `trace_ids` when
unavailable; never invent values.

`otlp_accepted` and `explorer_visible` are evidence claims even when the row is
not yet working: require an executed proof mode, durable evidence, observed
telemetry, and product validation before using either. Do not use a visibility
enum as a substitute for saved delivery evidence.

Also reconcile the claim with the matching instrumentation item's
`product_view`. Reject `otlp_accepted` or `explorer_visible` when that field says
no OTLP pipeline or export path exists. A statement that no *application-owned*
exporter was added is different: an evidenced agent- or platform-owned OTLP
path may still satisfy delivery proof.

Use only `app_test`, `unit`, `unit+otlp`, `full_runtime`, `contract_only`,
`static`, or `not_run` for `proof_mode`. Use only `explorer_visible`,
`otlp_accepted`, `not_explorer_visible`, `not_proven`, or `not_applicable` for
`visibility`. Unit proof may be working while `not_explorer_visible`; do not
inflate it into an explorer claim. An `explorer_visible` result must cite saved
query or Observer evidence.

For every scenario with `status: blocked`, require nonempty
`blocking_reason` and `unobserved_outcome` strings. `blocking_reason` is the
exact prerequisite failure, written in past or present tense and supported by
the scenario's command/evidence. `unobserved_outcome` is the exact runtime,
OTLP-delivery, or product observation that could not be captured. Omit both
fields for non-blocked scenarios. Keep remediation in finding `remaining` or
top-level `next_steps`; do not make the renderer infer a cause from an action.

Preserve proof provenance. When a focused test or other lower-level check ran,
retain its executed `proof_mode`, evidence, and `observed_telemetry`; do not
change it to `not_run`. A direct successful unit, application, or runtime
observation makes the matching telemetry `item_results` row `working`, even
when the finding remains `not_proven` because other scenarios were not
exercised. Source/config presence and an unbounded or ambiguous absence do not
qualify. A bounded expected-absence assertion for a removed item is governed by
the direct-assertion rule below. The instrumentation HTML presents scenario triggers as neutral
coverage context rather than a stronger-proof ladder or completion checklist.

Write one `item_results` row for every instrumentation
`telemetry_changes[].id`, in instrumentation order. The validator derives this
inventory from `.observe/otel-instrumentation.json`; it rejects missing,
duplicate, unknown, or reordered item IDs. A working item must cite its audit
scenario(s), direct evidence, observed telemetry, product validation, proof
mode, and visibility. This per-item join is the authoritative scalable mapping
from code/config change to telemetry to product result to proof.

Set the required boolean `direct_assertion_passed` before rolling up scenario
or finding coverage. It is `true` only when a saved unit, application, or
runtime assertion directly exercises the exact telemetry item or call site and
passes. For a `change_kind: removed` item, a bounded capture can set it `true`
only when it explicitly proves both the removed signal's absence and the
intended replacement owner's presence. Aggregate receiver counts, a different
signal, source/config presence, or a helper that never invokes the exact item
must set it `false`. The validator requires `direct_assertion_passed: true`
exactly when item `status` is `working`; incomplete finding or scenario coverage
cannot change either value. An executed direct failure remains `not_working`
with `direct_assertion_passed: false`.

A working removed item also requires this structured field so the two halves
of the assertion cannot collapse into a generic evidence sentence:

```json
"removal_proof": {
  "removed_signal": "HttpRequest",
  "replacement_signal": "GET /health",
  "absence_assertion_passed": true,
  "replacement_assertion_passed": true
}
```

`removed_signal` must exactly match the instrumentation item's `name`;
`replacement_signal` must name a distinct intended owner of the removed item's
signal type; its proof must use that type explicitly. Keep the saved
capture in `evidence` and the reader-friendly observation in
`observed_telemetry`.

This required field intentionally fails closed. Regenerate any older
`otel-verify` overlay that does not contain it; do not infer the value from the
old item status. The overlay remains schema version 1 because this is a
validation tightening of the still-evolving canonical flow, not a second
accepted wire format.

For each `not_working` finding, put the concrete observed failure in its failed
scenario's `observed_telemetry`. Use finding-level `remaining` only for the
repair-only plan: the concrete in-scope application code/config change that
`$otel-instrument` must make now. Do not append the verification rerun, proof
capture, or product inspection as another repair action. For `Fail`, use
top-level `next_steps` for the same immediate repair only. Do not describe a
failed row as pending, and do not turn exact scenario IDs or counts into manual
user instructions. `$otel-verify` never repairs application code; the scenario
mapping retains the affected confirmation scope. When verification is called
from instrumentation, return the result to that repair loop; after the repair,
the instrumentation workflow automatically invokes `$otel-verify` to confirm
the result instead of asking the user to start either workflow again.

When a failed `instrumentation_child` repair loop cannot continue because it
reached unselected work, a material decision, new authority, or an external
prerequisite, keep `remaining` and `next_steps` repair-only and add a separate
top-level boundary entry:

```json
"stop_boundaries": [
  {
    "finding_ids": ["OTEL-001"],
    "kind": "external_prerequisite",
    "reason": "Artifactory authentication is expired.",
    "required_action": "Restore Artifactory authentication for the locked dependency source.",
    "evidence": [".observe/evidence/runtime/dependency-restore.txt"]
  }
]
```

The allowed `kind` values are `unselected_work`, `material_decision`,
`new_authority`, and `external_prerequisite`. The validator accepts this field
only for `workflow_mode: instrumentation_child`, `result: Fail`, and
`lifecycle: intermediate`; every `finding_ids` value must identify a failed
finding. `reason` states the cause, `required_action` states the user or
external action that unblocks the parent, and `evidence` contains durable
proof. Omit `stop_boundaries` when the child is still an ordinary repair packet
or after the repair succeeds.

For a child invocation from an active instrumentation workflow, the canonical
failure fields are the repair packet: failed finding, item, and scenario IDs;
direct evidence; and repair-only `remaining`/`next_steps`. Mark that failed
artifact `workflow_mode: instrumentation_child` and `lifecycle: intermediate`.
Write and validate the artifacts, then return control without presenting a
terminal user handoff.
The parent instrumentation workflow owns classification and mutation. For a
standalone invocation, remain read-only and present `$otel-instrument` as the
single repair workflow. Never let invocation mode change verification evidence,
statuses, or scenario coverage.

The final verification overlay is current state. After a repair succeeds,
remove superseded failure observations, repair actions, trace IDs, and run-level
next steps from the final JSON. Preserve prior attempts only as explicitly
superseded evidence files; they are not current `remaining` work.

## Validate And Render

After the Markdown reader validator passes, run:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate-flow \
  .observe/otel-audit.json \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json \
  --verify-json .observe/otel-verify.json

python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" render-instrumentation-html \
  .observe/otel-audit.json \
  -o .observe/otel-instrumentation.html \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json \
  --verify-json .observe/otel-verify.json

# Active $otel-instrument child only, after the post-repair overlay is final:
python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" instrumentation-final-gate \
  .observe/otel-audit.json \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json \
  --verify-json .observe/otel-verify.json
```

The shared validator requires instrumentation JSON whenever verify JSON is
present. Repair every binding, ID/order, scenario coverage, status, or evidence
failure before finalizing.
The final gate allows incomplete proof with zero executed failures, but rejects
an unbound, standalone, intermediate, or `not_working` child artifact. Do not
run it merely to convert an intermediate failure into a user-facing error;
return that repair packet to the active instrumentation workflow first.

The refreshed instrumentation HTML is the concise human proof surface. Start
with one verification-state heading and one proof-and-delivery sentence, then
list every selected finding with what changed, how observability improves,
telemetry-item proof, coverage, and any remaining uncertainty. Do not add
per-finding target-product or generic executed-check summaries; the report-level
proof-and-delivery sentence and concrete coverage details already own that
context. Do not add
aggregate statistic cards, code-to-telemetry mapping ledgers, closure ledgers,
scenario-proof tables, or item-proof tables. Preserve their complete data in
`.observe/otel-instrumentation.json`, `.observe/otel-instrumentation.md`,
`.observe/otel-verify.json`, and `.observe/otel-verify.md`. Leave
`.observe/otel.html` as the audit and approval report.

Before **Coverage details**, replace a generic blocked count with **Runtime
verification unavailable**. Show the structured `blocking_reason` under **Why
runtime verification is unavailable**, mapped working item observations under
**Already proven**, and `unobserved_outcome` under **Still unobserved**.

Never print raw trace IDs or span IDs in that human HTML, including identifiers
embedded in `observed_telemetry`. Render **the generated trace** and the named
span or signal instead. Preserve exact identifiers in canonical `trace_ids`,
durable evidence, and Markdown `Technical Details` for reproducibility.
