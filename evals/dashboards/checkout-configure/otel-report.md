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

`http.server.request.duration` already carries an `error.type` attribute on
`POST /payment` (set via the `otelhttp` metric-attribute hook when
`doPayment` returns the 502 "payment gateway timeout" outcome), in addition
to its `http.route` attribute. `checkout.payment.errors` is a legacy custom
counter that was added before this attribute existed: it carries the same
`endpoint=/payment` dimension and increments on the identical 502 outcome the
histogram's `error.type` attribute already records, so it duplicates
coverage the histogram now provides rather than adding a new signal.

## Instrumentation

- OTel SDK initialized once in `main.go`; tracer + meter providers set.
- `otelhttp.NewHandler` wraps the chi router (route-aware, low cardinality).
- OTLP HTTP exporter → `http://localhost:4318`.
