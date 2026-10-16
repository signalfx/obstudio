### Step 1 -- Repository Discovery

Scan the repository to determine language, framework, and existing instrumentation.

1. Detect primary language and framework:
   - Go: `go.mod`
   - Python: `requirements.txt`, `pyproject.toml`, `setup.py`
   - Node.js: `package.json`
   - Java: `pom.xml`, `build.gradle`
   - Rust: `Cargo.toml`
   - .NET: `*.csproj`, `*.sln`
2. Identify entry points (`main`, `cmd/`, `app.py`, `index.ts`, etc.)
3. Enumerate all HTTP routes with method and path pattern (e.g. `GET /tasks`, `POST /tasks`, `GET /tasks/{id}`). List them explicitly in the report.
4. Use the Auto-Instrumentation Library Map below to identify which packages
  should be present for each detected dependency.
5. Detect incident-readiness ownership: user-visible workflows, dependency
  calls, background processing, queues/streams, data freshness, auth/edge
  paths, capacity limits, and release/config context. When any are present or
  when the user asks for faster incident detection/localization, load
  `../references/incident-readiness.md`. When incidents, postmortems, tickets,
  alerts, or failure examples are supplied, use its Incident-Evidence Mode and
  map each failure mechanism to its owning code or platform surface before
  scoring coverage.
6. Detect GenAI/LLM ownership: provider clients/model gateways, agents or
  workflows, tool/function dispatch, MCP when present, retrieval/RAG,
  model/deployment config, model/config compatibility,
  expected-vs-running model/config state, fallback/readiness checks, token
  accounting, call counts, prompt/response assembly, AI-derived data jobs,
  AI-path synthetic/canary checks, or usage logging. When any are present, load
  `../references/genai-readiness.md`.
  Follow its GenAI Semconv Source Contract before scoring GenAI coverage:
  reconcile detected AI surfaces with official semconv docs when available,
  record live-or-snapshot provenance, and build a semconv closure matrix.
  Apply GenAI Instrumentation Selection and the Required GenAI Coverage
  Profile: only a runtime with no existing telemetry instrumentation and a
  compatible supported AO SDK for its language defaults to Splunk AO span
  creation. When no compatible AO SDK is available, plan that language's native
  OTel libraries and the same applicable GenAI/vendor coverage; record the
  current support evidence and actionable native gaps rather than blocking
  instrumentation on AO SDK availability. Preserve and enrich existing OTel/Galileo/AO
  producers, providers and exporters, including generic spans, metrics-only
  and logs-only pipelines. Missing GenAI coverage does not make them fresh. Read
  `../references/splunk-agent-observability.md` for fresh-agent SDK APIs and
  current official examples when the fresh or existing AO producer path applies.
  Before prescribing creators on that Python Splunk AO path,
  complete its mandatory per-function producer decision gate for every actual
  agent/model/tool/retrieval function. Keep native SDK `@log` versus justified
  application-owned function-decorator choices consistent across findings;
  record proposed patterns and probe acceptance without executing them.
  In correlation proposals, keep absent optional IDs absent. Distinguish a
  source-backed application execution ID from a provider-supplied tool-call ID;
  do not propose telemetry-only IDs or retrofit them into an earlier provider
  response to make a join pass. Include
  the intended Splunk AO runtime in the AO assessment below when that default
  producer is selected; absence of an installed SDK does not exclude its
  source-backed project, Agent Stream, or routing configuration gaps. Include
  applicable redacted inputs/outputs and vendor fields in executable findings,
  acceptance and expected telemetry; published Opt-In does not make them
  optional for this profile. Record the actual producer and field availability.
  When GenAI incidents, postmortems, alerts, tickets, or failure examples are
  part of the request, use GenAI incident-evidence mode and map each failure
  as `incident class -> failure mechanism -> repo/service owner -> code surface ->`
  required signal before scoring whether instrumentation is MTTD-improving or
  localization-only. Map each failure
  mechanism to provider/model gateway, workflow, tool/function execution or
  AI-owned session/stream including MCP when present, retrieval/RAG, streaming,
  token/context, prompt/response parser, safety/policy, AI-derived data,
  model/config rollout, or AI-owned cache/session evidence.
  When the user asks about Splunk Agent Observability coverage, routing, or
  product resources, or the repository contains Agent Observability project,
  Agent Stream, dataset, prompt, annotation, evaluator, integration, routing
  configuration, or any `splunk_ao` dependency/import, also read
  `../references/splunk-agent-observability.md`.
  Apply the Splunk AO Runtime Coverage Contract below to every in-scope agent
  runtime, not only to files that import the SDK. An evaluation-only import
  must not hide an interactive runtime from this assessment.
  Before scoring AO routing, record a source-backed compatibility decision in
  canonical Audit Evidence and the affected runtime readiness/finding rows:
  classify the selected resource API/authentication and existing exporter's
  per-request trace routing separately as `supported`,
  `unsupported` (name the missing contract), or `unverified` (name the exact
  package/runtime evidence unavailable after inspection). Do not defer this
  classification to a future acceptance test. Separately classify fresh cloud
  Agent Stream receipt; source capability, local receipt, and an upstream
  acknowledgement do not prove it. If no local gateway was inspected, name
  Splunk Observability Studio as the preferred local AO gateway candidate and
  mark both its availability and concrete endpoint `unverified`; never invent
  an address. Preserve an explicit operator or direct-cloud destination. When
  AO settings are absent, keep the routing gap independent of an existing
  ordinary OTLP endpoint and put the required exclusive Studio profile in the
  AO routing finding's `required_fix` and acceptance criteria: a
  `.env.studio.example` or repository-native named profile filled from an
  actually discovered same-namespace loopback API origin during instrumentation.
  For existing non-AO applications, plan SDK-free resource resolution and merge
  the target-supported project/stream headers into the existing trace exporter;
  preserve its endpoint/protocol and unrelated headers. Current Studio uses
  `projectid`/`logstreamid`; public standalone AO docs use
  `projectid`/`agentstreamid`. Do not prescribe a new SDK or second AO exporter.
  Require the SDK API/console/auth profile only when an SDK path is selected;
  isolate its inherited direct-cloud settings in that profile. Require real
  project/stream resolution before export. Describe missing wiring even when the gateway is currently
  unavailable; mark endpoint and delivery proof unverified instead of filling
  a guessed port or claiming it works.
7. Record exact evidence paths that should appear in the report:
  - Dependency manifest: `go.mod`, `package.json`, `pyproject.toml`, `pom.xml`, etc.
  - Process entry point: `main.go`, `cmd/.../main.go`, `app.py`, `app.js`, `TasksApplication.java`, etc.
  - Route source: router/controller files such as `TaskController.java`, `app.py`, `app.js`, or `kvstore/http.go`.
  - Traffic and readiness clients when they exercise a GenAI path: demo, load, eval, or replay scripts, plus AI-path synthetic or canary scripts such as `load_demo.py`,
    `smoke.py`, `scripts/check-*`, or `tests/e2e/*`.
  - Runtime/startup files when present: `Dockerfile`, `docker-compose.yml`, `Makefile`, `package.json` scripts, launch configs, worker files.
  Use complete repository-relative paths with an optional `:line`,
  `:start-end`, or comma-separated line selector. The HTML renderer links only
  exact existing in-repository files; do not shorten citations to basenames,
  use globs, or guess paths when the owning file can be named precisely.
8. Inventory project runtime and verification evidence without installing or
  changing anything:
  - wrappers and task runners such as `mvnw`, `gradlew`, Make, package scripts,
    tox/nox, Cargo, or solution test projects
  - toolchain/version files and manifest runtime requirements
  - lockfiles, CI test commands, devcontainer config, and existing test layout
  - locally safe compile/type/import/test commands implied by project config
  Record configured requirements, not the shell's accidental default runtime.
9. Make one explicit GenAI ownership decision from the completed source scan:
  - `Yes` when any provider/model, agent/workflow, tool/MCP, retrieval/RAG,
    memory/context, evaluation, prompt/response, model/config, token usage, or
    other AI-path surface is owned by the repository.
  - `No` only when the dependency and source scan finds none of those surfaces.
  Record the decision both as `**GenAI ownership detected:** Yes|No` near the
  report status and as an exact `GenAI ownership` row in `## Audit Evidence`.
  The two values must match.

