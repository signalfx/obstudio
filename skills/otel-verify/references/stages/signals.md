### 5. Run Signal Verification

Run the smallest set of commands that proves the inventories. If a live app,
network, Docker, credentials, or long-running service is required, first look
for an offline unit/integration alternative.

#### Conditional Full Runtime Acceptance

When `../references/full-runtime-acceptance.md` is triggered, execute that gate
after build/import viability and focused tests. Do not defer it merely because
a synthetic-root or direct call-site harness exists. Use the audit's
`Proof Level` and local-safe fixture column to start the actual process and
exercise the complete runtime-required route/scenario matrix. If no safe local
profile exists, document the exact missing prerequisite and keep those rows
`Partial`, `Blocked`, or `Not proven`.

Use the same selected project runtime for temporary harnesses that you used for
compile/import checks. Do not compile a harness with a global classpath,
interpreter, package manager, or SDK when the project has a configured wrapper
or toolchain.

Coverage rules:

- A row is app-verified only when app code ran through an existing test, newly
  authored repo test, temporary app-code harness, or live smoke.
- Spans are verified only when name/pattern, required attributes, status/error
  behavior, and parent/child topology when relevant are asserted or observed.
- Metrics are verified only when a datapoint is observed or asserted for each
  expected metric name, unit, instrument type, and required complete dimension
  set. A source definition is not emission proof. Reject unexpected transient
  outcome/error dimensions as well as missing required dimensions.
- Logs are verified only when a log record is observed or asserted with
  expected body/category, severity, trace/span correlation when required, and
  redaction.
- Trace topology is verified only when expected parent -> child edges, links,
  or span depth are asserted or visible in collector or Splunk Observability Studio evidence. Span
  presence alone is not DAG proof.
- Path coverage is verified only when the scenario trigger ran or was
  faithfully synthesized, expected topology/signals were asserted, and
  collector or Splunk Observability Studio evidence was captured when OTLP is available.
- Runtime-only rows are verified only by the real process with its actual
  agent, preload, middleware, or startup bootstrap. A synthetic owning root or
  direct handler call cannot prove automatic server span count, kind, route
  name, automatic metric emission, or duplicate suppression.
- If the audit names multiple telemetry-distinct outcomes for one workflow,
  such as success, failure, interrupt, empty, unavailable, retry, fallback, or
  timeout, treat each as a separate path scenario unless source inspection
  proves identical telemetry.

Use this status vocabulary:

- `Verified: unit`: deterministic app-code assertion or in-memory exporter
  proof, not exported to a collector.
- `Verified: OTLP`: collector or Splunk Observability Studio evidence from a real SDK exporter.
- `Verified: unit+OTLP`: deterministic assertions and collector or Splunk Observability Studio
  evidence from the same focused scenario when possible.
- `Verified: app test`: committed or newly authored repo-native test executes
  app code and asserts telemetry. Use `Verified: app test+OTLP` when paired
  with local OTLP proof.
- `Source only`: source definition found but no emission was observed or
  asserted. Do not use this for declared dependencies that cannot be resolved.
- `Not emitted`: scenario ran but expected telemetry did not appear.
- `Not run`: scenario was not executed.
- `Blocked`: verification could not be attempted due to a concrete local
  prerequisite, including unresolved declared dependencies.
- `Not configured`: the requested signal has no implementation or runtime
  configuration, such as an absent OTLP log bridge/exporter.
- `Not applicable`: audit confirms no signal of that type was added or
  modified.

When a row is not fully verified, include one concrete reason: missing harness,
requires full app startup, live provider, credentials, unsafe side effect,
undriven error/timeout/stream/shutdown path, no log exporter, collector eviction,
source-only definition, missing metric datapoint, missing span attributes or
parentage, or missing log severity/body/correlation/redaction.

### 6. Prefer Unit+OTLP Contract Harnesses

When Splunk Observability Studio, a local collector, or an explicit OTLP endpoint is available,
try to upgrade deterministic unit/integration proof to `Verified: unit+OTLP`
for every language and framework.

Follow `references/explorer-witness.md`: keep the source alive through exact
queries, save sanitized query responses before shutdown, and report live
visibility separately from post-exit persistence. Expected local eviction is
not an instrumentation failure.

- Configure real SDK tracer, meter, and logger providers before importing app
  modules that cache OTel globals.
- Export from the same focused fake-input scenario that performs assertions.
- Prefer one trace per path scenario. Use stable attributes such as
  `verification.scenario`, `verification.path`,
  `verification.audit_source`, and `verification.coverage_kind`.
- Resolve the current local endpoint with the shared receiver precedence and
  preserve its exact port. HTTP `127.0.0.1:4318` and gRPC `127.0.0.1:4317` are
  conventional fallbacks only. Never export verification telemetry to production.
- Run at least one deterministic OTLP check on a non-default local port, or use
  existing evidence that did so, so hardcoded `4317`/`4318` behavior cannot
  pass. Do not probe the conventional ports after a configured or advertised
  endpoint has been resolved.
- Verify the effective endpoint, protocol, and path separately for traces,
  metrics, and logs. If one signal fails, test the configured exporter against
  the matching receiver: gRPC commonly uses `4317`; HTTP/protobuf commonly
  uses `4318/v1/<signal>`. Do not treat successful traces as evidence that the
  metrics exporter is valid.
- For the default Studio pipeline, verify the consumed launch profile has
  `OTEL_LOGS_EXPORTER=otlp` and that application LogRecords arrive in Studio
  alongside the actual trace spans and metric datapoints. A generated `none`
  setting without an explicit user/operator opt-out does not satisfy default
  log acceptance. SDK `@log` GenAI spans and stdout correlation do not prove
  log export. Keep intentional opt-out tests separate from the normal launch.
- Verify dependency compatibility using the actual installed/locked packages
  and current official metadata/APIs; record exact resolved versions and
  source dates in run evidence. Skills contain no fixed library release
  recipes. Do not upgrade the application during read-only verification or
  claim a newer proposed compatible set was installed or executed.
- Assert effective resource attributes from collector data, including
  `service.name`, environment, and version. Source-level merge logic alone does
  not prove operator-provided values survive provider construction.
- For HTTP auto-instrumentation, assert the exact emitted request-duration
  metric and route dimensions. If stable semantic conventions were requested,
  require `http.server.request.duration`; an alternate metric in source or a unit
  fake does not satisfy that runtime row.
- Keep a Splunk Observability Studio contract process alive until trace, metric, and log queries
  complete; some local explorers evict telemetry for short-lived sources.
- Mark `Verified: unit+OTLP` only when assertions and collector or Splunk Observability Studio
  evidence both pass. If assertions pass but export is unavailable, use
  `Verified: unit`.
- Keep application startup independent of receiver discovery. It may consume
  persisted standard `OTEL_EXPORTER_OTLP_*` and supported AO SDK endpoint/auth
  settings, but it must not query `observer_status`, MCP, or Studio-specific
  discovery/route-registration APIs. Normal SDK authentication and resource
  calls to the configured cloud-compatible endpoint are allowed.

For selected Splunk Agent Observability work, verify four outcomes separately:

- the project is resolved or created through a supported product path;
- the dedicated Agent Stream is resolved or created;
- the selected application routing mode is configured and exercised; and
- a fresh application trace is observed in the intended project and stream.

For selected resource provisioning, inspect the configured `ao_target` and
exercise the application's actual provisioning step with credential-free API
fakes. Existing non-AO paths must work without importing or installing the AO
SDK: use its configured standard resource HTTP client and existing exporter.
Prove both-existing causes zero creates, both-missing and mixed resources are
resolved or created in the intended project, and a repeated run reuses the
same IDs. Exercise duplicate/conflict recovery by exact scoped relookup,
ambiguous and wrong-project resources, unresolved explicit IDs, and lookup or
creation permission/server failures. Failures must leave ordinary OTel active
and must not trigger alternate names or blind repeat creates. Lookup-only code
does not prove the missing-resource branch. Record reused/created resources
separately from attempted or blocked provisioning and fresh cloud receipt;
verify mode must not provision live resources merely to produce evidence.

For each selected resource, inventory lookup and creation as separate paths.
Exercise 401, 403, timeout, and 5xx failures for project lookup, Agent Stream
lookup, project creation, and Agent Stream creation wherever the actual
runtime supports that operation; an unsupported creation branch must be
reported as missing rather than tested through a replacement implementation.
Inspect call counts and sink initialization to prove failure isolation. Reconcile
the actual loaded profile and runtime-native selectors with standard
`SPLUNK_AO_PROJECT(_ID)` and `SPLUNK_AO_AGENT_STREAM(_ID)` settings, then test
non-default and conflicting values to establish which selectors the source
consumes and their precedence. Do not assume standard SDK variables control a
runtime that passes its own resource names explicitly. Prove explicit-ID
plumbing when supported, or state the source-backed name-only limitation;
passing an ID string to a name lookup does not prove ID support.

For a non-AO application, verify the actual launch consumes the resolved IDs
through the existing exporter's supported trace-header hook: current Studio
uses `projectid`/`logstreamid`, public standalone AO docs use
`projectid`/`agentstreamid`. Verify the exact target contract and authentication,
preserved endpoint/protocol/non-default port and harmless existing headers,
no AO header leakage to metrics/logs, no second provider/SDK creator, one AO
delivery per operation and unchanged unrelated sinks. Test resource failure
before binding headers and normal resource resolution through the same gateway
connection. A sample env file or fake lookup alone does not prove this path.
Local Studio visibility proves receiver delivery only. For Python SDK gateway
mode, verify its actual profile loader and env generator deliver populated
`SPLUNK_AO_API_URL`, `SPLUNK_AO_CONSOLE_URL`, and
`SPLUNK_AO_API_KEY=local-gateway` to the provisioning process through a
credential-free SDK boundary. Compare with the discovered API base, including
non-default ports; an unused sample, pass-through allowlist, or blank generated
assignment is `Not configured`. Keep verify read-only for application/env
files and report the missing fields instead of repairing them. Preserve
explicit direct-cloud mode and do not require this trio for an unselected or
direct-cloud AO path. For other languages, verify the runtime's actual supported
gateway endpoint, authentication, resource selectors and consumed profile;
absence of Python SDK variables alone is not `Not configured`. Keep source
configuration, runtime receipt and fresh cloud visibility separate. Separately
prove that Studio uses its active
connection/realm, supplies upstream auth,
preserves per-request resource bindings without cross-application leakage, and
handles unavailable or changed connections honestly. Application cloud
credentials are not a prerequisite for this mode. A missing Studio connection
or required resource permission may block live product proof without blocking
credential-free configuration, provider-reuse, lifecycle, content-safety, and
duplicate-span tests.

Apply the per-tool vendor content contract in
`../references/genai-readiness.md` per actual tool span ID. Arguments/results
alone or messages on its parent/model do not satisfy the tool's message fields.
For the GenAI path, check arguments against both `gen_ai.tool.call.arguments`
and schema-valid `gen_ai.input.messages`, and produced results against both
`gen_ai.tool.call.result` and `gen_ai.output.messages`. A supported
OpenInference `input.value`/`output.value` path is an explicit alternative,
not a reason to silently pass missing content. Compare the same sanitized
source values, correlation and configured limits; missing, malformed or
mismatched mappings are individual failures. For error/cancel/timeout without
a produced result, require error/lifecycle evidence and an exact absent-output
reason, never a fabricated successful output. A fixture-only pass remains
structural proof; SDK-created spans still need actual runtime capture.

For selected GenAI spans, reconcile current OTel docs/schemas and both vendor
integration guides before scoring. Inventory every operation and field with
official level, vendor requirement, skill acceptance, applicability, actual
source value, original/AO/exported value and proof. Check span kind/name,
provider/model, parameters, response/finish reasons, usage, streaming,
conversation/tool-call IDs, input/output messages, effective instructions/tool
definitions, actual arguments/results and retrieval content when applicable.
SDK-created spans are not automatic proof; empty placeholders, omitted
applicable content and wrong schema/value mappings fail required coverage.
For a compatibility exception, verify the actual public OTel function creator,
initial kind/request fields, active context, retained provider and configured
or selected export paths;
never count its processor as SDK span creation. After a repair, reconcile all
normal report sections with current creator/kind/output evidence. A stale SDK
label or repaired failure left in an older section is a report inconsistency.
Before finalizing, reconcile every requested case and source-known request
control with its report evidence. Inventory controls at their actual request
call sites, then compare each attribute's expected safe source value with the
captured value or absence. Record applicability, result and proof. Naming a
missing control without its known source value does not complete this
comparison; a similarly named tool-result field is not a request control.
Use supplied SDK source and probe facts to decide that captured package's
capability or failure concretely now for each function. Reconcile its ledger
decision with the report: SDK decorator/type, exact justified application-owned
decorator fallback, or preserved producer. Separate dispatch, captured fields,
lifecycle/protocol and normal versus custom sink support from unexecuted
application/wire proof. A conditional "when supported" or hypothetical future
compatibility does not decide a source/probe case with available facts.
For supplied native signal examples, compare each signal's endpoint/protocol/path
and available record values with its contract. Assess log body, severity,
resource, logger scope and trace/span ID presence separately from an actual
match to an owning span. Record supported fields and missing evidence even
when runtime delivery is unproven; a synthetic record is not receiver or cloud
receipt. Generic policy does not assess a supplied parameter, dependency
selection or signal record.
Include exact source URLs and provided
revision/date/hash receipts rather than only naming an input artifact.
Supplemental source or captured cases may use accurate Markdown, JSON or linked
equivalent evidence; preserve canonical JSON contracts separately and never
invent live findings for fixtures. State an omitted or unavailable check
explicitly instead of silently dropping the case or field.
An explicit restricted-content scenario can pass its safety assertion while
remaining partial for the full profile. Never fabricate successful output for
failed operations or duplicate system-role content in separate instructions.
Execute success plus stream-error/timeout/cancel cases at actual SDK/application
boundaries; auxiliary suggestions/title/subagent calls are operations too.
Prove one canonical producer, correct parent context and no unfinished spans.
Check existing SDK partial-rejection/export-health diagnostics and distinguish
receiver receipt, accepted batch, source/cloud inventory and product visibility.
No trace complete flag substitutes for per-field or per-source-span proof.
When verifying producer-selection scenarios, publish a separate row for each
runtime: current canonical creator/provider/exporter, intended preserved or
fresh SDK path, named supported API and matching official example/version
evidence or exact unavailable prerequisite. Do not leave a generic 'SDK or
another producer' statement. Publish real conversation/tool-call correlation
as per-field results too: a known missing call ID is a gap, an unavailable
session ID is unproven/N/A according to current applicability, and neither is
silently invented. Keep prospective configuration distinct from observed
app-code span creation and fixture-only structural evidence.

Run Splunk Observability Studio validation when the user requests it, but classify each finding
before using it as an application result:

- `actionable`: emitted telemetry violates the selected convention or expected
  contract; repair or report it.
- `registry mismatch`: the validator's core Weaver registry marks GenAI/MCP
  fields as moved to a dedicated registry, rejects application-owned custom
  metrics/attributes, or rejects framework-owned attributes such as
  `asgi.event.type`. Record this separately and do not call the application
  failed solely from the raw red/violation count.
- `library-owned compatibility`: official auto-instrumentation emits a shape
  the validator interprets differently, such as omitting `server.port` for a
  default HTTPS port. Record the package/version and affected signal; do not
  rewrite unrelated app telemetry merely to silence the finding.
- `stale`: telemetry arrived during validation because a periodic exporter was
  still running. Save the run id and evidence snapshot; freshness churn is not
  signal failure.

Report the raw validator summary, the classification, and the count of
actionable application findings. Never hide findings, and never equate a large
unclassified advisory count with verification status.

Emit a nested temporary harness when topology is necessary and the real path
cannot run. Topology is necessary when the audit or user scope includes
workflow/agent/tool/retrieval/memory traces, GenAI flow graph, LangGraph,
Temporal, queues/jobs, async handoff, MCP tool execution, streaming lifecycle,
parent/child shape, duplicate-span prevention, or an explorer DAG.

Nested topology harness rules:

- Derive expected edges from the inventories, for example
  `workflow -> agent -> llm.call`, `agent -> tool`, `tool -> mcp`, or
  `stream -> send_failed event`.
- Prefer real instrumented call sites. If imports are blocked, use a generated
  temporary SDK contract with the same nesting and label it
  `generated temporary nested SDK contract`.
- Keep child spans active inside the parent span context. Do not create all
  spans as siblings under a synthetic root unless topology is out of scope.
- For async or queue boundaries, use parent/child when context propagates
  synchronously or span links when the architecture expects links.
- Assert topology after export by querying parent span ids, links, span depth,
  or Splunk Observability Studio flow nodes/edges when available.

### 7. Author App-Code Tests When Requested

Enter this mode only when the user explicitly asks to add, repair, persist, or
write unit/integration tests. Follow
`references/app-code-test-authoring.md`.

Rules:

- Use the repo's existing test framework, fixtures, naming, and fake patterns.
- Add focused tests near the instrumented code's existing test area.
- Install OTel test providers before importing modules that cache tracers,
  meters, or loggers.
- Execute the real app function, route handler, middleware, workflow method,
  adapter, startup hook, job, or service runner with fake dependencies.
- Assert span names, parentage, required attributes, status/events, metric
  datapoints, log records, correlation, and redaction.
- Run the focused tests and include their paths and results in
  `.observe/otel-verify.md`.
- If dependency or fixture support is missing, report the smallest required
  seam instead of faking away the behavior in a misleading test.

