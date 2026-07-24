# Instrumentation Repair Loop

Load this reference only after source viability or child verification records
an executed failure. It governs ownership classification, repair, recheck, and
the current-state overlay.

## Contents

- Failure ownership
- Repair and confirmation
- Overlay freshness
- Stop boundaries
- Delivery and full-runtime reconciliation

## Failure Ownership

Treat verification as a repair loop, not a terminal handoff. Before finalizing
any `Fail` result or run with a `not_working` finding, scenario, or telemetry
item, build this table in working notes:

`failure -> failing source/config -> selected finding -> ownership -> evidence`

Classify a failure as **instrumentation-owned** when:

- the current instrumentation diff introduced or modified the failing behavior;
- wiring, provider, dependency injection, runtime configuration, or a test seam
  required by the current instrumentation change is missing or incorrect; or
- a pre-existing OTel code/config defect inside dependency-closed selected
  scope prevents a selected telemetry outcome from working.

Do not classify unrelated business logic, an unselected feature, an external
service failure, unavailable credentials, or a live-platform outage as
instrumentation-owned merely because verification encountered it. Cite the
changed hunk, selected OTel source/config, or direct runtime evidence for every
decision. When Git or a saved pre-run snapshot exists, compare the failing path
with that baseline: an unchanged selected OTel wiring defect is pre-existing
but instrumentation-owned, not introduced by the current diff. Uncertainty
alone is not evidence that repair is out of scope.

## Repair And Confirmation

For every safe, in-scope instrumentation-owned failure, make a concrete
code/config repair and continue until the affected check passes or an evidenced
stop boundary is reached. One failed repair attempt is never completion. Add or
strengthen the smallest repo-native regression test that would have caught the
failure when a practical seam exists. Rerun affected compile/focused-test gates,
then invoke verification for the affected scenarios.

Continue while an iteration can make a safe in-scope change or gather evidence
needed to choose one. Never repeat an unchanged verification command and call
it a repair. Do not ask the user to invoke `$otel-instrument` again, relabel an
executed failure as `not_proven`, or finalize at the first failed check. A
failed child overlay written during this loop is intermediate, not the final
handoff. Do not finalize while a safe in-scope instrumentation-owned failure
remains.

Keep repair and confirmation distinct. The repair action names the application
code/config change `$otel-instrument` makes. `$otel-verify` only confirms the
changed behavior; it never performs repair. Invoke that confirmation inside
this workflow. Do not render it as a second user action or another repair
bullet. Exact scenario IDs are verifier-owned scope, not manual user steps.

## Overlay Freshness

The final overlays are current-state artifacts, not an attempt log. After a
repair succeeds, replace superseded failure statuses, repair actions, trace
IDs, and run-level next steps with the latest result. Do not expose an old
failure or repair CTA on the first screen. If history is useful, retain it only
as explicitly superseded technical evidence under `.observe/evidence/<run>/`.

Before invoking verification in canonical flow, write instrumentation JSON and
follow `Validate And Render Instrumentation` in
`json-approval-handoff.md`. Repair validation failures and pass the same
selection; never broaden the handoff. Instrumentation `next_steps` and finding
`follow_up_actions` must already be durable implementation or product actions,
not instructions to run or continue the child verifier.

For every iteration preserve this order:

1. Repair application code/config.
2. Update exact instrumentation change/source/test/evidence rows.
3. Rerun compile and focused tests.
4. Invoke affected verification scenarios.
5. Replace the current verification overlay.

The verifier must bind `instrumentation_sha256` to the updated normalized
instrumentation overlay, which transitively includes `selection_sha256`. Never
reuse proof from an earlier overlay merely because finding or item IDs match.

## Stop Boundaries

Stop only when repair needs unselected work, a material behavior choice, new
authority, or a concrete external prerequisite. Name the exact boundary and
evidence rather than saying verification is pending.

If a child remains `not_working`, preserve `lifecycle: intermediate`, the
executed failure, repair-only finding `remaining`, and repair-only top-level
`next_steps`. Record the boundary separately in `stop_boundaries[]` with its
affected failed finding IDs, bounded `kind`, declarative `reason`, external or
user `required_action`, and durable `evidence`. Keep instrumentation
`meta.result: Fail` and the finding `not_working`; a boundary never turns an
observed telemetry failure into `Blocked` or `not_proven`.

## Delivery And Runtime Reconciliation

Before finalizing, reconcile delivery wording across overlays. An item whose
`product_view` denies an OTLP pipeline/export path cannot be paired with
`otlp_accepted` or `explorer_visible`. Distinguish “no application-owned
exporter was added” from an evidenced agent- or platform-owned export path.

Record the verification result and `.observe/otel-verify.md` path in the
instrumentation Markdown. If verification cannot run, record the exact blocker
and do not call instrumentation verified. When verification JSON exists,
validate and render the complete flow, then refresh instrumentation HTML. Never
render downstream state into `.observe/otel.html`.

When a claim depends on auto-instrumentation startup, framework route
resolution, automatic metrics, duplicate automatic-span prevention,
startup/exporter wiring, or runtime-installed OTLP logs, read
`../../references/full-runtime-acceptance.md`. Apply its one-shot loopback-bind
`scripts/probe_loopback_bind.py` preflight before creating a listener-dependent
receiver/harness. Attempt the
gate without asking when a safe local profile/fixture exists and the preflight
passes. Otherwise record the exact unavailable runtime, listener, dependency,
credential, or fixture. `Not run` or “no collector was run” alone is not a
blocker. Do not finalize while a safe local profile exists and the required
gate has not been attempted.
