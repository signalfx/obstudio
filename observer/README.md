# Splunk Observability Studio

Splunk Observability Studio is a local OpenTelemetry collector and explorer.
It receives OTLP traces, metrics, and logs, keeps them in bounded memory, and
makes the same evidence available through a browser UI, REST API, and MCP tools.

## Quick start

From the repository root or from `observer/`, run `make run`. The
`observer/Makefile` delegates to the root build, so the command behaves the
same in either directory. To run an extracted release instead, use:

```bash
./obstudio
```

Examples in this guide use the release binary. For a source build, run them
from the repository root and replace `./obstudio` with `./build/obstudio`.

Splunk Observability Studio starts these local endpoints:

| Service | Default endpoint |
|---|---|
| Splunk Observability Studio UI and REST API | `http://127.0.0.1:3000` |
| MCP | `http://127.0.0.1:3000/mcp` |
| OTLP/HTTP | `http://127.0.0.1:4318` |
| OTLP/gRPC | `127.0.0.1:4317` |

The UI port and receiver ports are independent. Run `PORT=41234 ./obstudio` to
move only the UI, REST, and MCP listener. Set `OTLP_HTTP_PORT` or
`OTLP_GRPC_PORT` to move the corresponding receiver.

## Sending telemetry

Install your application's OpenTelemetry SDK or auto-instrumentation first.
Then run these commands in the shell that starts your application:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4318"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_TRACES_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_SERVICE_NAME=my-service
```

Exporter packages and environment-variable support vary by language. The
Splunk Observability Studio skills can audit and configure a service when you
do not already have an OpenTelemetry setup.

Start the application, exercise a real request, and open
`http://127.0.0.1:3000`. Use **Live** or press `P` while the UI is focused
to pause and resume updates.

## Explore and validate

| View | Use it to... |
|---|---|
| **Overview** | Review the latest audit score, findings, and next workflow step. |
| **Services** | Compare request volume, errors, and duration by service. |
| **Traces** | Follow request waterfalls, dependencies, attributes, and errors. |
| **Metrics** | Inspect metric types, dimensions, resources, and retained points. |
| **Logs** | Filter structured messages and follow trace correlations. |
| **Validation** | Find OpenTelemetry semantic-convention problems. |
| **Dashboards** | Preview generated dashboard Terraform against local data. |
| **Cloud** | Configure optional Splunk Observability Cloud export. |

Dashboard previews are approximate because SignalFlow runs in Splunk
Observability Cloud. Missing local series are shown as empty panels rather than
fabricated data.

### Validation

Open **Validation** and run an analysis after telemetry arrives. Splunk
Observability Studio uses the bundled `weaver` runtime and retains the latest
result. New telemetry marks that result stale until validation is refreshed.

### MCP tools

Developers normally ask the connected agent a question instead of sending
JSON-RPC to `/mcp` directly. The core tools let an agent:

- list and inspect traces with `observer_traces_overview` and
  `observer_trace_detail`;
- list and inspect metrics with `observer_metrics_overview` and
  `observer_metric_detail`;
- search logs with `observer_logs_overview`;
- inspect, analyze, or refresh validation with `observer_validation_status`,
  `observer_validation_analyze`, and `observer_validation_refresh`;
- answer task-level token questions with `observer_token_usage_overview`;
- inspect endpoints and counts with `observer_status`; and
- delete retained telemetry with `observer_clear`.

`observer_validation_analyze` runs validation when no result exists. When its
retained result is stale, it returns that analysis with a freshness notice.
Use `observer_validation_refresh` only when you explicitly want a new run.

## Coding-agent token telemetry

Token telemetry supports **Codex and Claude Code only** and is configured
through the standalone `obstudio` CLI. Installation does not change provider
routing; enablement is explicit.

Enable providers and inspect the same targets:

```bash
./obstudio token-telemetry enable --target=codex,claude-code
./obstudio token-telemetry status --target=codex,claude-code
```

Running `enable` replaces recognized provider OTLP routes; there is no separate
force flag. Splunk Observability Studio does not save the replaced destinations.
`disable` removes only unchanged values managed by Splunk Observability Studio
and leaves later edits alone.

The default sends logs to `http://127.0.0.1:4318/v1/logs` and derives the
matching trace and metric endpoints.

If Splunk Observability Studio uses a custom OTLP/HTTP port, pass its full logs
endpoint:

```bash
./obstudio token-telemetry enable --target=codex,claude-code --endpoint=http://127.0.0.1:14318/v1/logs
```

### Choose repository correlation

New targets default to `path`. For an existing target, omitting
`--repository-correlation` preserves its recorded setting.

| Mode | Data added by Splunk Observability Studio |
|---|---|
| `path` | Repository name plus canonical repository and workspace paths; supports exact-path queries. |
| `name` | Repository name without filesystem paths. |
| `off` | No normalized repository correlation. |

Claude Code repository correlation requires the Splunk Observability Studio
plugin's SessionStart hook to emit a session association event. Codex can also
derive repository context from working-directory data in its task spans.

For example:

```bash
./obstudio token-telemetry enable --target=claude-code --repository-correlation=name
```

These modes do not rewrite raw provider telemetry, which can still include a
provider-supplied working directory.

### Verify token accounting

1. Start Splunk Observability Studio, enable the provider, and fully restart
   every affected Codex or Claude process. Start a new task or session.
2. Run `$otel-audit` as the only work in a fresh Codex task, or run
   `/otel-audit` in a fresh Claude Code session. Plugin users can use the
   namespaced `/obstudio:otel-audit` form.
3. Keep the provider process running while you inspect its live Logs, Traces,
   Metrics, and Services views.
4. In an MCP-enabled task, ask one of these questions:

   - “How many tokens did the latest audit use? Include coverage and accounting
     status.”
   - “Break the latest audit down into input, cache, output, and reasoning
     tokens. Show unknown values as unknown.”
   - “How many tokens did conversation `<conversation-id>` use?”
   - “How many tokens did the latest audit in repository
     `<repository-name-or-path>` use?”

The agent calls `observer_token_usage_overview` for you. Read its result as
follows:

- **Measurement:** `status` says whether Splunk Observability Studio retained
  usable token data. Unknown values remain unknown rather than being treated as
  zero.
- **Accounting:** `accountingStatus` describes completeness. Splunk
  Observability Studio reconciles overlapping logs, spans, and metrics instead
  of adding duplicate measurements.
- **Repository attribution:** `repositoryCorrelationStatus` describes whether
  Splunk Observability Studio could associate the task with a repository.
  Repository filters exclude tasks whose association cannot be proven.
- **Live views:** Services lists telemetry producers, not operating-system
  processes. Keep the provider process running while demonstrating its traces,
  logs, metrics, and service entry; those signals leave the UI when it
  disconnects.
- **Completed usage:** Token accounting is retained separately after a process
  disconnects. It remains queryable until Splunk Observability Studio is
  cleared, exits, or overwrites that bounded history.
- **Trace retention:** Splunk Observability Studio protects recent provider
  traces from unrelated telemetry while the producer is connected. A compacted
  trace shows a lower-bound span count such as `8+` without changing service
  aggregates or validation results.

When finished, remove unchanged routes managed by Splunk Observability Studio:

```bash
./obstudio token-telemetry disable --target=codex,claude-code
```

`disable` also removes each target's saved repository-correlation setting. To
keep token telemetry enabled without normalized repository attribution, use
`enable` with `--repository-correlation=off` instead.

### Codex

By default, Codex CLI, IDE, and Desktop processes share
`~/.codex/config.toml`; when `CODEX_HOME` is set, token setup uses
`$CODEX_HOME/config.toml`. Restart each process after an exporter change.

| Existing Codex configuration | What `enable` does |
|---|---|
| No exporter | Adds a Splunk Observability Studio-managed local exporter. |
| Recognized inline assignment | Replaces and manages the complete exporter assignment. |
| Canonical OTLP/HTTP table with an endpoint | Redirects and manages its endpoint and protocol entries while preserving headers and unrelated settings. |
| Compatible canonical table without an endpoint | Completes the route and manages its endpoint and protocol entries. |
| Unsupported, malformed, or multiply defined exporter | Stops without editing the configuration. |

While enabled, Codex's exporters for logs, traces, and metrics point to Splunk
Observability Studio. `disable` removes unchanged managed routes and does not
recover previous destinations. Codex token histograms remain visible in
Metrics, but their current points do not have stable task or turn identifiers.
Correlated totals therefore use the richer Codex logs and task spans.

### Claude Code

- An active `ENABLE_BETA_TRACING_DETAILED` and `BETA_TRACING_ENDPOINT` pair
  overrides the standard log and trace exporters. `enable` manages and
  normalizes that active pair to Splunk Observability Studio.
- Existing generic OTLP endpoint and protocol values are redirected and
  managed. Required signal-specific routes are written locally even when
  matching values are inherited.
- A local override re-enables an OTel SDK disabled by inherited or configured
  settings. Existing interval, temporality, TLS, header, and unrelated settings
  remain unchanged.
- Removing a managed local override can expose an unchanged inherited or
  higher-precedence route. Splunk Observability Studio does not restore that route.

## Optional Splunk Observability Cloud forwarding

Splunk Observability Studio can optionally forward received traces and metrics
to Splunk while keeping its UI available. Logs remain local. The [user
guide](../docs/USER.md#forward-to-splunk-observability-cloud) provides the
env-file example and credential scope.

## REST API

The REST API uses the Splunk Observability Studio UI base URL. Common routes are:

- health and endpoint status: `GET /api/health`;
- traces: `GET /api/query/traces` and
  `GET /api/query/traces/{traceId}`;
- metrics, logs, and counts: `GET /api/query/metrics`,
  `GET /api/query/logs`, and `GET /api/query/stats`;
- validation: `GET /api/query/validation/summary`,
  `POST /api/validation/analyze`, and `POST /api/validation/refresh`;
- live updates: `GET /api/ws` (WebSocket);
- audit and dashboard data: `GET /api/audit/score` and
  `GET /api/dashboards/preview`; and
- retained telemetry deletion: `DELETE /api/data`.

## Environment variables

`PORT`, `OTLP_HTTP_PORT`, and `OTLP_GRPC_PORT` move the three listeners
independently. `OBSTUDIO_WORKSPACE_ROOT` selects the workspace used for audit
and dashboard files, while `OBSTUDIO_AUDIT_REPORT` selects the audit shown in
Overview. Use `./obstudio --env-file <path>` for another startup env file.

## Troubleshooting

- **Splunk Observability Studio will not start:** check `3000`, `4318`, and
  `4317` separately. Change `PORT`, `OTLP_HTTP_PORT`, or `OTLP_GRPC_PORT` for
  the listener that is busy.
- **No telemetry appears:** confirm that the SDK has OTLP exporters enabled,
  uses the expected protocol, sends to this instance's receiver ports, and
  reports the service name you expect.
- **Validation cannot run:** keep the bundled `weaver` binary beside
  `obstudio`, or make `weaver` available on `PATH`.
- **Agent telemetry is missing:** run
  `./obstudio token-telemetry status --target=<provider>`, restart the provider,
  and confirm that provider telemetry and MCP both reach the same instance.
- **Data disappeared:** Splunk Observability Studio storage is bounded and in
  memory. Clear, process exit, overwrite, and provider disconnect affect the
  views described above.

### Claude Desktop telemetry

Claude Desktop's active Setup profile takes precedence over user-level Claude
Code settings. `--target=claude-code` neither inspects nor edits that profile.
If the profile disables trace export or routes OTLP elsewhere, the running
Desktop process will not appear in Splunk Observability Studio even when
user-level status is enabled. A routed session appears in Services under its
reported resource name, commonly `claude-code` or `claude-code-desktop`.

For a non-destructive test while keeping any required organization profile:

1. Select an editable local Setup profile.
2. Enable Claude telemetry and enhanced traces, use OTLP/HTTP protobuf, and
   send logs, traces, and metrics to `http://127.0.0.1:4318`.
3. Fully restart the Desktop Code session after switching profiles.

If the profile is organization-locked or must retain a corporate destination,
use a separate Claude Code CLI process or ask the profile administrator to
route through Splunk Observability Studio. Only that administrator can change a
locked destination; Splunk Observability Studio cannot override or silently
replace it.

## Developing Splunk Observability Studio

OTLP/HTTP and OTLP/gRPC feed the bounded in-memory store. The Splunk
Observability Studio UI, REST API, and MCP tools query that same data.

| Path | Responsibility |
|---|---|
| `cmd/obstudio/` | CLI, installer, lifecycle, and process startup. |
| `internal/otlp/` | OTLP/HTTP and OTLP/gRPC receivers. |
| `internal/store/` | Bounded telemetry storage and subscriptions. |
| `internal/api/` | REST query and mutation handlers. |
| `internal/mcp/` | HTTP and stdio MCP tools. |
| `internal/web/` | Embedded UI, SPA fallback, and live updates. |
| `client/` | React UI built with esbuild. |

Run `make test` for Go tests and `make test-client` for the UI. See
[`CONTRIBUTING.md`](../CONTRIBUTING.md) for the full build, test, and pull
request workflow.
