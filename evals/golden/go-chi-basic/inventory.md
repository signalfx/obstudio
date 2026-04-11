# go-chi-basic - Observability

> Golden reference for eval comparison

## KPI Table

| Status | KPI | Component | Class | Metric | Trace | Log | Signal Name | Trace-Derivable |
|--------|-----|-----------|-------|--------|-------|-----|-------------|-----------------|
| | HTTP request latency | HTTP Server | Standard | Yes | Yes | No | `http.server.request.duration` | Yes |
| | HTTP request count | HTTP Server | Standard | Yes | Yes | No | `http.server.request.count` | Yes |
| | HTTP error rate | HTTP Server | Standard | Yes | Yes | No | `http.server.error.count` | Yes |
| | HTTP active requests | HTTP Server | Standard | Yes | No | No | `http.server.active_requests` | No |
| | Task creation count | Business Logic | Business | Yes | No | No | `tasks.created.count` | No |
| | Task completion count | Business Logic | Business | Yes | No | No | `tasks.completed.count` | No |
| | Task deletion count | Business Logic | Business | Yes | No | No | `tasks.deleted.count` | No |
| | Active task count | In-Memory Store | Business | Yes | No | No | `tasks.active.count` | No |

## Expected Structural Properties

- language: go
- framework: chi
- sdk_init_file: telemetry.go (or similar single-file init)
- auto_instrumentation_packages:
  - "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
- custom_metrics: 4 (tasks.created.count, tasks.completed.count, tasks.deleted.count, tasks.active.count)
- components: HTTP Server, Business Logic, In-Memory Store
- fault_domains_count: >= 5
- kpi_count: >= 8
- business_kpi_count: >= 4
