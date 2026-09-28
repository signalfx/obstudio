# Splunk Agent Observability Findings

Use this reference when the user asks whether a GenAI or agent application can
populate Splunk Agent Observability, when an audit finds existing Agent
Observability routing or resource configuration, or when a selected finding
has `finding_group: splunk-agent-observability`.

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

Appropriate AO findings include source-backed work for an existing or intended:

- project and dedicated Agent Stream;
- direct application routing to those resources;
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
- direct stream routing depends on project, Agent Stream, and the required OTel
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

## Direct Runtime Result

Selected AO work must leave durable application or deployment configuration
that works without Splunk Observability Studio in the runtime data path. Use a
Splunk-supported SDK or product API only when source and target-product
evidence support it. Keep credentials in operator-owned secret storage, use
checked-in placeholders or secret references, and never write access tokens to
tracked files.

Obstudio may help audit, select, and verify the work, but the deployed
application must export directly through its configured OpenTelemetry or
supported Splunk Agent Observability path. Verification must distinguish:

- a resource that was created or resolved;
- direct application routing that was exercised; and
- a fresh application trace or configured object that was observed in the
  intended Agent Observability project and Agent Stream.

Do not call a resource-configuration finding `working` from a successful API response
alone when its acceptance criteria require application data in the product.

## Splunk AO Python Compatibility

Use this contract when Python dependencies or source contain `splunk_ao`.
Determine behavior from the installed version and its source or API docs. The
patterns below were reconciled against the official
[`splunk/splunk-ao-python`](https://github.com/splunk/splunk-ao-python)
repository at commit `7a80c1df3a6f5728eec8a470fe7498a3dc76086a`; record the installed
package version and current source provenance when making a version-sensitive
change.

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

When the application has neither OpenTelemetry nor Splunk AO span creation,
use the selected finding and user intent to choose how spans are created. Ordinary OTel
findings default to application-owned official OpenTelemetry. Use the Splunk AO
instrumentation path only when the selected scope calls for SDK-created spans or a
supported Splunk AO framework integration. Install only the extras required by
the detected framework, decorate or wrap stable operation boundaries, and do
not convert unrelated functions into spans.

If a high-level helper creates a provider, retain the returned provider in
application startup state, pass it to supported instrumentation that
must join the trace, and call `provider.shutdown()` at process teardown. If a
`SplunkAOLogger` or SDK context manages the sink instead, prove its supported
`logger.terminate()` or process teardown path. A flush drains completed work;
it does not conclude unfinished operations or replace shutdown.

### Existing OpenTelemetry Provider

Preserve the application's existing provider. For export-only adoption, call
`add_splunk_ao_span_processor` with that exact provider once, retain any
existing processors, set or preserve the intended global provider separately,
and keep `provider.shutdown()` in the application teardown path. Do not create
a second provider merely to export to Splunk AO.

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
raw input or output. Prefer an app-owned metadata-only OTel span when the SDK
path cannot prevent raw capture. Do not claim that renaming a parameter,
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
- error and generator/stream completion behavior;
- `provider.shutdown()` for an application provider and `logger.terminate()`
  for a Splunk AO logger; and
- no duplicate workflow, model, tool, or retrieval spans.

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

Keep missing application-owned spans, metrics, events, resources, attributes,
and lifecycle handling as ordinary OTel findings. They remain independent of
the export path and may be added around application boundaries while Galileo
stays in place, provided representative trace proof shows no
duplicate logical operations. Keep project, Agent Stream, dataset, prompt,
annotation, evaluator, integration, and attachment work as AO configuration
findings.

Create a Galileo-versus-`splunk-ao` `manual decision` only when validated
source and target-product evidence shows that the required routing, field
mapping, or supported runtime behavior has two real mutually exclusive
supported paths. Give each option a separate executable finding and disjoint
`unlocks`; answering the decision must not select either branch. When the
evidence shows the current Galileo path can satisfy the requirement, retain it
and do not create a migration branch. When it shows Galileo cannot satisfy the
requirement, do not present it as an equivalent option.

For a selected keep-Galileo path, preserve Galileo configuration and add only
the missing non-overlapping OTel or AO configuration. For a selected
`splunk-ao` branch, disable the overlapping Galileo processor, wrappers,
callbacks, and preload configuration before enabling `splunk-ao`. Verify a
fresh application trace in the intended project and Agent Stream, inspect the
required Agent Observability fields, and prove one canonical span per logical
operation. A successful configuration call without fresh routed application
data and duplicate-span proof is not a working result.
