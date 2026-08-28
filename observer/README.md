# Observer

Local OpenTelemetry Collector for Observability Studio — receives OTLP
telemetry, stores it in memory, and exposes it via REST API, MCP (for AI
agents), and a browser-based Telemetry Explorer.

## Quick Start

```bash
make run
```

Run this either from the repository root or from `observer/`. The
`observer/Makefile` delegates to the repo-root build so the commands stay
in sync.

This builds and starts the collector on default ports:

| Service | URL |
|---|---|
| Telemetry Explorer (Web UI) | http://localhost:3000 |
| OTLP/HTTP receiver | http://localhost:4318 |
| OTLP/gRPC receiver | localhost:4317 |
| MCP endpoint | http://localhost:3000/mcp |

Ports 4317 and 4318 must be free. If the VS Code or Kiro extension or another
collector is already running, either stop it first or override with
environment variables (`PORT`, `OTLP_HTTP_PORT`, `OTLP_GRPC_HOST`,
`OTLP_GRPC_PORT`).

Validation uses the bundled `weaver` runtime that `make build` places
next to `build/obstudio`. If you move the binary manually, keep `weaver`
beside it or make `weaver` available on `PATH`.

## Architecture

```
OTLP/HTTP + gRPC ──▶ In-memory Store
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
          REST API     MCP (HTTP    Web UI + WS
         /api/query    + stdio)     (React SPA)
```

- **`internal/otlp/`** — OTLP/HTTP and gRPC receivers, connection tracking
- **`internal/store/`** — in-memory telemetry store with pub/sub
- **`internal/api/`** — REST query endpoints
- **`internal/mcp/`** — MCP server (HTTP and stdio transports)
- **`internal/web/`** — static file server, SPA fallback, WebSocket
- **`client/`** — self-contained React client (built via esbuild)

## Environment Variables

### Core

| Variable | Default | Description |
|---|---|---|
| `HOST` | `127.0.0.1` | UI, API, MCP, and OTLP/HTTP bind address; also the default for OTLP/gRPC |
| `PORT` | `3000` | Web UI / API / MCP port |
| `OTLP_HTTP_PORT` | `4318` | OTLP/HTTP receiver port |
| `OTLP_GRPC_HOST` | `HOST` | OTLP/gRPC proxy bind host; set to a loopback address when `HOST` is a container wildcard |
| `OTLP_GRPC_PORT` | `4317` | OTLP/gRPC receiver port |

### Optional Splunk Observability Cloud forwarding

Observer can forward received telemetry to Splunk Observability Cloud.
Metrics and traces are configured independently; both are disabled by default.

**Shared credentials** (used by both metrics and traces):

| Variable | Description |
|---|---|
| `SPLUNK_REALM` or `OBSTUDIO_SPLUNK_REALM` | Splunk realm (e.g. `us1`, `eu0`). Used to build the default ingest endpoint when no explicit endpoint is set. |
| `SPLUNK_ACCESS_TOKEN` | Splunk org access token with ingest scope. |

**Metrics forwarding** (`/v2/datapoint/otlp`):

| Variable | Default | Description |
|---|---|---|
| `OBSTUDIO_SPLUNK_METRICS_EXPORT` or `SPLUNK_METRICS_EXPORT` | `false` | Enable metrics forwarding. |
| `OBSTUDIO_SPLUNK_METRICS_ENDPOINT` | auto from realm | Override the metrics ingest URL. |
| `OBSTUDIO_SPLUNK_METRICS_TIMEOUT` | `5s` | Per-request timeout (e.g. `10s` or `10`). |

**Traces forwarding** (`/v2/trace/otlp`):

| Variable | Default | Description |
|---|---|---|
| `OBSTUDIO_SPLUNK_TRACES_EXPORT` or `SPLUNK_TRACES_EXPORT` | `false` | Enable traces forwarding. Sending spans to Splunk makes the instrumented service visible as an APM service. |
| `OBSTUDIO_SPLUNK_TRACES_ENDPOINT` | auto from realm | Override the traces ingest URL. |
| `OBSTUDIO_SPLUNK_TRACES_TIMEOUT` | `5s` | Per-request timeout (e.g. `10s` or `10`). |

**Example**: forward both metrics and traces for realm `us1`:

```bash
export SPLUNK_REALM=us1
export SPLUNK_ACCESS_TOKEN=<your-token>
export OBSTUDIO_SPLUNK_METRICS_EXPORT=true
export OBSTUDIO_SPLUNK_TRACES_EXPORT=true
make run
```

## Sending Telemetry

Point any OpenTelemetry SDK at the receiver:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

Or send directly with curl:

```bash
curl -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"my-service"}}]},"scopeSpans":[{"spans":[{"traceId":"0af7651916cd43dd8448eb211c80319c","spanId":"b7ad6b7169203331","name":"hello","kind":1,"startTimeUnixNano":"1000000000","endTimeUnixNano":"2000000000","status":{}}]}]}]}'
```

## MCP Tools

AI agents can query telemetry via JSON-RPC at `/mcp`:

| Tool | Description |
|---|---|
| `observer_traces_overview` | List recent traces with span previews |
| `observer_trace_detail` | Fetch full trace by traceId |
| `observer_token_usage_overview` | Answer questions about normalized Codex, Claude, or span-based agent/task token usage, including cache/reasoning breakdowns and coverage |
| `observer_metrics_overview` | List metrics with summaries |
| `observer_metric_detail` | Fetch single metric by name |
| `observer_logs_overview` | List recent logs with filtering |
| `observer_status` | Return collector endpoints and stats |
| `observer_clear` | Clear all telemetry data |

### Audit token-usage demo

Installing the extension or plugin configures MCP but does not change provider
OTLP settings. Start Observer, then explicitly opt in one or both providers:

```bash
obstudio token-telemetry status --target=codex,claude-code
obstudio token-telemetry enable --target=codex,claude-code
```

The default sends logs to `http://127.0.0.1:4318/v1/logs`, traces to the
corresponding `/v1/traces` endpoint, and Claude metrics to `/v1/metrics`. Pass a
different full logs endpoint with `--endpoint`. Restart Codex or Claude Code
after enabling the configuration. A later `status` uses the recorded custom
endpoint unless `--endpoint` is supplied explicitly. Prompt text, tool content,
and raw API bodies remain disabled by provider defaults. For Claude, setup also
selects cumulative metric temporality when no preference exists so Observer can
prove full-session metric totals. An explicit user-owned temporality preference
is preserved and is never adopted for cleanup.

Repository correlation defaults to `path` when no mode has been recorded.
`path` exposes the repository name plus canonical repository and active
workspace paths; `name` omits the filesystem paths. Raw
provider telemetry is preserved and may contain a provider-emitted working
directory independently of these normalized fields. Pass
`--repository-correlation=off` to disable normalized repository attribution
or `--repository-correlation=name` to omit filesystem paths. Omitting the flag for
an already configured target preserves its recorded mode. Codex task spans can
provide a per-turn working directory directly. The plugin SessionStart hook
supplies the equivalent session-to-repository association for Claude and a
lifecycle fallback for Codex. These content-free correlation events are sent
only to the configured loopback Observer logs endpoint and retained in a
dedicated bounded in-memory ring. `name` and `path` reject a non-loopback
`--endpoint` before provider configuration is changed.

The Codex and Claude plugin SessionStart hooks can start or reuse the detached
Observer serving the plugin's direct HTTP MCP endpoint. The VS Code extension
can instead run or connect to an Observer. Provider telemetry and MCP queries
must target that same Observer process to share its bounded in-memory history.
Stopping that process clears the ephemeral history.

1. Run `$otel-audit` against a service as the only work in a fresh Codex turn, or run `/obstudio:otel-audit` as the only work in a fresh Claude prompt.
2. Ask: "How many agent tokens did the latest audit use? Compare the provider-reported and independently derived totals, and state measurement coverage and accounting status."
3. Ask: "Break that audit down into input, cached input, cache-creation input, output, and reasoning output. Show unknown values as unknown, not zero."
4. Ask: "Which of the five most recent audit tasks used the most tokens?"
5. For a known task URL, ask: "How many exact tokens were used in Codex conversation `<ID from codex://threads/...>`?" The agent passes that ID as `conversationId`; the tool also accepts `threadId` as an alias because agents commonly infer that name from the URL. Claude session IDs use the canonical `conversationId` filter.
6. Ask: "How many agent tokens did the latest audit in repository `entity-model-service` use? State both token-accounting and repository-correlation coverage."

The agent discovers and calls `observer_token_usage_overview` internally; the
user does not need to issue a JSON-RPC request. A completed native provider task
span with recognized aggregate usage defines an exact task boundary and can
supply the accounting directly when provider logs are incomplete or have been
evicted. A completed Claude interaction span without aggregate usage does not
prove that every child request span has arrived; its retained child total is a
measured subtotal with partial accounting until an exact cumulative metric or
another complete provider source replaces it. For an explicit thread
or session query, a still-in-progress question is omitted when completed tasks
for that conversation are retained. Without a trace ID, Codex
`response.completed` logs are grouped by turn before conversation fallback;
Claude `api_request` logs are grouped by prompt before session fallback. When
Claude's richer log/trace exporters are unavailable, provider-native
`claude_code.token.usage` metrics are grouped by `session.id`; unique delta
points are summed for retained-window measurement and cumulative series use
only their latest non-decreasing point. Metrics are exact only when monotonic
cumulative input, cache-read, cache-creation, and output are all retained,
including explicit zero values. Non-monotonic sums or same-series cumulative
decreases remain available as raw metrics but are not interpreted as exact
token consumption. Delta series remain partial because a newly started Observer
cannot prove that it received earlier intervals.
Exact matching logs or spans take precedence over metrics; exact metrics
replace malformed or partial richer telemetry, while two partial sources are
not combined into a guessed total. If cumulative metrics show that a Claude
session predates retained Observer history, later exact per-request details
remain a measured subtotal but session accounting stays partial; the overlapping
metric value is not added to that subtotal.
Codex
cached input and reasoning remain breakdowns of reported input and output.
Claude normalized input is derived from uncached input plus cache-read and
cache-creation input. Claude's metric output includes provider thinking tokens,
so separate reasoning output and provider-reported total remain unknown while
the normalized input-plus-output total is derived exactly. Duplicate
response/request IDs and exact metric retransmissions are counted once. When a
completed Codex turn emits startup or earlier cumulative records, the tool
selects the record that matches the turn span's provider total instead of adding
those records together; `providerEventCount` exposes how many raw events were
considered. Completed provider-task snapshots, provider usage logs, and provider
token metrics have dedicated bounded in-memory rings, so unrelated high-volume
telemetry does not evict the accounting record. They remain available across
agent-process disconnects and idle session resets while Observer remains
running.

Repository queries use `repositoryName` or `repositoryPath`. The result reports
`repositoryCorrelationStatus` and `repositoryCoverage` separately from
`accountingStatus` and token measurement coverage. A task with exact token
accounting but no provable repository association is excluded from a repository
filter rather than guessed. No match returns `status: absent` with null totals,
which is distinct from a matched task whose provider explicitly reported zero.

Reconciled provider logs take precedence; a completed task span replaces rather
than augments incomplete logs, so the same request is never counted from both
sources. When no provider-native task accounting matches, the tool falls back to
generic GenAI spans, de-duplicates enclosing workflow summaries from model-call
spans, and excludes evaluation-only judge branches. Rubric/judge usage is not
stored as agent/task usage. `accountingStatus` distinguishes exact correlated
provider accounting from uncorrelated, partial, estimated, and unknown results.
The data remains ephemeral and is evicted by explicit clear, Observer exit, or
its dedicated bounded-ring overwrite. The tool's `limit` bounds returned task
rows only; totals and measurement coverage include every retained matching
task. `highestUsageTask` is also selected across every retained match and is
`null` when any matched task has an unknown effective total, so an unknown
measurement is never ranked as zero. Aggregate accounting becomes partial when completed-task retention has
discarded history, and Claude cumulative metric series that began before the
current Observer startup or most recent clear are partial rather than exact.

The setup command has no force mode. Matching Codex or Claude settings remain
user-owned. A nonmatching exporter, endpoint, protocol, header, or certificate
causes that provider target to fail without changing it; other requested targets
are still processed. Obstudio records only settings it adds. Disable removes
only those unchanged settings and preserves values the user modified later:

```bash
obstudio token-telemetry disable --target=codex,claude-code
```

Disable also removes that target's repository-correlation opt-in. To keep token
telemetry enabled but stop repository correlation, rerun enable with
`--repository-correlation=off`.

The command respects `CODEX_HOME` and `CLAUDE_CONFIG_DIR`. Codex and Claude
ownership is stored in `~/.obstudio/token-telemetry.json`; use
`OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH` only when an isolated state location is
required. Relative overrides and `~/...` resolve from the user home so the CLI
and plugin hook address the same file regardless of working directory. For
new provider configuration files and all ownership/recovery state, Obstudio
uses user-only permissions (a protected current-user DACL on Windows). Existing
Obstudio-owned state is hardened on replacement, while the mode or DACL of
existing provider files is preserved. Commands serialize
ownership changes and recover an interrupted config/state publish on the next
enable, disable, or status command. Recovery journals and ownership deltas are
target-specific, so an unresolved Codex change does not block or overwrite
Claude state, or vice versa. A provider file changed after the interruption is
preserved and reported instead of being overwritten.
For Claude Code, the command edits only the user-level
`settings.json` and inspects that file plus its inherited process environment.
Higher-precedence managed, command-line, local-project, or shared-project
settings remain untouched and can supersede the user-level values; use Claude
Code's `/status` view to verify the active setting sources for the target
project.

Exact accounting requires complete provider-native usage from a correlated
task boundary, correlated provider logs, or all four monotonic cumulative Claude
session metric components to reach the same Observer. The opt-in command leaves an existing
nonmatching exporter unchanged and reports the conflict; resolve that conflict
or route the existing destination through Observer before relying on
`accountingStatus: exact`. If a provider version emits neither usable signal,
the result remains `absent`/`unknown`; Observer does not fabricate an exact
value from a missing measurement.

## REST API

| Endpoint | Description |
|---|---|
| `GET /api/query/traces` | List traces |
| `GET /api/query/traces/{traceId}` | Trace detail |
| `GET /api/query/metrics` | List metrics |
| `GET /api/query/logs` | List logs |
| `GET /api/query/stats` | Aggregate counts |
| `DELETE /api/data` | Clear all data |
| `GET /api/ws` | WebSocket (live updates) |

## Make Targets

Targets are defined in the repository root and are also available from
`observer/` via the delegating `Makefile`:

| Target | Description |
|---|---|
| `make build` | Compile the binary (skills + client embedded) |
| `make run` | Build and run |
| `make test` | Run Go tests |
| `make test-client` | Run client unit tests |
| `make test-all` | Run Go + client + extension tests |
| `make tidy` | `go mod tidy` |
| `make fmt` | Format code |
| `make vet` | Run go vet |
| `make clean` | Remove build artifacts |

## Directory Layout

```
observer/
├── cmd/
│   ├── obstudio/          # CLI entry point (cobra)
│   ├── build-client/      # esbuild-based React client builder
│   └── stage-skills/      # Copies skills into embed directory
├── client/                # Self-contained React SPA
│   ├── src/
│   ├── package.json
│   └── scripts/
├── internal/
│   ├── store/             # In-memory telemetry store
│   ├── api/               # REST query handlers
│   ├── mcp/               # MCP server (HTTP + stdio)
│   ├── otlp/              # OTLP/HTTP receiver + connection tracking
│   ├── web/               # Static files, SPA fallback, WebSocket
│   ├── buildutil/         # Skill staging utilities
│   └── integration/       # Integration tests
├── go.mod
└── go.sum
```
