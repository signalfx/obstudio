# Observer-Go: OTel Collector as Observer

Observability Studio's Go backend (`observer-go/`) is built **on top of** the
OpenTelemetry Collector framework. Instead of implementing a custom OTLP server
from scratch, we embed the official Collector and extend it with two custom
components:

```
┌────────────────────────────────────────────────────┐
│                   obstudio binary                  │
│                                                    │
│  ┌──────────┐   pipeline    ┌──────────────────┐   │
│  │   OTLP   │──────────────▶│    obstudio      │   │
│  │ Receiver │  traces       │    Exporter      │   │
│  │ (grpc +  │  metrics      │  (pdata → store) │   │
│  │  http)   │  logs         └────────┬─────────┘   │
│  └──────────┘                        │             │
│                                      ▼             │
│                              ┌──────────────┐      │
│                              │  In-memory   │      │
│                              │    Store      │      │
│                              └──────┬───────┘      │
│                                     │              │
│  ┌──────────────────────────────────┴───────────┐  │
│  │           obstudio Extension                 │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │  │
│  │  │ REST API│  │   MCP   │  │   Web UI    │  │  │
│  │  │  /api/* │  │  /mcp   │  │   / (SSE)   │  │  │
│  │  └─────────┘  └─────────┘  └─────────────┘  │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

## Why the Collector Framework?

| Concern | Before (custom) | After (Collector) |
|---|---|---|
| OTLP parsing | Hand-written protobuf decode | Built-in `otlpreceiver` |
| gRPC + HTTP | Manual dual listeners | Single receiver, both protocols |
| Back-pressure | None | Collector queue + retry |
| Future extensibility | Rewrite | Add processors/exporters via config |
| Community alignment | Bespoke | Standard `ocb` builder-compatible |

## Components

### Exporter (`observer-go/exporter/`)

The **obstudio exporter** sits at the end of the Collector pipeline. It receives
`pdata` (the Collector's internal data model) and converts it into the
application's `store` types:

| pdata type | store type | conversion |
|---|---|---|
| `ptrace.Traces` | `[]store.Span` | `convertTraces()` |
| `pmetric.Metrics` | `[]store.MetricDataPoint` | `convertMetrics()` |
| `plog.Logs` | `[]store.LogRecord` | `convertLogs()` |

The exporter is registered as `obstudio` in the pipeline config:

```yaml
exporters:
  obstudio: {}

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [obstudio]
```

**Files:**
- `config.go` — empty config (no knobs needed)
- `factory.go` — factory registration for traces, metrics, logs
- `convert.go` — pdata → store conversion (IDs, timestamps, attributes, events, links)

### Extension (`observer-go/extension/`)

The **obstudio extension** runs an HTTP server alongside the Collector,
serving three surfaces from a single port:

| Path | Protocol | Purpose |
|---|---|---|
| `/api/query/*` | REST/JSON | Trace, metric, log queries; stats |
| `/mcp` | JSON-RPC 2.0 | MCP tool endpoints for AI agents |
| `/api/events` | SSE | Real-time telemetry change notifications |
| `/` | HTTP | Embedded single-page Telemetry Explorer UI |

The extension is configured with an `endpoint`:

```yaml
extensions:
  obstudio:
    endpoint: 127.0.0.1:3000

service:
  extensions: [obstudio]
```

**Files:**
- `config.go` — endpoint configuration with validation
- `factory.go` — factory registration
- `extension.go` — HTTP server lifecycle (Start / Shutdown)

### Internal (`observer-go/internal/`)

Shared packages that both the exporter and extension depend on:

| Package | Purpose |
|---|---|
| `internal/store` | Thread-safe in-memory storage, query engine, pub-sub for SSE |
| `internal/api` | REST API route registration and handlers |
| `internal/mcp` | MCP JSON-RPC handler, tool definitions, session management |
| `internal/web` | Embedded static UI, SSE event stream handler |

## Directory Layout

```
observer-go/
├── cmd/obstudio/main.go      # Entry point: assembles Collector + components
├── exporter/                  # Custom OTel Collector exporter
│   ├── config.go
│   ├── factory.go
│   └── convert.go
├── extension/                 # Custom OTel Collector extension
│   ├── config.go
│   ├── factory.go
│   └── extension.go
├── internal/
│   ├── store/store.go         # In-memory telemetry store
│   ├── api/handler.go         # REST API
│   ├── mcp/handler.go         # MCP server
│   └── web/
│       ├── server.go          # SSE + static file server
│       └── static/index.html  # Telemetry Explorer UI
├── go.mod
├── go.sum
├── Makefile
└── builder-config.yaml        # OTel Collector Builder (ocb) config
```

## Usage

### Build and Run

```bash
cd observer-go
make build
./obstudio
```

Or in one step:

```bash
make run
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HOST` | `127.0.0.1` | Bind address for all listeners |
| `PORT` | `3000` | Web UI / API / MCP port |
| `OTLP_HTTP_PORT` | `4318` | OTLP/HTTP receiver port |
| `OTLP_GRPC_PORT` | `4317` | OTLP/gRPC receiver port |

### Send Telemetry

Any OpenTelemetry SDK or Collector can export to obstudio:

```bash
# OTLP/HTTP
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318

# OTLP/gRPC
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

### Web UI

Open `http://localhost:3000` in a browser. The Telemetry Explorer shows three
tabs:

- **Traces** — grouped by trace ID, expandable to show span details
- **Metrics** — grouped by name/service/scope with data point previews
- **Logs** — reverse-chronological with severity coloring

Live updates via SSE — no polling.

### MCP (AI Agent Interface)

POST JSON-RPC 2.0 to `http://localhost:3000/mcp`:

```bash
curl -X POST http://localhost:3000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Available tools:

| Tool | Description |
|---|---|
| `observer_metrics_overview` | List metrics with summaries |
| `observer_metric_detail` | Fetch single metric by name |
| `observer_traces_overview` | List recent traces with span previews |
| `observer_trace_detail` | Fetch full trace by traceId |

### REST API

| Endpoint | Description |
|---|---|
| `GET /api/query/traces` | List traces (filters: serviceName, spanName, status) |
| `GET /api/query/traces/{traceId}` | Get trace detail |
| `GET /api/query/metrics` | List metrics (filters: metricName, serviceName, type) |
| `GET /api/query/logs` | List logs (filters: serviceName, severityText, body) |
| `GET /api/query/stats` | Aggregate counts and service names |
| `GET /api/events` | SSE stream of telemetry changes |

## OTel Collector Builder (ocb)

The `builder-config.yaml` can be used with the
[OpenTelemetry Collector Builder](https://github.com/open-telemetry/opentelemetry-collector/tree/main/cmd/builder)
to produce a standalone binary with only the components obstudio needs:

```bash
go install go.opentelemetry.io/collector/cmd/builder@latest
builder --config=builder-config.yaml
```

This produces a minimal binary in `./build/` with the OTLP receiver, obstudio
exporter, and obstudio extension baked in.
