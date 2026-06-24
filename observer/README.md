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

Ports 4317 and 4318 must be free. If the VS Code extension or another
collector is already running, either stop it first or override with
environment variables (`PORT`, `OTLP_HTTP_PORT`, `OTLP_GRPC_PORT`).

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
| `HOST` | `127.0.0.1` | Bind address |
| `PORT` | `3000` | Web UI / API / MCP port |
| `OTLP_HTTP_PORT` | `4318` | OTLP/HTTP receiver port |
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
| `observer_metrics_overview` | List metrics with summaries |
| `observer_metric_detail` | Fetch single metric by name |
| `observer_logs_overview` | List recent logs with filtering |
| `observer_status` | Return collector endpoints and stats |
| `observer_clear` | Clear all telemetry data |

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
