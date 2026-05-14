---
name: otel-instrument
description: >-
  Add OpenTelemetry observability to applications using auto-instrumentation
  and optional custom spans/metrics.   Use when the user types $otel-instrument,
  asks to "add OTel", "add tracing", "add metrics", "implement observability",
  "wire up telemetry", "instrument this service", or asks to add a specific
  custom signal like "add a metric to track queue depth", "add a span for
  payment processing", "track error rate for X".
metadata:
  author: otel-studio
  version: 0.1.1
  category: observability
---

# Instrument

Add OpenTelemetry observability to applications using auto-instrumentation and optional custom spans/metrics.

Prefer the application's current runtime shape. If the project already uses Docker/Compose or Kubernetes, fit instrumentation into that path. If the user does not have Docker or does not want Docker, do not introduce containers just for observability; use the host/native runtime patterns.

## Workflow

### 1. Preflight

Before editing anything, ground the plan with repo evidence:

- Confirm the language and framework from actual dependency or source files
- Confirm the target process from the repo's real start surface: `docker-compose.yml`, Kubernetes manifests, `package.json` scripts, `Makefile`, `Procfile`, PM2 configs, Supervisor configs, systemd units, launchd plists, PowerShell scripts, or a plain shell command
- Confirm existing telemetry indicators or record `none found`
- For Java projects, build an existing trace wiring inventory before adding any
  dependency, SDK/provider setup, tracer binding, or custom span:
  - Runtime/agent: `-javaagent`, `JAVA_TOOL_OPTIONS`, `OTEL_*`, launcher
    scripts, Docker/Kubernetes startup, sidecars, and collector config.
  - Build files: Maven/Gradle OTel dependencies, Java agent artifacts,
    framework tracing dependencies, and any existing telemetry modules.
  - SDK/provider setup: `OpenTelemetrySdk`, `SdkTracerProvider`,
    `GlobalOpenTelemetry`, `OpenTelemetry`, framework `@Bean`/`@Factory`,
    Guice `@Provides`, and external bootstrap modules named in the injector.
  - Tracer usage: constructor-injected `Tracer`, `getTracer`, `spanBuilder`,
    `Span.current`, span status, `recordException`, MDC/log correlation, and
    propagation inject/extract.
  Classify Java trace wiring as `auto-only`, `custom-with-provider`,
  `custom-provider-external`, or `missing` and state the evidence before editing.
- Confirm the planned `service.name` source and `deployment.environment` source
- Distinguish between application repos and tooling repos such as CLIs, MCP servers, workers, libraries, installers, and build tools. Instrument the executable path users or operators actually run today. Do not invent a web app, Docker path, or entrypoint that is not present.
- If the repo has multiple runnable surfaces, instrument the one the user actually cares about; otherwise ask which one matters
- If the repo is primarily tooling or library code and no runnable surface is obvious, stop and ask instead of inventing an app shell
- Ask one focused clarifying question only if the target process or runtime shape is still ambiguous after checking the repo

Do not proceed until you can state all of these clearly:

- target process
- runtime shape
- `service.name`
- environment dimension
- incremental addition vs new scaffold
- for Java, trace source of truth: existing provider/binding to reuse, existing
  agent-backed global provider, external provider likely supplied by bootstrap,
  or evidence that the provider/binding is missing

### Fast Path: Targeted Custom Signal

If the user is asking for a specific signal ("add a metric for queue depth",
"track error rate on payments", "add a span for the indexing job") AND the
preflight scan finds OTel SDK already initialized:

1. Skip Steps 2-3 (dependencies and auto-instrumentation are already present).
2. Go directly to Step 4 (Custom Instrumentation) with the user's request as context.
3. Add only the requested signal — do not re-scaffold or re-wire existing setup.
4. Proceed to Step 5 (build check).

If the preflight scan finds no OTel SDK, tell the user auto-instrumentation
needs to be set up first and continue with the full workflow (Steps 2-3).

### 2. Dependencies

Add the OpenTelemetry SDK and auto-instrumentation packages for the detected language. Load the appropriate reference file:

| Language | Reference | Key packages |
|----------|-----------|-------------|
| Python   | `./references/languages/python.md` | `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, framework instrumentation packages |
| Node.js  | `./references/languages/node.md` | `@opentelemetry/sdk-node`, `@opentelemetry/instrumentation-http`, `@opentelemetry/exporter-metrics-otlp-http`, `@opentelemetry/sdk-metrics`, detected framework instrumentation packages |
| Java     | `./references/languages/java.md` | OTel Java agent (javaagent JAR) |
| Go       | `./references/languages/go.md` | `go.opentelemetry.io/otel`, `go.opentelemetry.io/contrib` |

### 3. Instrument

Apply auto-instrumentation first, then add manual spans for key business operations. Read the language-specific reference for exact patterns.

**Critical for APM error tracking:**
- Set `otel.status_code` to `ERROR` on failures -- this is how APM backends identify errors
- For HTTP server spans, 5xx responses set ERROR automatically per OTel semantic conventions
- For custom spans wrapping business logic, explicitly set error status on exceptions
- Reuse the app's current startup entrypoint instead of replacing it with a new Docker-only path
- For Python, Node.js, and Java, prefer preload or agent wrappers plus env vars over large code refactors when auto-instrumentation already covers the framework
- For host/native runtimes, default OTLP endpoints to loopback (`http://localhost:4318`) unless the existing platform already provides a collector address
- For Python web services, do not satisfy implementation by only changing a Makefile, Docker command, or shell wrapper. Add an explicit setup module such as `otel_setup.py` and wire the app entry point to call it before framework instrumentation is activated.
- For Java/Spring Boot, prefer the OpenTelemetry Java agent. The final response must state the service-name setting (`OTEL_SERVICE_NAME` or `otel.service.name`), OTLP endpoint setting (`OTEL_EXPORTER_OTLP_ENDPOINT` or `otel.exporter.otlp.endpoint`), and that the agent provides HTTP server spans plus request duration metrics.

#### Implementation Rules

- Use only official OpenTelemetry packages (`go.opentelemetry.io/otel`, `go.opentelemetry.io/contrib`, `@opentelemetry/*`, `opentelemetry-*`). Do not use community or third-party OTel wrappers. The only exceptions are library-maintained integrations where no official package exists (e.g. `go-redis/redisotel`, `XSAM/otelsql`).
- Do not initialize the SDK more than once per process.
- Find any existing OTel setup before adding new code. Extend it.
- Reuse the existing trace source of truth. If Java custom spans already obtain a
  tracer through DI, framework beans, globals, or an agent-backed global
  provider, add spans through that path instead of creating a second provider or
  a new binding.
- Do not add a new Java dependency, SDK initializer, tracer provider, meter
  provider, or DI `Tracer` binding unless the inventory proves it is absent and
  required for the requested signal. If dependency manifests already contain the
  OTel APIs you are using, do not add duplicate dependencies.
- For Java DI apps, search every module/factory plus external bootstrap modules
  named in the injector. If a constructor already accepts `Tracer` and the app
  builds or starts, assume a binding may be provided externally. Add a fallback
  binding only after proving injector startup fails without it.
- If a Java fallback `Tracer` binding is truly needed, place it in an
  observability-owned module/factory such as `OtelModule`, `TelemetryModule`, or
  `ObservabilityConfig`, not in an unrelated persistence/client/business module.
  The fallback should bridge to the existing global/runtime provider
  (`GlobalOpenTelemetry.getTracer(...)` in Java agent setups) and must not
  initialize a second SDK.
- Place OTel initialization code in a separate file.
- Minimize changes to existing code. Do not move functions between files.
- Do not create spans for trivial helpers. Only span real diagnostic boundaries.
- Set span status to ERROR and call recordException on failed operations.
- When a framework-specific auto-instrumentation package only provides spans (not HTTP server metrics), wrap the outermost handler with `otelhttp.NewHandler` (Go) or equivalent to ensure `http.server.request.duration` and `http.server.active_requests` are emitted. Consult the Framework Selection Guide in the language reference for the correct wrapping pattern.
- HTTP server instrumentation must produce request-duration metrics as well as spans. Accept the current stable metric `http.server.request.duration` and the older `http.server.duration` name where SDK versions differ.
- For local, Docker, and eval-style runtime checks, configure metric export to flush quickly. When constructing a metric reader manually, use the language equivalent of `OTEL_METRIC_EXPORT_INTERVAL` with a safe local default of `1000` ms and `OTEL_METRIC_EXPORT_TIMEOUT` with a safe local default of `500` ms instead of relying on SDK defaults.
- Strictly adhere to OTel [semantic conventions](https://opentelemetry.io/docs/specs/semconv/) for span and metric naming and attributes for domains where such semantic conventions are defined.
- For domains where OTel semantic conventions exist, emit required spans and metrics only, with required attributes only. Do not emit spans or metrics that are marked optional, do not include attributes that are marked optional. Do not invent custom spans, metrics or attributes in domains where OTel semantic conventions exist.
- For custom attribute names use `{domain}.{noun}.{adjective}` format.
- Span names must be low-cardinality (no IDs, no variable path segments).
- Metric attributes must avoid high cardinality.
- Preserve existing env-var patterns for telemetry config instead of hardcoding endpoints.
- If the app is a library, provide an opt-in setup path rather than forcing SDK initialization on import.
- Keep the codebase idiomatic. Match the repo's dependency manager, config style, and lifecycle patterns.
- Obtain OTel Tracer, Meter once during startup and reuse it. Do not call `getTracer` or `getMeter` in hot paths.
- Create metric instruments once during startup and reuse them. Do not create instruments in hot paths.
- Metric instruments must be created with appropriate unit and description parameters.

#### Language-Specific Musts

Python:
- Add explicit dependency entries for `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, and each detected framework/client instrumentation package.
- Create a separate setup file such as `otel_setup.py`, `telemetry.py`, or `instrumentation.py`.
- Configure `Resource.create({"service.name": ...})`, `TracerProvider`, `MeterProvider`, OTLP trace exporter, and OTLP metric exporter in that setup file.
- Import and call the setup function from the app entry point before creating or instrumenting the app.
- For Flask, call `FlaskInstrumentor().instrument_app(app)`.
- For FastAPI, call `FastAPIInstrumentor.instrument_app(app)`.
- For Celery, call `CeleryInstrumentor().instrument()` in the worker path.
- Keep existing Docker/Compose/Makefile commands, but update them only as the startup surface for the explicit setup, not as a replacement for app wiring.

Node.js:
- Add `@opentelemetry/instrumentation-http` explicitly for HTTP server spans.
- Add the detected framework instrumentation explicitly, for example `@opentelemetry/instrumentation-express` for Express.
- Add `@opentelemetry/exporter-metrics-otlp-http` and `@opentelemetry/sdk-metrics` when wiring SDK-based metrics.
- Configure `PeriodicExportingMetricReader` with `exportIntervalMillis: Number(process.env.OTEL_METRIC_EXPORT_INTERVAL || 1000)` and `exportTimeoutMillis: Number(process.env.OTEL_METRIC_EXPORT_TIMEOUT || 500)` so HTTP duration metrics export during short runtime checks.
- Use the current `NodeSDK` metric reader option exactly as shown in the Node reference. Do not substitute `metricReaders` for `metricReader` unless the installed SDK version documents that option.
- Do not rely on `@opentelemetry/auto-instrumentations-node` alone when specific framework packages are expected.
- In the final response, name the updated preload command (`--require` or `--import`), the packages added, and that HTTP server spans plus request-duration metrics are expected.

Go:
- For HTTP services, use `otelhttp.NewHandler` as the outermost server handler so request-duration metrics are emitted, even when router-specific middleware is also used for route-aware spans.
- Configure `sdkmetric.NewPeriodicReader` with an interval derived from `OTEL_METRIC_EXPORT_INTERVAL`, defaulting to `1000` ms, and a timeout derived from `OTEL_METRIC_EXPORT_TIMEOUT`, defaulting to `500` ms, for local runtime checks.
- In the final response, state the server handler wrapping, service-name setting, OTLP endpoint setting, and that HTTP server spans plus request-duration metrics are expected.

Java:
- Use the Java agent for Spring Boot unless custom business spans are explicitly requested.
- Avoid adding SDK dependencies to `pom.xml` for basic Spring Boot coverage.
- Before adding Java dependencies or a `Tracer` provider, inspect existing
  `pom.xml`/Gradle files, Java agent startup, DI modules, framework factories,
  and current constructor-injected `Tracer` usage. Existing OTel dependencies or
  constructor-injected custom spans mean tracing was already partially present.
- Prefer `GlobalOpenTelemetry` only as a bridge to the Java agent's global
  provider. Do not call `OpenTelemetrySdk.builder()` or install another provider
  in an agent-instrumented app unless the repo already uses that pattern and
  there is one provider per process.
- For Guice/Micronaut/Spring DI, do not add `@Provides Tracer`, `@Bean Tracer`,
  or `@Factory Tracer` by default. First verify no existing binding is supplied
  by the app, framework, or external bootstrap module. If one is required, add it
  to an OTel/Telemetry module and mention in the final response why it was
  needed.
- Wire the agent through the existing startup surface, `JAVA_TOOL_OPTIONS`, or a documented run command.
- In the final response, explicitly mention the agent setup or path,
  `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, HTTP server spans, and
  `http.server.request.duration`.

### 4. Custom Instrumentation

After auto-instrumentation is wired up, prompt the user:

> Auto-instrumentation is configured. Would you like me to add custom spans or metrics for your business logic?

Then wait for the user's answer.

- **If no**: proceed to the build check (Step 5).
- **If yes**: analyze the codebase for high-value custom instrumentation points:
  - Error handling paths that catch and handle exceptions
  - Key business operations (payments, orders, user registration, etc.)
  - External calls not covered by auto-instrumentation libraries
  - Background workers and scheduled jobs
  - Cache interactions without auto-instrumentation support
  - Suggest specific spans and metrics with names, attributes, and rationale
  - Apply after user approval

### 5. Verify (Optional Build Check)

Verification is optional. Do not run install, build, test, startup,
Docker/Compose, curl, siege, Observer, or telemetry validation commands unless
the user asks for verification or approves it after being asked.

1. If the user explicitly says not to verify, skip verification.
2. If the user says verification is handled by an eval harness or another
   system, skip verification.
3. If the user already said exactly what check to run, run only that check.
4. If the user asked you to verify but did not say what to run, ask what build,
   test, startup, or runtime check they want.
5. If the user did not mention verification, ask: `Would you like me to run a
   build/start check?`
6. Run verification only after the user says yes and the check to run is clear.
7. If verification fails, fix issues caused by the instrumentation and report
   anything outside scope.

### 6. Enable Debugging in VS Code

This step is REQUIRED whenever `.vscode/launch.json` exists.

1. Check whether `.vscode/launch.json` exists.
2. If it exists, update at least one debug configuration for this service to include:
   - `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`
   - `OTEL_METRIC_EXPORT_INTERVAL=1000`
   - `OTEL_BSP_SCHEDULE_DELAY=100`
3. After editing, report which configuration was updated, the file path, and whether the env vars were added or already present.
4. If `.vscode/launch.json` exists and you do not update it, stop and explain why.
5. If `.vscode/launch.json` does not exist, explicitly report: `No .vscode/launch.json found; Step 6 skipped.`

### 7. Finalize

- In the final response, separate file changes from verified outcomes
- If verification is partial, say exactly what is working and what is still missing instead of reporting full success
- Always include the service-name configuration, OTLP endpoint configuration, and which automatic spans/metrics are expected from the instrumentation.

## Credential Safety

When the project uses or introduces env files:

1. **Ensure `.env` is gitignored before writing secrets**: Check `.gitignore` for `.env`. If it is missing, add it. Never allow a `.env` with access tokens to be committed.
2. **Create or update `.env.example` with safe placeholders**: Do this whenever the instrumentation introduces env vars. `.env.example` must never contain real tokens.
3. **Verify no tokens in tracked files**: Search tracked config files for access tokens and confirm no real token values appear in files that would be committed.

## Scope

- **New apps**: Full scaffold matching the current runtime shape: instrumentation, SDK init, env var config
- **Existing apps**: Incremental -- detect what's already present, add only what's missing
