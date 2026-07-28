# JSON Approval Handoff

Use this reference when `.observe/otel-audit.json` exists or the user supplies
finding IDs. For canonical JSON flow, this file owns executable selection,
instrumentation JSON, digest binding, and instrumentation HTML.

## Selection Gate

Before any application-code, dependency, runtime-config, or test edit:

1. Validate the audit:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" validate .observe/otel-audit.json
   ```

2. Accept finding IDs from one of these sources, in order:
   the user's current `$otel-instrument --ids OTEL-001,OTEL-002` request;
   otherwise a trusted repository state from an existing
   `.observe/otel-selection.json` or selected audit saved inside `.observe/`;
   otherwise an explicitly supplied saved-audit candidate; otherwise an
   automatically discovered matching saved
   audit only when no trusted repository selection exists; or, only for a bare/broad
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
   extracts `review_selection` from a selected audit copy, or adopts a
   saved/downloaded audit bound to the current audit ID and SHA-256 digest only
   when no trusted repository state takes precedence:

   ```bash
   python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" adopt-selection \
     .observe/otel-audit.json \
     -o .observe/otel-selection.json
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
   materializing `.observe/otel-selection.json`. Repository state outranks
   ambient downloads regardless of modification time; use an explicit
   candidate when the reviewer intentionally replaces existing repository
   scope. If it prints `PASS:` or
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
     -o .observe/otel-selection.json
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
     -o .observe/otel-selection.json
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
          "consumer_compatibility": {
            "status": "compatible",
            "existing_contract": ["existing dashboards group by route"],
            "instrumentation_action": "Added http.route while preserving existing safe route grouping.",
            "user_impact": "Existing consumers keep working while OTel-semantic route views become available.",
            "migration": []
          },
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
`Partial`, `Fail`, or `Blocked` for instrumentation `meta.result`; represent
skipped, not-run, or unavailable verification as `Partial` with affected
findings left `not_proven`, `not_configured`, or `deferred`; do not emit
`Not run` for instrumentation `meta.result`. Use `working`, `not_working`,
`not_proven`, `not_configured`, or `deferred` for finding status; and `span`,
`metric`, `log`, `resource`, or `configuration` for telemetry type.
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
product follow-up. Preserve each audit-authored attribute exactly: a key-only
promise stays key-only, while `key=value` keeps that exact bounded value. These
stable item IDs are the inventory that verification must cover exactly; a
free-text `changes` list is not a substitute.

For every telemetry item that changes, removes, renames, or replaces an
existing metric dimension, span attribute, span name, resource attribute, log
field, exporter setting, or metric name that existing dashboards, detectors,
entity mappings, alerts, or queries may consume, add `consumer_compatibility`.
Use:

```json
{
  "status": "compatible | breaking | requires_review",
  "existing_contract": ["metric foo dimension path"],
  "instrumentation_action": "Removed raw path and added bounded http.route.",
  "user_impact": "Dashboards grouped by path need migration.",
  "migration": ["Update filters from path to http.route."]
}
```

Use `compatible` when safe old names/dimensions are preserved while OTel
semantic fields are added. Use `breaking` when a consumer-visible contract is
removed, renamed, or changes meaning, including intentional removal of unsafe
high-cardinality dimensions. Use `requires_review` when source proves an
existing contract but the downstream consumers cannot be determined. A breaking
item must name the migration. Do not hide this information in `change` or
`product_view`; the human HTML renders it as **Consumer compatibility** under
the affected issue and summarizes the breaking count at the top.

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
schema fields. Author instrumentation `next_steps` and finding
`follow_up_actions` as durable implementation or product actions, never as an
instruction for the user to rerun `$otel-verify`. The human HTML must name the
concrete remaining repair, runtime prerequisite, or product-evidence step.

Render every selected finding once in the instrumentation HTML. Show all of its
finding-level `changes` values and use the bound audit finding's
`product_outcome` for **How it improves observability**. Do not keep only the
first N findings, collapse findings into themes, or substitute a component
summary. Keep a proof-first finding in this list even when its
`telemetry_changes` is empty. When verification proof is bound, render an
issue-local **Telemetry proof** table with `Telemetry change`, `What was
observed`, and `Status` columns for that finding's exact telemetry items.

Keep the human HTML concise. Start with one verification-state heading and one
proof-and-delivery sentence, followed immediately by every selected finding.
When verification is `Partial` with no `not_working` finding, use
**Verification incomplete — no observed failures** and state **X of Y telemetry
changes are proven**. State separately whether local OTLP delivery and Splunk
Observability Cloud were checked. Render canonical `not_proven` as
**verification incomplete** while preserving the machine value. Do not infer
merge readiness from these overlays without an explicit merge policy.

Do not render aggregate statistic cards, global code-to-telemetry mappings,
global item-proof ledgers, finding-level closure rows, or scenario proof in the
HTML. Preserve those complete technical records in
`.observe/otel-instrumentation.json`, `.observe/otel-instrumentation.md`,
`.observe/otel-verify.json`, and `.observe/otel-verify.md`. Removing those
duplicate HTML sections must not remove or weaken any canonical field,
validation rule, digest binding, or downstream proof handoff.

Do not render raw trace IDs or span IDs in the human HTML, even when they occur
inside `observed_telemetry`. Use **the generated trace** and a named span or
signal in reader prose. Preserve the exact identifier in verification
`trace_ids`, durable evidence, and Markdown `Technical Details` when needed.

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
The render command starts or reuses the restricted loopback report server and
returns browser-safe links for both `otel-instrumentation.html` and
`otel.html`. Use those HTTP links in the final response without opening them
automatically. Keep Markdown and JSON artifacts as absolute local-file links.
When a verify overlay is available, require its `instrumentation_sha256` to
match the exact normalized instrumentation overlay, including the bound
`selection_sha256`. Repair every binding, digest, ID-order, status, or evidence
error before rendering the reader report.
Leave `.observe/otel.html` as the audit and scope-planning surface; never render the
instrumentation or verification overlays into it.
