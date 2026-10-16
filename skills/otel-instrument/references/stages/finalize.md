### 7. Finalize

- In the final response, separate file changes from verified outcomes
- State the selected project runtime, affected-module compile/type/import
  result, focused tests that actually ran, and the verification result or
  blocking prerequisite.
- Write `.observe/otel-instrumentation.md` and include a `Signals Changed`
  summary with added, modified, and removed traces/spans, metrics, logs/events,
  runtime/config, and dependencies. If no prior audit existed, state that the
  report establishes the implementation baseline.
- In canonical flow, write and validate `.observe/otel-instrumentation.json`,
  render `.observe/otel-instrumentation.html` using
  `./references/json-approval-handoff.md`, and keep every selected finding
  exactly once. Leave `.observe/otel.html` as the audit and scope surface;
  never call unselected findings implemented.
- Include selected `Audit Gap Closure` counts by `Working`, `Not working`, `Not
  proven`, and `Not configured`. Do not report unselected findings as
  implemented work.
- For incident-readiness work, summarize each in-scope workflow, dependency,
  input-complexity, freshness, backpressure, synthetic/canary, auth/edge,
  capacity, health/readiness, and release/config surface as MTTD-improving,
  localization-only, provider/platform-owned, or uncovered. Name every
  remaining detector prerequisite and its owner; do not call the pass complete
  while an app-owned required signal is only a follow-up unless the user
  explicitly narrowed scope.
- When the source audit declares GenAI ownership, include the complete
  selected-scope `GenAI Readiness Closure` matrix and list every non-`Working`
  remaining signal in the final response.
- If canonical audit JSON is absent, stop before GenAI instrumentation and ask
  the user to run `$otel-audit`; do not collapse absent GenAI readiness into a
  generic implementation claim.
- Include `$otel-verify` results and `.observe/otel-verify.md` path when run.
  If detectors/configuration were requested, include `$splunk-configure`
  outputs and `.observe/splunk-configure-verify.md` status when run.
- In canonical flow, use the `render-instrumentation-html` command's returned
  loopback links for both `otel-instrumentation.html` and `otel.html` in the
  final response. Do not emit absolute local-file links for generated HTML and
  do not open either report automatically. On the permitted direct baseline
  path, link only the absolute `.observe/otel-instrumentation.md` report; do not
  claim or link audit, selection, JSON, or HTML artifacts that were not created.
  Keep Markdown and JSON report links as absolute local paths.
- If verification is partial, say exactly what is working and what is still missing instead of reporting full success
- Never say `complete`, `working`, or `verified` when the mandatory
  compile/type/import gate failed, was blocked, or was not run. Use
  `implemented; verification blocked/not run` and name the prerequisite.
- Always include the service-name configuration, OTLP endpoint configuration, and which automatic spans/metrics are expected from the instrumentation.
- State the selected log scope and the full-runtime acceptance result whenever
  either is applicable.
- For the default local log baseline, state the detected bridge, preserved
  stdout/file sinks, effective `OTEL_LOGS_EXPORTER` and signal-specific local
  logs endpoint, explicit opt-out behavior, duplicate-prevention proof, and
  that cloud forwarding/configuration remains traces and metrics only.
- For GenAI work, state which OTel GenAI operations were instrumented, which
  GenAI metrics are expected, whether trace continuity should produce a nested
  workflow/agent/tool/chat/retrieval shape, and which privacy/cardinality limits
  were enforced.
- For GenAI incident-evidence work, include a concise coverage summary by
  incident class or repo surface: MTTD-improving, localization-only, or
  uncovered. Name any remaining provider/model, workflow, tool/function
  execution or AI-owned session/stream including MCP when present, retrieval,
  streaming, token/context, prompt/response, safety/policy, AI-derived data,
  model/config rollout, or AI-owned cache/session owner that still blocks
  detector-ready coverage.

