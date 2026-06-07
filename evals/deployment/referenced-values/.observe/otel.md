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

No spans detected.

### Metrics

No metrics detected.

### Logs

No OTel log instrumentation detected.

## RED Signals

| Signal | Status | Detail |
|--------|--------|--------|
| Rate | missing | No request count metric or span source is present. |
| Errors | missing | No span status or error metric evidence is present. |
| Duration | missing | No request-duration metric or span source is present. |

## Deployment Context

| Area | Status | Evidence | Gap |
|------|--------|----------|-----|
| Platform/source | partial | Helm chart at chart/; Argo CD Application at gitops/application.yaml; Terraform helm_release at terraform/main.tf | Argo CD references $env/prod/orders-api.yaml and Terraform references ../env-values/prod/orders-api.yaml, but the env values source is referenced but not inspected |
| Service identity | covered | chart/values.yaml sets otel.resourceAttributes.service.name=orders-api | none |
| Release/config | unknown | chart image tag exists; env values source may override image, environment, region, config, or rollout attributes | referenced env values source not inspected |
| Health/capacity | partial | chart/templates/deployment.yaml has readinessProbe and memory/cpu settings | runtime health metrics are not proven |
| Export path | unknown | no OTLP endpoint in inspected chart values | referenced env values source not inspected |

## Gaps

- Missing Express auto-instrumentation and SDK initialization.
- Missing HTTP duration/error metrics.
- Missing deployment.environment and region attributes in inspected sources.
- Referenced values source is not inspected; do not treat its dimensions as available.
