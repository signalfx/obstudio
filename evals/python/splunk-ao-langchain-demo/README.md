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
The fixture proves the framework integration creates the expected trace without
pretending that local capture proves delivery to Splunk Observability Cloud. A
production deployment would replace the local model and in-memory hook with
the configured model provider and Splunk settings.

The callback creates the single expected span for each LangChain chain, model,
and tool operation. Do not add another OpenTelemetry span around the same
logical operation. The app explicitly calls `logger.terminate()` so completed
work is drained and shutdown behavior is testable.

The pinned callback serializes chain, model, and tool inputs and outputs into
raw trace fields; `tests/test_app.py` inspects those fields in the in-memory
batch. The committed example values are synthetic, but `run_demo(question)`
currently accepts arbitrary caller text. A production use of this pattern
needs an application-owned content boundary or a source-supported suppression
control before the callback sees unapproved data. Adding a separate redacted
field does not remove the callback's raw input or output.

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
