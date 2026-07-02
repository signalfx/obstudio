# Observability Report: checkout

**Language:** Go | **Framework:** chi | **Date:** 2026-05-01

## Summary

The `checkout` service is an HTTP API instrumented with OpenTelemetry via
`otelhttp`. It emits RED-style HTTP server metrics plus two custom business
metrics. OTLP export is wired to `localhost:4318`. `service.name=checkout` is
set on the resource.

## Routes

| Method | Path | Handler |
|---|---|---|
| GET | /health | healthHandler |
| GET | /cart | getCart |
| POST | /checkout | doCheckout |
| POST | /payment | doPayment |

### Metrics

| Name | Source | Type |
|---|---|---|
| http.server.request.duration | otelhttp | auto |
| http.server.active_requests | otelhttp | auto |
| http.server.request.size | otelhttp | auto |
| http.server.response.size | otelhttp | auto |
| checkout.orders.processed | manual | custom |
| checkout.payment.errors | manual | custom |

All metrics carry the `service.name=checkout` resource dimension. The custom
counters also carry an `endpoint` dimension.

## Instrumentation

- OTel SDK initialized once in `main.go`; tracer + meter providers set.
- `otelhttp.NewHandler` wraps the chi router (route-aware, low cardinality).
- OTLP HTTP exporter → `http://localhost:4318`.
