# Observability Report: orders-api

**Language:** Node.js | **Framework:** Express | **Date:** 2026-06-07

## Evidence

- Manifest: service/package.json
- Entry point: service/app.js
- Route source: service/app.js
- Runtime/startup: none detected
- Deployment/runtime: chart/, gitops/application.yaml, terraform/main.tf

## Routes

| Method | Path |
|--------|------|
| GET | /health |
| GET | /orders/{id} |

## Current Instrumentation

### Spans

| Name | Source | Type |
|------|--------|------|
| GET /orders/{id} | existing HTTP server instrumentation | auto |
| HTTP GET payments | existing HTTP client instrumentation | auto |
| db.query orders | existing database client instrumentation | auto |

### Metrics

| Name | Source | Type |
|------|--------|------|
| http.server.request.duration | existing HTTP server instrumentation | auto histogram |
| http.client.request.duration | existing HTTP client instrumentation | auto histogram |
| db.client.operation.duration | existing database client instrumentation | auto histogram |

### Logs

No OTel log instrumentation detected.

## RED Signals

| Signal | Status | Detail |
|--------|--------|--------|
| Rate | covered | Can be derived from request-duration histogram counts. |
| Errors | partial | Spans exist, but dependency error classification is not proven. |
| Duration | covered | Server, HTTP client, and database duration histograms are available. |

## Deployment Context

| Area | Status | Evidence | Gap |
|------|--------|----------|-----|
| Platform/source | partial | Helm chart at chart/; Argo CD Application at gitops/application.yaml; Terraform helm_release at terraform/main.tf | Argo CD references $deps/prod/orders-api-dependencies.yaml and Terraform references ../dependency-values/prod/orders-api-dependencies.yaml, but the dependency values source is referenced but not inspected |
| Service identity | missing | No service.name or OTEL_SERVICE_NAME in inspected sources | Add service identity in app/startup/deployment config |
| Release/config | partial | chart image tag 2.1.0 is present | config version and rollout id may live in referenced dependency values source |
| Dependency config | partial | app uses PAYMENTS_API_URL, PAYMENTS_TIMEOUT_MS, PAYMENTS_RETRY_POLICY, PAYMENTS_CIRCUIT_BREAKER, DATABASE_URL, and DB_POOL_MAX; chart maps timeout, retry policy, circuit breaker, pool max, ConfigMap ref, and Secret ref | referenced dependency values source not inspected; endpoint value, provider region, database URL value, credential reference target, and dependency config version are unknown |
| Dependency health | missing | HTTP client and database duration metrics exist, but no endpoint health, target health, unhealthy target, timeout count, or rate-limit metric is proven | add dependency endpoint health or platform target health metrics before endpoint-health detectors |
| Health/capacity | partial | readinessProbe exists; DB_POOL_MAX is configured | no runtime pool saturation, disk saturation, desired-vs-healthy, dependency availability, or platform health metrics are proven |
| Export path | missing | no OTLP endpoint in inspected deployment sources | add collector/export config |

## Gaps

- Missing service identity and export path.
- Dependency endpoint values, provider region, and config version are referenced but not inspected.
- Dependency endpoint health is not proven by deployment config alone.
- Dependency timeout/retry/circuit-breaker source names are visible, but detector dimensions must avoid full URLs and secret values.
