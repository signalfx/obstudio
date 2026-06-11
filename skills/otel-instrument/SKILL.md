---
name: otel-instrument
description: >-
  Add OpenTelemetry observability to applications using auto-instrumentation
  and optional custom spans/metrics.   Use when the user types $otel-instrument,
  asks to "add OTel", "add tracing", "add metrics", "implement observability",
  "wire up telemetry", "instrument this service", or asks to add a specific
  custom signal like "add a metric to track queue depth", "add a span for
  payment processing", "track error rate for X", asks to add signals that make
  incidents faster to detect or localize, or asks to instrument GenAI/LLM
  workflows with OpenTelemetry semantic conventions.
metadata:
  author: otel-studio
  version: 0.1.2
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
- Detect incident-readiness surfaces. Search source and config for user-visible
  workflows, dependency clients, background jobs, queues/streams, data
  freshness, auth/edge paths, capacity limits, and release/config context. When
  present or when the user asks for faster incident detection/localization, load
  `../references/incident-readiness.md`.
- When incident reports, postmortems, tickets, alerts, or user-provided failure
  examples are part of the request, use incident-evidence mode from
  `../references/incident-readiness.md`: map each failure mechanism to the
  owning code surface before editing, and judge proposed signals by whether they
  improve detection, routing, localization, or only documentation.
- Detect GenAI/LLM ownership. Search dependencies, config, and source for
  provider clients, model gateways, agent/workflow orchestration, tool/function
  dispatch, MCP, retrieval/RAG, model/deployment config, fallback, token usage,
  and usage logging. When present, load `../references/genai-readiness.md`.
- For Java projects, build a trace wiring inventory per `./references/languages/java.md` (Preflight section) and classify as `auto-only`, `custom-with-provider`, `custom-provider-external`, or `missing` before editing.
- Confirm the planned `service.name`, `service.version`,
  `deployment.environment`, `deployment.region`, `deployment.platform`, and
  `container.image.tag` or artifact-version sources when those dimensions are
  available and low-cardinality
- Prefer existing OTel semantic-convention or platform resource attribute names
  when they are already emitted. Treat `deployment.region`,
  `deployment.platform`, and `container.image.tag` as generic context aliases
  unless the repo already uses those exact attribute names.
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
- for Java, trace source of truth (see `./references/languages/java.md` Preflight section)
- incident-readiness surfaces and the workflow/dependency/freshness/backpressure
  signals to add, prove, or owner-map, when the repo owns those surfaces
- incident-evidence coverage when incidents are supplied: failure mechanism,
  owning code surface, signal to add or prove, expected MTTD/localization impact,
  and remaining non-code or dependency owner
- GenAI workflow surfaces and the GenAI semantic-convention signals to add,
  prove, or owner-map, when the repo owns LLM, agent, tool, or retrieval code

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

### Audit-Driven Incident Readiness

#### Audit Gap Contract

If `.observe/otel.md` contains `## Gap Ledger`, use that ledger as the source
of truth. The audit output is a contract, not background context. Start by
parsing every row into `gap_id`, `required_signals`, `owner`, `code_surface`,
and `acceptance_criteria`. If the audit predates `## Gap Ledger`, synthesize
the same fields from `## Gaps`, `## Incident Readiness`, `## GenAI Readiness`,
and `## Deployment Context` before editing code.

Reconcile every audit gap to a required instrumentation result:

| Audit Gap | Required Instrumentation Result |
|---|---|
| App-owned + patchable | Code added + tests |
| App-owned but unsafe/too large | Explicitly split into named follow-up batch |
| Provider/platform-owned | Owner mapped with exact missing source |
| Already covered | Proven with source path and signal name |

For each row, produce and maintain a closure matrix:
`gap_id -> required_signals -> implemented_signals -> tests ->
remaining_signals -> status`. The final gate is strict: the instrumentation
pass cannot say `covered`, `fixed`, `closed`, or `complete` unless every
required signal is either implemented with tests, proven existing with source
path and signal name, or explicitly owner-mapped with the exact missing source.
Optimize for honesty over broad progress. Partial closure is acceptable; silent
partial closure is the bug.

If `.observe/otel.md` contains `## Incident Readiness` rows with `partial` or
`missing` status and the user asked to instrument, treat those rows as an
approved request for custom incident-readiness instrumentation. Do not stop
after auto-instrumentation and do not ask the Step 4 custom-instrumentation
question for gaps that the repo clearly owns.

When the user asks broadly to apply readiness skills, improve MTTD, or fix
found gaps, treat the scope as **all discovered app-owned gaps**. Do not select
one representative or highest-value gap unless the user explicitly narrows the
scope to that gap.

1. Convert each partial/missing row into candidate signals using
   `../references/incident-readiness.md`.
2. Classify each candidate as:
   - **app-owned and patchable**: the code exposes the value accurately and a
     low-cardinality metric/span can be added in an owned handler, client,
     queue, worker, limiter, or health path.
   - **app-owned but unsafe/too large**: the code owns the signal, but the
     change cannot be safely completed in the current batch; split it into a
     named follow-up batch with exact remaining signals.
   - **deployment/platform-owned**: the signal belongs in Helm, Kubernetes,
     Terraform, VM/systemd, load balancer, collector, or runtime telemetry.
   - **already covered**: the signal exists and is proven with source path and
     signal name.
   - **unknown owner**: the audit names a dependency/config source that was not
     inspected.
3. Implement every safe app-owned patchable signal before moving to
   verification. Prefer workflow outcome/error/latency, dependency
   timeout/retry/rate-limit/error, queue/backpressure, freshness, or capacity
   saturation signals that can become detectors. If the full set is too large
   for one change, stop and report the scoped batch before editing; otherwise
   do not leave an app-owned candidate as a follow-up.
   Keep dependency timeout/retry/rate-limit/error coverage explicit when a
   downstream dependency is part of the gap.
4. Also close generic runtime surfaces discovered during the scan:
   - If the target code owns executor services, thread pools, worker pools,
     bounded queues, rejected-execution paths, queue-full handling, or async
     dispatch, add or prove detector-ready queue depth, active/inflight work,
     pool capacity, queue wait, rejected/shed work, timeout, and saturation outcome
     signals.
   - If the target code owns long-lived connection or streaming surfaces such as
     WebSocket, SSE, streaming HTTP/RPC, broker streams, or bidirectional client streams,
     add or prove lifecycle signals for connect/open,
     authentication/authorization, start/stop/detach/keepalive, close reason
     family, send/write failure, active connections/channels/streams, and stream
     duration/outcome. Treat close reason family and stream duration/outcome as
     required lifecycle signals when the code owns the stream.
   - If the target code owns auth, identity, token, secret, certificate, domain,
     or edge-routing flows, add or prove lifecycle, failure reason family,
     expiry/rotation, and route/config mismatch signals.
   - If the target code owns scheduled jobs, reports, exports, notifications,
     ingestion, sync, or derived data, add or prove last-success timestamp,
     freshness/age, duration, output count, dropped/skipped reason, and
     publish/consume outcome signals.
   - If the target code owns rollout/config/feature-flag decisions, add or prove
     low-cardinality version, config version, rollout batch, expected-vs-running,
     and decision outcome dimensions.
5. Also close GenAI/LLM surfaces discovered during the scan. Follow
   `../references/genai-readiness.md` and do not stop at semantic-convention
   spans when the incident mechanism needs detector-ready app-owned signals.
   If the target code owns provider/model gateway, agent/workflow orchestration,
   tool/function execution or AI-owned session/stream lifecycle including MCP
   when present, retrieval/RAG, streaming responses, token/context pressure,
   prompt/response assembly, safety/policy decisions, AI-derived data jobs,
   model/config rollout, or AI-owned cache/session state, add or prove every
   safe low-cardinality outcome, latency, error-class, duration, count, version,
   parse, freshness, fallback, rejection, prompt/tool schema, model/config
   readiness, model/config compatibility, and expected-vs-running model/config
   signal the code can observe accurately. Use the incident-readiness path for
   generic lifecycle, job, synthetic/canary, input-complexity,
   startup/deployment, capacity, and release/config surfaces. If incident
   evidence depends on missed, flapping, auto-resolved, or no-data alerts,
   record detector reliability evidence as a `$splunk-configure` handoff
   instead of app-owned GenAI instrumentation.
   For each app-owned GenAI surface, close the applicable trace, metric, and
   log/span-event planes. Metric-only closure is not acceptable for
   provider/model calls, streaming responses, tool execution, retrieval,
   prompt/response parsing, safety/policy decisions, model/config resolution, or
   AI-derived data jobs when the code can emit a meaningful span or span event.
   Add or prove low-cardinality GenAI spans with error status/`error.type`, add
   detector-ready metrics for MTTD signals, and add or prove trace-correlated
   logs or span events for lifecycle outcomes operators otherwise search logs
   for, such as retry scheduled, fallback selected/failed, stream
   truncated/finished, parse failure, safety rejection, and job success/failure.
   For token/context pressure gaps, `gen_ai.client.token.usage` plus a
   context-window usage gauge does not close a broader token-pressure gap
   unless the audit ledger only requires those two signals. If
   `required_signals` include context budget percent, truncation rate,
   token-limit errors, prompt/tool schema size, LLM call count per turn, or
   tool call count per turn, mark the row partial until each signal is
   implemented, proven, or owner-mapped. Use this exact style when only token
   and context-window usage were added: `Partial: token usage and context window added; truncation, token-limit error, prompt/tool schema size, and LLM-call fanout remain missing.`
6. Before finalizing, maintain a gap-closure matrix with one row per incident
   or readiness gap: `gap_id -> required_signals -> implemented_signals ->
   tests -> remaining_signals -> status`, plus repo evidence, owner, code
   location, action, trace evidence, metric evidence, log/event evidence, signal
   names/attributes, test/verification, and remaining owner/source. The
   compatibility form `gap -> repo evidence -> owner -> code location ->
   action -> trace evidence -> metric evidence -> log/event evidence -> signal
   names/attributes -> test/verification -> remaining owner` is acceptable only
   when no structured `gap_id` exists.
   action must be `add instrumentation`, `prove existing instrumentation`, or
   `mark out of scope with owner`.
   Every discovered gap must resolve to one of those actions before the work is
   called complete. A final response, audit, or PR description must not say
   complete, covered, or fixed while any app-owned gap is still only a
   follow-up.
7. Do not call incident-readiness instrumentation complete when an app-owned
   executor/backpressure, streaming, auth/edge, freshness/job, dependency, or
   release/config surface remains only listed as a follow-up, unless the user
   explicitly narrowed scope.
8. Do not call GenAI instrumentation complete when an app-owned provider/model,
   workflow, tool/function execution or AI-owned session/stream including MCP
   when present, retrieval, streaming, token/context, safety/policy,
   prompt/response, AI-derived data, model/config rollout, or AI-owned
   cache/session surface remains only listed as a follow-up, unless the user
   explicitly narrowed scope. Generic incident-readiness surfaces must also be
   closed through `../references/incident-readiness.md` when they are
   app-owned.
9. If no app-owned candidate is safe to patch, make no placeholder instruments.
   Instead, update the report or final response with `no safe app-owned
   incident-readiness patch found`, list the missing owner/source, and name the
   exact signal that remains a prerequisite for `$splunk-configure`.

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
- For Java trace wiring, DI binding, and provider rules, follow `./references/languages/java.md` (Implementation Rules section).
- Place OTel initialization code in a separate file.
- Minimize changes to existing code. Do not move functions between files.
- Do not create spans for trivial helpers. Only span real diagnostic boundaries.
- Set span status to ERROR and call recordException on failed operations.
- When a framework-specific auto-instrumentation package only provides spans (not HTTP server metrics), wrap the outermost handler with `otelhttp.NewHandler` (Go) or equivalent to ensure `http.server.request.duration` and `http.server.active_requests` are emitted. Consult the Framework Selection Guide in the language reference for the correct wrapping pattern.
- HTTP server instrumentation must produce request-duration metrics as well as spans. Accept the current stable metric `http.server.request.duration` and the older `http.server.duration` name where SDK versions differ.
- For local, Docker, and eval-style runtime checks, configure metric export to flush quickly. When constructing a metric reader manually, use the language equivalent of `OTEL_METRIC_EXPORT_INTERVAL` with a safe local default of `1000` ms and `OTEL_METRIC_EXPORT_TIMEOUT` with a safe local default of `500` ms instead of relying on SDK defaults.
- Strictly adhere to OTel [semantic conventions](https://opentelemetry.io/docs/specs/semconv/) for span and metric naming and attributes for domains where such semantic conventions are defined.
- For domains where OTel semantic conventions exist, use semantic-convention
  names and attributes. Start with required spans, metrics, and attributes; add
  recommended optional metrics or attributes only when a requested readiness
  signal depends on them, the service can observe the values accurately, and
  privacy/cardinality rules allow them. Do not invent custom spans, metrics, or
  attributes in domains where OTel semantic conventions exist.
- For incident-readiness work, follow `../references/incident-readiness.md`:
  instrument only code-evidenced API/workflow, customer-impact, dependency,
  freshness, backpressure, auth/edge, capacity, and release/config surfaces;
  prefer semantic-convention HTTP/RPC/database/messaging/runtime signals; add
  custom workflow, lag, freshness, outcome, retry, timeout, rate-limit,
  endpoint-health, target-health, drop-reason, circuit-breaker, CPU/memory/disk
  saturation, desired-vs-healthy, startup/readiness/healthcheck failure,
  traffic target health, and release/config signals only when the service owns
  and can observe them accurately.
- For GenAI/LLM code, follow `../references/genai-readiness.md`: create
  baseline distributed tracing plus OTel GenAI spans for inference,
  `invoke_agent`, `invoke_workflow`, `execute_tool`, and `retrieval` where code
  evidence exists; emit `gen_ai.client.operation.duration` and
  `gen_ai.client.token.usage` when the data is available; use stable tool names;
  add low-cardinality `error.type`; and avoid raw prompt, completion, retrieved
  content, tool argument, user, tenant, session, task, trace, or raw URL values
  in metric dimensions.
- GenAI instrumentation is incomplete if a patchable app-owned GenAI operation
  is closed only by a custom metric. Prefer the existing tracer/provider setup;
  wrap the operation in a stable span, set GenAI semantic attributes, set error
  status and `error.type` on failure, and add a span event or trace-correlated
  structured log for important lifecycle outcomes.
- For GenAI incident-readiness work, close every safe app-owned GenAI pathway
  gap discovered during the scan. Do not stop after one representative provider,
  token, stream, tool, retrieval, model/config, prompt/response, safety, or
  AI-derived data signal if the repo owns more patchable gaps. For each
  remaining gap, prove existing telemetry with file/line evidence or mark it out
  of scope with the owning deployment, platform, dependency, or
  `$splunk-configure` handoff.
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
- Follow `./references/languages/java.md` Implementation Rules for DI binding, provider reuse, and dependency checks.
- Wire the agent through the existing startup surface, `JAVA_TOOL_OPTIONS`, or a documented run command.
- In the final response, explicitly mention the agent setup or path,
  `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, HTTP server spans, and
  `http.server.request.duration`.

### 4. Custom Instrumentation

After auto-instrumentation is wired up, prompt the user:

> Auto-instrumentation is configured. Would you like me to add custom spans or metrics for your business logic?

Then wait for the user's answer.

Skip this prompt when the user already asked for a specific custom signal,
incident-readiness work, GenAI/LLM workflow instrumentation, or when the
Audit-Driven Incident Readiness path applies. In those cases, the user's
request and audit gaps are the approval context; implement the safe scoped
signals and clearly list any unpatched prerequisites.

- **If no**: proceed to the build check (Step 5).
- **If yes**: analyze the codebase for high-value custom instrumentation points:
  - Error handling paths that catch and handle exceptions
  - Key business operations (payments, orders, user registration, etc.)
  - External calls not covered by auto-instrumentation libraries
  - Background workers and scheduled jobs
  - Cache interactions without auto-instrumentation support
  - Incident-readiness boundaries: customer-impact workflow outcome, dependency
    retry/timeout/rate-limit/error class, dependency endpoint or target health,
    data freshness, queue depth/lag/oldest age, auth/edge failure class,
    CPU/memory/disk/concurrency saturation, desired-vs-healthy,
    startup/readiness/healthcheck failure, traffic target health, and
    release/config context when code evidence exists
  - Incident-evidence boundaries: every incident mechanism supplied by the user
    or available in local reports must map to either added/proven code-owned
    signals or an explicit external owner; do not stop at generic endpoint
    metrics when the incident mechanism was auth handshake, secret expiry,
    report freshness, rollout skew, dependency active-node health, or pool
    saturation
  - GenAI/LLM workflow boundaries: workflow span, agent/workflow invocation,
    LLM inference, tool execution, retrieval, fallback, token usage, and
    model/config readiness when code evidence exists
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
- For incident-readiness work, state which workflow, dependency, freshness,
  backpressure, auth/edge, capacity, and release/config signals were added and
  which gaps remain prerequisites for `$splunk-configure`.
- For incident-evidence work, include a concise coverage summary explaining
  whether each incident class would likely improve MTTD, improve localization
  only, or remain uncovered.
- Include exact deployment-context dimensions that were wired, such as
  `service.version`, `deployment.environment`, `deployment.region`,
  `deployment.platform`, `container.image.tag`, artifact version, config
  version, and rollout/canary id, or state which ones were not available from
  the repo.
- For GenAI work, state which OTel GenAI operations were instrumented, which
  GenAI metrics are expected, whether trace continuity should produce a nested
  workflow/agent/tool/chat/retrieval shape, and which privacy/cardinality limits
  were enforced.

## Credential Safety

When the project uses or introduces env files:

1. **Ensure `.env` is gitignored before writing secrets**: Check `.gitignore` for `.env`. If it is missing, add it. Never allow a `.env` with access tokens to be committed.
2. **Create or update `.env.example` with safe placeholders**: Do this whenever the instrumentation introduces env vars. `.env.example` must never contain real tokens.
3. **Verify no tokens in tracked files**: Search tracked config files for access tokens and confirm no real token values appear in files that would be committed.

## Scope

- **New apps**: Full scaffold matching the current runtime shape: instrumentation, SDK init, env var config
- **Existing apps**: Incremental -- detect what's already present, add only what's missing
