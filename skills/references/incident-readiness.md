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
- Customer-impact workflows: login, search, render/load, checkout/transaction,
  decision/evaluation, notification/delivery, ingestion, export, or sync.
- Dependencies: datastore, cache, search, message broker, object store, cloud API,
  internal service, and third-party client spans with operation, retry, timeout,
  circuit-breaker state, endpoint health, target health, availability, and
  rate-limit/throttle outcomes when available.
- Data freshness: newest event age, ingest lag, processing lag, accepted count,
  dropped count, and drop reason.
- Queue/backpressure: queue depth, consumer lag, oldest message age, rebalance
  count, paused/blocked consumers, worker saturation, and retry/dead-letter rate.
- Auth/edge: login, identity provider, token/session, domain routing, DNS, TLS,
  certificate, gateway, and edge route failures.
- Capacity: memory, heap, CPU, disk/filesystem, thread/worker pool, inflight
  work, concurrency, quota, throttling, rate limit, restart/crash-loop,
  desired-vs-healthy instances, startup/readiness/healthcheck failure, traffic
  target health, and autoscaling saturation.
- Release/config context: `service.version`, `deployment.environment`,
  `deployment.region`, `deployment.platform`, `container.image.tag`, artifact
  version, config version, feature flag, canary/rollout batch, runtime
  environment, and region/zone on spans and metrics when low-cardinality.

## Instrumentation Guidance

- Start with baseline request/job tracing, metrics, resource attributes, context
  propagation, and error status.
- Add workflow spans only at diagnostic boundaries: controller/handler, service
  workflow, dependency call, queue publish/consume, worker job, and scheduled job.
- Emit metrics only from values the service can observe accurately. Do not create
  placeholder instruments for unavailable signals.
- Prefer OTel semantic-convention names for HTTP, RPC, database, messaging, and
  runtime signals. Use custom metrics only when no convention exists.
- Use stable dimensions: `service.name`, `service.version`,
  `deployment.environment`, `deployment.region`, `deployment.platform`,
  `container.image.tag`, route or workflow name, dependency name, operation,
  status code, error class, region, artifact version, config version,
  canary/rollout batch, and low-cardinality outcome.
- Prefer existing OTel semantic-convention or platform resource attribute names
  when the repo already emits them. Treat generic names such as
  `deployment.region`, `deployment.platform`, and `container.image.tag` as
  context aliases, not as a reason to invent duplicate attributes beside proven
  names such as `cloud.region` or platform-provided container image attributes.
- Do not use user, account, tenant, request, session, task, trace, raw URL,
  payload, or high-cardinality IDs as metric attributes or detector group-by keys.

## Incident-Evidence Mode

Use this mode when incidents, alerts, postmortems, tickets, or failure examples
are supplied. Build a coverage matrix before editing:

`incident class -> failure mechanism -> owner -> code surface -> signal -> MTTD impact -> remaining owner`

- Treat the failure mechanism as the target, not the symptom. Endpoint 2xx/5xx
  metrics are not enough when the mechanism is an auth handshake, secret expiry,
  missing report output, rollout skew, dependency active-node loss, queue
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

- Executors and queues: queue depth, queue remaining/capacity, active or
  inflight work, pool size/max, queue wait, oldest age, timeout, rejected/shed
  work, and saturation outcome by low-cardinality pool/workflow/dependency.
- Streams and long-lived connections: open/connect, auth result, stream start,
  stop/detach/keepalive, close reason family, send/write failure, active
  connections/channels/streams, duration, and final outcome.
- Auth, edge, and secrets: login/auth handshake started/completed/failed,
  identity-provider outcome, token/session/domain-routing reason family,
  certificate or secret expiry age, rotation outcome, and config mismatch.
- Jobs, reports, exports, sync, and notifications: last-success timestamp,
  freshness/age, duration, output count, skipped/dropped reason, publish or
  delivery outcome, backlog/lag, and oldest pending work.
- Dependency and routing: dependency outcome, timeout, retry, throttle/rate
  limit, circuit-breaker state, endpoint or active-target health, route decision,
  fallback reason, and no-route/no-active-target outcome.
- Release and config: service version, artifact/image tag, config version,
  feature flag, rollout/canary batch, expected-vs-running version, and decision
  outcome when code or deployment sources expose them.

## Signal Targets

| Area | Useful signals |
|---|---|
| API/workflow | request/workflow duration, count, error count, status code, error class, outcome |
| Customer impact | workflow success/error/degraded/timeout by workflow and environment |
| Dependency | dependency duration/error/timeout/retry/rate-limit, endpoint health, target health, availability, and circuit-breaker state by dependency and operation |
| Freshness | newest event age, ingest lag, processing lag, accepted/dropped count by reason |
| Backpressure | queue depth, consumer lag, oldest message age, rebalance count, paused consumers |
| Auth/edge | login/auth duration/error, identity provider failure, DNS/TLS/cert/gateway failure |
| Capacity | CPU/memory/disk utilization, inflight work, worker/thread pool, concurrency, quota/throttle, restart/crash-loop, desired-vs-healthy, startup/readiness/healthcheck failure, traffic target health |
| Release context | service version, deployment environment/region/platform, container image tag, artifact version, config version, feature flag, canary/rollout batch |

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
