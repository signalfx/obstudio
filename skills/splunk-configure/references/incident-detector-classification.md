# Incident-Readiness Detector Classification

Read only when routed by `detector-classification.md`. These categories run
before generic RED categories and improve MTTD/localization without inventing
signals.

## Categories

### Impact Classification

Use `impact-classification` for explicit `impact`, `synthetic`,
`client_telemetry`, `workflow.state`, `workflow.outcome`, `customer_impact`, or
`degraded` signals, or availability evidence mapped to app/workflow impact.
Group only by proven low-cardinality workflow, region/environment, service,
dependency, or release dimensions. `availability` or `unavailable` alone is
not sufficient: dependency-specific availability remains a dependency signal.

### Auth/Edge

Use `auth-edge` for explicit login/auth/identity-provider/token/session,
domain-routing, DNS, TLS/certificate, gateway, or edge signals measuring
duration, success, error, timeout, expiry, or unavailability.

### Customer Impact

Use `customer-impact` for user-visible workflow/journey/render/load/transaction
signals measuring latency or bounded outcomes. `operation` alone is not
sufficient: a database, broker, cache, client, or dependency operation remains
a dependency signal rather than a client or dependency being mislabeled as a
customer workflow.

### Freshness and Backpressure

Use `freshness` for age/lag gauges or histograms with explicit freshness,
newest-event-age, event-age, ingest-lag, processing-lag, data-age, or staleness
meaning. Use a source-backed age SLO.

Use `backpressure` for queue depth/size, consumer lag, oldest-message age,
rebalance, paused/blocked consumer, or explicit backpressure. There is no
universal count threshold for queue depth or consumer lag. Use a source-backed
capacity/SLO, normalized saturation percentage, or proven historical baseline.
Use `85` only for a normalized percentage.

### Dependency

Use `dependency` for explicit dependency/client/external/datastore/database/
search/cache/broker/stream/cloud signals measuring duration, error, timeout,
retry, rate-limit, throttle, circuit-breaker state, endpoint health, target
health, availability, unavailable/unhealthy target count, or operation failure.
Group by proven low-cardinality dependency and operation dimensions.

### Capacity Saturation

Use `capacity-saturation` when an evidenced gauge/up-down counter or supported
event counter measures capacity/utilization/cpu/memory/heap/disk/filesystem,
JVM/thread-pool/worker/inflight/concurrency, desired-vs-healthy,
startup/readiness/healthcheck, quota/rate-limit/throttle, restart/crashloop, or
pod/node/task/process/HPA/ASG pressure.

For runtime CPU, source-backed CPU utilization such as
`process.cpu.utilization`, `process.runtime.*.cpu.utilization`, or
`jvm.cpu.recent_utilization` supports a CPU saturation detector. Do not use
thread count, heap, memory, GC, or worker count as CPU coverage. Treat
cumulative CPU time as a diagnostic rate using `rollup='rate'`; it does not
prove normalized CPU utilization or an alert threshold.

### Release Context

Use stable, low-cardinality `service.version`,
`deployment.environment.name`, `cloud.region`, `cloud.platform`,
`container.image.name`, `container.image.tags`, artifact version, config
version, feature flag, canary, rollout, or existing proven legacy aliases as
detector dimensions/dashboard filters. Pure release metadata is
`release-context`, not a standalone detector; classify a health signal by its
health category first.

## Priority and defaults

Priority is impact classification, auth/edge, customer impact, freshness,
backpressure, dependency, capacity saturation, then release context. Use
critical severity for unavailable/customer/auth outcomes, major for dependency
and capacity degradation, and thresholds/baselines owned by the source SLO or
service owner. Freshness uses an age threshold; error/retry/rebalance event
counters may use `against_recent`; normalized utilization may use a static
percentage. Do not invent raw-count thresholds.

If a required signal is absent or unproven, create an instrumentation/owner
prerequisite, not detector Terraform. Missed, flapping, auto-resolved, and
no-data alerts are detector reliability evidence for the alert-coverage
matrix. Do not generate service metric Terraform or ask app instrumentation to
emit alert lifecycle metrics unless the application owns those events.
