---
name: otel-instrument
description: >-
  Add OpenTelemetry traces, metrics, and local application logs through
  auto-instrumentation and selected custom signals, then write reports and
  verify unless blocked. Use for $otel-instrument, approved audit IDs or
  .observe/otel-selection.json, service instrumentation, specific spans or
  metrics, incident-detection signals, and GenAI/LLM semantic conventions.
---

# Instrument

Add OpenTelemetry to the application path users run. Preserve runtime shape,
telemetry contracts, and operator configuration. A broad OTel request is an
implementation workflow: change the in-scope service, report, and verify or
name the exact blocker.

Resolve paths written in this entrypoint from the directory containing the
loaded `otel-instrument/SKILL.md`. Inside a loaded reference, resolve relative
paths from that reference's directory. Never resolve skill references from the
service cwd or probe alternate skill copies unless a required file is missing.

## Load Guidance Progressively

Read only guidance that applies to the detected service:

1. Always read `./references/project-runtime-validation.md`.
2. Read exactly one detected-language guide, never all language guides:
   `./references/languages/python.md`, `./references/languages/node.md`,
   `./references/languages/java.md`, or `./references/languages/go.md`.
   That guide owns package choices, setup examples, framework wiring, local-log
   bridge details, and language-specific shutdown behavior.
3. For report rules, use one heading-bounded extraction of
   `../references/report-flow-contract.md`: keep the document prefix only until
   the paragraph beginning `For an audit,`, keep `## Status Rules` only until
   `## Audit Contract`, and keep `## Instrumentation Contract` only until
   `## Verification Report Contract`. For example:

   ```bash
   awk 'BEGIN { emit = 1 }
     /^For an audit,/ { emit = 0 }
     /^## Status Rules$/ { emit = 1 }
     /^## Audit Contract$/ { emit = 0 }
     /^## Instrumentation Contract$/ { emit = 1 }
     /^## Verification Report Contract$/ { emit = 0 }
     emit' <instrument-skill-dir>/../references/report-flow-contract.md
   ```

   Do not load audit-only reader guidance or the audit, verification, or
   Splunk Configure contract sections for this workflow. Do not substitute
   fixed line offsets; headings are the stable boundaries.
4. If `.observe/otel-audit.json` exists or exact finding IDs were supplied,
   read `./references/json-approval-handoff.md`. It is authoritative for
   selection precedence, digest binding, instrumentation JSON, and HTML.
5. Load `../references/incident-readiness.md` and
   `./references/incident-implementation.md` only when the repo owns an
   incident-readiness surface, the audit selects one, or the user supplies
   incident evidence or asks for faster detection/localization.
6. Load `../references/genai-readiness.md` and
   `./references/genai-implementation.md` only when source owns an LLM, agent,
   workflow, tool/function, MCP, retrieval, model/config, token/context,
   evaluation, memory, or other GenAI surface. Follow the shared GenAI Semconv
   Source, Single-Source Span, LLM Inference Lifecycle, token-pressure,
   privacy, and closure contracts in full.
7. Load `../references/full-runtime-acceptance.md` only when a claim depends on
   the real agent/preload, framework route resolution, automatic metrics,
   startup/exporter wiring, duplicate suppression, or a runtime-installed log
   bridge. Load `./references/signal-mapping-guide.md` only when choosing a
   custom signal type.

## 1. Preflight And Scope Gate

Ground the plan in repository evidence before the first edit.

### Canonical audit and selection

When `.observe/otel-audit.json` exists, it is the canonical audit. Follow
`./references/json-approval-handoff.md` before changing application code, dependencies,
runtime config, or tests. Validate the audit and a nonempty, dependency-closed
selection; use current-request IDs first, then trusted repository selection,
then a validated saved audit, and only use deterministic `select --all` for a
bare or broad instrumentation request with no saved scope. Run the idempotent
preflight exactly as follows: run the shared `adopt-selection` helper as an
idempotent preflight step before reporting a missing selection. If the helper
prints `PASS:` or `wrote`, immediately run `validate-flow` and continue the same
`$otel-instrument` run; do not ask the user to move a download, save again, or
rerun instrumentation. Never select
`manual decision` or `external follow-up` findings, infer a decision from
prose, bypass an unanswered dependency, or implement unselected work.

Implement exactly the selected IDs plus executable dependencies added by
`select`, which are `approved_ids` in canonical audit order, and run every
named verification scenario at its authored `proof_level`. Bind
`.observe/otel-instrumentation.json` to the complete normalized selection with
`selection_sha256`, including `decision_answers`.

When no canonical audit exists, a direct request for the standard
auto-instrumentation and default-local-log baseline may proceed. Do not fabricate IDs or
JSON overlays. When no canonical audit exists, stop before custom
instrumentation and ask the user to run `$otel-audit` first. Never infer scope
from a generated Markdown report.

### Repository and runtime evidence

- Detect language/framework from manifests and source. Select and probe the
  project-configured runtime described by
  `./references/project-runtime-validation.md`;
  do not silently use a conflicting shell default.
- Find the real executable/start surface (`cmd/.../main`, app module, package
  script, Make target, Compose/Kubernetes config, service unit, or equivalent).
  Instrument that boundary. Never initialize global providers merely because
  an importable library package contains handlers or business logic.
- Preserve the current host, container, or orchestrated startup path. Do not
  introduce Docker or invent a web entrypoint just for telemetry.
- If several runnable surfaces remain plausible, ask which matters. If this is
  a library/tooling repo with no evident executable, stop instead of inventing
  one.
- Inventory existing trace, metric, and log providers (including lazy/global
  construction), exporters, resources, propagation, bridges, shutdown paths,
  and no-op branches. Existing ownership of one signal does not prove the
  others are configured.
- Inventory consumer-visible metric names/dimensions, span names/attributes,
  resource/log fields, exporter settings, dashboards, detectors, entity maps,
  queries, and tests. Prefer additive semconv fields, preserve safe legacy
  aliases, and record compatible, breaking, or review-needed migrations in
  `telemetry_changes[].consumer_compatibility`.
- Confirm `service.name`, `service.version`, and environment ownership. Preserve
  operator values. Resolve an absent-value default from checked-in launch,
  Compose, runtime-eval, fixture, documentation, and test contracts before
  deriving one from the module, directory, or binary name. Never replace a
  repository-owned service default with a generic or shortened name. Prefer
  `deployment.environment.name`, `cloud.region`,
  `cloud.platform`, `container.image.name`, and `container.image.tags`; treat
  legacy aliases as existing inputs, not new duplicate attributes.
- Inventory the application logging stack and every stdout, file, platform,
  OTLP, and bridge path. Classify it as `local-otlp-default`,
  `explicitly-disabled`, `operator-owned`, `correlation-only`, or
  `unsupported-stack`.
- For existing audit scope, map each selected finding to its planned change and
  scenario IDs. A proof-only row may need no code change; do not invent one.

Before editing, state together: target executable, runtime shape and probe,
service name and environment source, existing-vs-new provider topology,
application-log classification, selected IDs and audit/selection binding when
present, changed consumer contracts, validation command, and scenario plan.
For incident or GenAI scope, also state the loaded reference, owned surfaces,
required signals, and remaining external owners.

## 2. Implement The Selected Baseline

Use the one detected-language guide for exact patterns. Apply
auto-instrumentation first, then only approved custom signals.

### Ownership and executable boundary

- Initialize each signal provider once per process in a separate telemetry
  setup file owned by the executable. Extend an existing provider rather than
  racing to register a second global provider.
- Keep importable libraries free of unconditional SDK/provider registration.
  Library handlers may propagate context and add request-local telemetry, but
  the executable entrypoint owns setup, outer framework wrapping, and shutdown.
- Reuse the actual startup command. Python must wire an explicit setup module;
  Node must preload before app imports; Java normally uses the agent; Go must
  call setup and wrap the handler from `cmd/.../main` or its equivalent.
- Obtain tracers/meters and create instruments during setup, not in hot paths.
  Use official OTel packages, except a library-maintained integration where no
  official package exists. Do not move business functions between files.
- Merge app resource defaults only for absent keys. Preserve
  `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`, safe consumer aliases, and
  one shared resource identity across traces, metrics, and logs.
- Resolve endpoint, protocol, and path independently per signal. Pair gRPC
  with its receiver and HTTP/protobuf with `/v1/traces`, `/v1/metrics`, or
  `/v1/logs`. Prove each configured signal separately.

### HTTP and errors

- Instrument the outermost executable HTTP server boundary so it emits server
  spans and request-duration metrics. For Go stdlib HTTP this means
  `otelhttp.NewHandler` wraps the real handler in the executable, not a library
  constructor. Router middleware sits inside it when route-pattern spans are
  needed. Prove low-cardinality route patterns and no duplicate server spans.
- Prefer `http.server.request.duration`; accept an older alternative only with
  runtime evidence. Use short local metric export interval/timeout defaults
  from the language guide so short checks flush.
- Record exceptions and set span status ERROR on failed custom operations.
  Keep span names and metric dimensions low-cardinality.
- Before adding a custom outcome counter/histogram inside an auto-instrumented
  HTTP, RPC, database, or messaging call, use its standard RED attributes or a
  supported per-call metric-attribute hook when those distinguish the outcome.
  Add a dedicated metric when no call exists or the standard attributes and
  language hooks cannot represent the detector-relevant distinction.

### Default Local Application Log Export

For a supported detected Python, Node, Java, or Go logging stack, local
Observer OTLP application-log export is part of the standard baseline:

- A request that excludes custom business spans limits span work only; it is
  not a log-export opt-out.
- Export locally only when `OTEL_LOGS_EXPORTER` is absent/`otlp` and the
  signal-specific logs endpoint is absent or exactly the detected local
  Observer receiver. Host default is `http://localhost:4318/v1/logs`; keep
  checked-in container URLs. Never infer locality from hostname syntax.
- `OTEL_LOGS_EXPORTER=none` disables the added local log path. Any other explicit exporter is
  operator-owned; add no local provider, exporter, or bridge and do not treat
  the environment value alone as proof that its pipeline works.
- A non-local endpoint on the absent/`otlp` branch is a boundary conflict:
  fail closed before constructing the local provider/bridge and report it.
- The Obstudio-owned local exporter must receive no cloud credential or auth
  header. Move generic direct-cloud endpoints/headers to trace- and
  metric-specific variables and remove the generic values. Do not pass
  `OTEL_EXPORTER_OTLP_LOGS_HEADERS` into the default local Observer exporter;
  an explicit logs header makes that path operator-owned and must be resolved
  or proven separately. Obstudio-to-Splunk cloud forwarding is traces and
  metrics only.
- Use one official bridge matching the detected logger, one LoggerProvider,
  exactly one bridge/export path, and one shutdown path. Preserve every existing
  console/file/platform sink and prevent duplicate bridge/export paths.
- Pass the active request context to application logging. Preserve fixture,
  documentation, and test contracts for exact log body/category, severity,
  and default `service.name`; do not replace a service-specific expectation
  with a generic example value. Preserve every distinct existing lifecycle-log
  contract as well: a shutdown/startup warning is not a duplicate of the
  request warning, and it needs trace/span IDs only if it runs inside an active
  span. Do not invent, remove, merge, or rename log bodies to manufacture proof.
- Apply privacy checks to the final pipeline, including formatters, adapters,
  access logs, MDC/context, and exception rendering. Do not emit raw request,
  user, tenant, session, URL, payload, secret, exception-text, or traceback
  values unless policy explicitly permits them.
- Focused and full-runtime proof must show the exact sanitized body/category,
  severity, shared resource identity, nonempty trace/span IDs inside an active
  request span, the preserved original sink, exactly one OTLP record per call,
  a flushed final record, and zero records under `none`. A config diff or
  stdout correlation fields alone are not OTLP export proof.

Follow the detected-language guide for bridge APIs, shutdown order, provider
reconciliation, and tests. If the stack cannot fan out safely, report
`unsupported-stack`; do not remove an existing sink to force coverage.

## 3. Conditional Custom Work

### Targeted signal

If the user requested one specific custom signal and OTel is already
initialized, preserve the existing setup and add only that signal. A canonical
selection still requires every selected ID and dependency; it cannot be
narrowed to one phrase from the request.

After a direct no-audit standard baseline, ask whether the user wants custom
spans or metrics. If yes, stop and route through `$otel-audit` first. Skip this
question when selected audit scope, incident-readiness scope, GenAI scope, or a
specific custom request already supplies approval.

### Incident readiness

When applicable, follow `../references/incident-readiness.md` in full. Map each
selected readiness gap to its owning code, exact low-cardinality signal,
scenario, and `MTTD-improving`, `localization-only`, external-owner, or
uncovered result. Do not call a row working while a required signal is absent,
only proposed, or backed by static/registration proof. For Go changes touching
goroutines, channels, queues, async persistence/indexing, eviction, or
callbacks, run `go test -race` for every changed package or record the exact
toolchain blocker.

### GenAI readiness

When applicable, follow `../references/genai-readiness.md` in full. Reconcile
all selected app-owned surfaces with its semconv closure matrix. Choose one
canonical GenAI span source per logical operation; configure suppression before
preload/bootstrap; preserve stable workflow/agent names and correct parent
context; add real model-call lifecycle spans rather than workflow-only usage;
keep content opt-in and metric dimensions bounded; and retain every incomplete
required token/context, tool, retrieval, memory, evaluation, cost, or
model/config signal in `remaining_signals`. `Remaining signals: none` is valid
only when every required signal is implemented, proven, or owner-mapped.

## 4. Validate And Verify

Follow `./references/project-runtime-validation.md` and keep one validation ledger keyed by
gate and relevant inputs. Run each locally safe project-configured gate after
the last relevant edit:

1. runtime probe and `git diff --check` plus syntax/config parsing;
2. compile, typecheck, or import every affected application module;
3. the narrowest tests that execute changed code;
4. in-memory or repo-native signal assertions for each changed call site and
   explicit absence proof for removed signals; and
5. a broader build/test only when shared wiring or manifests warrant it.

Confirm test filters matched. Preserve a passing gate until one of its inputs
changes; after repair, rerun only the failed and dependent invalidated gates,
never a passing gate merely for fresher report evidence. Do not substitute static source checks for executable
telemetry proof when a practical app-code seam exists. If the configured
runtime/dependency is unavailable, record the exact prerequisite and use
`Blocked` or `Not proven`; never claim verification.

For canonical scope, apply `$otel-verify` against the same bound selection
unless the user opts out or a prerequisite blocks it. Resolve only
`../otel-verify/SKILL.md` from the loaded skill directory; never search an
absolute or user-global skill location. If absent, record it unavailable. On
the direct no-audit baseline, do not load
`$otel-verify`: run inline project and applicable full-runtime proof, and record
standalone `$otel-verify` as `not applicable (no canonical audit/selection)`.
When a claim depends on real startup behavior, load and attempt
`../references/full-runtime-acceptance.md` without asking if the repo has a
safe local profile. “Not run” or “no collector” alone is not a blocker. Record
the executed command/result or the unavailable runtime, listener, dependency,
credential, or fixture. Do not finalize while a safe required profile exists
but has not been attempted.

## 5. Reports And Handoff

Always write `.observe/otel-instrumentation.md` with the exact reader order and
closure rules from the selected report-flow sections. It must include
`## Signals Changed`, `## Audit Gap Closure`, validation evidence, verification
handoff/results, remaining gaps, and next steps. `Signals Changed` is the
implementation-change inventory: list exact added, modified, removed, and
unchanged traces, metrics, logs, config, and dependencies. Claim removal only
when the prior report or Git diff proves it.

With canonical scope, use `./references/json-approval-handoff.md` to write and validate
`.observe/otel-instrumentation.json`, render
`.observe/otel-instrumentation.html`, and project every dependency-closed
selected finding exactly once. Keep unselected findings out. Use one Audit Gap
Closure row per selected finding and derive the report result from all closure
rows. Include `## GenAI Readiness Closure` only when the source audit declares
GenAI ownership; never invent it on the direct baseline path.

After verification, refresh the instrumentation HTML with the bound verify
overlay. Leave `.observe/otel.html` audit-only. Use the render command's
returned loopback links for both `otel-instrumentation.html` and `otel.html`.
Keep Markdown and JSON report links as absolute local paths, and do not open
either report automatically. If canonical JSON is absent, write/link only the
technical Markdown baseline report and do not claim audit, selection, JSON, or
HTML artifacts. In that report, record source audit and selected scope as
`not applicable (direct baseline)`. On the permitted direct baseline
  path, link only the absolute `.observe/otel-instrumentation.md` report.

Validate artifacts with their validator or targeted heading/status checks. Do
not reread a complete report solely to compose the final response or duplicate
the detailed command ledger across report sections.

The final response must separate files changed from proven outcomes and state:
selected runtime; compile/import and focused-test results; verification result
or exact blocker; service-name, environment, and per-signal endpoint settings;
expected automatic spans/metrics; application-log classification, bridge,
preserved sinks, opt-out, duplicate-prevention and runtime proof; added,
modified, removed, and unchanged signals; selected closure counts; and every
remaining incident/GenAI owner or signal. Never say complete, working, or
verified when a mandatory gate failed, was blocked, or did not run.

If verified metric evidence exists and the user requested alerting, dashboards,
detectors, or Splunk configuration, invoke or apply `$splunk-configure` and
include its output/verification status.

## 6. VS Code Debugging

If `.vscode/launch.json` exists, update at least one relevant configuration or
stop and explain why. Preserve operator-owned settings and add missing safe
local defaults:

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`
- `OTEL_LOGS_EXPORTER=otlp` only on the eligible local branch
- `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4318/v1/logs` only on that
  same branch
- `OTEL_METRIC_EXPORT_INTERVAL=1000`
- `OTEL_BSP_SCHEDULE_DELAY=100`

Do not add local log settings over `none`, another exporter, a non-local logs
endpoint, or an explicit logs header. Report the configuration and whether
each value was added or already present. If the file is absent, report exactly:
`No .vscode/launch.json found; Step 6 skipped.`

## Credential Safety And Scope

- Before writing secrets to an env file, ensure `.env` is ignored. Put only
  safe placeholders in `.env.example` and scan tracked config for real tokens.
- Existing apps: add only missing selected coverage. New apps: fit the full
  baseline into their current runtime shape. Libraries: provide opt-in setup;
  never initialize an SDK on import.
- Do not auto-publish dashboards, detectors, telemetry, or credentials. This
  skill changes the scoped repository and writes local `.observe/` artifacts;
  external mutation requires the appropriate downstream workflow and approval.
