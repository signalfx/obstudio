# Observer

Observer is Observability Studio's local OpenTelemetry collector and explorer.
It receives OTLP traces, metrics, and logs, keeps them in bounded memory, and
makes the same evidence available through a browser UI, REST API, and MCP tools.

## Quick start

From the repository root or from `observer/`:

```bash
make run
```

The `observer/Makefile` delegates to the root build, so the command behaves the
same in either directory. To run an extracted release instead, use:

```bash
./obstudio
```

Examples in this guide use the release binary. For a source build, run them
from the repository root and replace `./obstudio` with `./build/obstudio`.

Observer starts these local endpoints:

| Service | Default endpoint |
|---|---|
| Observer UI and REST API | `http://127.0.0.1:3000` |
| MCP | `http://127.0.0.1:3000/mcp` |
| OTLP/HTTP | `http://127.0.0.1:4318` |
| OTLP/gRPC | `127.0.0.1:4317` |

The UI port and receiver ports are independent. For example, move only the UI,
REST, and MCP listener with:

```bash
PORT=41234 ./obstudio
```

Set `OTLP_HTTP_PORT` or `OTLP_GRPC_PORT` to move the corresponding receiver.

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
Observability Studio skills can audit and configure a service when you do not
already have an OpenTelemetry setup.

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

Open **Validation** and run an analysis after telemetry arrives. Observer uses
the bundled `weaver` runtime and retains the latest result. New telemetry marks
that result stale until validation is refreshed.

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

Additional account and Splunk tools appear when those features are available.

## Audit token-usage demo

Token telemetry supports **Codex and Claude Code only** and is configured
through the standalone `obstudio` CLI. Installation does not change provider
routing; enablement is explicit.

Enable a provider and inspect the same target:

```bash
./obstudio token-telemetry enable --target=codex,claude-code
./obstudio token-telemetry status --target=codex,claude-code
```

`enable` is the takeover action for recognized provider OTLP routes; there is
no separate force flag. Observability Studio does not save replaced
destinations for later restoration. `disable` removes only unchanged values
managed by Observability Studio, and a route edited after enablement is left
alone.

The default sends logs to `http://127.0.0.1:4318/v1/logs` and derives the
matching trace and metric endpoints.

If Observer uses a custom OTLP/HTTP port, pass its full logs endpoint:

```bash
./obstudio token-telemetry enable --target=codex,claude-code --endpoint=http://127.0.0.1:14318/v1/logs
```

### Choose repository correlation

New targets default to `path`. For an existing target, omitting
`--repository-correlation` preserves its recorded setting.

| Mode | Data added by Observability Studio |
|---|---|
| `path` | Repository name plus canonical repository and workspace paths; supports exact-path queries. |
| `name` | Repository name without filesystem paths. |
| `off` | No normalized repository correlation. |

Claude Code repository correlation requires the Observability Studio plugin's
SessionStart hook to emit a session association event. Codex can also derive
repository context from working-directory data in its task spans.

For example:

```bash
./obstudio token-telemetry enable --target=claude-code --repository-correlation=name
```

These modes do not rewrite raw provider telemetry, which can still include a
provider-supplied working directory.

### Run the demo

1. Start Observer, enable the provider, and fully restart every affected Codex
   or Claude process. Start a new task or session.
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

The agent calls `observer_token_usage_overview` for you. Its `status` says
whether usable measurements were retained, `accountingStatus` describes token
accounting completeness, and `repositoryCorrelationStatus` describes
repository attribution. Unknown values are never treated as zero. Observer
reconciles overlapping logs, spans, and metrics instead of adding them
together. Repository filters exclude tasks whose association cannot be proven.

Services lists telemetry producers, not operating-system processes. A routed
Claude Desktop session commonly appears as `claude-code` or
`claude-code-desktop`.

Live provider traces, logs, and metrics leave the UI when that producer
disconnects. Completed token accounting remains in a separate bounded history
until Observer is cleared, exits, or overwrites it. Recent provider traces are
also protected by bounded retention; a compacted trace shows a lower-bound span
count such as `8+` without changing service aggregates or validation input.

When the demo is complete, remove unchanged routes managed by Observability
Studio:

```bash
./obstudio token-telemetry disable --target=codex,claude-code
```

### Provider notes

- **Codex:** CLI, IDE, and Desktop processes share `~/.codex/config.toml` and
  must each restart after an exporter change. Observability Studio manages
  recognized exporter forms and fails without changing malformed, unsupported,
  or duplicate definitions. Codex token histograms remain visible in Metrics,
  but correlated task totals come from richer logs and task spans.
- **Claude Code:** Observability Studio manages recognized signal-specific,
  generic, and active detailed-beta routes while leaving unrelated settings
  unchanged. A local override re-enables an inherited or configured disabled
  OTel SDK.
  Removing a managed local value can expose an unchanged higher-precedence
  route; Observability Studio does not restore it.

Claude Desktop's active Setup profile takes precedence over user-level Claude
Code settings, and `--target=claude-code` does not edit that profile. A Desktop
session will not appear in Observer if the profile disables tracing or routes
OTLP elsewhere, even when user-level status says enabled.

For a non-destructive Desktop test, keep any required organization profile and
select an editable local Setup profile that enables telemetry and enhanced
traces, uses OTLP/HTTP protobuf, and sends logs, traces, and metrics to
`http://127.0.0.1:4318`. Restart the Desktop Code session after switching. If
the profile is locked or must retain a corporate destination, use a separate
Claude Code CLI process or ask its administrator to route through Observer.
Observability Studio cannot override that destination.

## Optional Splunk Observability Cloud forwarding

Observer can optionally forward received traces and metrics to Splunk while
keeping the Observer UI available. Logs remain local. The
[user guide](../docs/USER.md#forward-to-splunk-observability-cloud) provides
the env-file example, credential scopes, endpoint overrides, and timeouts.

## REST API

The REST API uses the Observer UI base URL. Common routes are:

- health and endpoint status: `GET /api/health`;
- traces: `GET /api/query/traces` and
  `GET /api/query/traces/{traceId}`;
- metrics, logs, and counts: `GET /api/query/metrics`,
  `GET /api/query/logs`, and `GET /api/query/stats`;
- validation: `GET /api/query/validation/summary`,
  `POST /api/validation/analyze`, and `POST /api/validation/refresh`;
- audit and dashboard data: `GET /api/audit/score` and
  `GET /api/dashboards/preview`; and
- retained telemetry deletion: `DELETE /api/data`.

The UI also uses filter, finding, artifact, Cloud, and account routes.

## Environment variables

`PORT`, `OTLP_HTTP_PORT`, and `OTLP_GRPC_PORT` move the three listeners
independently. `OBSTUDIO_WORKSPACE_ROOT` selects the workspace used for audit
and dashboard files, while `OBSTUDIO_AUDIT_REPORT` selects the audit shown in
Overview. Use `./obstudio --env-file <path>` for another startup env file.

See the [user guide](../docs/USER.md#environment-variables) for defaults and
Splunk export settings.

## Troubleshooting

- **Observer will not start:** check `3000`, `4318`, and `4317` separately.
  Change `PORT`, `OTLP_HTTP_PORT`, or `OTLP_GRPC_PORT` for the listener that is
  busy.
- **No telemetry appears:** confirm that the SDK has OTLP exporters enabled,
  uses the expected protocol, sends to this Observer's receiver ports, and
  reports the service name you expect.
- **Validation cannot run:** keep the bundled `weaver` binary beside
  `obstudio`, or make `weaver` available on `PATH`.
- **Agent telemetry is missing:** run
  `./obstudio token-telemetry status --target=<provider>`, restart the provider,
  and confirm that provider telemetry and MCP both reach the same Observer. For
  Claude Desktop, also inspect the active Setup profile.
- **Data disappeared:** Observer storage is bounded and in memory. Clear,
  process exit, overwrite, and provider disconnect affect the views described
  above.

## Architecture

OTLP/HTTP and OTLP/gRPC feed the bounded in-memory store. The Observer UI,
REST API, and MCP tools query that same data.

| Path | Responsibility |
|---|---|
| `cmd/obstudio/` | CLI, installer, lifecycle, and process startup. |
| `internal/otlp/` | OTLP/HTTP and OTLP/gRPC receivers. |
| `internal/store/` | Bounded telemetry storage and subscriptions. |
| `internal/api/` | REST query and mutation handlers. |
| `internal/mcp/` | HTTP and stdio MCP tools. |
| `internal/web/` | Embedded UI, SPA fallback, and live updates. |
| `client/` | React Observer UI built with esbuild. |

Run `make test` for Go tests and `make test-client` for the UI. See
[`CONTRIBUTING.md`](../CONTRIBUTING.md) for the full build, test, and pull
request workflow.
