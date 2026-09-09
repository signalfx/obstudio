---
name: otel-audit
description: >-
  Scan a codebase for existing OpenTelemetry instrumentation and observability
  gaps. Read-only for application code: writes .observe/otel-audit.json and
  .observe/otel.html but does not modify service code. Use for $otel-audit,
  coverage/readiness reviews, incident detection or localization gaps, and
  GenAI/LLM semantic-convention checks. Use $otel-instrument for changes.
---

# Audit -- Observability Coverage Scan

## Overview

Scan a service repository to detect its language, framework, dependencies,
and existing OpenTelemetry instrumentation. Report what is instrumented,
what is missing, and any anti-patterns. This skill is read-only for application
code: it writes `.observe/otel-audit.json` and `.observe/otel.html` but does
not modify service code, dependencies, configuration, or tests.

Resolve paths in this entrypoint from the directory containing the loaded
`otel-audit/SKILL.md`. Inside a loaded reference, resolve relative paths from
that reference's directory. Here, `../references/<file>` means the shared
sibling under the parent skills directory, while `references/<file>` and
`scripts/<file>` are local to `otel-audit`. Never probe the service root or
repository root for these paths.

## Progressive Disclosure

Load guidance in this order so unrelated languages and modes never enter the
working context:

1. Complete repository discovery below.
2. Load only the detected language file under `references/languages/`.
3. Load `references/telemetry-assessment.md` for the source assessment.
4. Load `../references/incident-readiness.md` only for an incident-relevant
   surface or an explicit detection/localization request.
5. Load both `../references/genai-readiness.md` and
   `references/genai-audit.md` only when the source scan finds GenAI ownership.
6. After assessment is complete, load `references/report-contract.md` to write,
   finalize, and hand off the canonical artifacts.

Do not load the shared `../references/report-flow-contract.md`. The local
report contract is the sole authority for audit artifacts and handoff.

## Process

### Step 1 -- Repository Discovery

Scan the repository to determine language, framework, and existing instrumentation.

Start with one bounded `rg --files` inventory. For a small repository (at most
25 non-ignored files, one manifest, and no nested service root), inspect the
manifest, entrypoint, route/business source, tests, and startup files in batched
reads, then use focused `rg` queries for OTel, exporter, environment, and log
evidence. Do not repeat a complete file listing or the same repository-wide
search. For a larger or multi-service repository, narrow each search by the
detected manifest and target process before reading source.

1. Detect primary language and framework:
   - Go: `go.mod`
   - Python: `requirements.txt`, `pyproject.toml`, `setup.py`
   - Node.js: `package.json`
   - Java: `pom.xml`, `build.gradle`
   - Rust: `Cargo.toml`
   - .NET: `*.csproj`, `*.sln`
2. Identify entry points (`main`, `cmd/`, `app.py`, `index.ts`, etc.)
3. Enumerate all HTTP routes with method and path pattern (e.g. `GET /tasks`, `POST /tasks`, `GET /tasks/{id}`). List them explicitly in the report.
4. Load only the detected language reference from
  `references/languages/{go,python,node,java}.md`; do not load or restate
  unrelated language guidance. For Rust or .NET, use current official
  dependency evidence and record its source.
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
  `../references/genai-readiness.md` and `references/genai-audit.md`; do not
  load either reference for non-GenAI services.
  Follow its GenAI Semconv Source Contract before scoring GenAI coverage:
  reconcile detected AI surfaces with official semconv docs when available,
  record live-or-snapshot provenance, and build a semconv closure matrix.
  When GenAI incidents, postmortems, alerts, tickets, or failure examples are
  part of the request, use GenAI incident-evidence mode and map each failure
  as `incident class -> failure mechanism -> repo/service owner -> code surface ->`
  required signal before scoring whether instrumentation is MTTD-improving or
  localization-only. Map each failure
  mechanism to provider/model gateway, workflow, tool/function execution or
  AI-owned session/stream including MCP when present, retrieval/RAG, streaming,
  token/context, prompt/response parser, safety/policy, AI-derived data,
  model/config rollout, or AI-owned cache/session evidence.
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


### Step 2 -- Assess Existing Telemetry

Read `references/telemetry-assessment.md` and apply it to every target process
and signal. Reconcile source definitions with real entrypoint reachability;
source candidates are not runtime emission proof. For Python, run the bundled
`scripts/scan_python_otel_topology.py <service-root>` as directed there.

If Step 1 found incident-relevant ownership, apply the already routed incident
reference. If it found GenAI ownership, apply both routed GenAI references.
Otherwise do not load those references.

### Step 3 -- Write, Finalize, and Hand Off

Only after the source assessment is complete, read
`references/report-contract.md`. Write the canonical JSON first, generate the
HTML only through `finalize-audit`, and follow its exact chat handoff. Never
patch generated HTML and never modify application code, dependencies,
configuration, or tests.
