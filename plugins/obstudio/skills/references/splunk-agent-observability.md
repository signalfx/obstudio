# Splunk Agent Observability Findings

Use this reference for every source-owned agent runtime, or when the user asks whether a GenAI application can
populate Splunk Agent Observability, when an audit finds existing Agent
Observability routing or resource configuration, or when a selected finding
has `finding_group: splunk-agent-observability`.
Also use it when a fresh agent's selected default producer is Splunk AO, even
before the SDK is installed or configured.

## Agent Resource And Producer Decision

Project, dedicated Agent Stream and routing are default readiness requirements
for every agent. Read Galileo's native log stream as its stream binding; the
shared AO finding group describes configuration work, not a required SDK or a
destination migration. Respect explicit user exclusions and saved selections.
Use this matrix before authoring findings or changing a runtime:

| Source-owned agent runtime | Producer and destination | Resource and routing work |
|---|---|---|
| Fresh with compatible AO SDK | AO SDK creators/framework integration for supported operations; native OTel only for uncovered signals or a proven SDK limitation | Resolve/create project and stream with supported SDK clients; persist consumed configuration and use native SDK export. |
| Fresh without compatible or established AO SDK support | Native OTel with the full GenAI coverage profile | SDK-free resource resolution and supported trace-specific exporter headers; no invented SDK, runtime upgrade or sidecar. |
| Existing native OTel, including metrics/logs/export-only setups | Preserve producers, providers, exporters and ordinary signal destinations | SDK-free project/stream resolution and trace-header configuration on the selected existing exporter. |
| Existing Galileo, with or without native OTel | Preserve Galileo native instrumentation/export plus legitimate existing OTel sinks; fill only uncovered operations/signals | Supported Galileo project/log-stream clients and consumed vendor configuration; no automatic Splunk AO dependency or additional Studio route. |
| Existing AO SDK | Preserve SDK creators and export; fill version-specific gaps without duplicates | Reuse valid resource bindings, resolve/create missing ones and repair native SDK routing. |

Audit records each runtime's chosen row and evidence for project binding, stream
binding and routing. Covered bindings cite reachable source/configuration;
missing app-owned bindings get separate `default` configuration findings with
project -> stream -> route dependencies. Names, credentials and an explicit AO
request are not prerequisites for authoring that plan. Non-agent inference or
workflow code alone does not establish mandatory product adoption. Audit never
creates resources. Instrumentation implements only the validated selected scope.

## One Findings Ledger

Keep OpenTelemetry and Splunk Agent Observability work in the canonical
`findings` array. Do not add a top-level `splunk_agent_observability` object or
a peer report section. Author product-specific work with:

```json
{
  "id": "AO-001",
  "finding_group": "splunk-agent-observability",
  "expected_telemetry": [
    {
      "type": "configuration",
      "name": "agent-observability.project",
      "attributes": [],
      "product_view": "Agent Observability project routing"
    }
  ]
}
```

Omit `finding_group` for ordinary OpenTelemetry findings. The human audit
renders grouped AO cards under the existing `Findings` heading as the nested
`Splunk Agent Observability findings` subsection. It must never render a peer
top-level Agent Observability section.

## What Becomes An AO Finding

Create an AO finding only when repository, deployment, supplied product, or
validated API evidence establishes both a concrete gap and a safe action. Do
not turn the Agent Observability navigation into a generic checklist and do not
claim that spans create Agent Observability resources.

An agent runtime establishes intended project/stream support independently of
its producer. Inspect its actual launch profile and author separate source-backed
project binding, dedicated Agent Stream binding and routing findings where
missing, with `ao_target_scope: resource-routing` and `instrument_mode: default`.
Missing imports or credentials do not erase the intended-runtime assessment.
Disclose proposed service-derived names and offer optional supplied selectors
and reuse-only behavior. Do not infer global resource absence or create resources
during audit. Ordinary GenAI spans stay untagged in the same findings ledger.

Appropriate AO findings include source-backed work for an existing or intended:

- project and dedicated Agent Stream;
- application routing to those resources through the configured destination;
- dataset, prompt, annotation queue, annotation fields, or queue records;
- evaluator definition, provider integration, or Agent Stream attachment; and
- other supported product configuration required by a selected application.

Use `expected_telemetry.type: configuration` for Agent Observability resource or deployment
work. Keep application-owned OTel spans, metrics, logs, resources, and GenAI
semantic attributes as ordinary OpenTelemetry findings even when Splunk Agent
Observability consumes them. Never fabricate a span or metric to represent a
REST resource.

## Dependency Contract

Author prerequisites through the existing `dependencies` field. A selected
executable finding automatically includes executable prerequisites in
`approved_ids`; explicit intent remains in `requested_ids`. Put prerequisites
earlier in canonical order. Typical edges are:

- Agent Stream depends on project;
- stream routing depends on project, Agent Stream, and the required OTel
  exporter/GenAI trace finding;
- annotation fields depend on annotation queue;
- queue records depend on annotation queue and the source trace or dataset;
- evaluator attachment depends on evaluator definition and Agent Stream; and
- evaluator execution or Insights depends on the attachment and any required
  provider integration.

Do not duplicate dependency logic for AO findings. The shared selector owns
closure, stale-selection rejection, manual-decision unlocks, and external
blockers. A `manual decision` or `external follow-up` remains a blocker and is
never auto-selected.

## Project And Agent Stream Inputs

Audit resource existence separately from application binding. A missing live
binding does not prove that the cloud project or stream is absent. Keep the
project, Agent Stream, and routing findings distinct, and write each resource
finding's required fix as resolving an existing resource or creating it when
missing. Its acceptance criteria must exercise both outcomes; lookup-only
code with blank settings does not close a selected provisioning finding.

Mark Project, Agent Stream, and runtime-routing configuration findings with
`ao_target_scope: resource-routing` so the canonical selector can offer their
resource inputs. The marker is optional and valid only on AO configuration
findings. Unmarked legacy configuration names `agent-observability.project`,
`agent-observability.agent-stream`, `agent-observability.project-resource`,
`agent-observability.agent-stream-resource`, `agent-observability.runtime-routing`,
and `agent-observability.splunk-ao-routing` remain eligible. Keep the marker
absent for callback content-capture boundaries, datasets, prompts, and other
configuration whose selected work does not resolve Project/Agent Stream
identity. Neither an AO group nor a configuration type alone authorizes these
targets. Do not insert a marker into legacy normalized findings by default.

Offer optional Project name and Agent Stream name inputs in the audit's
selection controls for the selected resource-routing findings. Existing
configured names or IDs take precedence over
suggestions. When the application has no intended names, suggest the stable
service name as the project and `<service-name>-live` as its dedicated stream,
and label these as proposed names rather than existing resources. The user
can provide a different pair or select reuse-only behavior. Do not turn this
input into a manual-decision blocker or require a cloud secret in the report.

Persist supplied targets in the schema-v3 selection's optional `ao_target`:

```json
{
  "project_name": "assistant-v3",
  "agent_stream_name": "assistant-v3-local",
  "create_if_missing": true
}
```

Use `project_id` instead of `project_name`, or `agent_stream_id` instead of
`agent_stream_name`, to select an existing resource by ID. When resource selectors are supplied, each resource has
exactly one selector. A reuse-only policy may omit both selectors:
`{"create_if_missing": false}` uses the application's effective env/config
resource identity and forbids creation. `select --ao-reuse-only` and the audit
checkbox preserve that policy even with both optional fields blank; partial
resource overrides still require the complete pair. IDs are lookup-only: an unresolved ID never authorizes
creating a replacement. `create_if_missing: false` means reuse-only. The
target changes configuration, not selected scope, and participates in
`selection_sha256`; changing it invalidates older instrumentation evidence.
Keep schema-v1/v2 selections valid with their original normalized digests.
Use the shared `select` command's `--ao-project`, `--ao-project-id`,
`--ao-agent-stream`, `--ao-agent-stream-id`, and `--ao-reuse-only` flags to
materialize the target rather than hand-editing bound JSON. Resource inputs
never select otherwise unapproved AO findings.

## Idempotent Resource Provisioning

Selected AO resource work includes a runnable provisioning step, through the
installed supported SDK and the application's configured destination. A
one-time setup command is sufficient when its resolved bindings are persisted
and the real launch consumes them. Runtime `.get()` calls alone are sufficient
only after that provisioning step has resolved or created the selected
resources. Do not leave selected work as a placeholder profile asking the
operator to create resources that the supported API can create.

Resolve the exact project first, then the exact Agent Stream within that
project. Reuse a unique existing match without a create call. Reject ambiguous
matches and validate IDs and stream/project association before exporting. A
successful lookup that establishes absence permits one create for a selected,
named resource when `create_if_missing` is enabled. An authentication,
permission, timeout, or server failure during lookup is not absence and must
not trigger creation. Create a missing stream under an existing project, and
reuse a project successfully created by an earlier partial run.

Handle duplicate conflicts and uncertain create outcomes with a bounded exact
relookup of the same resource in the same project. Reuse only one validated
match; otherwise retain the failure. Never append random suffixes, choose an
unrelated resource, repeat a create blindly after a timeout, or delete a
successfully created project when stream creation fails. Inspect the installed
SDK's actual error contract; known authentication, permission, and server
errors remain failures rather than being classified as duplicate conflicts.
If the SDK discards status information, a read-only relookup may establish
the uncertain outcome, but an unresolved lookup must retain the original
failure and must not cause a second create.

For Python AO SDK or native OTel paths without Galileo,
`otel-instrument/scripts/resolve_ao_resources.py` provides this
provisioning path using the existing SDK, or the explicit SDK-free
`--studio-api-origin` HTTP mode for an existing non-AO application. Run it with
the project-managed Python environment after validating selected resource
scope; an SDK-free application must not gain a vendor dependency for this step. Use the paired helper only when both resource findings are selected;
for project-only scope, perform only the selected project operation through
the supported resource API, using the SDK-free HTTP client for a non-AO
application or its existing SDK client for an SDK-owned path. Never create an unselected stream as a side effect. Its JSON evidence
records reused, created, or recovered resources and
real IDs; it is evidence of resource resolution, not an additional selection
ledger or proof of cloud trace receipt. An application-native equivalent must
prove the same behavior. Add credential-free tests for both existing, both
missing, mixed existing/missing, repeated runs, project and stream creation
races, ambiguous/wrong-parent resources, and isolated lookup/create failures.

When live provisioning cannot run, record the attempted operation, selected
target, exact SDK/API failure or unavailable prerequisite, and remaining
resource work. Still implement and exercise the creation branch with fakes.
Do not report a lookup-only implementation as completed merely because the
gateway was previously unavailable; retry the configured API when that
prerequisite recovers. Keep ordinary OTel active if AO resolution fails.

## Configured Runtime Destination

Galileo native resource/export configuration follows **Existing Galileo
Applications** below; do not apply these AO gateway/cloud profiles to that
destination. An explicitly selected additional AO destination has its own
profile and must preserve Galileo.

For local development, default to an available Splunk Observability Studio
cloud-compatible gateway. Preserve an explicit operator destination or a user
request for direct cloud export. Studio is optional for source work and
credential-free tests. These are alternative routing modes, not two
mandatory exporters. Do not require application cloud credentials for the
gateway mode: Studio derives upstream API and ingest endpoints from its active
cloud connection and realm and supplies its own credentials server-side.

Resolve missing AO destination settings independently from ordinary OTel
settings. An existing `OTEL_EXPORTER_OTLP_ENDPOINT` does not select the AO
resource API or change an explicit AO destination. When AO has no explicit
destination, configure the available local Studio gateway through the
existing exporter's supported trace headers for a non-AO runtime, or the
installed SDK's supported endpoint mode for an SDK-owned runtime. Discover its API address during
instrumentation from advertised endpoints or checked-in topology; keep an
explicit ordinary OTLP destination intact. If the gateway is unavailable,
record the unresolved prerequisite without silently enabling direct cloud.

The current gateway's SDK resource API and routed trace ingest accept only
native loopback requests from the same network namespace as Studio. Its
`local-gateway` marker is public and is not a network authentication secret.
Do not recommend a Docker/Compose/Kubernetes bridge or service address for AO
gateway calls, even if that address is valid for ordinary OTLP. If the
application cannot reach Studio through same-namespace loopback, record that
exact compatibility blocker and preserve an explicit operator destination;
do not weaken the gateway trust boundary or silently switch to direct cloud.
Keep the application destination-agnostic. Use supported AO SDK resource calls
and standard OTLP export with durable endpoint configuration. Do not add an
Obstudio library, special route-registration call, startup endpoint discovery,
or hardcoded port to application code. Normal SDK project/stream calls to a
configured cloud-compatible endpoint are allowed; they are not discovery calls.
If the installed SDK cannot target that endpoint through supported
configuration, record the exact compatibility gap instead of patching a vendor
package or silently switching to direct cloud export.

Resolve or create the real project and dedicated Agent Stream through the
configured supported API. Carry their routing IDs on each trace export using
the supported exporter contract. Never replace per-application routing with a
global Studio destination binding, fabricate resource IDs, or assume that
ordinary OTLP forwarding automatically chooses an Agent Stream. Metrics follow
their configured OTLP path; local application logs remain local.

Verification must distinguish:

- the real project and Agent Stream resolved or created;
- the configured application route exercised, including local gateway receipt
  and upstream forwarding when that mode is selected; and
- a fresh application trace observed in the intended cloud project and stream.

A local receipt, resource API response, or upstream ingest acknowledgement is
not proof of cloud Agent Observability visibility. Verify the exact fresh trace
in the target product. Only when gateway mode is selected does its availability
affect live resource calls and export; it must not gate application startup,
ordinary instrumentation, or credential-free verification. In particular, do not claim delivery continues while the gateway is stopped. On a cloud connection change, upstream addresses and credentials must follow
that connection and old organization resource bindings must not be silently
reused. Re-resolve named resources or report the stale binding.

### Python SDK Gateway Configuration

Inspect the chosen SDK's deployment/configuration source: when O11y mode derives
cloud hosts from `SPLUNK_AO_REALM`, `SPLUNK_AO_API_URL` is not an O11y override
for that mode. Verify the supported configurable endpoint mode using `SPLUNK_AO_API_URL`,
`SPLUNK_AO_CONSOLE_URL`, and `SPLUNK_AO_API_KEY`. A compatible local Studio
gateway implements that standard SDK API/authentication contract and
`<api-base>/otel/v1/traces`, while delegating resource calls to cloud `/ao/api`
and ingest to the realm-derived trace endpoint. Studio's SDK-compatible gateway
accepts the public `local-gateway` marker. The SDK reads it as an ordinary API
key value; Studio recognizes the marker and supplies cloud authentication.
Prove compatibility with the installed SDK before using this configuration,
and record its version and effective endpoints.

Discover the API address separately from the OTLP address during configuration
using advertised service endpoints or checked-in runtime topology. For this
gateway, use only a loopback API and routed-trace address reachable from the
application's same network namespace; a container bridge address is not a
supported substitute. Preserve non-default ports. If no reachable API origin
can be discovered, leave the AO route unconfigured and report that exact
blocker; neither the conventional REST port nor the ordinary OTLP receiver
address is a substitute for discovery. Do not publish unsupported example
environment variables, hardcode a Studio port fallback in application code,
or make application startup call a Studio-specific API. A missing/disconnected
gateway or insufficient Studio-held resource permission is an explicit
prerequisite, not a reason to request a cloud token for the application.

### Configuration Profiles

For existing native OTel applications without Galileo, use the repository's normal profile/loader
to supply the resource setup command's explicit discovered API origin and
selectors, then persist the resolved IDs in the existing exporter's supported
trace-specific header configuration. Preserve the compatible endpoint,
protocol, harmless existing headers and all unrelated signal/exporter settings.
Exercise that actual loader and exporter constructor; do not add SDK variables,
an SDK import or a new config loader to an SDK-free application. Keep resource
resolution failure separate from the existing telemetry pipeline.

The following SDK configuration applies only when an SDK-owned path is
selected; it is not required by the header-only non-AO path above.
For selected AO configuration work, provide a Studio-only example profile:
`.env.studio.example` for a dotenv application, or the equivalent named
deployment/launch profile for the repository's configuration system. Put the
supported local AO API, console, and authentication settings together in that
profile. Verify the chosen SDK's support for `SPLUNK_AO_API_URL`,
`SPLUNK_AO_CONSOLE_URL`, and `SPLUNK_AO_API_KEY=local-gateway`. Render both URLs
from the discovered same-namespace loopback API origin, including its actual
port. The SDK appends its own resource and `/otel/v1/traces` paths; do not use
the ordinary OTLP receiver origin as the AO API origin. Include ordinary OTLP
settings only for the selected OTel work and preserve its explicit destination.
Include project/stream names through configuration that the application
actually consumes; do not invent SDK environment variables. A supplied
topology or example is configuration evidence, not delivery proof.
When AO settings are absent at instrumentation time, make this discovered
Studio profile the selected local launch configuration through the
repository's existing launch mechanism. Merely writing `.env.studio.example`
does not activate it. If discovery is blocked, keep ordinary OTel working and
report AO as blocked rather than manufacturing a source-level port default.

The Studio profile contains no active `SPLUNK_AO_REALM`,
`SPLUNK_AO_O11Y_TOKEN`, or other cloud credential. In this profile, do not mix these variables
with local gateway configuration. If a direct-cloud example is
requested or already maintained, keep it in a separate `.env.cloud.example`
or equivalent profile using the installed SDK's supported cloud mode; do not
mix the two modes in one file or activate both exporters. Document one-profile
loading and removal of inherited variables from the other AO mode: loading a
Studio dotenv file does not unset a realm/token already present in the parent
environment. Preserve an explicit active AO destination; the Studio example
does not authorize replacing it. Do not commit live credentials.

When Studio gateway mode is selected, populate the actual application or
deployment env profile before provisioning, not only the example. The
configured profile must supply `SPLUNK_AO_API_URL`,
`SPLUNK_AO_CONSOLE_URL`, and `SPLUNK_AO_API_KEY=local-gateway` from the
discovered same-namespace API base with its actual port. Exercise the real
profile loader and any env generator with a credential-free SDK boundary.
Prove the launched provisioning command receives all three populated values;
an allowlist or blank generated assignment is insufficient. Missing application
cloud credentials alone are not a provisioning blocker in this mode.

Resolve or create the configured project and dedicated Agent Stream through
normal SDK resource calls before the first AO trace export. Carry the resolved
IDs in each export. Resource failure must leave AO export unconfigured or
failed with the exact cause; it must not export with fabricated IDs, reuse an
unrelated stream, or change modes. Keep the application's existing non-AO
behavior according to its error-handling policy. Verify profile isolation,
resource-before-export ordering, and the failure path with credential-free
tests, then report live resource and delivery evidence separately.

## Splunk AO Python Compatibility

Use this contract when Python dependencies or source contain `splunk_ao`.
Determine behavior from the installed version and its source or API docs. The
patterns below were reconciled against the official
[`splunk/splunk-ao-python`](https://github.com/splunk/splunk-ao-python)
repository examples at the latest `main` revision resolved at task time;
record that revision, the installed package version, and current source
provenance when making a version-sensitive change.

Search imports, decorators, constructors, callbacks, provider setup, and
teardown for at least:

- `from splunk_ao import log`, `@log`, `span_type="tool"`, and
  `span_type="retriever"`;
- `SplunkAOLogger`, `splunk_ao_context`, `logger.conclude()`,
  `logger.flush()`, and `logger.terminate()`;
- supported provider/framework wrappers and handlers such as
  `splunk_ao.openai`, `SplunkAOCallback`, CrewAI, OpenAI Agents, Google ADK,
  A2A, middleware, and their configuration options;
- `add_splunk_ao_span_processor`, `configure_distributed_tracing`, and
  `instrument_distributed_tracing`; and
- direct OpenTelemetry `TracerProvider`, `set_tracer_provider`, processors,
  exporters, auto-instrumentation, and `provider.shutdown()` calls.

Describe what each detected API actually provides rather than treating the
package name as proof of complete coverage:

| Capability | Representative API | Result |
|---|---|---|
| span creation | `@log`, `SplunkAOLogger`, supported model wrappers and framework handlers | Creates workflow, model, tool, retrieval, or other application spans through the SDK export path. A top-level `@log` call starts the trace and nested decorated calls become children. These spans can inherit an active OTel parent without being emitted by the application's OTel provider. |
| export-only | `add_splunk_ao_span_processor(caller_provider)` | Adds Splunk AO export to the supplied provider. It does not discover or create missing application operations. |
| transport-only | `instrument_distributed_tracing(tracer_provider=...)` | Instruments supported HTTP server/client transports on the supplied or current provider. It does not add Splunk AO export. |
| combined setup | `configure_distributed_tracing(tracer_provider=..., app=...)` | Uses the supplied provider or returns a new provider, attaches export, and instruments selected transports. It does not replace the process-global provider. |
| resource management | project, Agent Stream, dataset, prompt, evaluator, annotation, or experiment clients | Creates or configures product resources; it is not evidence of application spans. |

Write the classification and its negative coverage consequence explicitly in
the audit evidence or relevant finding. Do not leave the reader or a
downstream skill to infer `export-only` from a flow arrow. For example, a
detected `add_splunk_ao_span_processor` path must say that it only exports
spans from the supplied provider and does not create missing workflow, model, tool, or
retrieval operations.

Do not describe `@log` as discovery-based automatic instrumentation. It
instruments the decorated function. Provider/framework wrappers instrument the
operations covered by that integration. An exporter or span
processor is never evidence that those operations exist.

### No Existing OpenTelemetry Provider

When a repository already uses `@log`, `SplunkAOLogger`, or a supported
framework wrapper, preserve valid SDK-created spans for the logical operations
they cover. Do not scaffold duplicate app-owned OTel
spans around those operations. Audit HTTP, runtime, metrics, logs, sessions,
streaming lifecycle, and uncovered GenAI operations independently; SDK-created
workflow or tool spans do not prove those other signals.

Default to **Fresh Agent SDK Instrumentation** only when the live runtime has
no existing telemetry instrumentation and its language has a compatible
supported Splunk AO SDK. Apply the native OTel language fallback below when no
such SDK is available. Existing generic OTel spans, a real
metrics or logs pipeline, an active export-only provider, Galileo or another
framework producer select incremental OTel gap filling. Preserve their
producers, providers and exporters, enrich supported hooks, and add only
source-proven uncovered operations; missing GenAI spans do not authorize SDK
adoption. Evaluation-only imports and unused packages do not establish live
instrumentation. Apply the shared GenAI Instrumentation Selection decision
before using any SDK creator below.

If a high-level helper creates a provider, retain the returned provider in
application startup state, pass it to supported instrumentation that
must join the trace, and call `provider.shutdown()` at process teardown. If a
`SplunkAOLogger` or SDK context manages the sink instead, prove its supported
`logger.terminate()` or process teardown path. A flush drains completed work;
it does not conclude unfinished operations or replace shutdown.

### Fresh Agent SDK Instrumentation

For a fresh agent whose language has a compatible supported Splunk AO SDK,
use its supported span-creation APIs, rather than only adding
`add_splunk_ao_span_processor`. Before choosing
an integration, inspect the current
[official SDK examples](https://github.com/splunk/splunk-ao-python/tree/main/examples)
and the matching installed API/source. Record the example path, revision/date,
SDK version and supported invocation pattern in the audit/implementation proof.
Do not copy a provider model, credential, project, stream, or deprecated
framework API from an example into the application.

Use the latest Python examples on the official SDK's `main` branch:

- [Function decorators](https://github.com/splunk/splunk-ao-python/blob/main/examples/logging-samples/banking-agent-sample/sample_app.py): `@log(span_type="agent")` and `@log(span_type="tool")` on actual function boundaries, with `splunk_ao_context` for destination/session scope.
- [Ollama chat](https://github.com/splunk/splunk-ao-python/blob/main/examples/chatbot/sample-project-chatbot/openai-ollama/app.py): a decorated chat function with the supported provider wrapper. Use it only when that client protocol matches the app; do not replace a native Ollama request merely to copy the example.
- [LangChain callback](https://github.com/splunk/splunk-ao-python/blob/main/examples/agent/langchain-agent/main.py): `SplunkAOCallback` and `splunk_ao_context` for callback-based model/chain/tool operation capture.
- [LangChain middleware](https://github.com/splunk/splunk-ao-python/blob/main/examples/agent/langchain-middleware/main.py): `SplunkAOMiddleware` on the supported `create_agent` middleware boundary. Choose callback OR middleware ownership for overlapping operations and confirm DeepAgents/framework/version compatibility before applying it.
- [Logger operations](https://github.com/splunk/splunk-ao-python/blob/main/examples/logging-samples/splunk-ao-logger/basic-example.py): actual input/output and available model/usage passed to `SplunkAOLogger`, with a trace concluded at the actual terminal boundary. Use supported logger/schema/decorator APIs when no matching framework integration exists.
- [Distributed tracing](https://github.com/splunk/splunk-ao-python/tree/main/examples/logging-samples/distributed-tracing): context propagation across services; complement GenAI creation with supported OTel transport instrumentation while preserving one producer per operation.

Resolve `main` at task time and record its revision/date in the report, then
check the relevant example and SDK source against the installed or proposed
package version. Do not treat a previously recorded commit as the latest
example. If current examples cannot be retrieved, report that prerequisite
and the snapshot actually used; do not claim a fresh check.

For a custom Python agent without a matching framework integration, choose the
supported decorator pattern first through the mandatory per-function producer
decision gate below. Complete that gate before selecting schema constructors
or a lower-level creator. The following lower-level method mapping is a fallback
capability checklist, not a pinned release recipe.
Current official examples and the chosen compatible package's inspected APIs
govern implementation. Record any decorator limitation that requires a fallback
and keep installed/runtime support unproven until checked.

| Actual operation boundary | Named SDK creator/lifecycle API | Source data and ownership |
|---|---|---|
| SDK trace envelope | `SplunkAOLogger.start_trace(...)` then `conclude(...)` | Vendor trace/session grouping; inspect whether the selected SDK emits an operation node. An envelope alone proves no actual workflow boundary. |
| Actual coordinated workflow | `SplunkAOLogger.add_workflow_span(...)` | Log one real workflow with actual input, terminal output, timestamps and children inside the trace envelope. Apply current OTel workflow applicability; never invent a workflow for a standalone agent. |
| Agent invocation | `SplunkAOLogger.add_agent_span(...)` | Actual agent identity, input/output and parent/children from the real invocation. |
| Model request | `SplunkAOLogger.add_llm_span(...)` | Actual request messages/model/parameters and observed response/usage; preserve CLIENT kind and real errors/partial outcomes. |
| Tool execution | `SplunkAOLogger.add_tool_span(...)` | Actual name/arguments/result/call ID and parent; no successful result on failure. |
| AI-context retrieval | `SplunkAOLogger.add_retriever_span(...)` | Actual query and available returned document/context data from a real retriever; ordinary database/auth lookup is not automatically retrieval. |
| Owned logger shutdown | `SplunkAOLogger.flush()` and `terminate()` | Conclude real operations first, then drain/close the owned sink. |

Use the latest
[`basic-example.py`](https://github.com/splunk/splunk-ao-python/blob/main/examples/logging-samples/splunk-ao-logger/basic-example.py)
and inspect the latest logger/schema source for methods that example does not exercise:
[`src/splunk_ao/logger/logger.py`](https://github.com/splunk/splunk-ao-python/blob/main/src/splunk_ao/logger/logger.py).
Record the resolved revision and matching package support in each producer
receipt. Inspect whether the selected logger omits its trace container from
emission; `add_workflow_span` supplies an actual workflow when applicable.
Starting the envelope plus logging one workflow is not a duplicate workflow.
These named creators are different from export-only `add_splunk_ao_span_processor`. A version may
need a supported application OTel processor/exporter hook to enrich the same
SDK-created span IDs from actual source metadata; such a hook creates no
operations and cannot repair data never captured. Preserve business return
values, exceptions and external call arguments/order exactly; keep telemetry
carriers out of business outputs. `Projects`/`AgentStreams` APIs configure
resources and do not create GenAI operation spans.

### Decorator Selection

For supported function scenarios, use the decorator pattern when adding or
repairing hooks. Prefer SDK `@log` at the uncovered operation boundary after
checking current [decorator documentation](https://agent-observability-docs.splunk.com/sdk-api/logging/log-decorator/log-decorator),
chosen package source and public configuration. This producer-choice gate applies
only to a genuinely uninstrumented runtime or a proven uncovered operation in
an existing AO-owned path. Preserve every existing producer, including one with
incomplete semantics; enrich its supported hooks. An unsupported field or kind
stays Partial with a precise manual decision instead of authorizing replacement.

**Mandatory per-function producer decision gate.** Before edits for fresh or
uncovered Python GenAI operations, record a decision for every actual source
function in the existing producer receipts and finding/result evidence. Apply
the SDK choice below when Splunk AO is selected or is the fresh default;
preserve explicit alternative producer choices under GenAI Instrumentation
Selection.

1. Name its source file, qualified function, actual operation/`span_type`, and
   sync, coroutine or generator shape. Identify any valid pre-existing
   producer and preserve that ownership without another operation node.
2. Assess native SDK `@log` for that function using the chosen compatible
   package's public source and available isolated probe evidence: input/result
   capture and source-side privacy bounds, required fields, used iteration
   protocol, partial output, early close/cancellation, creation-time kind and
   attributes, and actual sink/registration/lifecycle support. Dispatch support
   alone does not prove these contracts. Carry each observed source or wire
   probe failure into the affected function's decision before proposing future
   checks. Check response usage/finish conversion and the active span during
   the business call, which determines nested transport/retrieval parentage;
   completed leaf parentage alone does not prove leaf activation. An
   async-generator agent is supported
   in principle; check its actual bounds and close/cancel behavior rather than
   rejecting it by shape.
3. Choose native SDK `@log` when those applicable contracts are supported.
   Otherwise state the exact incompatible field, privacy, protocol,
   creation-time or sink fact and choose a named application-owned **function
   decorator** invoking a documented supported creator once at that same
   boundary. Preserve the business invocation/iteration protocol and required
   mappings; a schema constructor or inline manual scope is not this decision.
   Record the concrete decorator symbol and its attachment or invocation
   wrapper separately from the creator it calls. A generic promise to add an
   application-owned decorator does not identify the chosen function pattern.

If both the applicable native integration and documented SDK creator fail a
required contract, use the narrow public OTel compatibility exception below
instead of knowingly emitting invalid semantics from the same helper. A
source-only plan can select that supported pattern while leaving its runtime
proof unexecuted. Do not confuse a missing probe with a proven SDK limitation.

For either pattern, define assertions comparing the final sanitized content to
the actual source arguments, produced results and partial output on that same
native operation and its wire record. Attribute presence or sentinel absence
alone does not prove useful, equal input/output or distinguish null from no
produced result.

Use one capability table per function in existing report evidence, with rows
for argument/result conversion, privacy/bounds, model usage/finish mapping,
active business-call context, iteration/close/cancel, kind/initial attributes,
and sink/lifecycle. Mark each row Supported, Limited, Not proven or N/A and
cite its source/probe fact; generic future tests do not replace observed facts.
Keep observed native/helper behavior separate from the proposed producer's
acceptance. Compare actual captured input/result shapes and conversions with
the consumed source values, including input binding, flattening and empty
metadata. A bound-arguments object serialized as query text differs from the
query string consumed by retrieval. Proposing a better mapping does not make
the existing wire behavior unknown; faithful decoded shape and field provenance
are sufficient without duplicating every serialized literal.
Decode serialized probe payloads and normalize captured/emitted span IDs
(hex, UUID or protobuf base64) before comparing the current business-call
span to that operation and its parent. If the captured current span is the
parent instead of the leaf, record that limitation explicitly; completed
child parentage cannot establish active leaf context. For supplied model
responses, name known usage/finish fields that the native mapping omits.

Manual public scopes are for a source-proven non-function or external lifetime,
not a substitute for decorating a fresh function boundary. `@contextmanager`
on a scope factory, stdlib logging and an export-only processor are not SDK
`@log` or evidence that the business function is decorated. Judge the actual
invocation wrapper and ownership, not a literal annotation search. Keep a
proven pre-existing producer instead of adding a duplicate decorator.

Audit records this same decision as a proposed pattern and concrete probe
acceptance in existing `required_fix`/evidence/acceptance fields; it inspects
available source/receipts but does not install packages, run probes or contact
cloud. Missing capability evidence remains proposed/Not proven. Instrumentation
planning may mark a function Not configured/Partial when a checked documented
public creator candidate has an exact unresolved contract. Name the proposed
decorator attachment, blocked capability and required proof; this completes
the source assessment without authorizing edits or claiming creator support.
For implementation, instrumentation
must resolve the applicable decision before changing that function. Verification
fails a missing decision or newly added manual function scope without a proven
exception, even when emitted attributes are correct; unavailable source or
runtime proof keeps the affected acceptance Partial rather than implying
native or fallback compliance.

| Actual function scenario | Preferred pattern and required checks |
|---|---|
| Safe bounded sync/async function or bound method | SDK `@log` with the actual agent, tool, retrieval, model or workflow type; verify complete input binding including used variadic arguments, return/exception preservation and supported parameter mappings. Inspect classmethod/staticmethod decorator order and exclusion of `self`/`cls`. |
| Serial nested agent/workflow/tool/retrieval functions | Decorate each distinct uncovered source operation once. Verify actual parentage, context cleanup, resource route and one emitted node per boundary. Do not add a workflow only because the SDK creates a trace envelope. |
| Finite sync/async generator consumed through ordinary iteration | SDK `@log` when its aggregation, size bounds, termination and partial/error/cancel behavior meet the application's contract. Async generation is supported in principle, not a blanket fallback reason. |
| Provider/framework integration already creates the operation | Preserve that creator. Decorate only uncovered surrounding functions, never another model/tool span around the same captured operation. |
| SDK decorator cannot preserve a required capture, generator protocol, lifecycle, sampling or sink contract | Use an application-owned function decorator around the documented supported creator at the same boundary, with an exact reason and focused proof. Non-function/external lifetimes may use a manual public scope. |

Do not infer full decorator support solely from dispatching to an async/generator
wrapper. Inspect `send`/`throw`/`asend`/`athrow` if used, retained item counts,
early close, cancellation and genuine partial output. Inspect source-side input
binding, used variadic arguments, framework dispatch/introspection after
decoration, and result serialization: a documented `params["input"]` mapping or
redacted companion does not prove raw originals were excluded. Prove the chosen
public mechanism with synthetic raw-content sentinels before using it. Prefer
already safe bounded function data or a behavior-preserving telemetry boundary;
never sanitize business arguments/results in place merely to satisfy capture.

SDK `@log` may use a SDK-owned completed-record sink rather than the application's
global OTel provider. Verify its actual public destination/configuration and
same-operation fields; an adapter on an unrelated global provider cannot enrich
those records. Inspect native schema fields and any public ingestion hook
separately from an OTel exporter hook. A trace/schema ingestion hook is not proof
of a returned writable OTel span or a public exporter-registration seam. Normal
compatible SDK configuration may route that sink to Studio's SDK endpoint;
do not invent private sink injection or require a Studio-specific app adapter.
SDK operation records remain distinct from ordinary OTLP application logs.

When a precise SDK decorator limitation requires the public helper below, retain
the function decorator pattern around that helper. Name it as application-owned
and distinguish it from SDK `@log`; create one SDK operation, preserve business
values/errors/stream behavior and prove source-side redaction plus the actual
sink. A supported fallback is independent of gateway availability for source
instrumentation and local tests. Never declare a decorator path fully compliant
without emitted field, lifecycle and sink evidence.

### Public Schema Span Helpers

Before treating a logger's missing sink hook as an operation-wide blocker,
inspect the documented
[`start_splunk_ao_span`](https://agent-observability-docs.splunk.com/sdk-api/third-party-integrations/opentelemetry-and-openinference/start-splunk-ao-span)
alternative and its chosen-version source in `src/splunk_ao/otel.py`. This is
SDK span creation, unlike `add_splunk_ao_span_processor`. The public helper
accepts a schema record and yields the current writable OTel `Span`; it needs
no private logger sink injection. Record the exact schema/import, installed
version and provider/export registration used by the real application.

For supported `AgentSpan`, `LlmSpan`, `ToolSpan` and `RetrieverSpan` operations,
sanitize source values before constructing the schema record, then fill missing
attributes on that yielded span through `Span.set_attribute`/`set_attributes`.
Keep one SDK-created operation, its actual context, errors and business outcome.
Inspect when the chosen helper writes SDK-derived attributes, including context
exit; check the final emitted span for overwrites rather than assuming earlier
setters survive. Bind the helper to the actual registered provider, configure
the supported AO processor/exporter where selected, and prove owned flush and
shutdown. An unrelated provider or unregistered local provider proves no export.

Inspect creation-time capability too. If the chosen helper opens a name-only
span before yielding or writing schema-derived attributes, the sampler and
`on_start` do not receive those later fields. Inspect its public signature for
initial kind/attributes support instead of assuming either support or absence.
Same-span setters or a completed `ReadableSpan` view cannot repair earlier
inputs. Separate completed wire compatibility from recommended creation-time
support; disclose observed limits and keep affected attribute-based sampling
acceptance Partial. Do not patch SDK internals, invent arguments or add a
duplicate span.

Check support independently for each operation with the resolved compatible
SDK, schema and OTel packages. Probe same-span tool messages, truthful successful
null `output.value`, no-result errors and parent context. If an `LlmSpan` emits
`INTERNAL`, that does not close a separate-process model's `CLIENT` requirement.
Never invent a kind parameter, mutate SDK internals or claim full coverage from
the helper name. First assess the compatibility exception below; keep exact
unsupported fields/kinds Partial when no supported repair is available, and
do not make independently supported agent/tool/retrieval work depend on a
logger-only sink prerequisite. Source/probe capability remains distinct from
application integration, schema-valid wire export, resource binding and cloud
receipt. Existing valid producers are preserved rather than migrated to this
alternative.

### Per-Operation Public OTel Compatibility Exception

This exception selects a creator for a new, uncovered operation; it does not
replace an existing creator that emits incomplete semantics. Preserve that
creator and report the exact unsupported requirement and manual prerequisite
when supported same-span enrichment cannot repair it. Keep Splunk AO creation
as the default for a genuinely uninstrumented runtime where it meets the
selected contract. When current source/probes show that the applicable SDK integration and public
helper cannot meet a required kind, creation-time field, truthful content or
lifecycle contract, a named application-owned function decorator may create
that one operation through the documented public OTel API. Record the exact
failed SDK capability and chosen OTel signature. Reuse the existing registered
provider and configured export paths, preserving any existing or selected AO
processor/exporter. Retain SDK creators on supported boundaries and emit one
operation per real call. Label the creator as application OTel and report its
actual export path separately; an AO processor is not its creator. Do not
replace an existing OTel/Galileo/framework/AO producer or use an absent
gateway as a reason for this exception.

For a remote model, supply CLIENT and safe known request attributes when
creating the span, then keep it current around the actual provider call so
transport spans are its children. Prove the initial kind/fields with a sampler
or `on_start` observation as well as final serialized OTLP. A completed-span
adapter, late setter or private SDK mutation cannot repair creation-time kind.

Check the selected carrier/finalizer before implementation. A nonnullable
output field with an empty-message default cannot represent an unproduced
response merely by leaving the default untouched. Emit output only after a
real valid response or partial result exists; preserve true successful null
separately. Map model tool requests to typed `tool_call` parts and tool replies
to `tool_call_response` parts, retaining available IDs, names and sanitized
arguments/results. JSON text containing the provider's tool-call object is not
that structured mapping. Validate actual input/output attributes against the
current official message schemas and compare their useful content with source
values on the same span. Also validate every known part against its concrete
type definition: a permissive union or valid JSON alone can accept malformed
typed parts. Use the checked schema's actual fields (for example, a tool-call
response carries `response`, not a text part's `content`). Prove that an
available tool-call ID joins the model request, executing tool and response in
the next model input; do not drop or independently rewrite that identity.
Record schema provenance and per-payload/type validation results in evidence.
Source-only plans specify those validators and call-ID join assertions as
future acceptance, with their execution marked Not run.
Validate the provider response at the actual call boundary before recording
response content, usage or successful completion; a parser failure after the
decorator returns must not leave a successful inference span. Re-raise provider
failures and preserve business values; do not fabricate output to satisfy a
vendor requirement.

After a producer repair, regenerate the normal instrumentation JSON, Markdown,
HTML and bound verification artifacts from current source/proof. Reconcile the
operation's creator, kind, field ownership, counts and remaining gaps throughout
the reports. Appending a correction while earlier sections still claim SDK
creation, a repaired failure or missing kind leaves the report inconsistent.
Keep cloud receipt and live resource/lifecycle proof separate from local and
credential-free compatibility tests.
Source-only repair plans must carry this closure into future acceptance: apply
the authorized instrumentation, verify it, and if selected checks fail, route
repairs through instrumentation and rerun focused verification until Pass or an
exact blocker. Rebuild the normal reports from that producer and evidence.
Audit and verification remain read-only for application code; planning this
conditional loop neither executes it nor requires an initial failed run.

### Same SDK Span Content Enrichment

An actionable fresh-agent plan must name the SDK content carrier, the exact
application enrichment API and the selected sink/exporter registration path.
“Use a supported hook” is an unresolved prerequisite, not a complete repair.
Prefer supported native fields or a yielded writable OTel span when the chosen
integration provides them. For logger versions that expose only completed SDK
records, use an application exporter adapter without creating another span.

The following compatibility illustration requires chosen-package checks for
the carrier and public exporter interfaces. A test that uses an internal `_sink`
injection seam establishes isolated test behavior, not documented production
registration. Resolve the latest compatible releases and inspect their supported
application configuration boundary; do not assume that an old test proves the
currently selected SDK emits these fields or supports that sink route:

1. At the actual tool boundary, bind arguments and observe the return value or
   exception. Redact and bound the values before any SDK call. Track
   `produced_result` separately from the value, including successful null.
   Build current typed tool input/output messages from those same safe values;
   include only a real supplied call ID. Validate the dedicated arguments/result
   schemas as well as the message and concrete-part schemas. If the actual
   scalar/null cannot satisfy an object-only result schema, use a verified
   supported OpenInference alternative or keep that field gap explicit.
2. Use `SplunkAOLogger.add_tool_span(input=..., output=..., metadata=..., ...)`
   once for that real operation. Pass JSON of the safe arguments/result to
   native `input`/`output`, not raw originals with redacted companion fields.
   The supported `metadata` argument carries a JSON string containing the
   validated semantic attribute map, for example
   `{"application.genai.required": json.dumps(safe_attributes)}`. Bound this
   carrier too. In the checked version it reaches `splunk_ao.metadata` on the
   SDK-created OTel record; inspect the chosen serializer rather than assuming
   this key or adding a fictitious returned-span setter.
3. Implement the public OTel `SpanExporter.export(spans)` interface around the
   actual selected SDK sink's exporter. Parse only the verified safe carrier,
   validate it, remove only explicitly identified invalid owned content fields,
   and merge its attributes into a `ReadableSpan` view retaining
   the original context, parent, timestamps, resource, scope, kind, status,
   events, links and dropped counts. Forward each original operation once to the delegate;
   create no tracer/span IDs or sibling wrapper. The adapter cannot recover
   values that were never safely captured.
4. Register that adapter through a version-checked, application-owned SDK
   sink/exporter configuration boundary. Name the exact callable/signature in
   the report. A processor on an unrelated global provider does not enrich
   logger records exported by a separate sink. Do not patch SDK internals or
   assume an uninspected sink injection parameter is supported. If the chosen
   version offers no supported registration path, name that precise blocker
   and keep fresh content coverage Partial.

The public OTel interface is documented in
[`SpanExporter`](https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.export.html)
and
[`ReadableSpan`](https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.html).
This application adapter illustrates the identity-preserving copy; carrier
validation, schema checks and sink registration still need the chosen-version
proof above:

```python
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter

TOOL_CONTENT_FIELDS = {
    "gen_ai.tool.call.arguments", "gen_ai.tool.call.result",
    "gen_ai.input.messages", "gen_ai.output.messages", "input.value", "output.value",
}

class ToolContentView(ReadableSpan):
    def __init__(self, original, fields, removed):
        self.original = original
        super().__init__(
            name=original.name, context=original.context, parent=original.parent,
            resource=original.resource,
            attributes={
                **{key: value for key, value in (original.attributes or {}).items()
                   if key not in removed},
                **fields,
            },
            events=original.events, links=original.links, kind=original.kind,
            instrumentation_scope=original.instrumentation_scope,
            status=original.status, start_time=original.start_time,
            end_time=original.end_time,
        )

    @property
    def dropped_attributes(self):
        return self.original.dropped_attributes

    @property
    def dropped_events(self):
        return self.original.dropped_events

    @property
    def dropped_links(self):
        return self.original.dropped_links

class ToolContentExporter(SpanExporter):
    def __init__(self, delegate, validated_attributes):
        self.delegate = delegate
        self.validated_attributes = validated_attributes

    def export(self, spans):
        views = []
        for span in spans:
            fields, removed = self.validated_attributes(span)
            if not set(removed).issubset(TOOL_CONTENT_FIELDS):
                raise ValueError("Removal must be limited to owned tool content")
            views.append(ToolContentView(span, fields, removed)
                         if fields or removed else span)
        return self.delegate.export(views)

    def force_flush(self, timeout_millis=30000):
        return self.delegate.force_flush(timeout_millis)

    def shutdown(self):
        self.delegate.shutdown()
```

The validation callable returns `(validated_fields, removal_set)` and leaves
unrelated spans unchanged with `({}, set())`. Require the same owning tool's
safe values/identity and numeric limits; never reinterpret arbitrary metadata
as trusted GenAI content. Selective removal must be justified by that tool's
actual source outcome and current schema, not by deleting unrelated attributes.
For example, when a verified OpenInference output represents a real null,
remove a native schema-invalid `gen_ai.tool.call.result="null"`; simply adding
`output.value` does not repair the invalid field. For a failed call with no
produced result, remove any native fabricated successful result/output mapping
while retaining attempted input and error evidence. Do not remove required
safe output from a genuinely successful call to make a test pass. Retest the
whole resulting owned content set, not only the added fields; unsupported
representation or removal remains an explicit Partial gap. Error, timeout
and cancellation with no produced result retain ended ERROR/error.type and
no fabricated result/output mapping. Preserve native/input/output safety even
when exporter normalization replaces older message shapes. Forward delegate
export results and flush/shutdown behavior; do not hide rejected delivery.
Test source values, SDK native records and exported attributes/events/wire,
same trace/span/parent IDs, one node per actual call and unchanged business
arguments/results/errors/order. Missing registration or emitted proof remains
Not proven even when this concrete source recipe is available.

Prefer the matching framework/provider integration before writing operation
callbacks from scratch. Use decorators only on real logical boundaries and
verify what arguments/results they capture. Conclude SDK-created operations
and shut down the owned logger/provider, including streaming, auxiliary model
calls, timeout/cancellation and process teardown. SDK output must join the real
application trace and retain actual conversation/tool-call identity; do not
create an unexported synthetic parent or duplicate wrappers.

Apply `genai-readiness.md`'s Required GenAI Coverage Profile to SDK-created and
existing-library spans alike. Inspect actual emitted attributes: SDK use alone
does not prove current OTel or vendor completeness. Fill version-specific gaps
on the canonical operation through supported schema fields, callback hooks or
the yielded OTel span. For example, a version may omit agent provider or tool
message mappings despite the guide; preserve truthful provider identity and
consistent actual arguments/results without creating another operation span.
Do not edit dependencies/site-packages or assume export normalization repairs
missing data. If the required mapping cannot be supplied through a supported
application boundary, report that exact prerequisite as partial; do not
silently fall back to a metadata-only custom producer for a fresh agent.

This choice does not require Studio/gateway availability or live credentials
for source work and deterministic tests. Use the selected supported export
destination and normal SDK resource/config APIs; existing direct-cloud and
gateway behavior stays independent of the span-creation choice. For another
language, check current official documentation, package metadata and public
APIs for a compatible supported SDK/integration; record source/date and runtime
compatibility. Python examples do not prove another language's API. If the
language has no compatible supported Splunk AO SDK, use its native public
OpenTelemetry SDK, supported instrumentation and OTLP exporters. A bounded
check that cannot establish AO SDK support is recorded as unverified support,
not a reason to block the supported native path. Do not invent an AO package,
install a Python sidecar or require a deliberately failing SDK import.

Apply the entire applicable **Required GenAI Coverage Profile** from
`genai-readiness.md` to these native spans: actual operation/name/kind/parent,
provider/model and known request/response/usage fields, bounded safe typed
inputs/outputs, tool arguments/results plus their message mappings, retrieval
query/documents, source-supported correlation and correct error/cancel endings.
Preserve existing creators and use supported same-span hooks before adding
uncovered operations. Native libraries do not automatically fill these fields;
verify completed exported spans, concrete content schemas and full trace trees.
Missing source values remain explicit gaps or justified N/A rather than
fabricated defaults or successful outputs. Use the SDK-free resource and trace
routing path below for selected Project/Agent Stream configuration. SDK absence
does not make that configuration dependent on an AO span-creation library.

### Existing OpenTelemetry Provider

Preserve existing producers, providers and exporters for every signal. When
project/Agent Stream routing is selected for a non-AO application, resolve or
create the real resources independently of instrumentation. Use normal supported
resource APIs; do not install Splunk AO merely to obtain resource clients or an
export processor. The bundled resource helper's explicit
`--studio-api-origin <discovered-loopback-origin>` mode uses the current Studio
HTTP resource contract without an SDK dependency. It performs normal resource
calls, not endpoint discovery or a separate route-registration operation. Keep
lookup/create/repeated-run/duplicate-conflict proof and real IDs before binding
export. A failed lookup or create leaves the selected AO route unconfigured
while existing telemetry remains active.

Prefer adding routing headers to the existing compatible trace exporter. Inspect
its actual endpoint, protocol, constructor/env precedence and downstream
forwarding before editing. Current public standalone AO documentation specifies
`projectid` and `agentstreamid`; the current Studio receiver and inspected SDK
transport use `projectid` and `logstreamid`. Determine the target's supported
contract from current docs and installed/source evidence; do not send both
stream aliases or assume that the documentation contract fits every gateway.
For the current Studio HTTP/protobuf path, persist the resolved UUIDs in the
actual launch profile as:

```dotenv
OTEL_EXPORTER_OTLP_TRACES_HEADERS=projectid=<project-uuid>,logstreamid=<agent-stream-uuid>
```

Merge harmless existing trace headers, reject conflicting resource selectors,
and preserve the compatible explicit endpoint and protocol, including a
non-default port. Use trace-specific settings so AO routing/auth does not leak
into metrics or local logs. If code supplies exporter arguments directly,
configure that supported hook instead of writing unused environment variables.
If an operator destination cannot route to AO, preserve it and expose the exact
destination decision; do not silently retarget it or add another exporter.

When a distinct additional destination is explicitly selected, preserve the
original integration's effective configuration, including inherited vendor
project/stream names, API origins, credentials and loaded profile values.
An exclusive Studio profile isolates only incompatible settings of its own
selected SDK path; it must not unset another integration's namespace or reset
its configured stream to a default. Prove both effective destinations with
non-default operator values before and after the new launcher runs.

Inspect the existing exporter's actual header precedence too. If trace-specific
headers are absent and it inherits generic `OTEL_EXPORTER_OTLP_HEADERS`, adding
`OTEL_EXPORTER_OTLP_TRACES_HEADERS` can hide that fallback. Retain applicable
harmless inherited headers when merging the selected trace route, honor
explicit trace-header/constructor precedence, and leave global, metric and log
configuration intact. Authentication remains destination-scoped: do not copy
another destination's credentials into a new sink. Exercise the actual launcher
and exporter with sentinel harmless global and trace-specific headers.

The current Studio receiver recognizes this ID pair on `/v1/traces`,
`/otel/v1/traces` and `/v2/trace/otlp`. Successful normal resource resolution
through the same gateway confirms the route for its active cloud connection.
An ID copied from another connection is insufficient until resolved there.
Persisted UUID headers also do not restore the gateway's in-memory route after
its restart or active cloud connection change. Before treating routed delivery
as restored, run read-only project and scoped stream relookup through that
active gateway, using the persisted IDs with reuse-only semantics (or exact
name lookup). This deployment/resource bootstrap must not create duplicates,
replace the exporter, or make ordinary application instrumentation depend on a
reachable gateway. If relookup is unavailable, keep existing telemetry active
and report routed forwarding as unproven/failed. Test a cleared route followed
by relookup and repeated export, preserving IDs and zero additional creates;
headers alone before relookup must not be accepted as recovery proof.
The gateway retains local telemetry and uses its routed AO forwarding branch;
ordinary OTLP receipt without the pair does not select an Agent Stream. Check
rejected-span/partial-success responses, not only HTTP success. Resource
resolution, local routed receipt and cloud product visibility remain separate.

Inspect all active export paths to the final destination. Adding an AO
processor while an existing exporter already reaches that same AO destination
duplicates delivery. Prove one canonical operation and one export to each
selected destination, while preserving unrelated existing sinks. Only when
export-only SDK integration is explicitly chosen and compatible, register
`add_splunk_ao_span_processor` on the existing provider once and retain existing
processors; do not introduce SDK span creators. Keep the existing provider's
flush/shutdown ownership and prove both sinks drain without a second provider.

If supported HTTP propagation is also selected, pass the same provider to the
supported helper. Use `configure_distributed_tracing(tracer_provider=...)`
only when that provider still needs both Splunk AO export and supported
transport instrumentation. Use `instrument_distributed_tracing` when export is
already configured. A processor attached manually and then followed by
`configure_distributed_tracing` can register a second Splunk AO processor
because the high-level helper tracks only its own registrations; use the
transport-only helper in that case. Do not instrument the same HTTP client or
server through both the helper and a second instrumentor.

When existing OTel spans and Splunk AO span creation coexist, map the current
telemetry before editing:
`logical operation -> current span source -> exporter/provider -> privacy mode -> teardown`.
Keep one span source per logical operation. A Splunk AO processor
may export application OTel spans while `@log` or a framework handler creates
different non-overlapping operations, but the selected runtime must prove
correct trace parentage and no duplicate workflow, model, tool, or retrieval
spans across both export paths.

### Content Privacy

Treat content capture as a functional behavior, not documentation metadata.
State the reconciled documented behavior positively: by default, `@log`
captures function arguments and return values as operation input and output.
Do not weaken that fact to “may capture” merely because the installed package
is unavailable. Separately mark any version-specific suppression, redaction,
or exclusion control unproven until the installed version and supported API
are inspected. Before adding or preserving `@log` on a sensitive boundary,
identify the exact values captured and the installed version's supported
redaction or exclusion mechanism.

Unless raw content capture is approved, do not add `@log` directly to a
function whose parameters or return value contain prompts, completions,
retrieved documents, tool arguments/results, user/account identifiers, secrets,
or other sensitive values. Decorator or wrapper arguments and results must
already be safe metadata, or the installed integration must have a verified
control that prevents raw capture at the source. `redacted_input` and
`redacted_output` companion values do not by themselves remove the original
raw input or output. The required GenAI profile calls for useful bounded,
redacted inputs/outputs through verified source-side controls, not raw capture
or an optional content toggle. If the SDK path cannot meet that profile,
record the precise content/API prerequisite and keep coverage partial. An
explicitly selected metadata-only exception may use an app-owned OTel closure
for an existing producer, but cannot pass full required content coverage.
Do not claim that renaming a parameter,
omitting metric dimensions, adding companion redacted fields, or using an
exporter prevents the decorator from capturing content. If the installed SDK
cannot meet the selected privacy mode without changing application behavior,
record the exact blocker instead of silently exporting raw data.

### Deterministic Verification

Write focused tests before changing the telemetry setup. Local tests must use an
in-memory exporter, fake sink, or monkeypatched SDK boundary with no live
credentials and no provider/model network calls. Prove all applicable outcomes:

- reuse of the existing provider and the expected processor count;
- one span source and one node per logical operation;
- expected workflow/model/tool/retrieval parent-child shape;
- absence of a unique raw-content sentinel from every exported span attribute
  and event when capture is disabled or metadata-only;
- presence and latest-schema validity of applicable redacted input/output,
  instructions, tool definitions, arguments/results and vendor message
  mappings, matching actual invocation/result values in the required profile;
- truthful provider/request/response/usage/stream fields independently of
  content capture, with unavailable values explicitly unproven rather than zero;
- error and generator/stream completion behavior;
- `provider.shutdown()` for an application provider and `logger.terminate()`
  for a Splunk AO logger; and
- completed pending spans drain and owned sink resources close;
- no duplicate workflow, model, tool, or retrieval spans; and
- at most one export of each canonical operation to the same AO destination.

When the Splunk AO sink and application provider coexist, capture and inspect
both outputs. Static import matching proves classification, not runtime telemetry. Optional
live product verification may additionally prove fresh routing and field
population, but a local compatibility test must not depend on Lab0, a model API, or
the upstream examples repository.

## Upstream Example Policy

Use the official examples to discover realistic supported patterns and choose
representative framework coverage. Do not make shipped skill evals clone or run
the examples from a moving branch. Many examples require live credentials,
network services, optional packages, and provider-specific versions; those are
integration demonstrations rather than deterministic fixtures.

Encode the smallest behaviorally relevant patterns in local, credential-free
fixtures and cite the upstream repository plus commit used for reconciliation.
Prefer outcome assertions—complete coverage, provider reuse, safe content, lifecycle,
trace shape, and duplicate absence—over copying example files or exact source
text. Recheck the installed SDK or a newer pinned upstream commit when an API
signature or integration behavior affects the proposed change.

## Existing Galileo Applications

When the application already uses Galileo, preserve that integration by
default. Identify what it already provides before authoring findings: an OTel
span processor/exporter, a span-producing wrapper or callback bridge, and Galileo
resource configuration are separate capabilities. Do not treat the
presence of Galileo as permission to install `splunk-ao`, and never patch the
installed Galileo package or generated client.

Project and stream support still applies. Use the installed Galileo version's
native resource APIs, such as `galileo.projects.Projects` and
`galileo.log_streams.LogStreams`, and its existing processor/logger/context
configuration. Inspect signatures, pagination, name/ID support and errors before
implementing ordered lookup/create/reuse. The AO resource helper's default SDK
mode imports `splunk_ao`; do not invoke it for Galileo or install Splunk AO to
make it work. Use a supported Galileo client or application-owned adapter with
the same idempotency, association and failure-isolation acceptance above.
Persist selectors actually consumed by the runtime, for example supported
`GALILEO_PROJECT` and `GALILEO_LOG_STREAM` or explicit constructor/context
arguments, through its real launch profile. Preserve configured nondefault
stream names, API/console/auth settings and supported ID semantics. Do not
assume environment overrides a source-hardcoded constructor argument.
The native processor/exporter supplies the destination binding; verify its
actual outgoing headers/body/resource metadata rather than replacing it with
`OTEL_EXPORTER_OTLP_TRACES_HEADERS` or adding a Studio sink by default.
Classify missing bindings as default configuration findings under the shared
ledger; the target remains Galileo. Test the actual installed SDK with local
API/export fakes, not a replacement `galileo` module. Require a fresh trace in
the configured Galileo project/stream for live delivery proof. Any separately
requested Studio destination retains its own selection and preserves this path.

Keep missing application-owned spans, metrics, events, resources, attributes,
and lifecycle handling as ordinary OTel findings. They remain independent of
the export path and may be added around application boundaries while Galileo
stays in place, provided representative trace proof shows no
duplicate logical operations. Keep project, Agent Stream, dataset, prompt,
annotation, evaluator, integration, and attachment work as AO configuration
findings.

Preserve the existing Galileo path and close missing non-overlapping OTel or
selected AO resource/routing gaps through supported hooks and exporter
configuration. A missing field or incompatible destination requires exact
source/probe evidence and a prerequisite or destination decision, not a
replacement Splunk AO producer. Verify existing span/metric/log coverage and
one canonical operation before and after, then exercise the selected route.
A configuration call without application telemetry is not a working result.
