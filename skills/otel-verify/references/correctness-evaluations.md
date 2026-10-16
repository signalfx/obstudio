# Evaluate finding and instrumentation claims

Use this optional path when the project or user supplies a correctness contract
for `observer_skill_correctness_evaluate`, for example
`.observe/otel-correctness.json`. Discover the tool before calling it. Keep the
existing application tests, canonical report schemas, approval scope, and offline
verification behavior. Do not require Studio or change application code merely
to obtain this optional score.

## Expectations and evidence

Read the supplied contract and identify its author/source. It maps stable audit
finding IDs and verification scenario IDs to explicit expected telemetry. Prefer
an existing application test, independently maintained fixture, or user-reviewed
contract. A contract generated from the skill's own report cannot independently
establish correctness. Do not generate a contract by copying observed signals
and calling the resulting match proof; do not weaken expectations to make a run
pass. Source/configuration review and rubric judgment remain separate evidence.

Bind `runId` to the recorded skill invocation, `auditSha256` and optional
`instrumentationSha256` to the canonical report digests, and `sourceRevision` to
the tested source's `service.version`. Preserve the supplied finding/scenario
mapping and rule definitions. These digests identify inputs; the MCP tool does
not read local files or authenticate their contents.

The tool evaluates an atomic snapshot of retained application telemetry. Its
input contains 1–8 scenarios and at most 32 uniquely named rules overall. Each
scenario selects an exact application trace, harness witness span, and service:

```json
{
  "runId": "<recorded 32-hex run ID>",
  "auditSha256": "sha256:<canonical audit digest>",
  "sourceRevision": "<tested service.version>",
  "scenarios": [{
    "id": "tasks.create",
    "traceId": "<application trace ID>",
    "witnessSpanId": "<harness witness span ID>",
    "serviceName": "tasks",
    "rules": [{
      "name": "tasks.server.correct",
      "findingId": "OTEL-001",
      "claim": "instrumentation",
      "signal": "span",
      "signalName": "POST /tasks",
      "count": 1,
      "kind": "SERVER",
      "attributes": {"http.route": "/tasks"}
    }]
  }]
}
```

`claim: instrumentation` passes when the scenario satisfies the expected
contract. `claim: audit_gap` passes when that same expectation is violated,
supporting a specific claimed gap in the tested scenario. A conforming capture
refutes that gap. Neither proves all audit findings or all application paths.

Span rules accept exact `kind`, `status`, `parentName`, and scalar `attributes`.
Metric rules require `metricType` and `unit`, and may assert scalar attributes
plus `minValue`/`maxValue` for gauge/sum values. Histogram/summary checks require
a nonempty measurement. Log rules select `signalName` by the `event.name`
attribute, require `severity`, and may check attributes and `parentName` (the
owning application span name). Log correlation must resolve to a captured app
span. `count` means exact captured spans, datapoints, or log records, not total
business events, counter deltas, or statistical coverage.

## Independent harness capture

An existing test/harness should execute the actual application path and capture
all SDK-ended spans, datapoints, and logs for that isolated scenario. After the
scenario and synchronous exports finish, it emits an enclosing witness span
with scope `obstudio.verification`, status `OK`, matching service/version, and:

- `verification.run_id`: recorded skill run ID.
- `verification.scenario`: exact scenario ID.
- `verification.proof_mode`: `app_test` or `app_runtime`.
- `verification.completed`: true only after the trigger and capture finish.
- `verification.span_ids`: all captured application span IDs in this trace,
  excluding the witness; an empty array explicitly records no application spans.
- `verification.metric_count` and `verification.log_count`: exact captured counts
  for those signals; zero is distinct from an absent manifest field.

Use a dedicated scenario trace/service/version. The witness interval encloses
all records. Metric datapoints carry `verification.run_id` and
`verification.scenario` to avoid grading unrelated aggregate series. Logs carry
the scenario trace ID and owning app span ID. The witness's manifests must come
from the completed capture, never from expected rules or the skill's report.

The producer declares source, execution mode, and capture completeness. The tool
checks consistency and actual retained signals; it cannot authenticate that a
producer ran app code or that a contract author was independent. Preserve this
trust boundary in the report. A generated SDK-only example uses
`contract_only`; it cannot receive an application-correctness score. Do not
fabricate witness spans, manifests, source revisions, or proof modes.

## Interpret and publish

Unknown includes absent/stale witnesses, source/run mismatch, contract-only
captures, missing manifests, and retained data that differs from the manifest
(including eviction or partial export). Do not replace unknown with a numeric
pass. A closed capture with no expected signal can fail instrumentation and
support the corresponding audit gap; silence without capture proof cannot.

Determinate results become `gen_ai.evaluation.result` events linked to the skill
workflow and application witness. They include finding/scenario IDs, proof
mode, and an immutable receipt over expectations and retained evidence. They do
not change the recorder's workflow outcome or measure evaluator latency.

Record the tool result or exact unavailable prerequisite in the verification
report. Explain any contradiction with a prior reported success and map it to
the affected finding/scenario. Keep unproven optional evaluations separate from
existing independent app-test/runtime proof; an unavailable optional tool does
not invalidate that proof. Continue the ordinary verification workflow if this
tool or its prerequisites are unavailable. Never invent a passing event.
