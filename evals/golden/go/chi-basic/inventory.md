# go-chi-basic - Observability

> Golden reference for eval comparison

## SLI Definitions

| SLI | Golden Signal | Component | Target |
|-----|---------------|-----------|--------|
| HTTP request latency | Latency | HTTP Server | p99 < 500ms |
| HTTP request throughput | Traffic | HTTP Server | -- |
| HTTP error rate | Errors | HTTP Server | < 1% 5xx |
| HTTP server saturation | Saturation | HTTP Server | -- |
| Task creation rate | Traffic | Business Logic | -- |
| Task completion rate | Traffic | Business Logic | -- |
| Task deletion rate | Traffic | Business Logic | -- |
| Active task count | Saturation | In-Memory Store | -- |

## Spans

| Signal Name | Category | Component | SLIs | Status | Verified |
|-------------|----------|-----------|------|--------|----------|
| `HTTP {method} {route}` | OOB | HTTP Server | HTTP request latency, HTTP request throughput, HTTP error rate | | |

## Metrics

| Signal Name | Type | Category | Component | SLIs | Unit | Status | Verified |
|-------------|------|----------|-----------|------|------|--------|----------|
| `http.server.request.duration` | Histogram | Derived | HTTP Server | HTTP request latency | s | | |
| `http.server.active_requests` | UpDownCounter | OOB | HTTP Server | HTTP server saturation | {requests} | | |
| `tasks.created.count` | Counter | Custom | Business Logic | Task creation rate | {tasks} | | |
| `tasks.completed.count` | Counter | Custom | Business Logic | Task completion rate | {tasks} | | |
| `tasks.deleted.count` | Counter | Custom | Business Logic | Task deletion rate | {tasks} | | |
| `tasks.active.count` | Gauge | Custom | In-Memory Store | Active task count | {tasks} | | |

## Logs

| Signal Name | Category | Component | SLIs | Level | Status | Verified |
|-------------|----------|-----------|------|-------|--------|----------|

## Expected Structural Properties

- language: go
- framework: chi
- sdk_init_file: telemetry.go (or similar single-file init)
- auto_instrumentation_packages:
  - "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
- oob_span_count: 1
- oob_metric_count: 1
- derived_metric_count: 1
- custom_metric_count: 4
- sli_count: >= 8
- components: HTTP Server, Business Logic, In-Memory Store
- fault_domains_count: >= 5
