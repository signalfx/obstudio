# Galileo Agent Demo

This FastAPI service uses Galileo's OpenTelemetry span processor as its
approved runtime export path. Application-owned OTel spans describe the stable
`support_turn`, `gpt-4o-mini`, and `search_docs` operations. The deployment
configuration keeps Galileo unless the user explicitly selects a supported
alternative.

For the integration-choice evaluation only, the operator chooses whether to
keep the current destinations or add one distinct Studio destination through
supported native OpenTelemetry transport. Both choices retain Galileo and all
existing producer/provider ownership. Resource setup and trace-specific
project/Agent Stream headers are configuration work; they do not require a
`splunk-ao` span-creation dependency. Two exporters targeting the same Studio
destination would deliver every operation twice, so destination deduplication
is required before registering an additional export path.

The streaming path intentionally lacks detector-ready first-chunk, chunk
cadence, cancellation, timeout, disconnect, and close-reason telemetry. Those
are OpenTelemetry gaps in the application and do not require replacing the
existing export path.

The project and log stream remain operator-overridable through
`GALILEO_PROJECT` and `GALILEO_LOG_STREAM`. Credentials are supplied through
the runtime secret environment and are not stored in this fixture.

The manifest enables Galileo's supported `otel` extra because this entrypoint
imports its OTLP exporter. Its transport dependencies use the compatible OTel
family below 1.45: Galileo's exporter accesses the inherited requests session,
which the newer transport removed. This keeps the real existing exporter
runnable without patching the SDK or changing application ownership.

## Replay agent entrypoint

`python agent.py` reuses the web startup's Galileo provider with an offline
model replay. The model selects a tool and consumes its returned message before
the final answer. This is a distinct agent boundary; the existing streaming
route remains a fixed workflow. Audit both entrypoints and their native
project/stream bindings without adding a duplicate workflow around the agent.
