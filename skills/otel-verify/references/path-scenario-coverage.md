# Acceptance Scenario Coverage

Use this reference whenever `.observe/otel-audit.json` exists or direct
verification scope includes workflows, routes, jobs, startup, streaming, tools,
retrieval, redaction, or error paths.

## Goal

Verify paths, not only signal names. A path is a user-visible, API-visible, or
runtime scenario whose telemetry shape differs from other scenarios. Examples:
chat success, chat streaming, stream send failure, LLM timeout, tool success,
tool error, MCP request, retrieval empty result, memory upsert failure, proxy
route redaction, Logs v2 success, Logs v2 failure, process startup, FastAPI
request, and shutdown.

Do not claim all-path coverage from one aggregate contract trace. One trace may
prove exporter health or a compact signal contract, but path coverage requires
scenario-specific execution and evidence.

## Derive Acceptance Scenarios From The Audit

For a canonical flow, read `.observe/otel-audit.json`, the bound
`.observe/otel-selection.json`, and `.observe/otel-instrumentation.json`.
Extract only the approved findings' referenced scenarios and environments, and
preserve their stable IDs. Do not derive verification obligations from
unselected findings.

Without canonical audit JSON, derive scenarios only from the explicit user
scope, current source paths, and signal-affecting control flow. A prior
instrumentation report may supply evidence but must not expand scope.

When canonical or direct scope does not explicitly list paths, derive a conservative scenario
set from signal-affecting control flow only. Avoid path explosion: do not create
separate rows for micro-branches that emit identical telemetry. Split paths
when span names, parentage, status, events, metrics, log body/severity,
redaction behavior, resource attrs, or runtime wiring differ.

For every candidate path, record:

- source evidence: audit heading, route/workflow/source file, or diff hunk
- user/runtime trigger: HTTP route, workflow method, CLI command, startup hook,
  scheduler/job, stream callback, tool/MCP request, or provider adapter call
- expected added telemetry: trace/span/event names, metric names and
  dimensions, log bodies/categories/severity, runtime/exporter signal
- expected code proof: existing test, new repo test when requested, temporary
  app-code harness, live smoke, source-only, or blocked prerequisite
- expected OTLP proof: trace id per scenario, metric datapoint, log record, or
  explicit note that only in-memory evidence is available

## Required Inventory

Create this table before running checks:

```markdown
## Acceptance Scenario Inventory

| Scenario id | Audit/source evidence | Trigger | Expected topology/signals | Proof plan | Status |
|---|---|---|---|---|---|
```

Also create or feed this application-path table in the final report:

```markdown
## Application Code Path Verification

| Code path / user path | Source entrypoint | Trigger/fakes | Expected traces/metrics/logs | Test/harness | App code proof | OTLP/log/metric evidence | Status |
|---|---|---|---|---|---|---|---|
```

Use stable ids such as:

- `chat.success`
- `chat.stream.success`
- `chat.stream.send_failure`
- `workflow.remediation.success`
- `workflow.remediation.llm_error`
- `workflow.logs_v2.success`
- `workflow.logs_v2.failure`
- `tool.success`
- `tool.error`
- `mcp.request`
- `retrieval.memory.search`
- `retrieval.memory.empty`
- `memory.upsert`
- `proxy.openai.redaction.non_stream`
- `proxy.openai.redaction.stream`
- `runtime.fastapi.startup`
- `runtime.fastapi.request`
- `runtime.process.entrypoint`
- `runtime.service_runner.defaults`

## Scenario Execution Rules

- Prefer real app or real call-site execution with fake inputs.
- Test the path through the source entrypoint named by the audit whenever
  possible: route handler, workflow method, middleware, adapter, startup hook,
  runner, stream callback, or job function.
- Use generated nested SDK contracts only when real imports or call sites cannot
  run; label them `generated nested contract`.
- Emit one trace per scenario when OTLP is available. Multiple scenarios may run
  in one process, but each scenario should have a distinct root span and
  `verification.scenario=<scenario id>`.
- Keep topology realistic for the scenario. Do not put unrelated paths under
  one root merely to show all spans in one explorer view.
- Assert expected parent edges, span status, required attributes, metric
  datapoints, log correlation, and redaction in-process when possible.
- Query Obstudio or the collector while the harness is alive and record trace
  ids per scenario.
- Use the shared full-runtime acceptance contract for agent/preload signals,
  framework-resolved route names, automatic metrics, runtime log bridges, and
  duplicate automatic-span checks. Focused call-site or synthetic-root proof
  cannot close those rows.
- If a path cannot be executed because it starts a real service, requires live
  credentials, calls an external provider, or needs unsafe side effects, mark
  it with the exact status and reason. Do not hide it behind an aggregate trace.
- A source-only code read can document expected telemetry, but it does not prove
  the code works. Leave `App code proof` empty or `source only` and keep the
  status below fully verified.

## Report Requirements

Add this section to `.observe/otel-verify.md`:

```markdown
## Path Coverage Matrix

| Scenario id | Path / trigger | Expected signals | Trace id(s) | Status | Evidence or gap |
|---|---|---|---|---|---|
```

Also add:

```markdown
## Application Code Path Verification

| Code path / user path | Source entrypoint | Trigger/fakes | Expected traces/metrics/logs | Test/harness | App code proof | OTLP/log/metric evidence | Status |
|---|---|---|---|---|---|---|---|
```

Use statuses from the main skill:

- `Verified: unit`
- `Verified: OTLP`
- `Verified: unit+OTLP`
- `Verified: app test`
- `Verified: app test+OTLP`
- `Source only`
- `Not emitted`
- `Not run`
- `Blocked`
- `Not configured`
- `Not applicable`

For each path row, distinguish:

- `real app execution`: actual service/workflow/route path ran.
- `focused call-site execution`: instrumented function/decorator/handler ran
  with fakes, but not the full service.
- `generated nested contract`: SDK-created trace mimicked expected topology
  because real path could not run.
- `aggregate contract`: combined signal smoke; useful evidence for export and
  shape only, not all-path coverage.

The summary must include path counts, for example:

`Path coverage: 8/12 verified; 2 source-only; 1 not run; 1 blocked.`

If signal coverage is higher than path coverage, say so explicitly. Example:

`All span names were emitted, but only 8/12 audit-derived paths were executed; the remaining paths are source-only/not-run and keep the result Partial.`
