---
name: otel-audit
description: >-
  Scan a codebase for existing OpenTelemetry instrumentation and report
  on observability coverage gaps. Read-only -- does not modify code.
  Use when the user types $otel-audit, asks about observability gaps,
  wants to assess instrumentation coverage, says "what signals am I
  missing", "scan this service for observability", asks about
  "observability readiness", asks whether instrumentation can make incidents
  faster to detect or localize, asks whether GenAI/LLM workflows follow
  OpenTelemetry semantic conventions, or asks whether deployment, Helm, GitOps,
  Terraform, serverless, VM, container, dependency config, or runtime
  configuration supports observability. Do NOT use for implementing code
  changes -- use $otel-instrument instead.
metadata:
  author: otel-studio
  version: 0.6.1
  category: observability
---

# Audit -- Observability Coverage Scan

## Overview

Scan a service repository to detect its language, framework, dependencies,
and existing OpenTelemetry instrumentation. Report what is instrumented,
what is missing, and any anti-patterns. This skill is read-only -- no code
is modified.

## When to Use

- Assessing current instrumentation coverage before deciding whether to instrument
- Checking what auto-instrumentation is already wired up
- Identifying dependencies that lack matching OTel instrumentation
- Quick health check of an existing OTel setup
- Assessing whether API/workflow, dependency, data freshness, queue,
  auth/edge, capacity, and release/config signals can support incident
  detection and localization
- Assessing GenAI/LLM, agent, workflow, tool/function calling, retrieval/RAG,
  or model-gateway instrumentation against OpenTelemetry GenAI conventions
- Checking whether deployment/runtime configuration carries service name,
  environment, version, collector, health, capacity, rollout, and config context
- Checking whether deployment-owned dependency endpoints, regions, timeouts,
  retries, circuit breakers, or credential refs are discoverable

**When NOT to use:** If you want to add instrumentation, use `$otel-instrument`.

## Process

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
4. Use the Auto-Instrumentation Library Map below to identify which packages should be present for each detected dependency.
5. Detect incident-readiness ownership: user-visible workflows, dependency
  calls, background processing, queues/streams, data freshness, auth/edge
  paths, capacity limits, and release/config context. When present or when the
  user asks for faster incident detection/localization, load
  `../references/incident-readiness.md`.
6. Detect GenAI/LLM ownership: provider clients/model gateways, agents or
  workflows, tool/function/MCP dispatch, RAG/retrieval, model/deployment config,
  fallback/readiness checks, token accounting, call counts, or usage logging.
  When any are present, load `../references/genai-readiness.md`.
7. Detect deployment-context ownership. Search the current repo for runtime and
  deployment sources such as Docker Compose, Dockerfiles, systemd units, Procfiles,
  Helm charts, values files, Kustomize overlays, Kubernetes workloads, Argo CD,
  Flux, Terraform/Pulumi/CDK, ECS task definitions, serverless manifests, Nomad
  jobs, CI/CD release files, and deploy docs. If deployment context exists or the
  user provides deployment repo paths, load `../references/deployment-context-readiness.md`.
8. Resolve deployment references visible in inspected files. For example, follow
  Helm/helmfile value-file references, Argo CD/Flux source and value references,
  Terraform `helm_release.values` or tfvars, Kubernetes `configMapRef`/`secretRef`,
  Docker Compose `env_file`, systemd `EnvironmentFile`, serverless stage config,
  dependency endpoint/config references, and CI/CD chart/value path references
  when the target is present or supplied.
  If a referenced source is not available, pause before writing
  `.observe/otel.md` and ask once for its local path or URL. Name the referenced
  source from the inspected file, such as a chart path, values file, GitOps
  repo/path, IaC module, CI/CD template, environment file, ConfigMap, Secret,
  tfvars, stack config, or deployment pipeline. Do not treat this as optional
  report text; it is an interaction boundary. If the user provides paths,
  inspect them and continue. If the user says to continue without those sources,
  record them as `referenced but not inspected` and mark the affected deployment
  context as `unknown`, not `missing`.
9. If app code exists but production deployment sources are not discoverable,
  pause before writing `.observe/otel.md` and ask once for known chart, values,
  GitOps, IaC, CI/CD, or runtime repo paths. Ask for local paths or URLs and
  include examples such as `./chart`, `./values`, `./gitops`, `./terraform`,
  a Helm chart repo, an environment-values repo, or a deployment pipeline path.
  Do not treat this as optional report text; it is an interaction boundary.
  If the user provides paths, inspect them and continue. If the user says there
  are none, asks to continue app-code-only, or provides no paths after the ask,
  continue the app-code audit and mark deployment context as `unknown`, not
  `missing`.
10. Record exact evidence paths that should appear in the report:
  - Dependency manifest: `go.mod`, `package.json`, `pyproject.toml`, `pom.xml`, etc.
  - Process entry point: `main.go`, `cmd/.../main.go`, `app.py`, `app.js`, `TasksApplication.java`, etc.
  - Route source: router/controller files such as `TaskController.java`, `app.py`, `app.js`, or `kvstore/http.go`.
  - Runtime/startup files when present: `Dockerfile`, `docker-compose.yml`, `Makefile`, `package.json` scripts, launch configs, worker files.
  - Deployment/runtime files when present: `Chart.yaml`, `values*.yaml`,
    `kustomization.yaml`, Argo/Flux resources, Terraform/Pulumi/CDK files,
    task definitions, systemd units, serverless manifests, Nomad jobs, and CI/CD
    release files.
  - Dependency config sources when present: app config files, env var names,
    ConfigMap/Secret references, parameter-store refs, values/tfvars/stack
    config, service mesh or egress config, and gateway/route config.

### Step 2 -- Instrumentation Assessment

Check for existing OTel instrumentation and identify gaps. Inventory every
signal by type so the report can list them explicitly.

**SDK and configuration** -- search for:

- OTel SDK initialization files (`otel_setup.py`, `instrumentation.ts`, `otel.go`, etc.)
- OTel imports/dependencies (`opentelemetry`, `otel`, `otlp`, `go.opentelemetry.io`)
- Auto-instrumentation packages matching detected frameworks/clients
- `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT` in env files or configs

**Spans inventory** -- build a list of every span source:

- Auto-instrumentation packages that emit spans (check the "Signals" column in
the language reference). Enumerate every individual span name the package
produces -- one row per span. Never group spans with vague labels like
"HTTP server spans" or "gRPC server spans (all N RPCs)". For example,
`otelgrpc` on a server with methods `GetUser` and `ListUsers` produces spans
`/UserService/GetUser` and `/UserService/ListUsers` -- list each as its own
row.
- Custom span creation calls: `tracer.Start` / `span.End` (Go),
`tracer.start_as_current_span` / `tracer.start_span` (Python),
`tracer.startActiveSpan` / `tracer.startSpan` (Node.js),
`@WithSpan` / `Span.current()` (Java).
Record the span name and source file with line number.

**Metrics inventory** -- build a list of every metric source:

- Auto-instrumentation packages that emit metrics (check the "Signals" column).
Enumerate every individual metric name the package produces -- one row per
metric. Never group metrics with vague labels like "(+ related)" or
parenthetical summaries like "(goroutines, memory, GC)". For example,
`otelgrpc` emits `rpc.server.duration`, `rpc.server.request.size`,
`rpc.server.response.size`, `rpc.server.requests_per_rpc`, and
`rpc.server.responses_per_rpc` -- list each as its own row. Similarly,
`runtime.Start()` emits `process.runtime.go.goroutines`,
`process.runtime.go.mem.heap_alloc`, `process.runtime.go.gc.count`, etc. --
list each individually.
- Custom metric registrations: `meter.Int64Counter`, `meter.Float64Histogram`,
`meter.Int64ObservableGauge`, `meter.Int64UpDownCounter` (Go);
`meter.create_counter`, `meter.create_histogram`,
`meter.create_observable_gauge` (Python);
`meter.createCounter`, `meter.createHistogram`,
`meter.createObservableGauge` (Node.js).
Record the metric name and source file with line number.

**Logs inventory** -- build a list of OTel log integrations:

- OTel log bridge or SDK log packages (`opentelemetry-instrumentation-logging`
for Python, `@opentelemetry/instrumentation-winston` /
`@opentelemetry/instrumentation-pino` for Node.js).
- Trace-context injection into log records (`trace_id`, `span_id` fields).
- `span.AddEvent()` / `span.add_event()` calls used as structured log events.

**Dependencies without instrumentation** -- for each dependency detected in Step 1:

- Check if a matching auto-instrumentation package is installed
- Use the Auto-Instrumentation Library Map below as the checklist
- Flag any dependency that has an available auto-instrumentation package but is not instrumented

**RED signal assessment** -- for each RED dimension, determine status:

- **Rate:** Is there a metric or span source that enables request-count
derivation? (e.g. `http.server.request.duration` histogram counts, or
server spans from auto-instrumentation.)
Status: `covered` / `partial` / `missing`.

- **Errors:** Are span status codes set on failures? Is `recordException`
called? Do HTTP auto-instrumentation spans capture 5xx status?
Status: `covered` / `partial` / `missing`.
- **Duration:** Is there a histogram or span data that provides latency
percentiles? (e.g. `http.server.request.duration` histogram, or span
duration from auto-instrumentation.)
Status: `covered` / `partial` / `missing`.

**Incident readiness assessment** -- when incident-readiness evidence exists or
the user asks for faster incident detection/localization, use
`../references/incident-readiness.md` to check API/workflow, customer-impact,
dependency, freshness, backpressure, auth/edge, capacity, and release/config
signals. Add `## Incident Readiness` rows and `## Gaps` entries for missing
signals that would make incidents faster to detect, route, or localize. For
each gap, include the expected instrumentation action:
`add instrumentation`, `prove existing instrumentation`, or
`mark out of scope with owner`.

**GenAI readiness assessment** -- when GenAI/LLM evidence exists, use
`../references/genai-readiness.md` to check for baseline trace continuity,
OTel GenAI spans, semconv completeness, GenAI metrics, and privacy/cardinality
controls. Add `## GenAI Readiness` rows and `## Gaps` entries for missing
workflow, provider, model/config, tool, token pressure, retrieval, fallback, or
capacity signals. When the user asks for faster incident detection or
localization, identify which missing signals would make the issue easier to
detect, route, or localize. Do not mark a GenAI area complete just because one
representative signal exists; list every discovered app-owned gap separately so
`$otel-instrument` can add it, prove it, or owner-map it.

**Gap ledger contract** -- the audit output is a contract, not background context.
For every app-owned, provider-owned, platform-owned, or
already-covered readiness gap, create a structured ledger row with:
`gap_id`, `required_signals`, `owner`, `code_surface`, and
`acceptance_criteria`. Use stable IDs such as `G1`, `G2`, and split a gap when
required signals have different owners or acceptance criteria. Required signals
must be concrete signal names or signal intents, not vague area labels. For
example, a GenAI token/context pressure gap should name each required signal,
such as context budget percent, truncation rate, token-limit errors,
prompt/tool schema size, LLM-call count per turn, and tool-call count per turn.
Use owner values that map directly to the instrumentation result categories:
`App-owned + patchable`, `App-owned but unsafe/too large`,
`Provider/platform-owned`, or `Already covered`.

Status must be computed against every required signal in the ledger:

| Ledger result | Rule |
|---|---|
| `covered` | Every required signal is proven existing with source path and signal name. |
| `partial` | Some required signals exist, but remaining required signals are named. |
| `missing` | No required app-owned signal exists. |
| `owner-mapped` | The repo cannot accurately observe the signal and the provider/platform/deployment owner plus exact missing source is named. |

Do not collapse a partial gap into `covered` because one metric or span exists.
The ledger is the source of truth for `$otel-instrument` and
`$splunk-configure`.

**Deployment context assessment** -- when deployment/runtime sources are found
or supplied, use `../references/deployment-context-readiness.md` to identify
platform, source repo/path, runtime workload, and whether telemetry-critical
runtime settings exist. Add a `## Deployment Context` section and `## Gaps`
entries for missing service identity, environment, version, collector, health,
capacity, dependency config, rollout, or config signals. Use these status values:

- **covered** -- inspected deployment sources configure the signal.
- **partial** -- some runtime context exists, but key dimensions or health/capacity
  signals are missing.
- **missing** -- inspected deployment sources prove the signal is absent.
- **unknown** -- deployment sources were not discoverable or not provided.
  Include `referenced but not inspected` evidence when inspected deployment
  files point to another chart, values, GitOps, IaC, env, secret, or runtime
  config source that is not available in the workspace.

**Anti-patterns** -- flag any of these:

- Multiple SDK initializations in the same process
- Hardcoded OTLP endpoints instead of env vars
- Tracer/Meter created in hot paths instead of at startup
- High-cardinality attributes on metrics (user IDs, request IDs)
- Missing `recordException` in error handling paths
- Custom span names with variable segments (IDs, paths)
- Use of community or third-party OTel wrappers when an official OpenTelemetry package exists (e.g. `go.opentelemetry.io/contrib`, `@opentelemetry/`*, `opentelemetry-*`)

For partially instrumented Go services, explicitly check and report:

- hardcoded OTLP endpoints such as `collector.example.com`
- `otel.Tracer(...)` or `otel.Meter(...)` calls inside request handlers or loops
- high-cardinality span names such as `GetTask-{id}`
- missing `otel.SetTextMapPropagator(...)`
- missing `MeterProvider`, missing `service.name`, and missing provider shutdown/flush

### Step 3 -- Report

Write the report to `.observe/otel.md` inside the scanned service root (create
the `.observe/` directory if it does not exist). Also present a concise summary
in chat that references the file path.

Use this template for `.observe/otel.md`:

```
# Observability Report: {service-name}

**Language:** {language} | **Framework:** {framework} | **Date:** {YYYY-MM-DD}

## Evidence
- Manifest: {path}
- Entry point: {path}
- Route source: {path(s)}
- Runtime/startup: {path(s) or "none detected"}

## Routes

| Method | Path |
|--------|------|
| GET | /health |
| GET | /tasks |
| POST | /tasks |
| GET | /tasks/{id} |
| ... | ... |

## Current Instrumentation

### Spans

List every individual span name -- one row per span. Never group auto-
instrumented spans with vague labels like "HTTP server spans" or
"gRPC server spans (all N RPCs)".

| Name | Source | Type |
|------|--------|------|
| GET /tasks | otelhttp | auto |
| POST /tasks | otelhttp | auto |
| GET /tasks/{id} | otelhttp | auto |
| orders.process | orders/service.go:42 | custom |

If no span sources are found, write: "No spans detected."

### Metrics

List every individual metric name -- one row per metric. Never group auto-
instrumented metrics with vague labels like "(+ related)" or parenthetical
summaries.

| Name | Source | Type |
|------|--------|------|
| http.server.request.duration | otelhttp | auto |
| http.server.active_requests | otelhttp | auto |
| http.server.request.size | otelhttp | auto |
| http.server.response.size | otelhttp | auto |
| orders.processed.count | orders/metrics.go:15 | custom |

If no metric sources are found, write: "No metrics detected."

### Logs

| Integration | Source | Detail |
|-------------|--------|--------|
| trace-context injection | opentelemetry-instrumentation-logging | Injects trace_id/span_id into log records |
| span events | orders/service.go:55 | span.AddEvent("order.validated") |

If no OTel log integrations are found, write: "No OTel log instrumentation detected."

If no OTel packages or setup are found across all three signal types, include
the phrase: "OpenTelemetry instrumentation is missing."

## RED Signals

| Signal | Status | Detail |
|--------|--------|--------|
| Rate | {covered / partial / missing} | {which metric or span provides request counts, or what is missing} |
| Errors | {covered / partial / missing} | {which span status / recordException provides error visibility, or what is missing} |
| Duration | {covered / partial / missing} | {which histogram or span data provides latency percentiles, or what is missing} |

Status values:
- **covered** -- the signal is fully available from existing instrumentation.
- **partial** -- some data exists but key dimensions are missing (e.g. spans
  exist but no histogram for percentile breakdown).
- **missing** -- no data source provides this signal.

## Incident Readiness

Include when incident-readiness evidence exists or when the user asks for faster
incident detection/localization.

| Area | Status | Evidence | Gap | Detection/Localization Impact |
|------|--------|----------|-----|-------------------------------|
| API/workflow impact | {covered / partial / missing} | {route/workflow spans, latency/error/outcome metrics} | {missing workflow outcome, status code, error class, or latency metric} | {app-down vs degraded workflow remains slow to classify} |
| Dependencies | {covered / partial / missing} | {client spans/metrics by dependency and operation; endpoint health or target health metrics when available} | {missing retry, timeout, rate-limit, error class, endpoint health, target health, availability, or circuit-breaker state} | {root-cause dependency remains slow to localize} |
| Freshness/backpressure | {covered / partial / missing} | {lag, age, queue depth, consumer lag, dropped count} | {missing freshness lag, drop reason, oldest age, or paused consumer signal} | {stale data or backlog may not alert before user impact} |
| Auth/edge/capacity/release | {covered / partial / missing} | {auth/edge, CPU/memory/disk/concurrency capacity, desired-vs-healthy/readiness/startup/healthcheck, `service.version`, `deployment.environment`, `deployment.region`, `deployment.platform`, `container.image.tag`, artifact/config/rollout dimensions} | {missing auth failure class, disk or concurrency saturation, desired-vs-healthy, startup/readiness/healthcheck failure, traffic target health, or release/config context} | {impact cannot be correlated quickly to edge, capacity, platform health, or rollout changes} |

## GenAI Readiness

Include only when GenAI/LLM ownership evidence exists.

| Area | Status | Evidence | Gap | Detection/Localization Impact |
|------|--------|----------|-----|-------------------------------|
| Trace and semconv | {covered / partial / missing} | {workflow, agent, tool, chat, retrieval spans and gen_ai attrs} | {missing parent/child span, propagation, request model, provider, tool name, or error type} | {model/provider/tool issues remain slow to localize} |
| Metrics and detectors | {covered / partial / missing} | {gen_ai metrics or service-owned counters/histograms} | {missing latency/token/fanout/readiness/fallback metric} | {alert cannot fire before manual trace search} |
| Privacy/cardinality | {covered / partial / missing} | {content capture and attribute policy evidence} | {raw content or high-cardinality dimension risk} | {telemetry may be unsafe or unusable for alert grouping} |

## Deployment Context

Include when deployment/runtime sources exist, when the user supplies deployment
repo paths, or when the user asks about deployment-context readiness.

| Area | Status | Evidence | Gap |
|------|--------|----------|-----|
| Platform/source | {covered / partial / unknown} | {Kubernetes/Helm/GitOps/Terraform/Compose/ECS/Lambda/VM/etc. evidence} | {missing repo path or source detail} |
| Service identity | {covered / partial / missing / unknown} | {service.name / OTEL_SERVICE_NAME / resource attrs} | {missing identity signal} |
| Release/config | {covered / partial / missing / unknown} | {service.version, container.image.tag/artifact version, config version, rollout/canary id} | {missing release/config signal} |
| Dependency config | {covered / partial / missing / unknown} | {dependency endpoint alias, dependency type/name, timeout, retry, circuit breaker, provider region/deployment, config ref/version} | {missing dependency config source or referenced source detail} |
| Dependency health | {covered / partial / missing / unknown} | {endpoint health, target health, availability, error/timeout/rate-limit metrics, unhealthy target count} | {missing dependency health signal or platform metric source} |
| Health/capacity | {covered / partial / missing / unknown} | {startup/readiness/liveness checks, health checks, task health, restarts, desired vs healthy instances, CPU/memory/disk/concurrency/limits, throttles, quotas} | {missing health/capacity signal} |
| Export path | {covered / partial / missing / unknown} | {OTLP endpoint, collector sidecar/gateway, OTel Operator, env vars} | {missing export config} |

## Gap Ledger

This is the contract for `$otel-instrument` and `$splunk-configure`; do not
treat it as background context. Use the field names `gap_id`,
`required_signals`, `owner`, `code_surface`, and `acceptance_criteria` as the
handoff schema even though the table headers are human-readable.

| Gap ID | Status | Required Signals | Owner | Code Surface | Acceptance Criteria |
|--------|--------|------------------|-------|--------------|---------------------|
| G1 | {missing / partial / covered / owner-mapped} | {signal A; signal B; signal C} | {App-owned + patchable / App-owned but unsafe/too large / Provider/platform-owned / Already covered} | {file/path or referenced source} | {code + tests, proof path + signal name, or exact external owner/source} |
| ... | ... | ... | ... | ... | ... |

## Gaps
- {remaining non-RED gaps: missing auto-instrumentation packages, missing
  context propagation, missing OTLP exporter configuration, missing
  service.name resource, missing API/workflow impact, dependency endpoint
  health, freshness, backpressure, auth/edge, CPU/memory/disk capacity,
  desired-vs-healthy/readiness/startup/healthcheck, release/config, or GenAI
  signals, etc.}
- If no gaps remain, write: "No additional gaps detected."

## Anti-Patterns
- {any issues found, or "None detected"}

## Recommendation
- {actionable next step: "Run $otel-instrument to add auto-instrumentation
  for X, Y, Z" or "Instrumentation looks complete -- consider
  $otel-instrument for custom business metrics"}

---
*Generated by obstudio v0.6.1 otel-audit on {YYYY-MM-DD HH:MM UTC}*
```

Report requirements:

- If GenAI/LLM code is detected, include `## GenAI Readiness` after
  `## Incident Readiness` when that section applies, otherwise after
  `## RED Signals`; omit it otherwise.
- Keep GenAI readiness generic: no organization-specific service names,
  incident IDs, customer names, realms, or provider account names.
- Prefer OTel GenAI semconv. Treat missing `gen_ai.request.model` as a gap when
  the requested model is available.
- IDs for users, accounts, tenants, sessions, tasks, conversations, and traces
  may help trace drilldown, but must not be metric dimensions or detector
  group-by keys.
- If incident-readiness coverage is requested or detected, include
  `## Incident Readiness` after `## RED Signals` and before `## GenAI Readiness`
  when both sections apply.
- If deployment-context coverage is requested or detected, include
  `## Deployment Context` after the readiness sections and before `## Gaps`.
- Always include `## Gap Ledger` after readiness/deployment sections and before
  `## Gaps`. Every `## Gaps` bullet must map back to a Gap ID.
- Keep incident-readiness guidance generic: no organization-specific service
  names, incident IDs, customer names, realms, or product-specific workflow
  names.
- Treat missing workflow outcome, dependency endpoint health,
  freshness/backpressure, auth/edge, CPU/memory/disk/concurrency saturation,
  desired-vs-healthy/readiness/startup/healthcheck, and release/config
  correlation as gaps only when code or runtime evidence shows the service owns
  that surface.
- If instrumentation is incomplete, always include the exact token `$otel-instrument` in the recommendation.
- If OpenTelemetry is absent, include both words `OpenTelemetry` and `missing`.
- Name the concrete files that support findings; do not only refer to "the service" or "./service".
- For Node.js, mention `package.json` and the app entry point such as `app.js`.
- For Python, mention `pyproject.toml` or `requirements.txt`, the app file such as `app.py`, and runtime files such as `Dockerfile` or `docker-compose.yml` when present.
- For FastAPI/Celery services, mention the web app, worker file, Dockerfile, compose commands, FastAPI/ASGI coverage, Celery instrumentation, Redis instrumentation if Redis is present, and HTTP client instrumentation only when an HTTP client dependency is detected.
- For Java/Spring Boot, mention the Spring Boot entry point such as `TasksApplication.java`, controller files such as `TaskController.java`, and the Java agent recommendation.
- For Go multi-package services, name the process entry point such as `cmd/kvstore-server/main.go` and relevant library files. If filesystem persistence, background indexing, or LRU eviction exists, call those out explicitly.

**Chat summary:** After writing `.observe/otel.md`, present a brief summary in
chat that includes: RED signal statuses, count of gaps found, and the
recommendation line. End with: `Full report: .observe/otel.md`.

### Step 4 -- Verify Telemetry (optional)

After presenting the report, prompt the user:

> Would you like me to verify telemetry is flowing? This requires the Observer
> collector to be running locally.

Then wait for the user's answer.

- **If no**: done.
- **If yes**: run the verification:

1. **Check Observer availability:**
  ```
   curl -s http://localhost:3000/api/query/stats
  ```
   If this fails, tell the user the Observer is not reachable and how to start it.
2. **Clear stale data:**
  ```
   curl -s -X DELETE http://localhost:3000/api/data
  ```
3. **Start the app** with fast-flush settings:
  ```
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
   OTEL_SERVICE_NAME=<service-name>
   OTEL_BSP_SCHEDULE_DELAY=100
   OTEL_METRIC_EXPORT_INTERVAL=1000
  ```
4. **Exercise one happy-path endpoint** (e.g. `GET /health` or `GET /tasks`).
5. **Wait 3 seconds** for export, then check:
  ```
   GET /api/query/traces?serviceName=<service-name>
  ```
6. **Report results:**
  - Traces arrived: list service name, span count, root span name
  - No traces: suggest troubleshooting (wrong endpoint, missing SDK init, exporter misconfigured)
7. **Stop the app** after verification.

## Red Flags

- Fewer than expected auto-instrumentation packages for the detected dependencies
- SDK initialized but no auto-instrumentation packages installed
- OTel packages in dependencies but no SDK init file found
- Error handling code without span error status or recordException

## Auto-Instrumentation Library Map

Use these tables to check whether each detected dependency has a matching
auto-instrumentation package installed. Only flag gaps for dependencies that
appear in the project.

### Go

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `net/http` (stdlib) | `go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp` | spans + metrics |
| `gorilla/mux` | `go.opentelemetry.io/contrib/instrumentation/github.com/gorilla/mux/otelmux` | spans only |
| `go-chi/chi` | `go.opentelemetry.io/contrib/instrumentation/github.com/go-chi/chi/otelchi` | spans only |
| `gin-gonic/gin` | `go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin` | spans only |
| `google.golang.org/grpc` | `go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc` | spans + metrics |
| `database/sql` | `github.com/XSAM/otelsql` | spans only |
| `go-redis/redis` | `github.com/redis/go-redis/extra/redisotel` | spans only |
| `runtime` | `go.opentelemetry.io/contrib/instrumentation/runtime` | metrics only |
| `host` | `go.opentelemetry.io/contrib/instrumentation/host` | metrics only |
| `segmentio/kafka-go` | `go.opentelemetry.io/contrib/instrumentation/github.com/segmentio/kafka-go/otelsegmentio` | spans only |
| `aws-sdk-go-v2` | `go.opentelemetry.io/contrib/instrumentation/github.com/aws/aws-sdk-go-v2/otelaws` | spans only |

### Python

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `flask` | `opentelemetry-instrumentation-flask` | spans |
| `django` | `opentelemetry-instrumentation-django` | spans |
| `fastapi` / `starlette` | `opentelemetry-instrumentation-fastapi` | spans |
| `requests` | `opentelemetry-instrumentation-requests` | spans |
| `httpx` | `opentelemetry-instrumentation-httpx` | spans |
| `urllib3` | `opentelemetry-instrumentation-urllib3` | spans |
| `aiohttp` | `opentelemetry-instrumentation-aiohttp-client` | spans |
| `psycopg2` | `opentelemetry-instrumentation-psycopg2` | spans |
| `sqlalchemy` | `opentelemetry-instrumentation-sqlalchemy` | spans |
| `pymongo` | `opentelemetry-instrumentation-pymongo` | spans |
| `redis` | `opentelemetry-instrumentation-redis` | spans |
| `celery` | `opentelemetry-instrumentation-celery` | spans |
| `grpcio` | `opentelemetry-instrumentation-grpc` | spans |
| `kafka-python` / `confluent-kafka` | `opentelemetry-instrumentation-kafka-python` / `opentelemetry-instrumentation-confluent-kafka` | spans |
| `boto3` / `botocore` | `opentelemetry-instrumentation-botocore` | spans |
| `logging` (stdlib) | `opentelemetry-instrumentation-logging` | logs |

### Node.js

| Dependency | Auto-instrumentation Package | Signals |
|---|---|---|
| `express` | `@opentelemetry/instrumentation-express` | spans |
| `fastify` | `@opentelemetry/instrumentation-fastify` | spans |
| `koa` | `@opentelemetry/instrumentation-koa` | spans |
| `@nestjs/core` | `@opentelemetry/instrumentation-nestjs-core` | spans |
| `http` / `https` (stdlib) | `@opentelemetry/instrumentation-http` | spans |
| `pg` | `@opentelemetry/instrumentation-pg` | spans |
| `mysql2` | `@opentelemetry/instrumentation-mysql2` | spans |
| `mongodb` | `@opentelemetry/instrumentation-mongodb` | spans |
| `ioredis` | `@opentelemetry/instrumentation-ioredis` | spans |
| `redis` (node-redis v4+) | `@opentelemetry/instrumentation-redis-4` | spans |
| `@grpc/grpc-js` | `@opentelemetry/instrumentation-grpc` | spans |
| `kafkajs` | `@opentelemetry/instrumentation-kafkajs` | spans |
| `graphql` | `@opentelemetry/instrumentation-graphql` | spans |
| `aws-sdk` / `@aws-sdk/*` | `@opentelemetry/instrumentation-aws-sdk` | spans |

### Java

The OpenTelemetry Java agent auto-instruments without code changes:
- Spring MVC (REST controllers), Spring WebFlux, Spring Data (JPA, JDBC)
- RestTemplate and WebClient (outbound HTTP)
- Kafka, RabbitMQ, gRPC
- Servlet containers (Tomcat, Jetty, Undertow)
- JDBC drivers

## Troubleshooting

**No dependency manifest found:** Ask the user which subdirectory contains the service, then re-scan from that root.

**Multiple languages detected:** Ask which service to audit, or audit each independently.
