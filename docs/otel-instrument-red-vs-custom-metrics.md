# otel-instrument: custom metrics vs. APM RED-metric attributes

Status: investigation findings, not yet a spec. Root-caused against the
`otel-instrument` skill (not `splunk-detector-publish`) after a report that
instrumenting a simple checkout-style app produced 9 custom-metric/custom-
detector recommendations instead of relying on Splunk APM's out-of-the-box
(OOTB) RED-metric detectors.

## Report

Archana Padmasenan (Slack, 2026-07-06): instrumenting a simple local app with
the skills produced 9 detectors, all custom metrics and custom detectors, with
an attached `detector-sync.md` "Detector Sync Ledger" for
`obstudio-sample-checkout-api`. Question: why aren't Splunk APM's OOTB
metrics/detectors covering these instead?

## Reproduction

[`examples/python/checkout-red-demo`](../examples/python/checkout-red-demo)
is a small FastAPI checkout/payment API (`GET /cart`, `POST /checkout`,
`POST /payment`) with no OpenTelemetry instrumentation, modeling the same
shape as the reported `obstudio-sample-checkout-api` case. Verified locally:
the app runs, and a short load pass produces a real mix of `POST /payment`
200s and 502s (payment gateway timeout, ~15% of calls) alongside `/cart` and
`/checkout` traffic. That 502 path is the reproduction target: once
instrumented, does the skill represent "payment failed" as a dimension on the
route's RED metric, or as a standalone custom counter?

An existing in-repo fixture already shows the anti-pattern concretely:
[`evals/dashboards/checkout-detectors/detectors.tf.seed`](../evals/dashboards/checkout-detectors/detectors.tf.seed)
defines `high_error_rate`, a detector on a metric named `checkout.payment.errors`
(a standalone custom counter, per the paired
[`checkout-red/otel-report.md`](../evals/dashboards/checkout-red/otel-report.md)),
alongside two detectors on `http.server.request.duration` for latency and
throughput. `checkout.payment.errors` is exactly the kind of signal Archana is
asking about: per the
[OTel HTTP metrics semantic convention](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/),
it should be an `error.type`/`http.response.status_code` dimension on the same
`http.server.request.duration` histogram already emitted for `POST /payment`,
not a second, separately-tracked metric with its own detector. The
convention explicitly avoids separate success/failure metrics: the duration
histogram's own `_count` gives total requests, and `error.type` +
`http.response.status_code` on that same histogram give the error breakdown
— there is no parallel "error count" metric defined anywhere in the
convention for OTel to fall back to instead.

## Root cause

Traced through `skills/otel-instrument/SKILL.md` and its language references
(`references/languages/go.md`, plus python/node/java equivalents):

1. **The [OTel HTTP metrics semantic convention](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/)
   already defines the target shape, but the skill doesn't cite or apply it.**
   `http.server.request.duration` carries `error.type` and
   `http.response.status_code` as recommended attributes, and its
   `_count` suffix is the request-rate signal — so a single histogram is
   meant to cover Rate, Error, and Duration for a given route. The stated rule
   in the skill already points the right way, but only for whether to
   invent a new metric name — not for whether to add a dimension to an
   existing one.** SKILL.md lines 604-609: "Do not invent custom spans,
   metrics, or attributes where a semantic-convention signal satisfies the
   requirement." `skills/references/incident-readiness.md`: "Prefer OTel
   semantic-convention names for HTTP, RPC, database, messaging, and runtime
   signals. Use custom metrics only when no convention exists." Both rules
   are phrased as "does a convention exist for this metric", which a payment
   failure count trivially passes ("no, there's no semantic-convention metric
   named `payment.errors`") — the rules never ask the actually-relevant
   question, "is there already an existing RED metric on this route that a
   status/outcome attribute could be added to instead."

2. **Step 4 ("Custom Instrumentation") actively prompts toward new metrics,
   with no check against existing RED coverage.** SKILL.md lines 853-892 list
   "high-value custom instrumentation points" including "Key business
   operations (payments, orders, user registration, etc.)" and
   "Incident-readiness boundaries: customer-impact workflow outcome... ".
   Every language reference's "Custom Metrics" section (e.g.
   `references/languages/go.md` lines 343-400) then shows how to add a brand
   new `meter.Int64Counter(...)` — there is no parallel guidance anywhere
   showing how to add an attribute to the *existing* HTTP server metric
   instead. In Go, `otelhttp` exposes exactly this hook today:
   `otelhttp.ContextWithLabeler` + `(*otelhttp.Labeler).Add(...)` injects
   attributes from inside the handler directly into the metrics `otelhttp`
   emits for that request (confirmed against current `otelhttp` docs; the
   older `otelhttp.WithMetricAttributesFn` option that did the same thing at
   the middleware level is deprecated in favor of `Labeler`). Other
   languages' HTTP middlewares have their own equivalent (e.g. span/metric
   attribute callbacks), but SKILL.md never points to any of them — for
   exactly this case: "this failure is already inside a request `otelhttp`
   is measuring, attach the reason instead of counting it separately."

3. **`splunk-configure`'s classification rules then compound the problem
   downstream**, but are not themselves the root cause — they are working
   correctly off of the already-over-fragmented metric set the instrument
   step produced. `skills/splunk-configure/references/detector-classification.md`
   classifies any `.count`/`.total` metric containing an error keyword as its
   own **Error** detector candidate (Priority 10) and any `.duration`
   histogram as its own **Latency** detector candidate (Priority 9), with no
   rule that first asks "is this error count derivable as a filter on a
   latency/RED metric that already has a detector candidate for the same
   route?" Given `checkout.payment.errors` as a separate metric, this is the
   correct classification — the problem is that the metric shouldn't have
   existed as a separate instrument in the first place.

## Fix direction (not yet implemented)

Two complementary changes, not started in this session:

- **`otel-instrument`**: add an explicit decision step before Step 4 offers
  "key business operation" or "incident-readiness boundary" custom metrics
  for anything already inside an auto-instrumented request path — check
  whether the signal (outcome, failure reason, workflow name) can be added as
  an attribute on the existing RED metric via each language's metric-
  attribute hook (Go: `otelhttp.WithMetricAttributesFn`; equivalent for
  Python/Node/Java OTel HTTP middlewares) before proposing a new counter/
  histogram. Only fall back to a standalone custom metric when the signal
  genuinely doesn't correlate 1:1 with a single HTTP/RPC/DB request (e.g., a
  queue depth gauge, a background job outcome with no inbound request).
- **`splunk-configure` / `detector-classification.md`**: add a de-duplication
  pass before classification that groups candidate metrics by
  `service + route/operation` and flags when an Error or Throughput candidate
  and a Latency candidate on the same route could be satisfied by one
  RED-style detector reading dimensions off a single metric, rather than
  generating one detector per metric unconditionally.

Both changes should be validated against `examples/python/checkout-red-demo`
once implemented — instrument it, confirm the payment-failure signal lands as
an attribute rather than a new metric, then run `$splunk-configure` and
confirm detector count drops from one-per-metric to route-scoped RED
detectors.
