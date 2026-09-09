# Telemetry Assessment Contract

Load after repository discovery for every audit. Apply it only to the detected
processes, dependencies, signals, and logging surfaces.

### Step 2 -- Instrumentation Assessment

Check for existing OTel instrumentation and identify gaps. Inventory every
signal by type so the report can list them explicitly.

**SDK and configuration** -- search for:

- OTel SDK initialization files (`otel_setup.py`, `instrumentation.ts`, `otel.go`, etc.)
- OTel imports/dependencies (`opentelemetry`, `otel`, `otlp`, `go.opentelemetry.io`)
- Auto-instrumentation packages matching detected frameworks/clients
- `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT` in env files or configs
- Per-signal OTLP endpoint and protocol variables. Record the effective pair
  (`grpc` with the gRPC receiver, or `http/protobuf` with `/v1/<signal>`), not
  just a host or port. A configured endpoint with an incompatible protocol is
  a required exporter gap.
- Resolve whether the logs endpoint is the local Observer receiver or a direct
  cloud ingest endpoint. An unset signal-specific logs endpoint must not inherit
  a generic direct-cloud endpoint: local application logs default to Observer,
  while direct-cloud or Obstudio cloud forwarding is traces and metrics only.
  An explicit local Observer logs endpoint may participate in the default
  pipeline. An explicit non-local endpoint paired with an absent or `otlp`
  exporter is instead an operator-owned boundary conflict. Represent it as an
  `external follow-up` that requires the named operator to remove the non-local
  endpoint or replace it with the exact detected local Observer endpoint, plus
  a dependent `required`/`default` local-log finding. The
  dependency keeps the executable finding locked until the operator resolves
  the conflict; do not classify the conflict as a scan blocker or authorize
  the provider/bridge early. Preserve `none` and other
  non-OTLP exporter branches without validating their endpoint. Flag any cloud
  log endpoint, credential/header, exporter, or forwarding flag introduced by
  Obstudio instrumentation as a required boundary violation.
- Treat any nonempty generic `OTEL_EXPORTER_OTLP_HEADERS` as unsafe for an
  Obstudio-owned local log path, even when
  `OTEL_EXPORTER_OTLP_LOGS_HEADERS` is also set. SDKs may merge generic and
  signal-specific headers. Require the generic value to be moved to
  trace/metric signal variables and removed before local log export is enabled.
- Semantic-convention stability opt-ins and when they are set relative to SDK
  and framework imports. Treat a late opt-in as inactive for already-created
  instruments.

**Provider/exporter topology** -- build this per target process and per signal;
do not infer it only from the launch command or installed packages.

- Find explicit and lazy `TracerProvider`, `MeterProvider`, and
  `LoggerProvider` construction, global `set_*_provider` calls, no-op provider
  branches, exporter construction, resource creation, flush/shutdown, and
  helpers that initialize providers on first instrument access.
- Trace each provider helper from the selected process entrypoint and real
  startup environment to its recording call sites. Classify each signal as
  `source-active`, `externally bootstrapped`, `source-defined but inactive`, or
  `no provider`; none of these classifications is runtime emission proof.
- Keep provider ownership separate by signal. A process can own a real metrics
  provider while tracing and logs remain disabled. Never describe all OTel as
  no-op because one startup wrapper lacks `opentelemetry-instrument`.
- For Python repositories, run the bundled
  `../scripts/scan_python_otel_topology.py <service-root>` before reporting. The
  scanner finds candidates; reconcile every hit with target-process
  reachability before using it as evidence.
- Reconcile resource precedence. Identify operator-provided
  `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES`, app defaults, detector
  output, and any merge that overwrites `service.name`, environment, or
  version. Preserve operator values and classify hard-coded overwrite as a
  required resource-identity gap.
- For framework instrumentation, record whether the app is instrumented before
  serving begins. In frameworks that install middleware, instrumentation first
  invoked inside lifespan/startup can be too late; classify it as partial until
  source or runtime proof shows middleware was installed before the first
  request.

**Spans inventory** -- build a list of every span source:

- Auto-instrumentation packages that emit spans (check the "Signals" column in
the language reference). Enumerate every individual span name the package
produces -- one row per span. Never group spans with vague labels like
"HTTP server spans" or "gRPC server spans (all N RPCs)". For example,
`otelgrpc` on a server with methods `GetUser` and `ListUsers` produces spans
`/UserService/GetUser` and `/UserService/ListUsers` -- list each as its own
row.
- Custom span creation calls: `tracer.Start` / `span.End` (Go),
`tracer.start_as_current_span` / `tracer.start_span` (Python),
`tracer.startActiveSpan` / `tracer.startSpan` (Node.js),
`@WithSpan` / `Span.current()` (Java).
Record the span name and source file with line number.

**Metrics inventory** -- build a list of every metric source:

- Auto-instrumentation packages that emit metrics (check the "Signals" column).
Enumerate every individual metric name the package produces -- one row per
metric. Never group metrics with vague labels like "(+ related)" or
parenthetical summaries like "(goroutines, memory, GC)". For example,
`otelgrpc` emits `rpc.server.call.duration` (or the legacy `rpc.server.duration`
on older SDK versions), `rpc.server.request.size`, `rpc.server.response.size`,
`rpc.server.requests_per_rpc`, and `rpc.server.responses_per_rpc` -- list each
as its own row. Similarly,
`runtime.Start()` emits `process.runtime.go.goroutines`,
`process.runtime.go.mem.heap_alloc`, `process.runtime.go.gc.count`, etc. --
list each individually.
- Custom metric registrations: `meter.Int64Counter`, `meter.Float64Histogram`,
`meter.Int64ObservableGauge`, `meter.Int64UpDownCounter` (Go);
`meter.create_counter`, `meter.create_histogram`,
`meter.create_observable_gauge` (Python);
`meter.createCounter`, `meter.createHistogram`,
`meter.createObservableGauge` (Node.js).
Record the metric name and source file with line number.

**Logs inventory** -- build a list of OTel log integrations:

- OTel log bridge or SDK log packages
  (`opentelemetry-instrumentation-logging` for current Python releases, with
  the SDK `LoggingHandler` only as a pre-1.40 compatibility path;
  `@opentelemetry/instrumentation-console`,
  `@opentelemetry/instrumentation-winston`, or
  `@opentelemetry/instrumentation-pino` for Node.js; the Java agent's detected
  Logback/Log4j appender; and the matching
  `go.opentelemetry.io/contrib/bridges` package for Go).
- `LoggerProvider`, batch log record processor, OTLP log exporter,
  signal-specific logs endpoint, global registration, and shutdown/flush.
- Existing stdout, stderr, file, platform, appender, handler, transport, hook,
  and worker-thread sinks. Identify which stay active and whether two bridges
  would export the same application record twice.
- Trace-context injection into log records (`trace_id`, `span_id` fields).
- `span.AddEvent()` / `span.add_event()` calls used as structured log events.
- Logging formatters, filters, adapters, MDC/context variables, access-log
  formatters, and exception helpers that can add request, user, tenant,
  session, trace, raw URL, exception text, or traceback data. Check the final
  formatting path, not only application logger call arguments.
- Classify logs as `local-otlp-default`, `explicitly-disabled`,
  `operator-owned`, `correlation-only`, `unsupported-stack`, or `not
  configured`. Trace/MDC fields in stdout are not an OTLP log pipeline.
  `OTEL_LOGS_EXPORTER=none` is an explicit opt-out, while an absent exporter on
  a supported Python, Node.js, Java, or Go application logging stack requires a
  default local Observer OTLP pipeline only when the logs endpoint is absent or
  matches the detected local Observer receiver. Preserve any other explicit
  exporter as operator-owned without validating or supplementing its endpoint.
  For an absent/`otlp` exporter with an explicit non-local endpoint, record an
  external operator prerequisite and a dependent default local-log finding;
  do not classify it as working or select that implementation until the
  dependency is resolved. If `none` is set
  while an existing bridge still exports application records, report the
  ineffective opt-out as a required ownership gap.

**Audit document contract** -- the audit is a current-state baseline source
scan. Describe the instrumentation and gaps established by current repository
evidence. Implementation changes belong in `.observe/otel-instrumentation.md`.

**Verification plan** -- derive deterministic inputs for later
instrumentation and verification. This is source-derived planning, not runtime
proof.

- Define reusable test environments for each runnable surface. Give every
  environment a stable ID and record its configured runtime/toolchain,
  evidence file, expected project runner, affected module scope, and shared
  prerequisites once.
- Create one scenario per telemetry-distinct user, API, worker, startup,
  shutdown, error, timeout, streaming, tool, retrieval, or dependency path.
- Use stable scenario IDs such as `http.search.success`,
  `http.search.failure`, `runtime.startup`, or `worker.batch.failure`.
- Map each scenario to its source entrypoint, expected exact signals, and
  acceptance criteria: span status/attributes/parentage, metric datapoints and
  dimensions, log body/severity/correlation/redaction, or runtime/exporter
  behavior.
- Classify each scenario's required proof as `focused call-site`,
  `full runtime`, or `either`. Use `full runtime` when proof depends on agent or
  preload startup, framework-resolved route names, automatic metrics,
  runtime-installed log export, or absence of duplicate automatic spans.
- For a default local application-log pipeline, include scenarios that prove
  body/category, severity, the same service resource identity as traces and
  metrics, trace/span correlation inside an active span, final-pipeline
  redaction, preservation of the existing stdout/file sink, exactly one OTLP
  record per log call, provider shutdown/flush, and
  `OTEL_LOGS_EXPORTER=none` producing no OTLP record. When cloud trace/metric
  export or forwarding exists, also prove the application record remains
  visible in local Observer without any cloud log path.
- For every exact custom span name or operation entrypoint, create an explicit
  scenario row. Shared helper implementation is not proof that each operation
  emits its expected name and topology.
- Before writing a scenario, confirm every cited source path and symbol exists
  with `rg -n` or a language-aware index. Never hand off a guessed or stale
  symbol name.
- Reference one or more exact test-environment IDs from every acceptance
  scenario. Put local-safe fixture strategy and missing prerequisites in the
  environment profile, not repeated prose in each scenario row.
- Keep prerequisites explicit. Do not require live credentials when fakes or
  an existing test seam can exercise the same app code.
- Avoid path explosion: combine branches only when they emit identical
  telemetry; split success/failure or alternate paths when telemetry differs.

**Dependencies without instrumentation** -- for each dependency detected in Step 1:

- Check if a matching auto-instrumentation package is installed
- Use the already loaded detected-language reference as the checklist
- Flag any dependency that has an available auto-instrumentation package but is not instrumented

**Operational signal assessment** -- express rate, error, latency, and
saturation coverage as ordinary entries in `## Current Instrumentation`,
`## Gaps`, or `## Verification Plan` with exact source paths and signal names.

**Incident readiness assessment** -- when the repository owns incident-relevant
surfaces or the user asks for faster detection/localization, use
`../../references/incident-readiness.md` to assess API/workflow and customer
impact, dependencies, input complexity, freshness, backpressure,
synthetic/canary checks, auth/edge, capacity, and release/config context. For
incident evidence, classify each proposed signal as `MTTD-improving` only when
it can support a detector before or at first customer impact,
`localization-only` when it mainly narrows an already-detected fault,
`provider/platform-owned`, or `unknown owner`.

Record current readiness as `### Incident Readiness` under
`## Current Instrumentation`; do not add another top-level report section.
Readiness rows are audit context first. Promote a missing or partial readiness
surface into the single prioritized `## Gaps` table only when the repository
owns a concrete OTel closure gap: a span, metric, log, provider/exporter,
resource, semantic attribute, correlation, cardinality, or runtime lifecycle
change that can be implemented without changing the product/runtime contract.
The prioritized gap row and its mapped acceptance scenarios form the closure
contract for `$otel-instrument` and `$splunk-configure`:

- `Area` is the stable human-readable gap identity used downstream.
- `Required fix` names every required signal or exact owner mapping; it must not
  use a vague label such as `add observability`.
- `Instrument mode` records whether safe app-owned work is `default`, broader
  safe work is `fix all`, or an external/unsafe choice is `manual decision`.
- The mapped scenario provides the code surface, expected telemetry, proof
  level, and acceptance criteria.

Split a gap when required signals have different owners, instrument modes, or
acceptance criteria. Do not promote service behavior choices, health endpoint
semantics, readiness/liveness contracts, capacity policy, release policy, or
general operational observations into findings unless the user explicitly asks
for that domain and the row names concrete service-owned OTel telemetry to add
or repair. When an external owner must supply telemetry, record the owner and
requirement in the readiness row and summary by default; create an
`external follow-up` finding only when it blocks an in-scope service-owned OTel
finding. Do not mark a partial surface covered because one span or metric
exists, and do not imply that detector configuration can compensate for an
absent detector-critical metric.

**Deterministic gap section contract** -- the canonical audit has exactly one
actionable gap source: `findings`. Record GenAI detail in canonical
`genai_readiness` rows, promote only service-owned OTel telemetry closure rows
into `findings`, and keep the HTML decision view focused on those findings.

Populate canonical `findings` so the shared renderer can project the single
priority-ordered finding list; do not hand-author its layout. Use only `required`,
`recommended`, or `deferred` priorities and only `default`, `fix all`, `manual
decision`, or `external follow-up` instrument modes. Put baseline correctness,
trace continuity, error attribution, exporter/resource identity, cardinality
safety, and duplicate signal ownership in `required`. Put safe deeper
diagnostics and business metrics in `recommended` unless the request already
makes them mandatory. For a detected supported application logging stack, put
a missing local Observer provider/exporter/bridge in `required` with
`instrument_mode: default`; this makes it part of implicit broad/default
Obstudio instrumentation. Do not create that finding when logs are explicitly
disabled or a non-OTLP operator-owned exporter is already configured. When an
absent/`otlp` exporter is paired with an explicit non-local logs endpoint,
create an `external follow-up` whose exact `required_fix` and
`external_requirement` name the operator-owned configuration change, then
create the local-log `required`/`default` finding with that external ID in
`dependencies`. This valid dependency closure keeps the executable finding
locked; never put this configuration conflict in `scan_blockers`.
Keep product
behavior decisions,
readiness contract choices, content governance, safety policy, cost/billing
ownership, and external telemetry prerequisites out of canonical `findings` by
default; record them in readiness/context rows instead. Use `deferred` only for
a concrete prerequisite or decision that gates an in-scope service-owned OTel
finding. Every row must explain user/operator impact, state a specific OTel fix,
and cite the verification scenario IDs that can prove closure. Group related
routes and call sites by remediation theme instead of producing a row per edge.
Do not create manual or external findings just to record product/runtime
choices, billing, cost, safety policy, content-governance, or external business
context.
When a default GenAI gap involves duplicate or overlapping instrumentation,
name the intended canonical owner per logical operation and the pre-bootstrap
suppression surface in `Required fix`. If source evidence cannot support that
choice, use `manual decision`; do not hand `$otel-instrument` an unresolved
"select one canonical source" instruction in a `default` row.

For mutually exclusive choices, first decide whether the branches are in scope.
If the decision only changes product/runtime behavior, such as liveness versus
dependency-aware health, keep it in readiness context unless that domain was
explicitly requested. If multiple options each produce real service-owned OTel
instrumentation work, create one option-locked executable finding per real
branch, put each branch ID in only that option's `unlocks`, and keep those
unlock sets pairwise disjoint. Do not use one shared executable finding for
multiple exclusive options, and do not make two branch implementations appear
as simultaneous independent audit gaps before the user answers.

**Evidence and flow contract** -- write source evidence as a compact
`## Audit Evidence` table and create one `## Signal Flow` / `### Component Flow
Map` using the exact marker semantics defined in this skill. The map is
a reader aid, not runtime proof. Show only major process, dependency, and
telemetry edges; keep independent roots separate and point human-readable gap
markers to the prioritized gap table. Use only `[SOURCE-COVERED]` and
`[GAP: <area>]` markers.

**Anti-patterns** -- flag any of these:

- Multiple SDK initializations in the same process
- Hardcoded OTLP endpoints instead of env vars, except the required
  signal-specific local Observer logs fallback
- Tracer/Meter created in hot paths instead of at startup
- High-cardinality attributes on metrics (user IDs, request IDs)
- Missing `recordException` in error handling paths
- Custom span names with variable segments (IDs, paths)
- Use of community or third-party OTel wrappers when an official OpenTelemetry package exists (e.g. `go.opentelemetry.io/contrib`, `@opentelemetry/`*, `opentelemetry-*`)
- A generic direct-cloud OTLP endpoint implicitly receiving application logs,
  or an Obstudio-added Splunk cloud log endpoint/header/token/exporter/
  forwarding flag
- Two log providers, appenders, handlers, transports, hooks, or bridges that
  export the same application record twice
- Replacing an existing stdout/file sink when adding local OTLP logs

For partially instrumented Go services, explicitly check and report:

- hardcoded OTLP endpoints such as `collector.example.com`
- `otel.Tracer(...)` or `otel.Meter(...)` calls inside request handlers or loops
- high-cardinality span names such as `GetTask-{id}`
- missing `otel.SetTextMapPropagator(...)`
- missing `MeterProvider`, missing `service.name`, and missing provider shutdown/flush

## Warning Signs

- Fewer than expected auto-instrumentation packages for the detected dependencies
- SDK initialized but no auto-instrumentation packages installed
- OTel packages in dependencies but no SDK init file found
- Error handling code without span error status or recordException
