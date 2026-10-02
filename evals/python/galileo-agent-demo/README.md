# Galileo Agent Demo

This FastAPI service uses Galileo's OpenTelemetry span processor as its
approved runtime export path. Application-owned OTel spans describe the stable
`support_turn`, `gpt-4o-mini`, and `search_docs` operations. The deployment
configuration keeps Galileo unless the user explicitly selects a supported
alternative.

For the integration-choice evaluation only, a validated compatibility check
establishes two supported but mutually exclusive ways to satisfy dedicated
Agent Stream routing: retain the existing Galileo processor with the
operator-managed mapping, or disable that processor and configure `splunk-ao`
as the replacement export path. Enabling both paths would export the same
logical operations twice, so the audit must ask for one explicit choice without
preselecting either branch.

The streaming path intentionally lacks detector-ready first-chunk, chunk
cadence, cancellation, timeout, disconnect, and close-reason telemetry. Those
are OpenTelemetry gaps in the application and do not require replacing the
existing export path.

The project and log stream remain operator-overridable through
`GALILEO_PROJECT` and `GALILEO_LOG_STREAM`. Credentials are supplied through
the runtime secret environment and are not stored in this fixture.
