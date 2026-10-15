# Assistant v3 Framework Bridge Demo

This fixture separates app-owned lifecycle identities from externally
bootstrapped OpenTelemetry and framework instrumentation. The real startup
command uses `opentelemetry-instrument`; that stack must be preserved when
adding missing operation coverage or safe attributes/content.

The stable source identities are `assistant_v3_turn` and `deepagents`.
`SpanHandle` currently returns no-op handles, and `framework_shadow_nodes`
models response data such as `LangGraph` and `step tools`. Neither helper
labels nor these simulated JSON nodes prove received OpenTelemetry spans or
actual duplicates. An actor must inspect real producer ownership and emitted
telemetry before claiming coverage or a collision.

Add only source-proven missing operations through supported public hooks on
the current provider or framework. Retain current producers, providers,
exporters, destinations and launch behavior. Do not disable LangChain/OpenAI
instrumentors to prefer newly added app-owned spans, replace an existing
producer, or delete simulated business response fields to fake a clean trace.
Unsupported ownership/enrichment capability stays an exact incomplete/manual
gap, and absent runtime or cloud evidence stays Not proven.
