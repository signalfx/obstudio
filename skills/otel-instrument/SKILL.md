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
  version: 0.1.0
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
| Python   | `skills/references/languages/python.md` | `opentelemetry-distro`, `opentelemetry-exporter-otlp` |
| Node.js  | `skills/references/languages/node.md` | `@opentelemetry/sdk-node`, `@opentelemetry/auto-instrumentations-node` |
| Java     | `skills/references/languages/java.md` | OTel Java agent (javaagent JAR) |
| Go       | `skills/references/languages/go.md` | `go.opentelemetry.io/otel`, `go.opentelemetry.io/contrib` |

### 3. Instrument

Apply auto-instrumentation first, then add manual spans for key business operations. Read the language-specific reference for exact patterns.

**Critical for APM error tracking:**
- Set `otel.status_code` to `ERROR` on failures -- this is how APM backends identify errors
- For HTTP server spans, 5xx responses set ERROR automatically per OTel semantic conventions
- For custom spans wrapping business logic, explicitly set error status on exceptions
- Reuse the app's current startup entrypoint instead of replacing it with a new Docker-only path
- For Python, Node.js, and Java, prefer preload or agent wrappers plus env vars over large code refactors when auto-instrumentation already covers the framework
- For host/native runtimes, default OTLP endpoints to loopback (`http://localhost:4318`) unless the existing platform already provides a collector address

#### Implementation Rules

- Do not initialize the SDK more than once per process.
- Find any existing OTel setup before adding new code. Extend it.
- Place OTel initialization code in a separate file.
- Minimize changes to existing code. Do not move functions between files.
- Do not create spans for trivial helpers. Only span real diagnostic boundaries.
- Set span status to ERROR and call recordException on failed operations.
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

### 5. Verify (Build Check)

Confirm the instrumented app still builds and starts:

1. Run the language-appropriate build or compile step (e.g. `go build ./...`, `npm install`, `pip install -e .`).
2. Start the app briefly to confirm it boots without import or initialization errors, then stop it.
3. If either step fails, fix the issue before proceeding.

To verify that telemetry is actually flowing to a collector, use `$otel-audit` with the Observer running.

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

## Credential Safety

When the project uses or introduces env files:

1. **Ensure `.env` is gitignored before writing secrets**: Check `.gitignore` for `.env`. If it is missing, add it. Never allow a `.env` with access tokens to be committed.
2. **Create or update `.env.example` with safe placeholders**: Do this whenever the instrumentation introduces env vars. `.env.example` must never contain real tokens.
3. **Verify no tokens in tracked files**: Search tracked config files for access tokens and confirm no real token values appear in files that would be committed.

## Scope

- **New apps**: Full scaffold matching the current runtime shape: instrumentation, SDK init, env var config
- **Existing apps**: Incremental -- detect what's already present, add only what's missing
