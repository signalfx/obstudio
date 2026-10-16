### Implementation Report And Handoff

Check the three GenAI evidence tables before finalizing, including explicit
INTERNAL-agent provider, tool input/output message mappings and lifecycle rows.
Keep proposals separate from executed proof; correct omissions in the plan
without claiming that implementation or verification ran.

Always write `.observe/otel-instrumentation.md`. In canonical flow,
`./references/json-approval-handoff.md` remains the machine-schema and
instrumentation-HTML authority: write and validate
`.observe/otel-instrumentation.json`, render
`.observe/otel-instrumentation.html`, keep every selected finding exactly once,
and leave `.observe/otel.html` as the audit surface. On the permitted direct
baseline path where canonical JSON is absent, write the technical Markdown
report only, identify the source audit and selected scope as `not applicable
(direct baseline)`, and do not create instrumentation JSON/HTML or fabricate
audit IDs. Do not infer scope from generated Markdown reports.
Users open `.observe/otel-instrumentation.html` after instrumentation to review
the selected findings, what code/config changed, how observability improves,
telemetry proof, product-delivery status, and remaining prerequisites. Do not
use it to change selected scope; direct scope changes back to `.observe/otel.html`
and rerun instrumentation from the newly saved or copied command.

#### Reader Order

Use this shape:

```markdown
# OTel Instrumentation Report: <service>

**Result:** Pass | Partial | Fail | Blocked
**Source audit:** `.observe/otel-audit.json` | not applicable (direct baseline)
**Selected scope:** `.observe/otel-selection.json` | not applicable (direct baseline)
**Verification report:** `.observe/otel-verify.md` | not run | blocked
**Detector report:** `.observe/detectors.md` | not requested | blocked

## Executive Summary
## Flow
## Files Changed
## Signals Changed
## Audit Gap Closure
<!-- Include the next section only for a GenAI source audit. -->
## GenAI Readiness Closure
## Validation Gates
## Verification Handoff / Results
## Detector Handoff / Results
## Remaining Gaps
## Next Steps
```

#### Signals Changed

`Signals Changed` is the implementation-change inventory. Include:

| Signal type | Added | Modified | Removed | Product result / next product action | Evidence | Verification status |
|---|---|---|---|---|---|---|
| Traces/spans | exact span names or `None` | exact changes or `None` | exact removals or `None` | waterfall/map/filter result and follow-up | source paths + tests/harnesses | verified/partial/not run/blocked |
| Metrics | exact metric names or `None` | exact changes or `None` | exact removals or `None` | chart/dashboard/detector action | source paths + tests/harnesses | verified/partial/not run/blocked |
| Logs/events | bridge/event names or `None` | exact changes or `None` | exact removals or `None` | query/correlation result and follow-up | source paths + tests/harnesses | verified/partial/not run/blocked |
| Runtime/config | service/exporter/env/startup settings or `None` | exact changes or `None` | exact removals or `None` | service/environment/export diagnostics | startup/config paths | verified/partial/not run/blocked |
| Dependencies | OTel packages or `None` | version/package changes or `None` | removed packages or `None` | enabled runtime behavior | manifest/lockfile paths | verified/partial/not run/blocked |

Do not claim a removal unless the previous report or Git diff proves the signal
or configuration existed and current source proves it was removed. Use `None`
for empty cells. The final response must summarize added, modified, removed, and
unchanged signals by signal type and point to this report.
If any item changes an existing telemetry consumer contract, include a concise
`Consumer compatibility` subsection that lists the existing contract, whether
the change is compatible, breaking, or requires review, and the migration for
breaking changes.

For canonical scope, treat every instrumentation
`findings[].telemetry_changes[]` row as the durable code-to-product mapping.
Preserve its stable item ID, concrete code/config change, exact source or call
site, signal kind, newly added attributes/dimensions, product view, audit
scenarios, and item-specific follow-up actions. A free-text finding `changes`
list is not item coverage. Preserve audit-authored keys and bounded values
exactly. Never auto-publish without the downstream review workflow.

##### Incident Readiness Signal Roles

For selected incident-readiness work, include this nested table:

| Surface | Exact signal | Role | Detector use / reason | Proof | Remaining owner / prerequisite |
|---|---|---|---|---|---|

Use exactly `MTTD-improving`, `localization-only`,
`provider/platform-owned`, or `uncovered` in `Role`. Write one row per exact
added or proven signal; do not group metric names. Use `None` for `Exact signal`
only when owner-mapping an unavailable prerequisite, and name that owner or
prerequisite in the final column. This is a signal-role inventory, not another
gap ledger; reconcile audited surfaces through `Audit Gap Closure`.

#### Audit Gap Closure

This is the reader-facing technical reconciliation. Stable IDs and exact
selected scope live in canonical JSON.

| Finding | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|
| stable finding ID — exact audit title | concrete code/config change or `No code change` | scenario IDs and test mode | Working / Not working / Not proven / Not configured | direct evidence or exact blocker |

Use one row per selected audit finding and keep unselected findings out of this
implementation report. Canonical instrumentation JSON contains selected rows
only. `Not working` requires an executed failed check.
`Not proven` means the required scenario did not run or lacked a prerequisite.
Use `Not configured` when requested implementation is absent.

For every selected canonical row, project `What changed`, `Tested`, and
`Evidence / reason` exactly from instrumentation JSON `changes`, `tests`, and
`evidence` arrays in source order. After verification, only `Result` comes from
the bound verify row. Do not paraphrase projection cells independently.

For a GenAI audit, `GenAI Readiness Closure` is the detailed signal-level
reconciliation and `Audit Gap Closure` remains the prioritized user work queue.
Neither substitutes for the other. Follow the loaded GenAI reference for its
machine closure and rollup.

Derive `**Result:**` from all applicable closure tables. Do not use `Pass` while
an audit row is `Not working`, `Not proven`, or `Not configured`, or a GenAI row
is `Not working`, `Not proven`, or `Not configured`. Use `Partial` when
meaningful proof passed but any such row remains. `Deferred` may coexist with
`Pass` only when the exact external owner or explicit scope decision is
recorded.

#### Validation And Verification Handoff

For canonical flow, validate the audit, selection, instrumentation overlay, and
available verification overlay and render the human instrumentation HTML using
`json-approval-handoff.md`. Do not continue audit-driven instrumentation without
canonical JSON.

Maintain `## Verification Handoff / Results` using
`./references/project-runtime-validation.md`. Record the selected runtime, exact local-safe
commands and outcomes, changed source-to-scenario mappings, the `$otel-verify`
result/report path, and blocked prerequisites. This is not proof of emitted
telemetry unless a test, harness, or collector actually observed it.

Use the canonical audit, validated selection, and selected findings' referenced
verification scenarios as the handoff contract. Do not copy unrelated report
sections into audit or instrumentation reports.

When the user asks broadly to apply GenAI readiness skills, improve GenAI MTTD,
or fix found GenAI gaps, treat the scope as **all discovered app-owned GenAI
gaps**. Do not select one representative or highest-value gap unless the user
explicitly narrows the scope to that gap.

Close code-evidenced AI pathway surfaces from `../references/genai-readiness.md`:
provider/model gateway, agent/workflow orchestration, tool/function execution
or AI-owned session/stream lifecycle including MCP when present, retrieval/RAG,
streaming response lifecycle, token/context pressure, safety/policy outcome,
prompt/response assembly, AI-derived data freshness, memory/context operations,
evaluation quality, content governance, framework bridge configuration,
app-computed cost, model/config rollout, and AI-owned cache/session state.

For evaluation quality surfaces, code evidence such as evaluator classes,
scoring functions, LLM-as-judge calls, feedback processors, `EvalScore` models,
faithfulness/similarity/expectation metrics, pass/fail labels, or quality
report exporters is enough to require eval instrumentation.
Metrics-only coverage does not satisfy selected-trace eval visibility. Add or prove
`gen_ai.evaluation.result` on the relevant workflow/evaluation span with
`gen_ai.evaluation.name`, `gen_ai.evaluation.score.value` when numeric scores
exist, `gen_ai.evaluation.score.label` when labels/verdicts exist, and safe
parent linkage. Also add or prove detector-ready score distribution, pass/fail
or violation count, sample count/rate, evaluator duration/error/no-data, and
freshness by low-cardinality workflow/model/evaluation name. If the service
only emits eval counters, histograms, logs, or report files, keep the evaluation quality surface partial
and name the missing span-level eval event and remaining detector metrics.

For MCP, JSON-RPC, and tool dispatch, normalize request metadata before adding
attributes or metric dimensions. Never record JSON-RPC request IDs, raw request
IDs, session IDs, trace IDs, user/account/tenant IDs, raw tool arguments, raw
payloads, prompts, completions, or retrieved content as metric dimensions.
Use stable method names only from an allowlist or from known route/tool registration; otherwise record a low-cardinality method family such as
`known_tool`, `unknown_method`, `invalid_request`, or `unsupported_method`.

Prefer detector-ready metrics and span attributes for outcome, duration,
timeout, retry, rate-limit, fallback, active AI-owned sessions/streams, close
reason family, send/write failure, freshness, empty/low-confidence retrieval,
token budget, prompt build failure, response parse failure, AI-derived data
freshness, prompt/tool schema version, model/config readiness,
model/config compatibility, expected-vs-running model/config state, truncation,
rejection, LLM-call fanout, tool-call fanout, evaluation score/outcome,
memory hit/miss or staleness, content capture mode/redaction, app-owned cost
source, and version dimensions when the service can observe them accurately.
Use OTel GenAI semconv names when possible: `gen_ai.evaluation.result`,
`gen_ai.evaluation.name`, `gen_ai.evaluation.score.value`,
`gen_ai.evaluation.score.label`, safe `gen_ai.evaluation.explanation`, memory
operation names such as `search_memory`, `create_memory`, `update_memory`,
`upsert_memory`, and `delete_memory`, and content attributes required by the
GenAI coverage profile (published by OTel as Opt-In) such as
`gen_ai.input.messages`, `gen_ai.output.messages`,
`gen_ai.system_instructions`, `gen_ai.retrieval.documents`,
`gen_ai.retrieval.query.text`, `gen_ai.tool.definitions`, and
`gen_ai.tool.call.arguments`, and `gen_ai.tool.call.result`. Treat framework
bridges as covered only when OTel-compatible GenAI semconv output and privacy
settings are proven. Treat cost
as custom app-owned instrumentation only when the app owns an accurate pricing map; otherwise owner-map the billing or provider source. Generic non-AI runtime,
platform, or job surfaces are out of scope for this GenAI section unless source
evidence shows they carry or block the AI pathway.
If GenAI incident evidence depends on missed, flapping, auto-resolved, or no-data alerts, record detector reliability evidence as a `$splunk-configure`
handoff instead of adding app metrics for alert lifecycle behavior.

For AI-owned streaming generators, WebSocket/SSE handlers, callback bridges,
or protocol send loops, do not call stream lifecycle coverage complete without
a send/write failure signal. Add a counter, span event, or low-cardinality
outcome attribute for send/write failure when app code can observe it; otherwise
owner-map the missing source explicitly to the framework/server/platform.

For token/context pressure gaps, current inference usage metrics plus a
context-window usage gauge does not close a broader token-pressure gap unless
the audit contract only requires those two signals. If `required_signals`
include context budget percent, truncation rate, token-limit errors,
prompt/tool schema size, LLM call count per turn, or tool call count per turn,
mark the row partial until each signal is implemented, proven, or owner-mapped.
When the user broadly asks for GenAI readiness without a preexisting audit
contract, treat token/context pressure as requiring the same concrete signal
check: token usage, context budget percent, truncation, token-limit errors,
prompt/tool schema size or safe proxy, LLM-call count, and tool-call count when
the app can observe them.
Use this exact style when only token and context-window usage were added:
`Partial: token usage and context window added; truncation, token-limit error, prompt/tool schema size, and LLM-call fanout remain missing.`

If prompt/tool schema size cannot be measured safely, add a low-cardinality
detector-ready proxy metric such as schema JSON length bucket, schema field count,
prompt template length bucket, or tool count when the app can observe it.
Span attributes like prompt template version, schema version, or one-off schema
metadata help traces but do not close prompt/tool schema size pressure by themselves. If no safe metric or detector-ready existing signal exists, the
closure matrix and final response must keep prompt/tool schema size in
`remaining_signals` with the owner and missing source. Do the same for LLM-call
and tool-call fanout: implement per-workflow counts when observable, prove an
existing signal, or keep them explicitly partial.

Final summaries, PR descriptions, and audit updates must not omit residual
truncation, token-limit, prompt/tool schema size, LLM-call fanout, or
tool-call fanout gaps when they were in the audit contract or when broad GenAI
readiness instrumentation discovered the token/context surface.

For tool/function execution, GenAI spans alone do not satisfy detector-ready
tool coverage. When app code observes tool execution, add or prove a
tool-specific duration histogram and tool error/timeout counter using a stable
tool name and low-cardinality failure class. If only spans are safe, keep tool
latency/error metrics in `remaining_signals` and do not claim detector-ready
tool coverage.

Do not call GenAI instrumentation complete when an app-owned provider/model,
workflow, tool/function execution or AI-owned session/stream including MCP when
present, retrieval, streaming, token/context, safety/policy, prompt/response,
AI-derived data, memory/context, evaluation quality, content governance,
framework bridge, app-computed cost, model/config rollout, or AI-owned
cache/session surface remains only listed as a follow-up, unless the user
explicitly narrowed scope.

