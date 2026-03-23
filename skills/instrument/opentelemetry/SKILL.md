---
name: opentelemetry-instrumentation
description: Use this skill when instrumenting an application or service with OpenTelemetry SDKs, configuring OTLP export, adding spans/metrics/logs.
---

# OpenTelemetry Instrumentation

Use this skill when the user wants application code instrumented with OpenTelemetry.

## Workflow

- Inspect the application first. Identify the language, framework, process entrypoints,
  existing observability libraries, and where request or job lifecycles begin and end.
- Find any existing OpenTelemetry setup before adding new code. Extend it when possible
  instead of creating parallel tracer or meter initialization paths.
- Install or configure the language-appropriate OpenTelemetry SDK and OTLP exporter.
  Prefer stable packages and the simplest configuration that works in the repo.
- Initialize telemetry once, near application startup. Configure:
   - resource attributes, especially `service.name`
   - trace and metric OTLP exporters
   - graceful shutdown or flush on process exit
- Add instrumentation at meaningful boundaries:
   - inbound requests, RPC calls, queue consumers, CLI commands, or batch jobs
   - outbound HTTP, database, cache, or messaging calls
   - important internal operations where spans help explain latency or failure
- Prefer existing automatic instrumentation packages for common frameworks and clients.
  Add manual spans only where auto-instrumentation is missing or too coarse.
- Follow OpenTelemetry semantic conventions. Use stable span names, set attributes that
  help identify the operation, and record exceptions on failed spans.
- Keep the codebase idiomatic. Match the repo’s dependency manager, config style, and
  lifecycle patterns.
- Use additional language-specific instrumentation instructions. Find <language>.md file
  in this directory and follow instruction for that language.
- Enable debugging in VS Code. See instructions in a section below.
- When instrumentation is done ask the user if they want to run the service to see how it works.
  If the user wants to run, make sure you run the process with the following env variables set:
    - OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
    - OTEL_METRIC_EXPORT_INTERVAL=1000
    - OTEL_BSP_SCHEDULE_DELAY=100

## Enable debugging in VS Code

If running in VS Code enable debugging of created telemetry by creating or adjusting VS Code's
debugging configuration. If the project doesn't already have a launch.json, create one and
add a debug configuration to it.

Add the following env variables to debug configuration to make sure when running under
debugger the telemetry is sent to a locally running telemetry observer and is refreshed
often to enable live view in a locally running telemetry observer:
  - OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
  - OTEL_METRIC_EXPORT_INTERVAL=1000
  - OTEL_BSP_SCHEDULE_DELAY=100

## Implementation Rules

- Do not initialize the SDK more than once per process.
- Minimize changes to existing code, do not move functions to different files unless necessary.
- Do not create spans for trivial helper functions unless they represent a real diagnostic
  boundary.
- If span is created for erroneous operation make sure to set the status of the span to error.
- Prefer OpenTelemetry semantic conventions over custom ad hoc keys. If you need to invent
  a custom key name, follow OpenTelemetry recommendations for attribute naming.
- If the repo already uses environment variables for telemetry configuration, preserve that
  pattern instead of hardcoding endpoints.
- If the app is a library, instrument usage points or provide an opt-in setup path rather
  than forcing SDK initialization on import.
- When adding metric instrumentation be careful with what attributes you add. Avoid adding
  attributes that can have high cardinality.   
- Prefer to place OpenTelemetry initialization code in a separate file.

## Verification Checklist

- The application starts with telemetry enabled and without duplicate initialization.
- `service.name` and other core resource attributes are present.
- Expected spans are emitted for the target workflow.
- Exceptions and error status are recorded on failed operations.
- OTLP export points at the local Observer configuration used by Observability Studio.
- Shutdown paths flush telemetry cleanly when practical.

## Output Expectations

When using this skill, make the code changes directly. Keep the final explanation brief and
include:

- what was instrumented
- where SDK initialization lives
- how OTLP export is configured
- how the change was verified or what could not be verified
