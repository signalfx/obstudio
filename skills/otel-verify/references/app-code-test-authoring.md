# App-Code Test Authoring For OTel Verify

Use this reference only when the user explicitly asks to add, repair, persist,
or write unit/integration tests for OTel verification.

## Principle

Write tests that prove the application creates telemetry. Do not write tests
whose only behavior is manually creating SDK spans, metrics, or logs. Synthetic
SDK emission is useful for exporter smoke tests, but it is not app-code
verification.

Each test must be traceable to the audit-derived inventories:

- one or more `Added Telemetry Inventory` rows, naming the exact added span,
  metric, log/event, or runtime/exporter signal it verifies
- one `Acceptance Scenario Inventory` row, naming the user/application path it
  executes
- one `Application Code Path Verification` row, naming the source entrypoint,
  fake inputs, expected signals, and evidence

## Proof Levels

Prefer stronger proof when feasible:

1. `existing app test`: existing tracked test executes app code and asserts
   telemetry.
2. `new app unit test`: new focused test executes an instrumented function,
   decorator, route handler, middleware, workflow method, adapter, or startup
   hook with fakes and asserts telemetry.
3. `new app integration test`: new test boots a test app/process/client enough
   to exercise runtime wiring and asserts telemetry.
4. `temporary app-code harness`: inline or temp test executes app code and
   asserts telemetry; useful before deciding whether to persist a test.
5. `generated SDK contract`: does not execute app code; use only as fallback
   or exporter/schema smoke and label it contract-only.

## Required Test Shape

Each authored test should have:

- A clear scenario id from the acceptance scenario inventory.
- A clear added-signal id or exact signal name from the added telemetry
  inventory for every trace/span/event, metric, log/event, or runtime/exporter
  signal it asserts.
- OTel providers/exporters/readers installed before importing app modules that
  cache tracers, meters, or loggers.
- Fake dependencies for external providers, network calls, databases, queues,
  LLMs, or credentials.
- A real call into the instrumented app code.
- Assertions for the expected telemetry:
  - spans: name, parentage, status, required attributes, events
  - metrics: instrument name, datapoint value/count, unit when available, and
    required attributes/dimensions
  - logs: body/severity/category, trace/span correlation, redaction, and log
    exporter/handler path when logs are expected to be OTel-visible
  - resources/runtime: service name, environment, version, exporter defaults
- No production credentials, live LLM calls, or user data.

Tests that assert only "a span was emitted" are incomplete unless the audit
declares only that shape. Assert the code path's required attributes,
dimensions, parentage, error/status behavior, datapoint, and log fields needed
to show the instrumentation works.

## Where To Put Tests

Follow the repository's existing layout:

- Python: use existing `pytest` style under `tests/...`; prefer in-memory span
  exporters, metric readers, and `caplog` or SDK log exporters.
- Node/TypeScript: use existing Jest/Vitest style; initialize OTel SDK in a
  setup file or test-local bootstrap before imports.
- Go: use package-local `*_test.go`; pass contexts from parent spans into app
  calls and use SDK test exporters.
- Java/Kotlin: use existing JUnit/Gradle/Maven patterns; set SDK/autoconfigure
  before loading instrumented classes.
- .NET: use xUnit/NUnit/MSTest fixtures with `TracerProviderBuilder`,
  `MeterProviderBuilder`, and OpenTelemetry logging.
- Rust/Ruby/PHP: follow existing test conventions and use available SDK test
  exporters or logging bridges.

Do not add broad dependencies or alter lockfiles unless the user explicitly
approves. Prefer test fakes and existing fixtures.

## Assertions Before OTLP

Permanent unit tests should pass without requiring Obstudio or a local
collector. Use in-memory exporters/readers first. If explorer-visible proof is
also requested, run the same scenario or a paired temporary scenario with OTLP
export and query the collector.

## Report Mapping

For every test authored or reused, add a `Test Artifact Coverage` row:

```markdown
| Test or harness | Permanent? | App code executed | Signals asserted | OTLP exported | Result |
```

Then map the test to:

- `Added Telemetry Inventory`
- `Application Code Path Verification`
- `Path Coverage Matrix`
- `Signal Inventory Coverage`
- `Added Signal Verification Matrix`

If a test asserts a span name but not parentage, status, required attributes,
metric datapoints, or log redaction, mark the missing pieces as `Partial` or
`Not run`.

In the final report, the `How tested` field for each added signal should name
the test or harness, scenario id, app entrypoint, and proof level. Example:
`tests/workflows/test_logs_v2_telemetry.py::test_success executes
LogsV2Workflow.execute with fake repo/model client; asserts
workflow.logs_v2 span attributes and logs_v2.requests metric via in-memory SDK;
paired temp OTLP harness exported trace <id>.`
