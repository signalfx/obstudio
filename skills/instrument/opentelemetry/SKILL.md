---
name: opentelemetry-instrumentation
description: Use this skill when instrumenting an application with OpenTelemetry SDKs, configuring OTLP export, adding spans/metrics/logs, or adapting existing code so telemetry can be verified by Observability Studio and its local Observer.
---

# OpenTelemetry Instrumentation

Use this skill when the user wants application code instrumented with OpenTelemetry.

Observability Studio expects the target application to emit OTLP telemetry to the local
Observer process. Instrumentation work should therefore optimize for correct SDK setup,
useful telemetry, and easy local verification.

## Workflow

1. Inspect the application first. Identify the language, framework, process entrypoints,
   existing observability libraries, and where request or job lifecycles begin and end.
2. Find any existing OpenTelemetry setup before adding new code. Extend it when possible
   instead of creating parallel tracer or meter initialization paths.
3. Install or configure the language-appropriate OpenTelemetry SDK and OTLP exporter.
   Prefer stable packages and the simplest configuration that works in the repo.
4. Initialize telemetry once, near application startup. Configure:
   - resource attributes, especially `service.name`
   - OTLP endpoint/protocol expected by the local Observer
   - trace, metric, and log exporters only for signals the application actually emits
   - graceful shutdown or flush on process exit
5. Add instrumentation at meaningful boundaries:
   - inbound requests, RPC calls, queue consumers, CLI commands, or batch jobs
   - outbound HTTP, database, cache, or messaging calls
   - important internal operations where spans help explain latency or failure
6. Prefer existing automatic instrumentation packages for common frameworks and clients.
   Add manual spans only where auto-instrumentation is missing or too coarse.
7. Follow OpenTelemetry semantic conventions. Use stable span names, set attributes that
   help identify the operation, and record exceptions on failed spans.
8. Keep the codebase idiomatic. Match the repo’s dependency manager, config style, and
   lifecycle patterns. Avoid introducing a separate observability abstraction unless the
   project already has one.
9. Verify the result. Run the app or relevant tests, trigger instrumented paths, and
   confirm telemetry reaches the local Observer without obvious duplication or noise.

## Implementation Rules

- Do not initialize the SDK more than once per process.
- Do not create spans for trivial helper functions unless they represent a real diagnostic
  boundary.
- Prefer resource attributes and semantic attributes over custom ad hoc keys.
- If logs or metrics are not already part of the app, add them only when they materially
  help the user’s request.
- If the repo already uses environment variables for telemetry configuration, preserve that
  pattern instead of hardcoding endpoints.
- If the app is a library, instrument usage points or provide an opt-in setup path rather
  than forcing SDK initialization on import.

## Verification Checklist

- The application starts with telemetry enabled and without duplicate initialization.
- `service.name` and other core resource attributes are present.
- Expected spans are emitted for the target workflow.
- Exceptions and error status are recorded on failed operations.
- OTLP export points at the local Observer configuration used by Observability Studio.
   - Run application that is being instrumented. Make sure to set the following env variables:
       - `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`
       - `OTEL_METRIC_EXPORT_INTERVAL=1000` (if metrics are added, to make sure they are emitted during testing)
   - Connect to observer MCP endpoint http://127.0.0.1:3000/mcp. The MCP endpoint must return the telemetry that was emitted by the application.
   - Verify that metrics and spans emmited are as expected.
- Shutdown paths flush telemetry cleanly when practical.

## Output Expectations

When using this skill, make the code changes directly. Keep the final explanation brief and
include:

- what was instrumented
- where SDK initialization lives
- how OTLP export is configured
- how the change was verified or what could not be verified
