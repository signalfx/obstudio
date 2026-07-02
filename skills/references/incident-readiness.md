# Incident Readiness Reference

Load this reference when a repo owns user-visible workflows, background
processing, dependency calls, queues, data freshness, auth/edge paths, capacity
limits, release/config changes, or when the user asks for faster incident
detection, localization, or debugging.

## Goal

Create traces, metrics, and logs that can answer these questions quickly:

- Is the whole app down, or is one workflow degraded?
- Which workflow, dependency, queue, region/environment, or release is involved?
- Is the symptom request latency, errors, stale data, backlog, auth/edge failure,
  capacity saturation, or release/config related?
- What signal can become a detector or dashboard without manual trace search?

## Audit Checklist

- API/workflow paths: route spans, workflow spans, status code, error class,
  request count, latency histogram, and outcome by low-cardinality workflow.
- Customer-impact workflows: login, search, render/load, request/response,
  transaction, decision/evaluation, notification, ingestion, export, sync, or
  another user-visible path.
- Dependencies: datastore, cache, search, message broker, object store, cloud API,
  internal service, and third-party client spans with operation, retry, timeout,
  circuit-breaker state, endpoint health, target health, availability, and
  rate-limit/throttle outcomes when available.
- Data freshness: newest event age, ingest lag, processing lag, accepted count,
  dropped count, and drop reason.
- Input/payload complexity: request or job payload size bucket, item/entity
  count bucket, metadata count when relevant, parse/validation failure, and
  complexity bucket when these predict latency, errors, or saturation.
- Queue/backpressure: queue depth, consumer lag, oldest message age, rebalance
  count, paused/blocked consumers, worker saturation, and retry/dead-letter rate.
- Synthetic/canary workflow checks: result, latency, failed stage, timeout
  class, and workflow/environment dimensions when the service owns the check.
- Auth/edge: login, identity provider, token/session, domain routing, DNS, TLS,
  certificate, gateway, and edge route failures.
- Capacity: memory, heap, CPU, disk/filesystem, thread/worker pool, inflight
  work, concurrency, quota, throttling, rate limit, restart/crash-loop,
  desired-vs-healthy instances, startup/readiness/healthcheck failure, traffic
  target health, and autoscaling saturation.
- Release/config context: `service.version`, `deployment.environment.name`,
  `cloud.region`, `cloud.platform`, `container.image.name`,
  `container.image.tags`, artifact version, config version, feature flag,
  canary/rollout batch, runtime environment, and region/zone on spans and
  metrics when low-cardinality.

## Instrumentation Guidance

- Start with baseline request/job tracing, metrics, resource attributes, context
  propagation, and error status.
- Add workflow spans only at diagnostic boundaries: controller/handler, service
  workflow, dependency call, queue publish/consume, worker job, and scheduled job.
- Emit metrics only from values the service can observe accurately. Do not create
  placeholder instruments for unavailable signals.
- Treat time since last success/update as detector-ready freshness only when the
  source proves an expected cadence, pending/backlogged work, or accepted input
  that should have produced an update. Healthy idle time also makes a bare age
  gauge grow; without that demand/cadence evidence, classify it as context or
  localization-only and alert on backlog, queue delay, or missed schedule
  instead.
- Prefer OTel semantic-convention names for HTTP, RPC, database, messaging, and
  runtime signals. Use custom metrics only when no convention exists.
- Use stable dimensions: `service.name`, `service.version`,
  `deployment.environment.name`, `cloud.region`, `cloud.platform`,
  `container.image.name`, `container.image.tags`, route or workflow name,
  dependency name, operation, status code, error class, region, artifact
  version, config version, canary/rollout batch, and low-cardinality outcome.
- Prefer existing OTel semantic-convention or platform resource attribute names
  when the repo already emits them. Recognize legacy or custom names such as
  `deployment.environment`, `deployment.region`, `deployment.platform`, and
  `container.image.tag` as input aliases only; do not newly emit them or invent
  duplicate attributes beside `deployment.environment.name`, `cloud.region`,
  `cloud.platform`, or the platform-provided container image attributes.
- Do not use user, account, tenant, request, session, task, trace, raw URL,
  payload, or high-cardinality IDs as metric attributes or detector group-by keys.

## Incident-Evidence Mode

Use this mode when incidents, alerts, postmortems, tickets, or failure examples
are supplied. Build a coverage matrix before editing:

`incident class -> failure mechanism -> owner -> code surface -> signal -> MTTD impact -> remaining owner`

- Treat the failure mechanism as the target, not the symptom. Endpoint 2xx/5xx
  metrics are not enough when the mechanism is an auth handshake, secret expiry,
  missing or stale output, rollout skew, dependency target loss, queue
  saturation, or streaming lifecycle failure.
- Mark a signal **MTTD-improving** only when it can become a detector before or
  at first customer impact. Mark it **localization-only** when another alert
  already detects the incident and the signal mainly narrows the owner.
- For each app-owned mechanism, add or prove low-cardinality metrics in the
  owning handler, client, worker, queue, limiter, router, health, or lifecycle
  class. If ownership is external, name that owner and the prerequisite signal.
- Do not call incident coverage complete while an app-owned mechanism remains
  only a follow-up unless the user explicitly narrows scope.

## Required Surface Patterns

### Multi-Process Web And Worker Services

When one repository starts a web/API process and one or more background worker
processes:

- Give each process a distinct, operator-overridable `service.name` default
  (for example, `<service>-api` and `<service>-worker`) while sharing stable
  namespace, version, environment, and deployment context where appropriate.
- Configure providers and framework instrumentation only from that process's
  real entrypoint or startup hook. Importing a task module, Celery app, queue
  client, or shared business module from the API must not initialize the
  worker's provider or instrumentations.
- Instrument both sides of enqueue/consume boundaries. Record enqueue success
  only after the broker client returns successfully. On worker exceptions,
  explicitly record failure outcome and span error/exception before rethrowing;
  framework post-run hooks or assumed auto-instrumentation are not proof of the
  app-owned failure signal.
- Add focused tests that execute enqueue success/failure and worker task
  success/failure through an in-memory exporter or an equivalent app-code test
  seam. AST/source-string checks do not prove telemetry. If the configured
  runtime cannot import dependencies, keep the executable tests and report the
  exact restore/import blocker rather than replacing them with static checks.

### Concurrent Go Services

When Go instrumentation touches goroutines, channels, queues, asynchronous
persistence, background indexing, eviction, or observable callbacks, run
`go test -race` for every changed package or record the concrete
toolchain/platform blocker. A normal `go test` pass alone is not the concurrency
verification gate.

For every detector-critical asynchronous outcome or observable gauge added,
the focused test must drive the underlying app state to a non-default value and
assert the emitted datapoint and bounded dimensions. For example, exercise a
saturated or deterministic backpressure path, hold queued work long enough to
observe nonzero depth and oldest-age values, and trigger persistence failure and
capacity eviction when those signals are in scope. Instrument registration,
metric-name presence, and zero-value gauge collection are not proof of the
incident state the detector is meant to catch. If the state cannot be reached
safely with the repo's test seams, report that exact signal as `Not proven` and
keep the verification result `Partial`.

- Executors and queues: queue depth, queue remaining/capacity, active or
  inflight work, pool size/max, queue wait, oldest age, timeout, rejected/shed
  work, and saturation outcome by low-cardinality pool/workflow/dependency.
- Streams and long-lived connections: open/connect, auth result, stream start,
  stop/detach/keepalive, close reason family, send/write failure, active
  connections/channels/streams, duration, and final outcome.
- Input and payload complexity: payload size bucket, input size/complexity
  bucket, item/entity count, metadata count when relevant, parse/validation
  failure, truncation/drop reason, and final outcome.
- Auth, edge, and secrets: login/auth handshake started/completed/failed,
  identity-provider outcome, token/session/domain-routing reason family,
  certificate or secret expiry age, rotation outcome, and config mismatch.
- Jobs and offline/derived data outputs: last-success timestamp, freshness/age,
  duration, output count,
  skipped/dropped reason, publish or delivery outcome, backlog/lag, and oldest
  pending work.
- Synthetic/canary workflow checks: result, latency, failed stage, timeout
  class, no-run/stale-run age, and workflow/environment dimensions.
- Dependency and routing: dependency outcome, timeout, retry, throttle/rate
  limit, circuit-breaker state, endpoint or active-target health, route decision,
  fallback reason, fallback target readiness, and no-route/no-active-target
  outcome.
- Release and deployment/config compatibility: service version,
  artifact/image tag, config version, feature flag, rollout/canary batch,
  schema/migration version when present, expected-vs-running version, rollout
  progress or stalled rollout, compatibility failure class, and decision
  outcome when code or deployment sources expose them.

## Signal Targets

| Area | Useful signals |
|---|---|
| API/workflow | request/workflow duration, count, error count, status code, error class, outcome |
| Customer impact | workflow success/error/degraded/timeout by workflow and environment |
| Dependency | dependency duration/error/timeout/retry/rate-limit, endpoint health, target health, availability, and circuit-breaker state by dependency and operation |
| Freshness | newest event age, ingest lag, processing lag, accepted/dropped count by reason |
| Input complexity | payload size bucket, input size/complexity bucket, item/entity count, metadata count when relevant, parse/validation failure |
| Backpressure | queue depth, consumer lag, oldest message age, rebalance count, paused consumers |
| Synthetic/canary | workflow check result, latency, failed stage, timeout class, no-run/stale-run age |
| Auth/edge | login/auth duration/error, identity provider failure, DNS/TLS/cert/gateway failure |
| Capacity | CPU/memory/disk utilization, inflight work, worker/thread pool, concurrency, quota/throttle, restart/crash-loop, desired-vs-healthy, startup/readiness/healthcheck failure, traffic target health |
| Release context | service version, deployment environment/region/platform, container image tag, artifact version, config version, schema/migration version when present, feature flag, canary/rollout batch |

## Readiness Rules

- If a signal already exists, record its source and whether it is safe for alerting
  and dashboard grouping.
- If a signal is missing, record it as an instrumentation prerequisite for
  `$otel-instrument`; do not imply `$splunk-configure` can create detectors from
  absent metrics.
- If only traces exist, recommend metrics for detector-critical signals such as
  workflow latency, error count, freshness lag, queue lag, dependency failure,
  dependency endpoint health, desired-vs-healthy, readiness failure, and
  capacity saturation.
- If only metrics exist, recommend trace attributes or logs that localize the
  fault domain: workflow, dependency, operation, error class, release/config,
  deployment platform, deployment region, and environment.
