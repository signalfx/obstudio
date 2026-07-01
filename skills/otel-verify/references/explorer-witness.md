# Explorer Witness Contract

Use this contract whenever verification claims that telemetry is visible in
Obstudio or another local trace/metric/log explorer.

## Lifecycle

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

Never place credentials, raw prompts/content, user/session/request IDs, or
other sensitive payloads in saved evidence. Trace IDs may be recorded as
technical proof but must not become metric dimensions.

When the explorer also runs semantic-convention validation, preserve the raw
summary and classify findings as actionable, registry mismatch, or stale.
Moved GenAI/MCP registry entries, custom app-owned signals absent from the core
registry, and framework-owned `asgi.event.type` findings do not by themselves
prove application telemetry is invalid.

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
