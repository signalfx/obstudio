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
corresponding `/v1/traces` endpoint, and provider metrics to `/v1/metrics`. Pass a
different full logs endpoint with `--endpoint`. Restart Codex or Claude Code
after enabling the configuration, then start a fresh task or session. An
already-open task keeps the MCP tools and telemetry routing loaded when that
provider process started; reopening its URL does not refresh them. A later
`status` uses the recorded custom endpoint unless `--endpoint` is supplied
explicitly. Prompt text, tool content, and raw API bodies remain disabled by
provider defaults. For Claude, setup also selects cumulative metric temporality
when no preference exists so Observer can prove full-session metric totals. An
explicit user-owned temporality preference is preserved and is never adopted
for cleanup. The explicit `enable` command takes over every recognized provider
OTLP route, including routes that already match Observer. `disable` removes
unchanged Obstudio-managed routes without restoring replaced prior destinations;
values edited after enable are preserved.

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

Keep the new provider process running while checking the Logs, Traces, Metrics,
and Services views. Disconnecting it removes that process's live signals by
design. After the task completes or the process exits, ask the token question
in a fresh MCP-enabled task: the compact completed accounting history is kept
separately from those live views until Observer is cleared, exits, or overwrites
its bounded accounting ring.

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

For each correlated request or task, the tool compares recognized normalized
token fields and selects the more informative provider log or native span. The
other source may fill only missing fields when effective totals agree and all
overlapping fields are compatible; the two totals are never added. A log/span
source disagreement is reported as partial instead of guessed. Claude cumulative
token metrics validate an equal per-request subtotal or replace an incomplete
or disagreeing subtotal only when they form an exact retained session window,
and an overlapping metric total is never added to logs or spans. Codex emits
both operational metrics and a `codex.turn.token_usage` histogram with input,
cached-input, output, reasoning-output, and total token types. Current Codex
metric points do not carry a stable thread or turn identifier, so they are
shown in Metrics Explorer but are not merged into task accounting. Correlated
Codex response-completed logs and task spans remain the authoritative task
sources and prevent the unkeyed metric from duplicating their totals. When no
provider-native task accounting matches, the tool
falls back to generic GenAI spans, de-duplicates enclosing workflow summaries
from model-call spans, and excludes evaluation-only judge branches.
Rubric/judge usage is not stored as agent/task usage. `accountingStatus`
distinguishes exact correlated provider accounting from uncorrelated, partial,
estimated, and unknown results.
Claude usage reconstructed from request spans remains partial after an
interaction root completes because separately batched child requests can still
arrive. A complete cumulative session metric window can replace that subtotal
and promote the result to exact without adding either source twice.
The data remains ephemeral and is evicted by explicit clear, Observer exit, or
its dedicated bounded-ring overwrite. The tool's `limit` bounds returned task
rows only; totals and measurement coverage include every retained matching
task. `highestUsageTask` is also selected across every retained match and is
`null` when any matched task has an unknown effective total, so an unknown
measurement is never ranked as zero. Aggregate accounting becomes partial when completed-task retention has
discarded history, and Claude cumulative metric series that began before the
current Observer startup or most recent clear are partial rather than exact.
Recent native Codex and Claude traces also use one shared bounded provider ring
and are de-duplicated into trace list, detail, and MCP correlation queries. Each
retained trace is capped at eight representative spans so one large trace
cannot monopolize the projection. A compacted trace reports
`retentionTruncated: true`, the UI renders its count as a retained lower bound
such as `8+`, and exact span-count or duration filters exclude it. Raw span
counts, per-service duration/error aggregates, and validation snapshots do not
include projected spans; the provider service name remains discoverable after
raw-span eviction with aggregate fields left empty. Process disconnect removes
that process's live traces, logs, and metrics from Observer views; bounded
token-accounting history remains available to the token-usage tool until
explicit clear, Observer exit, or accounting-ring overwrite.

The explicit setup command is the takeover action; there is no separate force
mode. Every recognized Codex or Claude exporter, endpoint, and protocol route is
owned and normalized to Observer, including matching, inherited, and explicit
empty values; missing signal routes are added. Disable removes a managed value
only while the current value still matches the one Obstudio wrote and preserves
values edited after enable. Replaced prior routes are not retained for later
disable or restored:

```bash
obstudio token-telemetry disable --target=codex,claude-code
```

For Codex, takeover supports inline exporter assignments and the canonical
`[otel.exporter.otlp-http]`, `[otel.trace_exporter.otlp-http]`, and
`[otel.metrics_exporter.otlp-http]` tables. Canonical-table
headers and unrelated settings remain in place; a replaced inline assignment
is removed by disable when it remains unchanged. Unsupported,
malformed, or multiply defined exporter syntax fails closed instead of risking
an invalid TOML file; other requested provider targets are still processed.
For Claude, the command sets signal-specific logs, traces, and metrics exporter,
protocol, and endpoint values. If generic OTLP endpoint or protocol values are
present, it redirects those too. It also locally clears an active
`OTEL_SDK_DISABLED` and redirects an active legacy detailed-beta endpoint.
Unrelated settings, TLS material, headers, and existing interval or temporality
preferences remain unchanged. Removing a local Claude override can expose an
unchanged inherited or higher-precedence route again; Obstudio does not restore
that route.

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
project. Claude Desktop launches embedded Code sessions with its active Setup
profile as higher-precedence managed settings. The `claude-code` target neither
inspects nor edits that profile, so its status describes the user-level CLI
configuration only. If the Desktop profile routes OTLP to another collector or
disables trace export, opening Desktop or running a task sends no corresponding
signal to local Observer. Services is derived from received telemetry rather
than process discovery; a correctly routed Desktop session appears under its
reported resource name, commonly `claude-code` or `claude-code-desktop`.

For a non-destructive Desktop test, retain any required organization profile
and use an intentionally local, editable Setup profile that enables Claude
telemetry and enhanced traces and routes OTLP/HTTP protobuf logs, traces, and
metrics to `http://127.0.0.1:4318`. Fully restart the Desktop Code session after
switching profiles. If the active profile is organization-locked or must retain
a corporate destination, use a separately started Claude Code CLI process or
ask the organization or profile administrator to route through Observer; only
that administrator can change an organization-locked destination. Obstudio
cannot override and does not silently replace the profile destination.

Claude's legacy detailed-beta pair, `ENABLE_BETA_TRACING_DETAILED=1` plus a
non-empty `BETA_TRACING_ENDPOINT`, sends logs and traces to that endpoint
instead of the standard OTLP exporters. Enable owns an active pair, normalizes
its endpoint to the Observer base URL, and removes both managed values on disable.
This also corrects a trailing slash that would otherwise make Claude append
unsupported double-slash signal paths. Before enable, status reports that route
as a conflict requiring takeover; after enable, all three standard signal routes
and the active detailed route point to Observer.

The same takeover rule applies to existing generic Claude OTLP routing and to
all three Codex exporters. A missing Codex exporter is added. A canonical
Codex `otlp-http` table with only one of `endpoint` or `protocol` is completed;
matching route lines are marked as managed, while nonmatching values are
replaced in place. Disable removes unchanged managed lines rather than restoring
their prior values. Surrounding tables, headers, unrelated comments, and
unrelated values remain in place; a comment attached to a replaced routing line
is removed with that line and is not recovered by disable.

Codex reads these settings from its shared `~/.codex/config.toml` across the
CLI, IDE integrations, and Desktop. Start a new CLI process and fully restart
the IDE or Desktop app-server after changing an exporter. While token telemetry
is enabled, Codex's single logs, traces, and metrics exporters point to Observer;
disable removes unchanged managed routes and does not recover previous destinations.

Exact accounting requires complete provider-native usage from a correlated
task boundary, correlated provider logs, or all four monotonic cumulative Claude
session metric components to reach the same Observer. The opt-in command routes
valid user-level provider settings to Observer, but a higher-precedence managed
profile or launcher environment can still supersede them. If a provider version
emits no usable signal, the result remains `absent`/`unknown`; Observer does not
fabricate an exact value from a missing measurement.

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
