# GenAI Implementation

Load this instrument-specific reference together with
`../../references/genai-readiness.md` only when source evidence establishes a
GenAI surface. The shared reference owns semantic-convention and readiness
definitions; this file owns implementation closure and runtime wiring.

## GenAI Readiness Contract

If the canonical audit contains top-level `genai_readiness`, use those rows as
the source of truth. Parse each row by human-readable `surface` plus
`required_signals`, `owner/source_files`, and `acceptance_criteria`. Use the
surface name as the human-facing identifier throughout implementation and
reporting. Maintain this closure matrix:

`surface -> required_signals -> implemented_signals -> tests ->
remaining_signals -> status`

The instrumentation pass cannot say `covered`, `fixed`, `closed`, or
`complete` unless every required GenAI signal is implemented with tests, proven
existing with source path and signal name, or owner-mapped to the exact missing
source. For every GenAI instrumentation run, include a concise closure summary
and say `Remaining signals: none` only when no row is partial. When canonical
audit JSON is absent, do not invent `## GenAI Readiness Closure` rows or
continue audit-driven custom instrumentation.

When the user broadly asks for GenAI readiness, improve GenAI MTTD, or fix
found GenAI gaps, use all discovered app-owned GenAI gaps unless explicitly
narrowed. In GenAI incident-evidence mode, map each AI pathway failure
mechanism to its owning provider/model gateway, agent/workflow, tool/function
execution or AI-owned session/stream including MCP when present, retrieval/RAG,
streaming, token/context, prompt/response assembly, safety/policy, AI-derived
data, model/config rollout, or AI-owned cache/session surface. Classify each
result as `MTTD-improving`, `localization-only`, or remaining owner work. This
is GenAI incident-evidence mode: map every AI pathway failure mechanism,
including tool/function execution, before editing. Do not call GenAI
instrumentation complete while an app-owned required surface remains
only a follow-up unless scope was explicitly narrowed.

Follow the shared GenAI Semconv Source Contract before editing: reconcile
detected surfaces with live official documentation when available, record
repo/branch-or-commit/docs/date/live-or-snapshot provenance, and build a semconv
closure matrix.

## One Canonical Trace Shape

Apply the Single-Source GenAI Span Contract before adding manual spans.
Inventory framework/vendor bridges, provider SDK hooks, callbacks, middleware,
auto-instrumentors, and existing app spans. Choose one canonical GenAI span
source per logical operation. If a bridge already emits correct spans, add only
missing context, aggregates, metrics, or owner mappings; do not create duplicate
app-owned `chat` or `execute_tool` spans. If app-owned spans are canonical,
disable, opt out of, or suppress overlapping framework/vendor GenAI
instrumentation using the discovered runtime mechanism. Do not hard-code this
decision to one framework. Keep HTTP/database/runtime auto-instrumentation when
it does not create duplicate GenAI nodes.

Apply suppression in the launch environment before auto-instrumentation
bootstrap. Update actual Makefile targets, service runner scripts, Docker or
Helm env, VS Code launch configs, procfiles, units, or generated env scripts.
App module code that mutates environment variables after import is not
sufficient proof because framework hooks may already be registered.

Preserve stable business workflow identity and stable agent identity from
constants, registrations, factory/class/callback names, docs, telemetry event
names, or prior trace names. Do not invent names from HTTP routes or
session-derived labels. Preserve source names such as `assistant_v3_turn` and
`deepagents`; do not replace them with `assistant_v3_session_turn`,
`POST /v2/assistant/sessions`, `assistant_v3_agent`, or a generic
service-derived wrapper name.

For app-owned model calls, apply the LLM Inference Lifecycle Contract. Add or
prove a real model-call lifecycle span at the provider request boundary, using
`on_chat_model_start`, `on_chat_model_end`, and `on_chat_model_error` or their
equivalents. Workflow-level token accounting or a final usage event is not a
substitute. Set `gen_ai.operation.name` such as `chat`, `generate_content`, or
`text_completion`, request/response model, provider, final usage, and error
status on the inference span.

Preserve owning workflow/agent parent context so event-derived `chat` and
`execute_tool` spans are not siblings of the workflow under a generic HTTP root
or generic server span. Capture context before long-lived helper/setup spans
such as memory store, checkpointer, database session, or stream-writer; helper
spans must not become the parent. Write aggregate counters to the workflow
span, not whichever current span is active.

For async generator, `create_task`, `anext`, task handoff, or similar
yield/task boundaries, store and explicitly pass a workflow span/context handle
to the callback/event translator. Do not leave a current-span context manager
open across a scheduling boundary. When carriers may be immutable/frozen, do
not mutate them. Treat readonly declarations, record/value types, absence of a
mutation API, and existing copy construction as evidence. Use idiomatic copy/
replacement (`dataclasses.replace`, `attrs.evolve`, `model_copy(update=...)`,
Java records/builders, TypeScript object spread or `Readonly<T>`,
`structuredClone` only for plain-data carriers, Go value copies, or the
framework's request clone/with-context API). Never clone live OTel `Context` or
`Span` handles. If no safe copy exists, use invocation-scoped sidecar context,
clear it after cleanup, and do not key it by raw user, tenant, session, request,
or trace IDs. Add focused or explicit static proof that parent context is passed
and the original immutable input remains unchanged; guard Python frozen inputs
against `FrozenInstanceError`.

## Span-First And Detector-Ready Signals

For local span-first trace explorers such as Splunk Observability Studio, metrics alone are not enough for a selected-trace summary. Put safe `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, `gen_ai.usage.total_tokens`, model, stable tool,
memory, evaluation, fanout, and `error.type` attributes on the most specific
owning GenAI span and aggregate to the workflow when useful.

For evaluation quality surfaces, source evidence includes evaluator classes,
scoring functions, LLM-as-judge calls, `EvalScore` models, and
faithfulness/similarity/expectation metrics. Metrics-only coverage does not
satisfy selected-trace eval visibility. Add or prove
`gen_ai.evaluation.result` on the relevant workflow/evaluation span,
`gen_ai.evaluation.score.value`, `gen_ai.evaluation.score.label`, and a
span-level eval event; otherwise keep the evaluation quality surface partial.

For MCP/JSON-RPC and tool dispatch, Never record JSON-RPC request IDs, raw
request/session/user/tenant/trace IDs, tool arguments, or payloads as metric
dimensions. Derive stable names from an allowlist or known route/tool registration; otherwise use `known_tool`, `unknown_method`, `invalid_request`,
or `unsupported_method`. A send/write failure signal is required for app-owned
streaming or protocol send loops. GenAI spans alone do not satisfy detector-ready tool coverage: add or prove a tool-specific duration histogram
and tool error/timeout counter, or owner-map the missing source explicitly.
Use a focused repo-native test; Do not finalize with a compile or static string
check as the only telemetry proof.

For token/context pressure, token usage and a context-window gauge do not close
a broader gap when required signals include context budget percent, truncation
rate, token-limit errors, prompt/tool schema size, LLM call count per turn, or
tool call count per turn. When broadly asked for GenAI readiness, require the
same set. Use this exact partial style when applicable:
`Partial: token usage and context window added; truncation, token-limit error,
prompt/tool schema size, and LLM-call fanout remain missing.`

If prompt/tool schema size or safe proxy cannot be measured directly, use a low-cardinality
detector-ready proxy metric such as schema JSON length bucket, schema field
count, prompt template length bucket, or tool count. Span attributes like prompt template version help traces but do not close prompt/tool schema size pressure.
Keep the missing signal and owner in `remaining_signals`. Final summaries, PR descriptions, and audit updates must not omit residual truncation, token-limit,
prompt/tool schema size, LLM-call fanout, or tool-call fanout gaps.

Close code-evidenced memory/context operations, evaluation quality, content
governance, framework bridge, and app-computed cost only with their shared
reference contracts. Use OTel attributes including `gen_ai.input.messages`,
`gen_ai.retrieval.documents`, and `gen_ai.tool.call.arguments` only under the
opt-in governance policy. Treat cost as app-owned only with an accurate pricing
map; otherwise owner-map the billing or provider source. Record detector
reliability evidence for missed, flapping, auto-resolved, or no-data alerts as
a `$splunk-configure` handoff rather than inventing application metrics.

Source-owned model/config compatibility, response parsing, prompt/tool schema versions, and
expected-vs-running model/config are detector-relevant when source owns them.
If canonical audit JSON is absent, do not synthesize these closure obligations.
