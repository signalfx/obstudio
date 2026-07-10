# Checkout RED Demo

Small FastAPI checkout/payment API with no OpenTelemetry instrumentation.
Reproduces the scenario reported against `otel-instrument`: a plain
request/checkout/payment flow where `/payment` fails with a 5xx a fraction of
the time.

Use it to reproduce and later fix
[the otel-instrument custom-metric-vs-RED-attribute issue](../../../docs/otel-instrument-red-vs-custom-metrics.md):
running `$otel-instrument` against this app should not need to invent
standalone custom metrics/detectors for "payment errors" or "checkout
throughput" -- `otelhttp`'s `http.server.request.duration` on `POST /payment`
and `POST /checkout` already carries `http.status_code`/`error.type`, which is
what Splunk APM's OOTB RED detectors key off. A per-route/per-outcome
dimension on that existing metric, not a new `checkout.payment.errors`
counter, is the correct shape.

## Run

```sh
cd examples/python/checkout-red-demo
make dev
```

In another terminal:

```sh
make load
```

The service listens on `http://localhost:8030`.

## Demo Workflow

1. Run the baseline app and load generator.
2. Run `$otel-audit` on this directory and review the reported metrics.
3. Run `$otel-instrument` on this directory and inspect which metrics it adds
   beyond the `otelhttp` RED signals -- this is the reproduction step.
4. Run `$splunk-configure` (or `$otel-audit` -> `$splunk-configure`) and count
   how many detectors it proposes vs. how many are actually not already
   covered by Splunk APM's OOTB RED detectors on `/checkout` and `/payment`.
