# Splunk AO LangChain Demo

This app exercises the supported `SplunkAOCallback` integration with a real
LangChain runnable, tool, and model lifecycle. `DemoLocalLLM` is a deterministic
`FakeListLLM`, and Splunk AO's `ingestion_hook` captures completed trace batches
in memory. The app therefore needs no OpenAI API key, no Splunk access token,
and no network service.

Dependency installation fetches a pinned public `splunk-ao-python` Git commit;
it does not require access to Splunk's private Python package registry. Once
installed, the application and tests run without network access.

"Credential-free" describes how the test runs; it is not part of the app name.
The fixture proves framework callback ownership without pretending that local
capture proves delivery to Splunk Observability Cloud. A production deployment
would replace the local model and in-memory hook with operator-owned provider
and Splunk configuration.

The callback is the one canonical span producer for the LangChain chain, model,
and tool operations. Do not add app-owned OpenTelemetry spans around the same
logical operations. The app explicitly calls `logger.terminate()` so completed
work is drained and the SDK-owned lifecycle is testable.

Run it locally:

```bash
make run
make test
```

Run the skill evals from the repository root:

```bash
make eval-rubric SKILL=skills/otel-audit CASE=python/splunk-ao-langchain-demo
make eval-rubric SKILL=skills/otel-instrument CASE=python/splunk-ao-langchain-demo
```
