# Explorer Witness Contract

Use this contract whenever verification claims that telemetry is visible in
Obstudio or another local trace/metric/log explorer.

## Lifecycle

For local Obstudio, treat telemetry ownership as keyed to the emitting source
PID and potentially evicted as soon as that process disconnects unless a saved
post-exit query proves persistence. A Maven/Gradle parent process is not the
source when a Surefire/Failsafe/test-worker JVM emitted the telemetry.

1. Start the real app or app-code harness as a managed background process.
2. Emit a machine-detectable readiness marker only after providers are
   configured and the scenario has exported successfully.
   Verify each signal's effective endpoint/protocol/path; one successful
   exporter does not prove the others.
3. Keep the source process and providers alive while querying the explorer.
4. Query exact trace IDs and expected metric/log filters with bounded retries.
5. Save sanitized query responses under
   `.observe/evidence/<verification-run>/` before stopping the source.
6. Record the evidence paths, trace IDs, metric names, and query outcomes in
   `.observe/otel-verify.md`.
   Include exact metric units/dimension sets and effective service,
   environment, and version resource attributes.
7. Stop the source after evidence capture unless the user explicitly asks for
   an interactive held-open demo. If left running, report its PID and stop
   command.

Do not run a short-lived test JVM to completion and query Obstudio afterward.
Hold the emitting JVM open after the scenario and provider flush, query and
save evidence while that exact PID is alive, then release it to exit. A zero
post-exit query without a live witness is missing visibility proof, not proof
that the application emitted nothing.

Never place credentials, raw prompts/content, user/session/request IDs, or
other sensitive payloads in saved evidence. Trace IDs may be recorded as
technical proof but must not become metric dimensions.

## Unit+OTLP Contract Harness

- Configure real SDK tracer, meter, and logger providers before importing app
  modules that cache OTel globals.
- Export from the same focused fake-input scenario that performs deterministic
  assertions. Prefer one trace per path scenario and use stable attributes such
  as `verification.scenario`, `verification.path`,
  `verification.audit_source`, and `verification.coverage_kind`.
- Use only local/test endpoints such as HTTP `127.0.0.1:4318` or gRPC
  `127.0.0.1:4317`. Never export verification telemetry to production.
- Verify the effective endpoint, protocol, and path separately for traces,
  metrics, and logs. gRPC commonly uses `4317`; HTTP/protobuf commonly uses
  `4318/v1/<signal>`. A successful trace export does not prove the metrics or
  logs exporter.
- Assert effective resource attributes from collector data, including
  `service.name`, environment, and version. Source-level merge logic does not
  prove operator-provided values survive provider construction.
- For HTTP auto-instrumentation, assert the exact emitted request-duration
  metric and route dimensions. If stable semantic conventions were requested,
  require `http.server.request.duration`; an alternate source-level or unit-fake
  metric does not satisfy that runtime row.
- Mark `Verified: unit+OTLP` only when deterministic assertions and
  collector/explorer evidence both pass. If assertions pass but export is
  unavailable, use `Verified: unit`.

## Validation Classification

When the explorer also runs semantic-convention validation, preserve the raw
summary and classify every finding before using it as an application result:

- `actionable`: emitted telemetry violates the selected convention or expected
  contract; repair or report it.
- `registry mismatch`: the core Weaver registry marks GenAI/MCP fields as moved
  to a dedicated registry, rejects application-owned custom metrics or
  attributes, or rejects framework-owned fields such as `asgi.event.type`.
  Record this separately; the raw red/violation count alone does not prove the
  application failed.
- `library-owned compatibility`: official auto-instrumentation emits a shape
  the validator interprets differently, such as omitting `server.port` for a
  default HTTPS port. Record the package/version and affected signal; do not
  rewrite unrelated app telemetry merely to silence the finding.
- `stale`: telemetry arrived during validation because a periodic exporter was
  still running. Save the run id and evidence snapshot; freshness churn is not
  signal failure.

Report the raw validator summary, classification, and actionable application
finding count. Never hide findings or equate an unclassified advisory count
with verification status.

## Visibility States

- `Live explorer-visible`: the explorer query returned the signal while the
  source was alive.
- `Live explorer-visible (ephemeral)`: visibility was proven, and the local
  explorer is known to evict the source after exit.
- `Persisted after source exit`: a post-exit query returned the saved signal.
- `OTLP accepted, explorer not proven`: exporter flush succeeded, but no
  explorer query returned the signal.
- `Not explorer-visible`: the query ran while the source was alive and the
  expected signal was absent.

Do not call expected local eviction an instrumentation failure. Do not imply
post-exit persistence from a live query. Durable retention requires collector
or product support; verification can preserve evidence but cannot create
retention semantics the explorer does not provide.
