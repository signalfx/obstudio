# Observer-TS

Local OpenTelemetry Collector for Observability Studio — receives OTLP
telemetry, stores it in memory, and exposes it via REST API, WebSocket, MCP
(for AI agents), and a browser-based Telemetry Explorer. Built with Bun and
TypeScript.

## Quick Start

```bash
bun install
make dev
```

This starts the collector with hot reload on default ports:

| Service | URL |
|---|---|
| Telemetry Explorer (Web UI) | http://localhost:3000 |
| OTLP/HTTP receiver | http://localhost:4318 |
| OTLP/gRPC receiver | localhost:4317 |
| MCP endpoint | http://localhost:3000/mcp |

## Architecture

Standalone TypeScript server — no OTel Collector framework dependency.

```
OTLP/HTTP Receiver ──▶ Convert ──▶ In-memory Store
OTLP/gRPC Receiver ──▶ Convert ──┘       │
                                          ├──▶ REST API
                                          ├──▶ WebSocket (live updates)
                                          ├──▶ MCP (AI agent tools)
                                          └──▶ Web UI (embedded assets)
```

- **OTLP receivers** (`src/otlp/`) — HTTP and gRPC, protobuf and JSON
- **Store** (`src/store/`) — in-memory storage with pub/sub notifications
- **API** (`src/api/`) — REST queries and WebSocket live streaming
- **MCP** (`src/mcp/`) — JSON-RPC tool server for AI agents (HTTP + stdio)
- **Web** (`src/web/`) — Bun.serve with embedded static assets for compiled binaries

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

## Homebrew (local)

```bash
make build
tar -czf dist/obstudio-darwin-arm64.tar.gz -C dist obstudio
cp dist/obstudio-darwin-arm64.tar.gz "$(brew --cache)/"
brew tap-new signalfx/obstudio          # first time only
cp Formula/obstudio.rb /opt/homebrew/Library/Taps/signalfx/homebrew-obstudio/Formula/
brew install signalfx/obstudio/obstudio
```

## MCP Tools

AI agents can query telemetry via JSON-RPC at `/mcp`:

| Tool | Description |
|---|---|
| `observer_traces_overview` | List recent traces with span previews and status summaries |
| `observer_trace_detail` | Fetch full trace by traceId with ordered spans and attributes |
| `observer_metrics_overview` | List metrics with compact summaries and datapoint previews |
| `observer_metric_detail` | Fetch a single metric by exact name with full datapoints |
| `observer_clear` | Clear all telemetry data from the in-memory store |

## REST API

| Endpoint | Description |
|---|---|
| `GET /api/query/traces` | List traces |
| `GET /api/query/traces/:traceId` | Trace detail |
| `GET /api/query/metrics` | List metrics |
| `GET /api/query/logs` | List logs |
| `GET /api/query/stats` | Aggregate counts |
| `GET /api/query/service-map` | Service dependency map |
| `GET /api/ws` | WebSocket live stream |

## Make Targets

| Target | Description |
|---|---|
| `make dev` | Start with hot reload |
| `make build` | Compile standalone binary |
| `make build-all` | Cross-compile for linux/darwin x64/arm64 |
| `make test` | Run tests |
| `make embed-static` | Embed React client into TypeScript module |
| `make clean` | Remove dist/ |

## Directory Layout

```
observer-ts/
├── src/
│   ├── index.ts                  # CLI entrypoint
│   ├── api/
│   │   ├── rest.ts               # REST query handlers
│   │   └── websocket.ts          # WebSocket live updates
│   ├── mcp/
│   │   ├── handler.ts            # MCP tool definitions
│   │   ├── http-transport.ts     # MCP over HTTP
│   │   └── stdio-transport.ts    # MCP over stdio
│   ├── otlp/
│   │   ├── convert.ts            # OTLP → internal types
│   │   ├── grpc-receiver.ts      # OTLP/gRPC on port 4317
│   │   ├── http-receiver.ts      # OTLP/HTTP on port 4318
│   │   ├── proto.ts              # Protobuf encode/decode
│   │   ├── otlp-descriptors.json # Pre-built proto descriptors
│   │   └── protos/               # Vendored OTel proto v1.5.0
│   ├── store/
│   │   ├── store.ts              # In-memory store with pub/sub
│   │   ├── query.ts              # Query/filter logic
│   │   └── types.ts              # Span, Metric, Log types
│   ├── util/
│   │   ├── env.ts                # Environment variable helpers
│   │   └── camel-to-kebab.ts     # Naming utility
│   └── web/
│       ├── server.ts             # Bun.serve HTTP server
│       └── embedded-assets.ts    # Auto-generated embedded UI
├── test/
│   ├── api/                      # REST + WebSocket tests
│   ├── otlp/                     # Receiver + conversion tests
│   ├── store/                    # Store tests
│   ├── integration/              # End-to-end tests
│   └── load/                     # Load testing tools
├── scripts/
│   └── embed-static.ts           # Static asset embedding script
├── Formula/
│   └── obstudio.rb               # Homebrew formula
├── Makefile
├── package.json
└── tsconfig.json
```
