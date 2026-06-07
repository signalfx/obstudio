# Observability Report: orders-api

**Language:** Node.js | **Framework:** Express | **Date:** 2026-06-07

## Evidence
- Manifest: `service/package.json`
- Entry point: `service/app.js`
- Route source: `service/app.js`
- Runtime/startup: `service/package.json`
- Deployment/runtime: `chart/Chart.yaml`, `chart/values.yaml`, `chart/templates/deployment.yaml`, `values/prod/orders-api.yaml`, `gitops/application.yaml`, `terraform/main.tf`

## Routes

| Method | Path |
|--------|------|
| GET | /health |
| GET | /orders |
| POST | /orders |

## Current Instrumentation

### Spans

| Name | Source | Type |
|------|--------|------|
| GET /health | existing OTel HTTP instrumentation | auto |
| GET /orders | existing OTel HTTP instrumentation | auto |
| POST /orders | existing OTel HTTP instrumentation | auto |

### Metrics

| Name | Source | Type |
|------|--------|------|
| http.server.request.duration | existing OTel HTTP instrumentation | auto histogram |

### Logs

No OTel log instrumentation detected.

## RED Signals

| Signal | Status | Detail |
|--------|--------|--------|
| Rate | covered | Can be derived from `http.server.request.duration` count. |
| Errors | missing | No span status or error metric evidence is present. |
| Duration | covered | `http.server.request.duration` is available for latency detectors. |

## Deployment Context

| Area | Status | Evidence | Gap |
|------|--------|----------|-----|
| Platform/source | covered | Helm chart, prod values, Argo CD multi-source Application, Terraform `helm_release` | None |
| Service identity | covered | `service.name=orders-api` in Helm values | None |
| Release/config | partial | image tag `1.4.2`, `service.version`, `deployment.rollout.id=batch-20260607` | No explicit config version |
| Health/capacity | partial | readiness probe and CPU/memory requests/limits in deployment template | No restart/crash-loop or platform health metric evidence |
| Export path | covered | `OTEL_EXPORTER_OTLP_ENDPOINT` in deployment template and prod values | None |

## Gaps
- Missing error visibility.
- Missing config version and runtime health metrics for release/capacity detectors.

## Anti-Patterns
- None detected.

## Recommendation
- Run `$otel-instrument` to add error visibility and runtime health metric prerequisites.
