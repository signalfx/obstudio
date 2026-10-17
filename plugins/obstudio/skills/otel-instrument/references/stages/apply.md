### 2. Dependencies

Add the OpenTelemetry SDK and auto-instrumentation packages for the detected language. Load the appropriate reference file:

| Language | Reference | Key packages |
|----------|-----------|-------------|
| Python   | `./references/languages/python.md` | `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, the stdlib logging bridge, framework instrumentation packages |
| Node.js  | `./references/languages/node.md` | `@opentelemetry/sdk-node`, trace/metric/log OTLP exporters, `@opentelemetry/sdk-logs`, the detected logging bridge, framework instrumentation packages |
| Java     | `./references/languages/java.md` | OTel Java agent (javaagent JAR) |
| Go       | `./references/languages/go.md` | `go.opentelemetry.io/otel`, the log SDK and OTLP log exporter, and the detected `go.opentelemetry.io/contrib/bridges` package |

### 3. Instrument

Apply auto-instrumentation first, then add manual spans for key business operations. Read the language-specific reference for exact patterns.

**Critical for APM error tracking:**
- Set `otel.status_code` to `ERROR` on failures -- this is how APM backends identify errors
- For HTTP server spans, 5xx responses set ERROR automatically per OTel semantic conventions
- For custom spans wrapping business logic, explicitly set error status on exceptions
- Reuse the app's current startup entrypoint instead of replacing it with a new Docker-only path
- For Python, Node.js, and Java, prefer preload or agent wrappers plus env vars over large code refactors when auto-instrumentation already covers the framework
- For host/native runtimes, default OTLP export to the resolved current
  Obstudio receiver. Use `http://127.0.0.1:4318` only as the conventional
  fallback when no endpoint is configured or discoverable; never replace a
  detected non-default port.
- For a supported application logging stack, default logs to the local Splunk Observability Studio
  receiver with its resolved signal-specific endpoint, conventionally
  `http://127.0.0.1:4318/v1/logs` only as the final fallback. Do not let a generic direct-cloud OTLP
  endpoint become the implicit log destination.
- For Python web services, do not satisfy implementation by only changing a Makefile, Docker command, or shell wrapper. Add an explicit setup module such as `otel_setup.py` and wire the app entry point to call it before framework instrumentation is activated.
- For Java/Spring Boot, prefer the OpenTelemetry Java agent. The final response must state the service-name setting (`OTEL_SERVICE_NAME` or `otel.service.name`), OTLP endpoint setting (`OTEL_EXPORTER_OTLP_ENDPOINT` or `otel.exporter.otlp.endpoint`), and that the agent provides HTTP server spans plus request duration metrics.

#### Implementation Rules

- Use official OpenTelemetry packages (`go.opentelemetry.io/otel`, `go.opentelemetry.io/contrib`, `@opentelemetry/*`, `opentelemetry-*`) for baseline non-GenAI instrumentation and app-owned OTel gap closure. Supported existing GenAI libraries, including Galileo, are preserved, and fresh agents use supported `splunk-ao` span creation by default under GenAI Instrumentation Selection. That fresh default does not require an AO finding-group label or a separate explicit SDK-choice request. Other exceptions remain library-maintained integrations where no official package exists (for example `go-redis/redisotel` and `XSAM/otelsql`). Treat `splunk-ao` as a supported span-creation and export integration, not as an official OTel instrumentation package.
- Do not initialize the SDK more than once per process.
- Find any existing OTel setup before adding new code. Extend it. Treat lazy
  provider helpers and providers initialized on first instrument creation as
  existing setup even when the startup wrapper itself contains no OTel call.
- Keep one global provider per signal. Preserve the actual source-owned
  provider and its resource/exporter ownership. Add providers only for absent
  signals; adapt new hooks to existing instances and never let new bootstrap
  code race the existing `set_meter_provider` path.
- Preserve operator resource values. Merge app defaults only for absent keys;
  do not overwrite `OTEL_SERVICE_NAME`, `deployment.environment`,
  `deployment.environment.name`, or `service.version` from
  `OTEL_RESOURCE_ATTRIBUTES`. Add a focused resource-merge test and assert the
  effective resource in live OTLP evidence.
- Preserve consumer-visible resource aliases when they are safe and already
  emitted, such as a legacy realm or namespace attribute used by dashboards or
  entity mappings. Add the OTel semantic resource attribute beside the alias
  unless the audit/user explicitly approves a breaking migration; if an alias
  is removed, mark the telemetry item `consumer_compatibility.status=breaking`
  and name the migration.
- Resolve the exporter per signal as an endpoint/protocol/path tuple. Pair gRPC
  with the gRPC receiver (commonly `4317`) and `http/protobuf` with an HTTP
  signal path such as `4318/v1/metrics`. Do not assume one generic endpoint
  configures every exporter. A successful trace export does not prove metrics
  or logs; exercise each configured signal and repair protocol errors before
  reporting it as working.
- Treat all literal `4317` and `4318` values in language examples as
  conventional fallbacks, not equality gates. Use the receiver endpoint
  resolved during preflight in generated code, launch configuration, and
  tests. Generated application startup must not call `observer_status`, MCP,
  Studio-specific discovery, or a route-registration API. Normal AO SDK
  resource calls use their configured standard API endpoint.
- Keep local application-log export separate from cloud export. When a generic
  `OTEL_EXPORTER_OTLP_ENDPOINT` is a direct-cloud endpoint, configure traces and
  metrics with their signal-specific endpoints and give logs a local Splunk Observability Studio
  `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`. Never copy a Splunk realm, ingest URL,
  access token, auth header, or cloud exporter into log configuration. Optional
  Splunk Observability Studio cloud forwarding remains traces and metrics only; never add a log
  forwarding flag or cloud logs pipeline. Remove a generic
  `OTEL_EXPORTER_OTLP_HEADERS` value from the shared startup surface after
  moving it to trace- and metric-specific headers; reject it from an
  Splunk Observability Studio-owned local log path even when
  `OTEL_EXPORTER_OTLP_LOGS_HEADERS` is also set, because SDKs may merge generic
  and signal-specific headers.
- For Java trace wiring, DI binding, and provider rules, follow `./references/languages/java.md` (Implementation Rules section).
- Place OTel initialization code in a separate file.
- Minimize changes to existing code. Do not move functions between files.
- Do not create spans for trivial helpers. Only span real diagnostic boundaries.
- Set span status to ERROR and call recordException on failed operations.
- When a framework-specific auto-instrumentation package only provides spans (not HTTP server metrics), wrap the outermost handler with `otelhttp.NewHandler` (Go) or equivalent to ensure `http.server.request.duration` and `http.server.active_requests` are emitted. Consult the Framework Selection Guide in the language reference for the correct wrapping pattern.
- HTTP server instrumentation must produce request-duration metrics as well as
  spans. Prefer the current stable metric `http.server.request.duration`. When
  the installed SDK requires a semantic-convention stability opt-in, set it in
  the launch environment before importing or constructing the instrumentor.
  Accept `http.server.duration` only when the installed SDK truly emits the
  alternate name and record that exact runtime evidence; never claim both names.
- For local, Docker, and eval-style runtime checks, configure metric export to flush quickly. When constructing a metric reader manually, use the language equivalent of `OTEL_METRIC_EXPORT_INTERVAL` with a safe local default of `1000` ms and `OTEL_METRIC_EXPORT_TIMEOUT` with a safe local default of `500` ms instead of relying on SDK defaults.
- Strictly adhere to OTel [semantic conventions](https://opentelemetry.io/docs/specs/semconv/) for span and metric naming and attributes for domains where such semantic conventions are defined.
- For domains where OTel semantic conventions exist, use semantic-convention
  names and attributes. Start with required spans, metrics, and attributes; add
  recommended optional signals only when an approved readiness or verification
  requirement depends on them, the service can observe the value accurately,
  and privacy/cardinality rules permit it. Do not invent custom spans, metrics,
  or attributes where a semantic-convention signal satisfies the requirement.
- When changing an existing metric's dimensions or a span/resource/log
  attribute contract, default to additive compatibility: keep safe existing
  fields and add semantic-convention fields. A same-name metric with removed or
  renamed dimensions is a breaking consumer change unless the removed dimension
  is unsafe high-cardinality data; even then, report it as an intentional
  breaking migration and provide the replacement query dimension.
- Before adding any custom counter or histogram for an outcome that occurs
  inside a call already covered by an auto-instrumented RED metric, check
  whether that outcome can instead be recorded as an attribute on the existing
  metric via the language's per-call metric-attribute hook (see
  `#### Language-Specific Musts` below), rather than as a new standalone
  metric. Each convention below defines its own error/status attributes for
  exactly this purpose:
  - [HTTP server/client metrics](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/):
    `http.server.request.duration` / `http.client.request.duration` carry
    `error.type` and `http.response.status_code`.
  - [RPC server/client metrics](https://opentelemetry.io/docs/specs/semconv/rpc/rpc-metrics/):
    `rpc.server.call.duration` / `rpc.client.call.duration` carry `error.type`
    and `rpc.response.status_code`. Only fall back to the legacy
    `rpc.server.duration` / `rpc.client.duration` names when runtime evidence
    shows the installed SDK still emits those instead.
  - [Database client metrics](https://opentelemetry.io/docs/specs/semconv/database/database-metrics/):
    `db.client.operation.duration` carries `error.type` and
    `db.response.status_code`.
  - [Messaging metrics](https://opentelemetry.io/docs/specs/semconv/messaging/messaging-metrics/):
    `messaging.client.operation.duration` and `messaging.process.duration`
    carry `error.type` when the operation fails.

  Prefer the attribute over a dedicated custom metric whenever the outcome
  can be faithfully represented on the RED metric for that call *and* the
  language has a way to set it there: either auto-instrumentation already
  emits a relevant `error.type`/`*.response.status_code` attribute that
  actually distinguishes this outcome, or the language has a supported
  per-call metric-attribute hook that can set a standard *or custom*
  attribute on the metric (see `#### Language-Specific Musts` below -- for
  example Go's `otelhttp.Labeler`, which can attach a custom attribute like
  `outcome.reason` even when the outcome is not expressible via the standard
  status/error attributes alone). A dedicated custom metric is correct
  whenever that's not the case: a queue-depth gauge or a background job
  outcome with no inbound request has no call to attach to; or the outcome
  is not expressible via the standard status/error attributes alone (for
  example a business outcome that occurs once per request but is not
  distinguishable from the standard attributes -- a logical failure returned
  as HTTP 200, or two distinct failure causes sharing one HTTP status) and
  the language's auto-instrumentation also has no per-call metric-attribute
  hook to carry a custom attribute instead (Python's ASGI/WSGI hooks and
  Node's `@opentelemetry/instrumentation-http` only add span attributes, not
  metric attributes). In each of those cases, add the dedicated metric
  instead of suppressing the only detector-ready signal for the outcome.
- For incident-readiness work, follow
  `../references/incident-readiness.md`. Instrument only source-evidenced
  workflow, dependency, input-complexity, freshness, backpressure,
  synthetic/canary, auth/edge, capacity, health/readiness, and release/config
  surfaces. Prefer semantic-convention HTTP, RPC, database, messaging, process,
  and runtime signals; add custom outcome, lag, freshness, queue, retry,
  timeout, rate-limit, endpoint/target-health, drop/reject, circuit-breaker,
  saturation, desired-vs-healthy, startup/readiness/healthcheck, compatibility,
  and rollout signals only when the service owns and can observe them
  accurately.
- For GenAI/LLM code, follow `../references/genai-readiness.md`: create
  baseline distributed tracing plus OTel GenAI spans for inference,
  `invoke_agent`, `invoke_workflow`, `plan`, `execute_tool`, `retrieval`, and
  memory operations where code evidence exists; emit
  the current inference duration and usage metrics from the shared reference
  when their source data is available and selected by the
  audit or requested signal scope; use stable tool names;
  add low-cardinality `error.type`; and avoid raw prompt, completion, retrieved
  content, memory record, tool argument, evaluation explanation, user, tenant,
  session, task, request, trace, or raw URL values in metric dimensions.
  Use the current inference metric names, instrument types, units and required
  measurement attributes; include applicable `gen_ai.token.modality` and known
  stable `gen_ai.operation.name`, `gen_ai.provider.name`, and
  `gen_ai.request.model` on the metric measurement itself, not only on the
  owning chat span. Preserve existing legacy metric producers as consumer
  contracts; do not silently rename them. Assert exact current and preserved
  contracts separately on collected metric points.
- When an audit selects only selected tool operations by exact stable name,
  branch at the tool dispatch or execution boundary: emit `execute_tool`
  spans and attributes for those names only. Let unselected tool names follow
  the existing execution path with the same result or error and without a new
  GenAI tool span. Test a selected success, a selected failure, and an
  unselected or unknown tool name to prove both telemetry scope and unchanged
  application behavior.
- For **Retrieval inside a tool**, preserve exactly one `execute_tool {tool}` span
  and add exactly one nested `retrieval {source}` child span for the distinct
  code-owned retrieval operation. Set `gen_ai.operation.name=retrieval` and a
  stable low-cardinality `gen_ai.data_source.id`; do not replace the outer tool
  span or count one operation as the other. The required GenAI profile includes
  actual redacted `gen_ai.retrieval.query.text` and
  `gen_ai.retrieval.documents` when available. Preserve an explicitly selected
  content restriction and mark required content partial rather than silently
  overriding it. Add focused telemetry proof that executes the path,
  asserts exactly one span of each kind, and proves the retrieval parent span ID equals the tool span ID using completed spans from an in-memory SDK exporter.
  Inspect the recorded retrieval `parent.span_id` and recorded tool
  `context.span_id`; object-parent equality in a custom recording tracer is
  insufficient ID proof. The test asserts `gen_ai.operation.name` and `gen_ai.data_source.id`
  on the retrieval child, proves safe query/document content matches the actual
  operation in the required profile, and proves sensitive sentinels are absent
  from all exported attributes/events. For restricted capture, assert content
  absence and retain the missing full-content acceptance honestly.
- Prove every custom metric's exact name, unit, instrument type, and complete
  emitted dimension sets. Lifecycle-specific counters must retain their
  specific error class; generic terminal errors must not overwrite earlier
  token-limit, truncation, timeout, provider, or tool classifications. Do not
  attach transient terminal outcome/error dimensions to intermediate gauges or
  size measurements unless the metric contract explicitly requires them.
- Keep production instrumentation independent of audit, report and eval input
  files. If runtime schema validation needs a data asset, make it an
  application-owned asset included by the normal packaging/deployment path;
  validation-only schemas remain in tests. Prove actual startup and local
  export from a clean application copy without `.observe`, `eval/inputs`,
  harness workspaces or absolute paths to the development directory. Include the
  declared application assets and normal operator configuration in that test.
- For GenAI/LLM code, apply the `Single-Source GenAI Span Contract` before
  adding manual spans. Inventory framework/vendor bridges, provider SDK hooks,
  callbacks, middleware, auto-instrumentors, and existing app spans that can
  emit GenAI telemetry. Choose one canonical GenAI span source per logical
  operation: workflow, agent, model call, tool call, retrieval, memory operation, or
  evaluation result. If a framework/vendor bridge already emits correct GenAI
  semconv spans with lifecycle, privacy, model/tool attributes, and parent
  context, keep that bridge and add only missing workflow/agent context,
  aggregates, metrics, or owner mappings; do not create duplicate app-owned
  `chat` or `execute_tool` spans for those same operations. Preserve existing
  app-owned spans in the same way. A new uncovered operation must not duplicate
  another active creator; enrich that creator through supported hooks first.
  Do not disable existing bridges or replace their operations merely because
  a new wrapper is easier to author. If ownership conflicts already exist or
  supported enrichment cannot make a producer safe, record the exact affected
  operations and prerequisite/manual decision. Preserve unrelated coverage.
  Inspect the actual preload/agent/auto-instrumentation bootstrap and exercise
  changes through the real launch profile. Module-local environment edits
  after bootstrap do not prove the active producer/configuration state.
  Verification or static proof must show one GenAI node per logical operation,
  no wrapper-only spans counted as tools, expected LLM/tool counts, stable
  model/tool names, and workflow/agent parent shape such as
  `invoke_workflow -> invoke_agent -> chat/execute_tool`. Required proof should
  name stable model/tool names explicitly.
- For Python `splunk_ao`, apply the **Splunk AO Python compatibility** guidance
  from the shared Agent Observability reference before changing providers or
  GenAI spans. Identify `@log`, `SplunkAOLogger`, and supported wrappers or
  handlers as span creation; identify `add_splunk_ao_span_processor` as
  export-only; distinguish `configure_distributed_tracing` combined setup from
  `instrument_distributed_tracing` transport-only behavior.
  - With **no existing OpenTelemetry provider**, preserve valid `@log` or
    framework-created operations as the existing span source. Add the minimum
    supported integration only for selected uncovered operations, and do not
    add an app-owned OTel span around the same logical operation. Treat HTTP,
    metrics, logs, streaming, sessions, and uncovered GenAI operations as
    independent closure work.
    Only a live runtime without any existing telemetry instrumentation uses
    supported Splunk AO creators by default. Apply the mandatory per-function producer decision gate in
    Decorator Selection before choosing helpers: use SDK `@log` for every
    supported uncovered function scenario, or an application-owned function
    decorator invoking the documented chosen creator for an exact SDK decorator
    contract limitation. If both SDK choices cannot meet required semantics,
    assess the shared per-operation public OTel compatibility exception before
    accepting a known-invalid helper. Preserve supported framework/provider ownership without a
    duplicate decorator span. Inspect current examples and chosen compatible
    APIs; evaluation-only imports do not cover a live runtime, while an active
    HTTP provider still selects incremental OTel gap filling.
  - With an **existing OpenTelemetry provider**, preserve that provider and
    all existing producers/exporters. Prefer SDK-free resource resolution and
    trace headers on the existing compatible exporter as the shared reference
    specifies. Do not introduce an AO SDK dependency or creator. The following
    SDK-specific configuration applies to an already selected compatible SDK
    export path, not to header-only existing exporters. A single
    `add_splunk_ao_span_processor` registration is valid only when all AO
    spans share one resolved destination. If the application chooses project
    or Agent Stream per request, do not register a startup-wide singleton AO
    processor: use route-keyed exporters/processors with exclusive dispatch
    for each completed span. Do not create or install a second provider. Pass
    the same provider to supported transport instrumentation only when
    selected and not already owned.
  - Before changing dependency declarations, inspect the actual installed
    `splunk-ao` version and its supported Python API. Prefer a compatible
    pinned released package already available to the application; do not copy
    a VCS pin from an unrelated optional/evaluation runtime merely because
    its import name matches. Persist the selected SDK in both the manifest
    and lockfile and run its import/configuration check. If dependency
    resolution is unavailable, retain the already installed SDK environment
    for credential-free compatibility tests, record the lock as a distinct
    blocker, and leave AO status partial; do not misreport this as missing
    cloud credentials or a durable installed route.
  - Inspect when the selected `SplunkAOOTLPExporter` captures project and Agent
    Stream routing. If it captures them at construction, a processor created
    by `add_splunk_ao_span_processor(provider)` inherits that fixed route.
    Calling it without routing arguments and later adding project/stream span
    attributes does not route those spans. The SDK's `splunk_ao_context` is
    imported from `splunk_ao`, not `splunk_ao.otel`, and a context entered
    after processor creation cannot retarget its exporter. Resolve real
    resource IDs before constructing an AO exporter. For two application
    streams, use separate supported SDK exporters/processors keyed by the
    resolved IDs and dispatch each completed span to exactly one destination
    selected at span start; registering both processors unfiltered on one
    provider broadcasts every span to both streams. An absent request selector
    may use a configured default route, but an explicit unknown route key or a
    project/stream lookup failure must fail closed for AO; never normalize it
    to the default or reuse another stream. Keep AO export disabled for an
    unresolved route while ordinary OTel still works. Prove the two
    effective SDK export destinations and their project/stream IDs from
    completed batches or captured requests; two mocked lookups or span-name
    attributes alone are insufficient. Keep the discovered Studio API origin
    in the selected configuration profile and actual launch selection, not as
    a fallback port constant in app code. For a credential-free proof,
    configure the real SDK against two resolved route pairs, substitute only
    its network exporter with a capture sink, exercise two request-selected
    operations and a third request-selected route whose project or Agent
    Stream lookup fails, then assert one export with the matching
    project/stream headers for each resolved route. Inspect the selected SDK's
    actual test-only delegate seam, such as `_exporter_factory` when supported,
    to capture its endpoint and `projectid`/`logstreamid` headers; construct
    the real SDK exporter for each route and replace only its network delegate.
    Replacing `SplunkAOOTLPExporter` itself with a fake proves only app
    dispatch, not the installed SDK contract. Explicitly assert that
    the unresolved third route creates no AO exporter and produces zero AO
    exports; test an explicit unknown key as well as a configured key whose
    lookup fails. Merely leaving an operation unrouted does not prove failure
    isolation. An in-memory ordinary OTel exporter should still receive all
    operations. Do not call selected AO routing working when this test is
    absent or blocked.
  - Ship a dedicated Studio-only profile, such as `.env.studio.example`, and
    document how the repository's actual local launch selects it. A general
    `.env.example` that mixes ordinary OTLP and AO placeholders is not that
    profile. When a reachable Studio gateway was discovered, write its real
    API and console origins with their actual port into the dedicated profile
    and run an installed-SDK configuration/import check using that profile.
    Blank URL values, angle-bracket port placeholders, and an unselected
    example do not constitute a working AO route. If discovery is unavailable,
    do not put active fabricated endpoint values in the Studio profile or
    launch configuration: leave the route blocked with the exact discovery
    failure. A credential-free installed-SDK configuration check may instead
    use a temporary loopback test origin and captured transport, but must not
    be reported as live Studio delivery. For that isolated Studio-mode check,
    clear inherited `SPLUNK_AO_REALM` and O11y token variables; set the
    temporary origin as both `SPLUNK_AO_API_URL` and
    `SPLUNK_AO_CONSOLE_URL` with `SPLUNK_AO_API_KEY=local-gateway`.
    Intercept only the SDK's health, login, and current-user network calls,
    then construct the real `SplunkAOOTLPExporter` with its test-only captured
    network delegate. Assert the effective `/otel/v1/traces` endpoint and
    `Splunk-AO-API-Key`, `projectid`, and `logstreamid` headers. A test using
    `SPLUNK_AO_REALM` plus an O11y token proves direct mode, not the Studio
    profile, even if both tests produce project/stream headers.
  - Keep the AO setup failure boundary around SDK import, client construction,
    project/stream API calls, and exporter/processor construction. A missing,
    disconnected, incompatible, or unauthorized Studio gateway disables only
    AO export with a value-free diagnostic; it must not stop application
    startup, suppress ordinary OTel spans or metrics, or switch to direct
    cloud. Test an API compatibility error such as a failed SDK login and
    assert the live application request plus ordinary OTel exporter still work.
  - Before adding `@log`, account for its documented capture of function
    arguments and return values. Use a boundary whose arguments and result
    are already safely transformed metadata or a
    source-verified integration control that prevents raw capture; otherwise
    report the SDK privacy blocker and keep required coverage partial. A
    selected restricted-content closure for an existing producer may stay
    metadata-only, but does not pass the required GenAI content profile.
    Companion `redacted_input` or `redacted_output` values alone are not proof
    that the original raw values were removed. Never expose raw
    prompts, completions, retrieved documents, tool arguments/results,
    identifiers, or secrets merely to gain an AO node.
  - Add credential-free tests using an in-memory exporter, fake sink, or
    monkeypatched SDK boundary. Assert reuse of the existing provider, processor count,
    shutdown/termination, expected parentage and one-node counts, content
    absence with a unique sentinel, and duplicate-span prevention. When the
    Splunk AO sink and application provider coexist, inspect both outputs.
    In the required profile also assert applicable redacted inputs/outputs,
    instructions, effective tools, actual arguments/results and vendor message
    mappings against current OTel schemas and real invocation/result values.
    Check provider/request/response/usage and stream fields independently;
    do not infer complete coverage from SDK adoption or export success.
    Live delivery is separate proof;
    do not require live credentials for the compatibility tests.
  - For a finite `@log` application, finish each SDK-created operation and
    prove the logger's supported teardown path. Where the installed SDK exposes
    `splunk_ao_context.get_logger_instance()`, terminate that logger once after
    work concludes (or prove the SDK's registered process-teardown callback).
    `splunk_ao_context.flush()` can drain completed spans, but flush alone does not terminate
    the logger or close an unfinished operation. Keep `provider.shutdown()` for
    any separate app-owned provider. In tests, capture both SDK-created and app-owned spans
    from both independent entrypoints, assert the expected logical operation
    count in each path, and inspect the combined output when both paths are
    active. A fake sink can prove lifecycle calls and duplicate prevention;
    it cannot prove live Splunk delivery.
- Preserve existing application stable business workflow identity when setting
  `gen_ai.workflow.name` and workflow span names. Prefer constants, function or
  handler names, workflow registrations, telemetry event names, docs, or prior
  trace names. Do not derive GenAI workflow names from HTTP routes, request
  resources, session/storage tables, or transport labels. If source evidence
  shows a workflow is named `assistant_v3_turn`, keep `assistant_v3_turn`;
  never rename it to `assistant_v3_session_turn`, `POST /v2/assistant/sessions`,
  or another route/session-derived value. If the app has no stable workflow
  identity, keep the HTTP route as the HTTP span and mark GenAI workflow
  coverage partial instead of inventing a low-cardinality workflow name.
  Do not invent names from HTTP routes or session-derived labels.
- Preserve existing application stable agent identity when setting
  `gen_ai.agent.name` and agent span names. Prefer framework agent names, agent
  factory names, class names, registration names, callback owner names, docs, or
  prior trace names. If source evidence shows a DeepAgents-backed agent, use the
  discovered stable agent identity such as `deepagents`; never rename it to
  `assistant_v3_agent`, `assistant`, `agent`, or another generic service-derived
  wrapper name. If the app has no stable agent identity, keep agent coverage
  partial instead of inventing one.
- For app-owned LLM/model calls, apply the `LLM Inference Lifecycle Contract`.
  Do not satisfy inference coverage with workflow-level token accounting,
  final usage events, token usage, or model names only on the workflow span.
  Add or prove a real model-call lifecycle span at the provider request
  boundary: start before the call or stream starts, end after the
  response/terminal stream event, and end with error status for exceptions,
  cancellations, provider timeouts, or stream-close failures. In LangChain,
  LangGraph, DeepAgents, callback, or event-stream based systems, hook
  `on_chat_model_start`, `on_chat_model_end`, and `on_chat_model_error` or the
  equivalent lifecycle callbacks. In direct SDK/model-gateway code, wrap the
  provider call or streaming generator. The span must carry
  `gen_ai.operation.name` such as `chat`, `generate_content`, or
  `text_completion`, `gen_ai.provider.name`, `gen_ai.request.model` when known,
  `gen_ai.response.model` when known, and token usage on that inference span
  when provider usage is available. For current inference usage counters,
  put the required `gen_ai.token.modality` and known stable `gen_ai.operation.name`,
  `gen_ai.provider.name`, and `gen_ai.request.model` on the token metric as
  attributes too; span attributes alone do not make token metrics filterable
  by operation, provider, or model. Include `gen_ai.response.model` on the
  token metric when known. Never use prompt, response, session, or user content
  as metric attributes.
- Preserve the owning workflow/agent context for event-derived GenAI spans. In
  callback, stream, LangChain, LangGraph, or DeepAgents integrations, capture
  the workflow/agent context and use it when starting chat/model and tool
  spans. Do not let callback-created `chat` or `execute_tool` spans attach to a
  generic HTTP root span as siblings of the workflow. A representative trace
  should prove a shape such as `workflow -> chat`, `workflow -> execute_tool`,
  and follow-up `workflow -> chat` or `agent -> chat` edges.
- Capture that workflow/agent context before opening long-lived helper/setup
  spans such as memory store, checkpointer, database session, stream-writer,
  resource setup, or lifecycle wrappers. These helper spans must not become the
  parent for model/tool lifecycle spans. Event-derived `chat` and `execute_tool`
  spans must use the captured workflow/agent context, not whichever helper span
  happens to be current when a callback is translated. Store the workflow/agent
  span object or context explicitly so stream cleanup writes aggregates to that
  owner even if the current span has changed.
  Use this rule for memory store, checkpointer, database session, stream-writer,
  or resource setup paths: helper spans must not become the parent; capture the
  workflow/agent context before opening helper spans, start event-derived `chat`
  and `execute_tool` spans with that captured context, and write aggregate
  counters to the workflow span, not to whichever current span is active.
- In async generator, SSE, WebSocket, ping-loop, timeout-wrapper, or task handoff
  paths that advance a stream with `create_task`, `wait`, `anext`, or equivalent
  scheduling, do not keep an OpenTelemetry current-span context manager open
  across yield/task boundaries. Start the workflow/agent span with an explicit
  parent context, store a workflow span/context handle, pass that handle into the
  callback/event translator, and end the workflow span manually after stream
  cleanup.
- When the captured workflow/agent context must travel through a request, turn
  input, event payload, callback state, or config object that may be
  immutable/frozen or owned by a framework, do not mutate that carrier in place.
  Treat a carrier as immutable/frozen when source evidence shows frozen or
  readonly declarations, record/value types, no mutation API, framework request
  immutability patterns, or existing code constructs new copies instead of
  mutating.
  Use the app's idiomatic copy/replacement API: Python `dataclasses.replace`,
  `attrs.evolve`, pydantic `model_copy(update=...)` or `copy(update=...)` as
  supported by the installed carrier API;
  Java records, builders, or copy constructors; TypeScript object spread,
  explicit `Readonly<T>` replacements, or `structuredClone` only for plain-data
  carriers and never for live OTel `Context` or `Span` handles; Go value copies
  with explicit field replacement; or the framework's request clone/with-context
  API. If no safe copy path exists, use a separate invocation-scoped sidecar
  context: a local object, context variable, request-scoped map, or callback
  state keyed to the invocation lifecycle and cleared after cleanup. Do not key
  sidecar context by raw user, tenant, session, request, or trace IDs. Add a
  focused test, or explicit static proof when the repo has no test harness, that
  proves the parent context is passed downstream and the original immutable
  input remains unchanged; for Python, guard against `FrozenInstanceError`
  regressions when a frozen dataclass or model is present.
- Put aggregate selected-trace GenAI attributes on the workflow span or
  most specific owning GenAI span, not on a generic HTTP root span or generic server span.
  This includes `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`, an application/vendor-owned derived total,
  `assistant.llm.calls`, and `assistant.tool.calls`. The HTTP root can remain
  the server entrypoint, but it should not become the evidence for a GenAI flow
  card unless it is explicitly instrumented as the workflow span.
- If runtime telemetry verification is unavailable, perform a static
  instrumentation proof before claiming GenAI trace coverage: identify the
  model-call source file, the lifecycle hook or client wrapper, the created
  inference span name, required `gen_ai.*` attributes, parent-context handoff,
  aggregate-attribute placement, end/error path, and a focused test or compile
  check. If the proof shows only workflow-level usage attributes and no
  inference span, or chat/tool spans that are siblings of the workflow under a
  generic HTTP root span, keep the surface partial in `remaining_signals`.
- For local span-first trace explorers such as Splunk Observability Studio, metrics alone are not enough
  for a selected-trace summary. When provider usage, model, tool,
  memory, evaluation, or fanout data is available, also set safe span attributes
  on the most specific GenAI span and aggregate to the workflow span when
  useful: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
  an application/vendor-owned derived total, `gen_ai.request.model`,
  `gen_ai.response.model`, service-owned LLM/tool call counts, stable
  `gen_ai.tool.name`, memory operation names, evaluation names/labels, and
  low-cardinality `error.type`.
- Reconcile newly added `gen_ai.*` attributes with the current official
  registry. Do not introduce `gen_ai.usage.total_tokens` when it is not
  published there; a useful derived total belongs in an application/vendor
  namespace with actual/estimated count provenance. Preserve a proven existing
  consumer alias as legacy rather than requiring it on fresh spans.
- For assistant, agent, or streaming workflows, instrument first non-ping event
  or first chunk latency, timeout, cancellation, disconnect, close reason
  family, and send/write failure. Normalize timeout classes such as
  `first_event_timeout` instead of relying only on framework exception class
  names, while still recording the exception on the span.
- For custom attribute names use `{domain}.{noun}.{adjective}` format.
- Span names must be low-cardinality (no IDs, no variable path segments).
- Metric attributes must avoid high cardinality.
- Preserve existing env-var patterns for operator-owned telemetry config. The
  only endpoint literal the default log path may introduce is the
  signal-specific local Splunk Observability Studio fallback; it must not inherit a generic
  direct-cloud endpoint.
- If the app is a library, provide an opt-in setup path rather than forcing SDK initialization on import.
- Keep the codebase idiomatic. Match the repo's dependency manager, config style, and lifecycle patterns.
- Obtain OTel Tracer, Meter once during startup and reuse it. Do not call `getTracer` or `getMeter` in hot paths.
- Create metric instruments once during startup and reuse them. Do not create instruments in hot paths.
- Metric instruments must be created with appropriate unit and description parameters.

#### Default Local Application Log Export

- Classify application logs during preflight as `local-otlp-default`,
  `explicitly-disabled`, `operator-owned`, `correlation-only`, or
  `unsupported-stack`. Trace/MDC fields in stdout are correlation-only, not an
  OTLP log pipeline.
- For a supported Python, Node.js, Java, or Go application logging stack,
  configure local Splunk Observability Studio OTLP export by default. Use the official log SDK,
  batch processor/exporter, and the official bridge for the detected stack.
  Keep one `LoggerProvider` and exactly one bridge/export path per record.
- Preserve operator ownership. Never overwrite an explicitly set
  `OTEL_LOGS_EXPORTER` or `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`.
  `OTEL_LOGS_EXPORTER=none` disables the added provider/exporter and bridge.
  Another explicit exporter is operator-owned and must not be supplemented
  with a second local pipeline, but its provider/exporter/bridge must be proven;
  an environment value by itself is not evidence of export. When the exporter
  is absent or explicitly `otlp`, an explicit signal endpoint may be used by
  the Splunk Observability Studio-owned pipeline only when it exactly matches the detected local
  Splunk Observability Studio receiver for the selected runtime and protocol. The detected
  receiver may use any valid port. Resolve it during instrumentation from the
  shared local-receiver contract and adapt it to the checked-in Docker/Compose
  service address when applicable.
  Default an absent exporter to `otlp` and an absent endpoint to that detected
  local receiver. If the explicit endpoint is non-local or direct-cloud, do not
  construct or enable the Splunk Observability Studio provider/exporter/bridge; fail closed for
  the local log branch and report the operator-owned boundary conflict. Never
  turn that log-only conflict into an application startup exception or disable
  the operator-owned trace/metric route. Keep the original logging sink active.
  Do not validate the logs
  endpoint on the `none` or other non-OTLP exporter branches, because those
  branches remain wholly operator-owned.
- Preserve existing stdout, stderr, file, and platform logging sinks. Add the
  OTel bridge alongside them; do not replace their handlers, appenders,
  transports, levels, formatters, or rotation policy. If the stack cannot fan
  out safely, keep it `unsupported-stack` and report the exact missing bridge
  instead of silently removing the existing sink.
- Never derive the default log destination from a generic endpoint that points
  directly at a cloud ingest service. Use a signal-specific local logs endpoint
  and keep any direct-cloud endpoints signal-specific to traces and metrics.
  Splunk Observability Studio cloud forwarding to Splunk is traces and metrics only. Do not add a
  cloud log endpoint, cloud log header/token, cloud log exporter, or log
  forwarding flag.
- Resolve the log protocol independently. The local baseline is
  `http/protobuf` with `/v1/logs`; when an explicit signal-specific protocol is
  different, select its matching official exporter and endpoint shape or
  report it unsupported. Never silently send HTTP to a gRPC endpoint. A generic
  header must not be inherited or merged into logs: move
  `OTEL_EXPORTER_OTLP_HEADERS` to trace/metric signal variables and remove the
  generic value before enabling the local log path, even when an explicit
  signal-specific log header is present. Preserve the operator-owned
  `OTEL_EXPORTER_OTLP_LOGS_HEADERS` value after the generic value is removed.
  Until that migration is complete, skip only the local log exporter/bridge and
  report the conflict; do not reject startup or discard the existing
  trace/metric provider configuration.
- Before adding a bridge, search for auto-instrumentation, handlers, appenders,
  transports, hooks, and worker-thread exporters that already send the same
  record to OTel. Choose one owner and disable or omit the overlap. Preserve
  correlation injection without creating a second exported record.
- Apply privacy checks to the final logging pipeline: formatter fields,
  adapters, MDC/context variables, framework access logs, and exception
  rendering. Removing IDs from one `logger.*` call is insufficient when a
  formatter or access logger adds them back. Keep raw request/user/tenant/
  session IDs, raw dynamic URLs, exception text, and tracebacks out of the
  approved application-log surface unless the policy explicitly permits them.
- Add focused and full-runtime proof for log body/category, severity, shared
  resource identity, trace/span correlation in an active span, redaction,
  preservation of the existing sink, explicit `none` opt-out, and exactly one
  OTLP record per application log call. When cloud trace/metric forwarding is
  configured, also prove the log is visible in local Splunk Observability Studio and no cloud log
  exporter or forwarding path was configured.
- When `OTEL_LOGS_EXPORTER=none`, disable or bypass any previously discovered
  application-log provider/bridge as needed to prove zero OTLP application log
  records; leaving an already-active bridge in place is not a valid opt-out.
- Report a missing default or requested local export pipeline as `Not
  configured`, not `Not proven`. Use `Not proven` only after configuration
  exists but its required runtime scenario did not run.

#### Language-Specific Musts

Python:
- Add explicit dependency entries for `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, and each detected framework/client instrumentation package.
- Create a separate setup file such as `otel_setup.py`, `telemetry.py`, or `instrumentation.py`.
- Configure a shared `Resource.create({"service.name": ...})`, trace provider,
  meter provider, and default local log provider/exporter in that setup file only
  for signals the process does not already own. If a source-owned provider
  exists, move or adapt its construction into the shared setup while preserving
  existing wrappers, views, file-export modes, and tests; do not create a
  second provider.
- Import and call the setup function from the app entry point before creating or instrumenting the app.
- For Flask, call `FlaskInstrumentor().instrument_app(app)`.
- For FastAPI, call `FastAPIInstrumentor.instrument_app(app)` immediately
  after app construction and before lifespan/startup begins. Do not first call
  it inside lifespan: Starlette/FastAPI middleware installation is too late
  after the application has started serving.
- For Celery, call `CeleryInstrumentor().instrument()` in the worker path.
- Keep existing Docker/Compose/Makefile commands, but update them only as the startup surface for the explicit setup, not as a replacement for app wiring.
- For stdlib `logging` (including Flask/Django logging), use the current
  `opentelemetry-instrumentation-logging` bridge backed by `LoggerProvider`,
  `BatchLogRecordProcessor`, and the selected OTLP log exporter. Its guarded
  setup must preserve logging configuration performed before or after OTel;
  do not call `basicConfig(force=True)` or replace stdout/file handlers. For a
  project whose installed instrumentor lacks that supported bridge, inspect
  and retain its documented SDK `LoggingHandler` compatibility path instead
  of forcing an upgrade. Shut the
  log provider down with the other providers.
- The ASGI/WSGI instrumentation underlying Flask/FastAPI already sets
  `http.response.status_code` on `http.server.request.duration` for every
  request, and `error.type` for a 5xx (or otherwise invalid) status, with no
  extra code -- a plain 4xx client-error response does not set `error.type`
  on a server span. `server_request_hook`/`response_hook` only set span
  attributes, not metric attributes; they are not a route to a new dimension
  on the duration metric itself. Do not add a standalone counter for a
  request outcome the duration metric already attributes correctly.

Node.js:
- Add `@opentelemetry/instrumentation-http` explicitly for HTTP server spans.
- Add the detected framework instrumentation explicitly, for example `@opentelemetry/instrumentation-express` for Express.
- Add `@opentelemetry/exporter-metrics-otlp-http` and `@opentelemetry/sdk-metrics` when wiring SDK-based metrics.
- Add `@opentelemetry/exporter-logs-otlp-proto` for the default
  `http/protobuf` path and
  `@opentelemetry/sdk-logs`, pass one `BatchLogRecordProcessor` through
  `NodeSDK.logRecordProcessors`, and add only the detected official bridge.
  For detected `console.*` calls, use
  `@opentelemetry/instrumentation-console` only after checking its current
  package engines, peers and API against the selected runtime and project.
  Choose the latest compatible release; it must emit LogRecords while
  preserving console output. If no compatible bridge exists under the project
  constraints, report the exact unsupported contract instead of forcing an
  upgrade. Otherwise select the detected Winston or Pino
  instrumentation/transport bridge. Keep existing console/file transports.
  Do not enable an instrumentation sender and an OTel transport for the same
  logger; `sdk.shutdown()` must flush logs as well as traces and metrics.
- Configure `PeriodicExportingMetricReader` with `exportIntervalMillis: Number(process.env.OTEL_METRIC_EXPORT_INTERVAL || 1000)` and `exportTimeoutMillis: Number(process.env.OTEL_METRIC_EXPORT_TIMEOUT || 500)` so HTTP duration metrics export during short runtime checks.
- Use the current `NodeSDK` metric reader option exactly as shown in the Node reference. Do not substitute `metricReaders` for `metricReader` unless the installed SDK version documents that option.
- Do not rely on `@opentelemetry/auto-instrumentations-node` alone when specific framework packages are expected.
- In the final response, name the updated preload command (`--require` or `--import`), the packages added, and that HTTP server spans plus request-duration metrics are expected.
- `@opentelemetry/instrumentation-http` already sets `http.response.status_code`
  on `http.server.request.duration` from the response for every request with no
  extra code. It does not set `error.type` from a failing status code:
  `error.type` there is reserved for a lower-level request/response transport
  error (for example a socket error before a status was ever sent), not an
  ordinary 4xx/5xx completion. Its hooks (`requestHook`, `responseHook`,
  `startIncomingSpanHook`) only add span attributes, not metric attributes.
  Do not add a standalone counter for a request outcome that `http.response.status_code`
  already distinguishes; `@opentelemetry/instrumentation-http` has no per-call
  metric-attribute hook, so a finer-grained reason dimension that the status
  code alone cannot express does need its own custom metric here.

Go:
- For HTTP services, use `otelhttp.NewHandler` as the outermost server handler so request-duration metrics are emitted, even when router-specific middleware is also used for route-aware spans.
- For chi, gin, mux, or another router with parameterized routes, route-aware
  server spans are required. Add the matching framework middleware inside the
  outer `otelhttp.NewHandler`, then prove at least one parameterized route uses
  its low-cardinality route pattern rather than a constant `server` span name.
  Also prove the combined wrappers do not emit duplicate server spans.
- Configure `sdkmetric.NewPeriodicReader` with an interval derived from `OTEL_METRIC_EXPORT_INTERVAL`, defaulting to `1000` ms, and a timeout derived from `OTEL_METRIC_EXPORT_TIMEOUT`, defaulting to `500` ms, for local runtime checks.
- Add `go.opentelemetry.io/otel/sdk/log`,
  `go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp`, and exactly
  one official `go.opentelemetry.io/contrib/bridges` package matching the
  detected logger. Register one global log provider, preserve the existing
  stdout/file handler through fan-out, pass `context.Context` to logging calls
  for trace correlation, and shut the log provider down.
- In the final response, state the server handler wrapping, service-name setting, OTLP endpoint setting, and that HTTP server spans plus request-duration metrics are expected.
- `otelhttp.NewHandler` already sets `http.response.status_code` on
  `http.server.request.duration` from the response status with no extra code.
  It does not set `error.type` from that status: `otelhttp`'s metric
  attributes never include `error.type` for an ordinary 4xx/5xx completion.
  When a handler needs a dimension `otelhttp` cannot derive from the
  status code alone (a specific failure reason such as a downstream timeout
  vs. a validation error, both returning the same HTTP status), pull the
  `Labeler` that `otelhttp.NewHandler` already injects into the request
  context and add the attribute from inside the handler instead of creating
  a new counter:
  ```go
  labeler, _ := otelhttp.LabelerFromContext(r.Context())
  labeler.Add(attribute.String("outcome.reason", "gateway_timeout"))
  ```
  No extra `otelhttp.NewHandler` option is needed; the labeler is present in
  context for every request the handler already wraps. The older
  `otelhttp.WithMetricAttributesFn` middleware option is deprecated in favor
  of this per-request `Labeler`. A custom attribute like `outcome.reason` is
  detector-ready without a standalone counter: see
  `splunk-configure/references/detector-classification.md`'s "Evidenced
  Non-Standard Outcome Attribute" rule, which generates an attribute-filtered
  outcome detector directly from an evidenced non-standard histogram
  attribute.

Java:
- Use the Java agent for Spring Boot unless custom business spans are explicitly requested.
- Avoid adding SDK dependencies to `pom.xml` for basic Spring Boot coverage.
- Follow `./references/languages/java.md` Implementation Rules for DI binding, provider reuse, and dependency checks.
- Wire the agent through the existing startup surface, `JAVA_TOOL_OPTIONS`, or a documented run command.
- Default the Java agent's application log exporter to `otlp` only when
  `OTEL_LOGS_EXPORTER` is absent and the logs endpoint is absent or matches the
  detected local Splunk Observability Studio receiver. Set that local
  `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`, and rely on the agent's detected
  Logback/Log4j bridge plus JVM shutdown hook. A non-local explicit endpoint on
  the absent/`otlp` branch is a fail-closed boundary conflict and must not start
  the agent-owned log path. Preserve explicit `none`, other exporter choices,
  existing appenders, and any single existing OTel appender; never install a
  second bridge.
- In the final response, explicitly mention the agent setup or path,
  `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, HTTP server spans, and
  `http.server.request.duration`.

### 4. Custom Instrumentation

After auto-instrumentation is wired up, prompt the user:

> Auto-instrumentation is configured. Would you like me to add custom spans or metrics for your business logic?

Then wait for the user's answer.

Skip this prompt when the user already asked for incident-readiness or GenAI/LLM
workflow instrumentation, a specific custom signal, when an Audit-Driven
Readiness path applies, or when a validated canonical selection exists. In
canonical flow, the selection is the approval context and only selected work is
implemented. When no canonical audit exists, stop before custom
instrumentation and ask the user to run `$otel-audit` first.

- **If no**: proceed to the project-runtime validation gate (Step 5).
- **If yes**: for each candidate point below, first check whether it occurs
  inside a call an auto-instrumented RED metric already measures (HTTP, RPC,
  DB, or messaging — see `#### Implementation Rules`); if so, prefer adding
  an attribute to that existing metric via the language's per-call
  metric-attribute hook over defining a new counter/histogram. Analyze the
  codebase for high-value custom instrumentation points:
  - Error handling paths that catch and handle exceptions
  - Key business operations (payments, orders, user registration, etc.)
  - External calls not covered by auto-instrumentation libraries
  - Background workers and scheduled jobs
  - Cache interactions without auto-instrumentation support
  - Incident-readiness boundaries: customer-impact workflow outcome,
    dependency timeout/retry/rate-limit/error and endpoint/target health, input
    complexity, freshness, queue/backpressure, synthetic/canary result,
    auth/edge failure, capacity saturation, desired-vs-healthy,
    startup/readiness/healthcheck, traffic target health, and release/config
    context when code evidence exists
  - Incident-evidence boundaries: every supplied failure mechanism must map to
    an added or proven code-owned signal or an explicit external owner; generic
    endpoint metrics are insufficient when the mechanism is auth handshake,
    secret expiry, stale output, rollout skew, dependency target health, stream
    lifecycle, or pool saturation
  - GenAI/LLM workflow boundaries: workflow span, agent/workflow invocation,
    LLM inference, tool/function execution, MCP method dispatch when present,
    retrieval, fallback, token usage, model/config readiness, prompt/response
    parse outcome, safety/policy outcome, AI-derived data freshness, and
    AI-owned session/stream lifecycle when code evidence exists
  - Suggest specific spans and metrics with names, attributes, and rationale
  - Apply after user approval

