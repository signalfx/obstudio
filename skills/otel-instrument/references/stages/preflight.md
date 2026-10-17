### 1. Preflight

Before editing anything, ground the plan with repo evidence:

#### Canonical Audit And Selection Gate

When `.observe/otel-audit.json` exists, treat it as the canonical audit.
Executable scope may come from a selected-audit copy's `review_selection`,
from a materialized `.observe/otel-selection.json`, or from exact IDs supplied
in the current request; when none are present and the user asks for bare or
broad instrumentation, use deterministic `select --all`. `.observe/otel.html`
is the audit and scope-planning surface. Never open or read an audit Markdown
report. Before any application-code,
dependency, runtime-config, or test edit, read and follow
`./references/json-approval-handoff.md`. Do not proceed without a validated,
nonempty executable selection. A valid answer-only handoff persists
`decision_answers` but authorizes no code edits.
Selection precedence is current-request exact `--ids`, then an existing or
embedded repository selection, then an explicitly supplied saved-audit
candidate, then an automatically adopted saved audit only when no repository
selection exists, and finally bare/broad `select --all`. Unless current-request
`--ids` already wrote a fresh selection, run the shared `adopt-selection` helper
as an idempotent preflight step before reporting a missing selection. If the
helper prints `PASS:` or `wrote`, immediately run `validate-flow` and continue
the same `$otel-instrument` run; do not ask the user to move a download, save
again, or rerun instrumentation. If no saved selection exists and the request is
bare/broad, run `select --all`; if it prints manual-decision options, stop
before edits and present those exact `--decision OTEL-###=option-id` choices.
Never choose between mutually exclusive telemetry owners or paths. Stop before
edits only when the audit is invalid, stale, not broad enough to imply all
eligible work, or the bound/created selection has empty `approved_ids`.
Implement exactly the dependency-closed selected IDs.
Bind `.observe/otel-instrumentation.json` to the entire normalized selection
with `selection_sha256`, not only to its audit and executable IDs. This digest
includes `decision_answers` and any schema-v3 `ao_target`; changing an answer
or AO target invalidates older
instrumentation even when `approved_ids` is unchanged.
When no canonical audit exists, a direct request for the standard
auto-instrumentation and default-local-log baseline may proceed after this
preflight without fabricating audit IDs or selection artifacts. Keep that
no-audit path limited to the standard baseline: stop before custom signals,
incident-readiness or GenAI work, or any request that needs finding-level scope,
and ask the user to run `$otel-audit` first. Never infer scope from generated
Markdown reports.

- Confirm the language and framework from actual dependency or source files
- Resolve the latest compatible published library release set from official
  package metadata, compatibility documentation and the project resolver.
  Check runtime, peer dependencies, SDK/exporter/bridge APIs and existing
  constraints together; do not independently mix latest packages or force an
  unrelated upgrade. Keep fixed library release numbers out of skill recipes.
  Record the resolved versions, metadata source/date and tested signatures in
  the run report, then persist the approved dependency set in the app lockfile.
- Check current Splunk AO SDK support for the application's actual language
  separately from native OTel support. Without a compatible supported AO SDK,
  use that language's public OTel libraries/instrumentation and apply the entire
  applicable Required GenAI Coverage Profile, including Splunk AO/Galileo content
  mappings, known parameters, correct kinds and complete trace trees. Follow the
  shared GenAI selection rule; AO SDK absence is not a blocker, permission to
  omit semantics, or a reason to install a Python sidecar. Preserve existing
  providers/exporters and keep selected resource/routing work SDK-free.
- Read `./references/project-runtime-validation.md`, inventory the repository's
  configured runtime and build/test commands, and select the locally available
  project runtime before editing. Do not use the shell's default runtime when
  wrappers, toolchain files, manifests, CI, or existing project environments
  select another one.
- Confirm the target process from the repo's real start surface: `docker-compose.yml`, Kubernetes manifests, `package.json` scripts, `Makefile`, `Procfile`, PM2 configs, Supervisor configs, systemd units, launchd plists, PowerShell scripts, or a plain shell command
- Confirm existing telemetry indicators or record `none found`
- Resolve each local OTLP receiver endpoint with the shared precedence:
  signal-specific OTel config, compatible generic OTel config, advertised
  Obstudio status when available, checked-in receiver ports and runtime
  topology, then the conventional local fallback. Record the selected source,
  protocol, path, and port. Preserve configured non-default ports exactly.
- Inventory existing telemetry consumer contracts before editing: metric names
  and dimensions, span names and attributes, resource attributes, log
  correlation fields, exporter settings, checked-in dashboards/detectors,
  entity-mapping resources, and query/test fixtures. Adding OTel semantic
  fields is encouraged, but do not silently remove, rename, or change the
  meaning/cardinality of existing low-cardinality fields that consumers may
  use. Preserve safe legacy aliases by default, replace unsafe high-cardinality
  fields such as raw URL paths with bounded alternatives, and record every
  preserved, breaking, or review-needed consumer contract in
  `telemetry_changes[].consumer_compatibility`.
- Build a provider/exporter topology per signal before choosing SDK or preload
  wiring. Find explicit and lazy provider construction, global registration,
  exporters, resources, no-op branches, and shutdown paths, then prove
  reachability from the selected process. For Python, run
  `../otel-audit/scripts/scan_python_otel_topology.py <service-root>` when that
  bundled scanner is available and reconcile its candidates with source.
  Existing ownership of any one signal makes this an incremental integration;
  it does not prove that the other signals are configured.
- Inventory the application logging stack and every stdout, stderr, file,
  platform, and existing OTLP sink. For a supported Python, Node.js, Java, or
  Go logging stack, local Splunk Observability Studio OTLP log export is part of the default
  Splunk Observability Studio baseline only when the exporter is absent or `otlp` and the logs
  endpoint is absent or exactly the detected local Splunk Observability Studio receiver. Treat
  `OTEL_LOGS_EXPORTER=none` as an explicit opt-out, and preserve every other
  explicit exporter as operator-owned without validating or supplementing its
  endpoint. An explicit non-local logs endpoint with an absent or `otlp`
  exporter is an operator-owned boundary conflict: do not construct or enable
  a Splunk Observability Studio log provider, exporter, or bridge; fail closed and report the
  configuration for operator resolution. Plan one log provider, one exporter
  path, and one bridge; preserve existing stdout/file sinks and identify any
  duplicate bridge before editing.
- Apply that log baseline to direct instrumentation requests even when no
  canonical audit exists. A request that excludes custom business spans limits
  span work only; it is not a log-export opt-out. Only the explicit exporter,
  endpoint, and supported-stack conditions above may suppress the default local
  log pipeline.
- In the normal generated launch profile, explicitly set
  `OTEL_LOGS_EXPORTER=otlp` with the resolved local Studio logs endpoint and
  matching protocol, alongside trace and metric export. Do not generate `none`
  as the default or use an unrequested log-disable override to make startup or
  verification pass. Honor a real explicit user/operator opt-out separately;
  SDK `@log` GenAI spans and stdout correlation do not replace OTLP LogRecords.
  Verify application log receipt in Studio as well as traces and metrics.
- When `.observe/otel-audit.json` exists, use only the validated selected
  findings and their referenced `verification.scenarios` and environments as
  the implementation and validation plan. Preserve every stable finding,
  scenario, and environment ID. Keep each `proof_level`; do not downgrade a
  `full runtime` scenario to focused call-site proof.
- Keep selected Splunk Agent Observability configuration work in the same
  dependency-closed selected-work queue as OTel work. Do not infer scope from
  a separate AO section or create a second selection ledger. The implemented
  application or deployment uses the selected destination mode. Preserve
  configured supported AO APIs, operator destinations, and direct-cloud
  requests. When AO destination settings are absent, default the local route
  to an available cloud-compatible Studio gateway. Its absence must not block
  source instrumentation, SDK imports, local tests, or implementation of the
  supported resource-creation branch. For existing non-AO applications, use
  SDK-free resource APIs and the existing exporter's trace-specific headers
  under the shared AO reference; do not introduce a vendor SDK dependency,
  replacement provider or second AO export path. For an SDK-owned path, use
  normal AO SDK resource calls and per-request routing, not a Studio-specific application adapter or
  global destination registration. Local receiver receipt is not cloud proof.
  Resolve absent AO settings independently of any existing OTel endpoint and
  provide the Studio-only example profile described in
  `../references/splunk-agent-observability.md`. Preserve explicit active
  destinations and prove mode isolation, resource-before-export ordering,
  and resource-resolution failure without live cloud credentials.
  Consume supplied project/Agent Stream names or IDs and reuse-only behavior
  from the validated selection's `ao_target`. If absent, preserve the
  application's configured target; otherwise use the audit's disclosed stable
  service-derived names and bind them through `select` before implementation.
  Do not silently skip selected AO work when names are blank. Follow the
  shared AO reference's Idempotent Resource Provisioning contract: reuse exact
  existing resources, create missing selected named resources, and recover
  duplicate races through bounded exact relookup. A resource input changes
  the selection digest but never adds unselected findings.
  Treat blank audit resource fields as an env/config fallback. Read the same
  profile the real application launch uses, including its existing native AO
  aliases. Supported SDK selectors are `SPLUNK_AO_PROJECT` or
  `SPLUNK_AO_PROJECT_ID`, and `SPLUNK_AO_AGENT_STREAM` or
  `SPLUNK_AO_AGENT_STREAM_ID`; supplied selection values override those
  resource settings. Apply fallback independently to each resource: preserve
  every configured selector and fill only a missing project or stream selector
  with its audit-disclosed stable name. For example, keep an existing project
  ID while adding the disclosed stream name. Create or update that launch
  profile with those missing values and mirror safe values in its example
  env file. Preserve
  unrelated OTel settings, credentials, and the selected destination; do not
  overwrite the env file from a template. Materialize the effective target in
  the selection before provisioning. The bundled Python helper reads omitted
  selectors from the process environment; load the env profile through the
  project's runner, such as `uv run --env-file .env`, or pass existing
  application-native alias values as explicit helper arguments. Do not add a
  new dotenv parser or gateway-specific config loader to application code.
  Validate that the actual launch reads the persisted target, and record its
  source as supplied input, existing env, or disclosed default. No selected
  AO work means no AO env additions or resource creation.
- Detect incident-readiness surfaces. Search source and configuration for
  user-visible workflows, dependency clients, background jobs, queues/streams,
  data freshness, input complexity, synthetic/canary checks, auth/edge paths,
  capacity limits, and release/config context. When any are present or when the
  user asks for faster incident detection/localization, load
  `../references/incident-readiness.md`.
- When incidents, postmortems, tickets, alerts, or failure examples are supplied,
  use Incident-Evidence Mode from `../references/incident-readiness.md`: map
  each failure mechanism to the owning code or platform surface and classify
  the proposed signal as MTTD-improving, localization-only, or still uncovered
  before editing.
- Detect GenAI/LLM ownership. Search dependencies, config, and source for
  provider clients, model gateways, agent/workflow orchestration, tool/function
  dispatch, MCP when present, retrieval/RAG, model/deployment config, fallback,
  token usage, prompt/response assembly, AI-derived data jobs, AI-path
  synthetic/canary checks, and usage logging. When present, load
  `../references/genai-readiness.md`.
  Follow its GenAI Semconv Source Contract before editing: reconcile detected
  AI surfaces with official semconv docs when available, record
  live-or-snapshot provenance, and build a semconv closure matrix.
  Apply GenAI Instrumentation Selection and the Required GenAI Coverage
  Profile. Only a target runtime with no existing telemetry instrumentation is
  fresh; generic OTel, metrics-only, logs-only and active export-only pipelines
  stay incremental. Read `../references/splunk-agent-observability.md` for a fresh
  agent even without an existing SDK import: use supported Splunk AO
  span creators/framework integration when a compatible SDK exists for its
  language; otherwise select native OTel with the full applicable field profile.
  For a selected supported AO SDK, use the shared per-operation public
  OTel exception only for source-proven incompatible SDK boundaries. An
  export-only processor is not a creator. Preserve all existing producers,
  providers and exporters and fill only proven gaps. Record before/after
  operation and field inventories and prove no lost coverage or duplicate
  operation/export. Applicable safe content/vendor fields are required
  acceptance; a published Opt-In label or metadata-only span is not closure.
- When GenAI incidents, postmortems, tickets, alerts, or failure examples are
  part of the request, use GenAI incident-evidence mode from
  `../references/genai-readiness.md`: map each AI pathway failure mechanism to
  the owning provider/model gateway, workflow, tool/function execution or
  AI-owned session/stream including MCP when present, retrieval/RAG, streaming,
  token/context, prompt/response parser, safety/policy, AI-derived data,
  model/config rollout, or AI-owned state surface before editing.
- For Java projects, build a trace wiring inventory per `./references/languages/java.md` (Preflight section) and classify as `auto-only`, `custom-with-provider`, `custom-provider-external`, or `missing` before editing.
- Confirm the planned `service.name`, `service.version`, and environment source.
  Also record available low-cardinality region, platform, image/artifact,
  config, and rollout sources. Prefer existing OTel semantic-convention or
  platform resource attribute names, including `deployment.environment.name`,
  `cloud.region`, `cloud.platform`, `container.image.name`, and
  `container.image.tags`. Treat `deployment.environment`,
  `deployment.region`, `deployment.platform`, and `container.image.tag` as
  legacy or custom input aliases only, not names to newly emit or reasons to
  duplicate the standard attributes.
- Distinguish between application repos and tooling repos such as CLIs, MCP servers, workers, libraries, installers, and build tools. Instrument the executable path users or operators actually run today. Do not invent a web app, Docker path, or entrypoint that is not present.
- If the repo has multiple runnable surfaces, instrument the one the user actually cares about; otherwise ask which one matters
- If the repo is primarily tooling or library code and no runnable surface is obvious, stop and ask instead of inventing an app shell
- Ask one focused clarifying question only if the target process or runtime shape is still ambiguous after checking the repo

Do not proceed until you can state all of these clearly:

- target process
- runtime shape
- `service.name`
- environment dimension
- incremental addition vs new scaffold
- selected project runtime, probe command, and affected-module validation
  command, or the exact prerequisite that makes validation unavailable
- audit gap closure plan: rows in scope now, rows deferred by mode or explicit
  user scope, and the scenario IDs that will prove each in-scope row
- canonical audit ID and SHA-256, dependency-closed selected finding IDs
  (`approved_ids`) in audit order, and the validated selection path when
  `.observe/otel-audit.json` exists
- for Java, trace source of truth (see `./references/languages/java.md` Preflight section)
- incident-readiness surfaces and the workflow, dependency, input complexity,
  freshness, backpressure, synthetic/canary, auth/edge, capacity, and
  release/config signals to add or prove when the repo owns those surfaces
- incident-evidence coverage when failure examples are supplied: failure
  mechanism, owner, code surface, signal to add or prove, expected MTTD or
  localization impact, and remaining external owner
- GenAI workflow surfaces and the GenAI semantic-convention plus service-owned
  readiness signals to add, when the repo owns LLM, agent, tool/function, MCP,
  retrieval, streaming, model/config, token/context, prompt/response,
  safety/policy, AI-derived data, memory/context, evaluation quality, content
  capture, framework bridge, app-computed cost, or AI-owned state code
- GenAI incident coverage when GenAI incidents or AI pathway failures are
  supplied: failure mechanism, provider/model/tool/retrieval/config/prompt/
  AI-derived-data owner, signal to add or prove, expected MTTD/localization
  impact, and remaining non-code or dependency owner

State these preflight values together in one explicit progress note before the
first file edit. Do not defer `service.name` or environment ownership to the
final report.

