# Detector Classification Core

Read this core for every detector run. It classifies generic RED metrics,
deduplicates route signals, and routes specialized evidence without loading it.

## Conditional routes

Load a route only when its condition is present in the validated input:

| Reference | Load when |
|---|---|
| `incident-detector-classification.md` | The mode is `alert-coverage-audit`, `impact-classify`, or `blast-radius`; an incident-readiness row exists; or a candidate name/dimension explicitly contains an impact, auth/edge, freshness, backpressure, dependency, capacity, CPU, release, or deployment marker. |
| `genai-detector-classification.md` | `meta.genai_ownership_detected` is true, a GenAI Readiness row exists, or a candidate has explicit `gen_ai`, LLM, inference, embedding, provider, agent, tool-call, retrieval/RAG, evaluation, or content-governance context. |

Do not load either specialized reference for an ordinary generic latency,
error, throughput, or saturation set. When loaded, specialized categories win
before the generic categories below.

## Route-Level De-duplication

Before classification, group metrics with the same `service.name` and the same
low-cardinality route/operation value (`http.route`, `rpc.method`,
`db.operation.name`, or equivalent). A duration histogram plus a counter that
only restates that route's error/status or total-call outcome is one RED source.

A route group forms only when the shared route/operation is source-backed and:

- an error/status counter restates an outcome already available on the
  histogram as `error.type`, a failing `*.response.status_code`, or another
  evidenced failure-only bounded attribute; or
- a total-call counter is derivable from the histogram observation count and
  has no failure-only dimension absent from the histogram.

For a formed group:

- generate one **latency** detector from the histogram percentile;
- generate at most one **error** detector from the same histogram's count
  rollup, route filter, and proven failing outcome filter;
- generate at most one **throughput** detector from the same histogram's count
  rollup and route filter, with no outcome filter;
- report the redundant counter as merged, not silently skipped; and
- keep a counter independent when it carries a useful dimension the histogram
  does not.

Never wildcard a response-status attribute: select only evidenced failing
values. An `error.type='*'` existence filter is valid when the evidence proves
that attribute is failure-only. A non-standard attribute such as
`outcome.reason='gateway_timeout'` may supply the error detector only when its
bounded value is proven failure-only. If a standard error attribute also
exists, add a separate outcome detector only when the custom attribute
distinguishes failure causes the standard attribute cannot; never duplicate a
1:1 signal.

## Generic RED categories

Apply these after any loaded specialized categories:

| Category | Match | Default treatment |
|---|---|---|
| `latency` | Histogram whose name contains `.duration` | p99 threshold |
| `error` | Counter ending `.total` or `.count` with `error`, `failure`, `failed`, `invalid`, `rejected`, `timeout`, or `exception` | increase against recent baseline |
| `throughput` | Other counter ending `.total` or `.count` | drop/spike against recent baseline |
| `saturation` | Gauge/up-down counter with `connections`, `pool`, `buffer`, `queue`, `lag`, `utilization`, `capacity`, `active`, `pending`, `heap`, `memory`, `disk`, `filesystem`, `goroutines`, or `threads` | source-backed static threshold |

Names alone never prove that a metric exists, is accepted, has safe dimensions,
or has a meaningful threshold. Preserve exact unit, temporality, attribute,
route, and proof evidence from the selected input contract.

### Generic RED coverage floor

Establish request-path RED coverage before selecting an unrelated business
counter as generic throughput:

- when an accepted request-duration histogram exists, prefer its observation
  count as the service or route throughput detector;
- otherwise retain an accepted request-activity metric such as
  `http.server.active_requests` as saturation when its source-backed threshold
  is actionable; and
- treat a distinct business counter as additional workflow coverage, never as
  a substitute for both request throughput and request saturation.

This ordering keeps the detector set small while preserving a baseline view of
traffic and request pressure.

## Exclusions and priority

Apply Route-Level De-duplication first. Then use this priority:

1. loaded GenAI category;
2. loaded incident-readiness category;
3. latency;
4. error;
5. throughput;
6. saturation.

Skip and explain:

- an auto-instrumented metric only when a custom metric covers the same signal
  more precisely and no route group applies;
- a runtime/host metric without an actionable threshold, including cumulative
  CPU time without safe normalization;
- informational-only uptime/version metrics; and
- any missing, unverified, unsafe, partial, owner-mapped, or duplicate signal.

Do not invent a count threshold. The common `85` saturation default is valid
only for an evidenced normalized percentage, never raw active requests, queue
depth, lag, connections, threads, or bytes.
