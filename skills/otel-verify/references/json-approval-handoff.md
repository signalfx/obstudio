# JSON Approval Handoff

Use this reference when `.observe/otel-audit.json` exists or the user supplies
finding IDs. It binds verification to the approved instrumentation scope.
For canonical JSON flow, this file owns the approved scope, verification
schema, digest binding, status rollup, and instrumentation HTML refresh.

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
     -o .observe/otel-selection.json
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

   Selection-only validation can guide a direct read-only run when the
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
  "next_steps": []
}
```

Use `meta.workflow_mode: standalone` and `meta.lifecycle: final` for a direct
verification request. A child invoked by `$otel-instrument` uses
`instrumentation_child`; when an executed failure remains, keep
`lifecycle: intermediate`, finding `remaining`, and top-level `next_steps`
repair-only. If the parent repair loop must stop, record the external boundary
separately:

```json
{
  "stop_boundaries": [
    {
      "finding_ids": ["OTEL-001"],
      "kind": "external_prerequisite",
      "reason": "The locked dependency registry rejected the configured credential.",
      "required_action": "Renew repository access for the locked dependency restore.",
      "evidence": [".observe/evidence/run/dependency-restore.log"]
    }
  ]
}
```

`kind` is one of `unselected_work`, `material_decision`, `new_authority`, or
`external_prerequisite`. A stop boundary never relabels an executed failure as
`Blocked` or `not_proven`.

Copy `audit_id` and `audit_sha256` from the selection. Obtain the canonical
`instrumentation_sha256` exactly once from the active bundle:

```bash
python3 -I "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" instrumentation-digest \
  .observe/otel-audit.json \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json
```

Copy that command's digest into the verification overlay. Any material
instrumentation change, including change text, source, tests, or evidence,
invalidates prior verification even when item IDs are unchanged. The digest
also binds the exact normalized selection through `selection_sha256`.

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

Preserve proof provenance. When a focused test or other lower-level check ran,
retain its executed `proof_mode`, evidence, and `observed_telemetry`; do not
change it to `not_run`. Direct item proof may coexist with incomplete scenario
coverage. Source/config presence or ambiguous absence is not runtime proof. The
instrumentation HTML presents scenario triggers as neutral coverage context,
not as a stronger-proof ladder or completion checklist.

Write one `item_results` row for every instrumentation
`telemetry_changes[].id`, in instrumentation order. The validator derives this
inventory from `.observe/otel-instrumentation.json`; it rejects missing,
duplicate, unknown, or reordered item IDs. A working item must cite its audit
scenario(s), direct evidence, observed telemetry, product validation, proof
mode, and visibility. This per-item join is the authoritative scalable mapping
from code/config change to telemetry to product result to proof.

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
```

The shared validator requires instrumentation JSON whenever verify JSON is
present. Repair every binding, ID/order, scenario coverage, status, or evidence
failure before finalizing.

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

Never print raw trace IDs or span IDs in that human HTML, including identifiers
embedded in `observed_telemetry`. Render **the generated trace** and the named
span or signal instead. Preserve exact identifiers in canonical `trace_ids`,
durable evidence, and Markdown `Technical Details` for reproducibility.
