# Observer-Go

Local OpenTelemetry Collector for Observability Studio — receives OTLP
telemetry, stores it in memory, and exposes it via REST API, MCP (for AI
agents), and a browser-based Telemetry Explorer.

## Quick Start

```bash
make run
```

This builds and starts the collector on default ports:

| Service | URL |
|---|---|
| Telemetry Explorer (Web UI) | http://localhost:3000 |
| OTLP/HTTP receiver | http://localhost:4318 |
| OTLP/gRPC receiver | localhost:4317 |
| MCP endpoint | http://localhost:3000/mcp |

## Architecture

Built on the [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
framework with two custom components:

```
OTLP Receiver ──▶ obstudio Exporter ──▶ In-memory Store
                                              │
                  obstudio Extension ◀────────┘
                  (REST API + MCP + Web UI + SSE)
```

- **Exporter** (`exporter/`) — converts Collector `pdata` into store types
- **Extension** (`extension/`) — HTTP server serving all user-facing surfaces
- **Internal** (`internal/`) — store, API handlers, MCP server, embedded web UI

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HOST` | `127.0.0.1` | Bind address |
| `PORT` | `3000` | Web UI / API / MCP port |
| `OTLP_HTTP_PORT` | `4318` | OTLP/HTTP receiver port |
| `OTLP_GRPC_PORT` | `4317` | OTLP/gRPC receiver port |

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

## REST API

| Endpoint | Description |
|---|---|
| `GET /api/query/traces` | List traces |
| `GET /api/query/traces/{traceId}` | Trace detail |
| `GET /api/query/metrics` | List metrics |
| `GET /api/query/logs` | List logs |
| `GET /api/query/stats` | Aggregate counts |
| `GET /api/events` | SSE stream |

## Make Targets

| Target | Description |
|---|---|
| `make build` | Compile the binary |
| `make run` | Build and run |
| `make test` | Run tests |
| `make tidy` | `go mod tidy` |
| `make fmt` | Format code |
| `make vet` | Run go vet |
| `make clean` | Remove binary |

## OTel Collector Builder

Use `builder-config.yaml` with
[ocb](https://github.com/open-telemetry/opentelemetry-collector/tree/main/cmd/builder)
to produce a standalone distribution:

```bash
builder --config=builder-config.yaml
```

## Directory Layout

```
observer-go/
├── cmd/obstudio/main.go
├── exporter/
│   ├── config.go
│   ├── factory.go
│   └── convert.go
├── extension/
│   ├── config.go
│   ├── factory.go
│   └── extension.go
├── internal/
│   ├── store/store.go
│   ├── api/handler.go
│   ├── mcp/handler.go
│   └── web/
│       ├── server.go
│       └── static/index.html
├── go.mod
├── go.sum
├── Makefile
└── builder-config.yaml
```
