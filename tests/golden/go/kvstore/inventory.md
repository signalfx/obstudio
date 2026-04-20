# go-kvstore - Observability

> Golden reference for eval comparison

## SLI Definitions

| SLI | Golden Signal | Component | Target |
|-----|---------------|-----------|--------|
| HTTP request latency | Latency | HTTP Server | p99 < 500ms |
| HTTP request throughput | Traffic | HTTP Server | -- |
| HTTP error rate | Errors | HTTP Server | < 1% 5xx |
| KV get latency | Latency | KV Store | p99 < 10ms |
| KV set throughput | Traffic | KV Store | -- |
| KV delete throughput | Traffic | KV Store | -- |
| Search latency | Latency | Search Index | p99 < 50ms |
| Cache hit rate | Errors | KV Store | > 95% |
| Eviction rate | Saturation | KV Store | -- |
| Active key count | Saturation | KV Store | -- |

## Spans

| Signal Name | Category | Component | SLIs | Status | Verified |
|-------------|----------|-----------|------|--------|----------|
| `HTTP {method} {route}` | OOB | HTTP Server | HTTP request latency, HTTP request throughput, HTTP error rate | | |
| `kvstore.get` | Custom | KV Store | KV get latency, Cache hit rate | | |
| `kvstore.set` | Custom | KV Store | KV set throughput | | |
| `kvstore.delete` | Custom | KV Store | KV delete throughput | | |
| `kvstore.search` | Custom | Search Index | Search latency | | |

## Metrics

| Signal Name | Type | Category | Component | SLIs | Unit | Status | Verified |
|-------------|------|----------|-----------|------|------|--------|----------|
| `http.server.request.duration` | Histogram | Derived | HTTP Server | HTTP request latency | s | | |
| `kvstore.get.duration` | Histogram | Custom | KV Store | KV get latency | ms | | |
| `kvstore.set.count` | Counter | Custom | KV Store | KV set throughput | {operations} | | |
| `kvstore.delete.count` | Counter | Custom | KV Store | KV delete throughput | {operations} | | |
| `kvstore.search.duration` | Histogram | Custom | Search Index | Search latency | ms | | |
| `kvstore.keys.count` | Gauge | Custom | KV Store | Active key count | {keys} | | |
| `kvstore.evictions.count` | Counter | Custom | KV Store | Eviction rate | {evictions} | | |
| `kvstore.cache.hit_ratio` | Gauge | Custom | KV Store | Cache hit rate | 1 | | |

## Logs

| Signal Name | Category | Component | SLIs | Level | Status | Verified |
|-------------|----------|-----------|------|-------|--------|----------|
| `kvstore.persist.failure` | Custom | KV Store | | error | | |
| `kvstore.eviction` | Custom | KV Store | Eviction rate | warn | | |

## Expected Structural Properties

- language: go
- framework: net/http
- sdk_init_file: telemetry.go (or similar single-file init)
- auto_instrumentation_packages:
  - "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
- oob_span_count: 1
- oob_metric_count: 0
- derived_metric_count: 1
- custom_metric_count: 7
- custom_span_count: 4
- sli_count: >= 10
- components: HTTP Server, KV Store, Search Index
- fault_domains_count: >= 5
