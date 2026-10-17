# Publish audit, instrumentation, and verification reports

Use the advertised MCP report writer for the current stage:

| Skill | Tool | Structured report |
|---|---|---|
| otel-audit | `observer_audit_report_write` | Canonical schema-v2 audit |
| otel-instrument | `observer_instrumentation_report_write` | Bound schema-v1 instrumentation overlay |
| otel-verify | `observer_verification_report_write` | Bound schema-v1 verification overlay |

Supply the existing absolute service `repoRoot` and the canonical JSON object as
`report`. Keep findings, decisions, source citations, item/scenario IDs, proof
modes, limitations and independent expectations unchanged. The existing audit,
selection and implementation prerequisites must be on the MCP server's filesystem.
The server validates their digest bindings, writes the canonical JSON, generates
the Markdown compatibility views and existing HTML, and returns a compact
receipt with file paths, hashes and a loopback HTML URL. Do not author duplicate
Markdown or HTML, or read generated documents back into context merely to copy
them. Preserve the skill's normal final-response contract: the compact tool
receipt does not replace required response headings, per-item tables or proof
qualifications. For `otel-verify`, retain `What Changed`, `Tested And Working`,
the individual-result table, `Not Working Or Not Proven`, and `Proof` in the
final response, including the explicit empty-inventory marker when applicable.
For `otel-instrument`, retain the finalization contract: finding closure counts,
explicit added/modified/removed/unchanged signal summaries, the absolute
`otel-verify.md` path when present, and the instrumentation report links. Derive
these summaries from the submitted canonical data; report publication does not
independently establish their correctness.
Copy the receipt's `links` verbatim; local-file targets are absolute and must not
be shortened to relative paths. Do not add further copies beyond the required
response contract. For an audit, use `links.review_report`
in the single `Review report: [otel.html](<url>)` line.

Pass `runId` only when this skill's recorder invocation is retained in this
Studio. The server links its measured report-write operation to that run.
Without it, the report operation still has its own server-created trace. A
report write establishes publication, not earlier analysis, application execution,
complete workflow duration or independently correct findings. `validated: true`
describes report validation, not application verification.

Supply substantive reader context as structured `details`, not Markdown:

- `summary`, `verificationHandoff`, `detectorHandoff`, `remainingGaps`, and
  `supplementalEvidence`: lists of concrete source/evidence-backed statements.
- `genaiClosure`: rows `[surface, required signals, implemented/proven, tests,
  remaining signals, result]`. Required for audited GenAI ownership.
- `incidentRoles`: rows `[surface, exact signal, role, detector use/reason,
  proof, remaining owner/prerequisite]`. Required for audited incident readiness.
- `validationGates`: rows `[gate, command/check, result/evidence]`.
- `runtimeDependencies`: rows `[runtime, configuration source, resolved
  dependencies, command, result/evidence]`.

The stage's existing source, compatibility, GenAI, incident, privacy and proof
requirements still apply. Publication does not supply missing evidence, run
tests or invoke the optional correctness evaluator. Never change a failed or
unproven status to make rendering succeed. Keep unknown correctness separate.
Finish the runtime/endpoint, scenario, reader-context and optional correctness
reconciliation before publishing the complete payload. Put bounded-proof
qualifications in `summary` and missing capture, witness, runtime, explorer or
cloud prerequisites in `remainingGaps`; do not bury them only in diagnostics.
Submit the completed packet once. If later evidence requires a correction,
republish through the same tool and preserve that revision rather than patching
generated Markdown or HTML.

Discover tools once. If the host does not advertise them and
`OBSTUDIO_SKILL_MCP_ENDPOINT` explicitly names a loopback MCP endpoint, use
`tools/list` then `tools/call`. Respect `none`; do not guess ports or change
provider telemetry settings or host configuration.

When the tool, server filesystem, compatible Python runtime or transport is
unavailable, use the same bundled `scripts/report_writer.py` engine from the
shared references directory with a JSON request on stdin (`kind` is `audit`,
`instrumentation` or `verification`, plus `repoRoot`, `report`, optional
`details` and `serve`). Original report CLI commands remain compatible.
Explicit direct baseline instrumentation without a canonical audit retains
its documented local path; do not manufacture an audit or approval scope.
Do not use fallback to bypass invalid input, stale bindings or evidence errors:
repair the inputs or report the blocker. `serve: false` writes offline files.
If serving is unavailable, use the existing local-file fallback and do not
repeatedly retry a denied bind.

Retries of unchanged inputs reuse the artifact receipt. Existing bound
downstream reports prevent silently replacing their audit baseline; explicitly
resolve or archive the old flow first. Verification refreshes its own reports
and the instrumentation views while preserving audit HTML and human selection.
