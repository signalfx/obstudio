# Deployment Context Readiness Reference

Load this reference when a task mentions deployment/runtime observability, Helm,
values files, GitOps, Terraform, serverless, VM, container runtime, release/config
context, health checks, capacity, rollout, or when deployment artifacts are found.

## Goal

Connect application telemetry to the runtime source of truth so alerts and
dashboards can answer:

- Which version, environment, region, rollout, or config is affected?
- Is the app code failing, or is the runtime unhealthy?
- Is a dependency failing, or is the dependency endpoint, region, timeout,
  retry, circuit breaker, credential reference, or egress route misconfigured?
- Are failures tied to health checks, restarts, capacity, target health, or deploys?
- Which repository should be changed: app code, chart, values, GitOps, IaC, or runtime config?

## Discovery

Inspect the current repo first, then any user-supplied paths. Do not guess or
clone private deployment repos. If app code exists but deployment sources are not
discoverable, pause before finalizing the audit or instrumentation plan and ask
once for chart, values, GitOps, IaC, CI/CD, or runtime paths. Ask for local paths
or URLs and give examples such as `./chart`, `./values`, `./gitops`,
`./terraform`, a Helm chart repo, an environment-values repo, or a deployment
pipeline path. If paths are not provided, mark deployment context as `unknown`,
not `missing`.

Common sources:

| Platform/source | Files or resources |
|---|---|
| Docker Compose | `docker-compose.yml`, `.env.example`, service `healthcheck`, image/env blocks |
| Kubernetes raw manifests | `Deployment`, `StatefulSet`, `DaemonSet`, `Job`, `CronJob`, `Service`, `Ingress` |
| Helm | `Chart.yaml`, `values*.yaml`, `templates/*.yaml`, `helmfile.yaml` |
| Kustomize | `kustomization.yaml`, base/overlay patches, generated ConfigMaps/Secrets |
| GitOps | Argo CD `Application`/`ApplicationSet`, Flux `HelmRelease`, `GitRepository`, `Kustomization` |
| IaC | Terraform `helm_release`, Kubernetes provider resources, Pulumi/CDK deploy definitions |
| ECS/Fargate | task definitions, service definitions, target groups, Terraform/CDK/SAM wrappers |
| Serverless | Lambda/SAM/CDK/Serverless Framework, Cloud Run/App Runner service config |
| VM/process | systemd units, Supervisor, launchd, Procfile, shell wrappers, AMI/image metadata |
| Nomad/batch | Nomad jobs, Cron, Airflow DAGs, scheduled tasks, batch job specs |
| Edge/gateway | Ingress, ALB/NLB/API Gateway, Envoy/Istio/Linkerd/NGINX config |
| OTel Operator | `Instrumentation` CRs, workload auto-instrumentation annotations |

## Reference Resolution

Deployment sources often point to other runtime sources. Follow references that
are visible in inspected files, but do not clone private repos or invent local
paths. If a referenced source is not present in the workspace or supplied paths,
pause before writing the audit or instrumentation output and ask once for the
local path or URL. Name the referenced source from the inspected file, such as a
chart path, values file, GitOps repo/path, IaC module, CI/CD template,
environment file, ConfigMap, Secret, tfvars, stack config, or deployment
pipeline. If the user provides paths, inspect them and continue. If the user
declines or asks to continue without them, record the source as `referenced but
not inspected` and mark the affected deployment context as `unknown`, not
`missing`.

Common reference patterns:

| Source | References to resolve |
|---|---|
| Helm | `values*.yaml`, `helmfile.yaml`, `--values`, `-f`, `valuesFrom` |
| Argo CD | `sources[]`, `repoURL`, `path`, `ref`, `helm.valueFiles`, `ApplicationSet` generators |
| Flux | `HelmRelease.valuesFrom`, `GitRepository`, `Kustomization`, `OCIRepository` |
| Terraform/Pulumi/CDK | `helm_release.values`, `set`, `set_sensitive`, `tfvars`, stack config |
| Kubernetes | `configMapRef`, `secretRef`, projected volumes, mounted config files |
| Docker Compose | `env_file`, `.env`, extension files passed with multiple `-f` flags |
| ECS/Fargate | task definition env files, SSM/Secrets Manager refs, service/task modules |
| Serverless | stage config, parameter refs, secret refs, provider-specific env files |
| VM/process | `EnvironmentFile`, Supervisor includes, Procfile wrappers, launch scripts |
| CI/CD | deploy scripts, release workflows, chart path, values path, image tag source |

## Dependency Config Mapping

When app code or manifests show outbound dependencies, map those dependencies to
deployment-owned configuration before deciding what is covered. Track source
names and references, not secret values.

Look for:

- Dependency endpoints or aliases: database/cache/search/broker/API base URLs,
  host aliases, service discovery names, queue/topic/stream names, provider
  deployment names, or egress routes.
- Runtime behavior config: timeout, retry count/backoff, circuit breaker state,
  connection pool, concurrency, batch size, and rate-limit settings.
- Provider placement: region, realm, zone, account/project, cluster, namespace,
  gateway, service mesh route, or cloud/provider deployment.
- Config provenance: ConfigMap/Secret reference names, parameter-store refs,
  values files, tfvars, stack config, feature flag/config version, or rollout id.

If an app dependency is detected but the deployment config source that owns its
endpoint, timeout, retry, circuit breaker, region, or credential reference is
not inspected, mark dependency config as `unknown` with `referenced but not
inspected` evidence. Do not mark the dependency signal as missing just because
the values repo, secret provider, tfvars, or release config repo is unavailable.

## Status Semantics

- `covered`: inspected source configures the signal.
- `partial`: some context exists, but key dimensions or runtime signals are absent.
- `missing`: inspected source proves the signal is absent.
- `unknown`: deployment source was not found or not provided.

Do not turn `unknown` into a detector. Ask for source paths or report a
prerequisite.

## Runtime Signal Checklist

Prefer stable, low-cardinality resource attributes, env vars, labels, or metric
dimensions:

| Area | Useful signals |
|---|---|
| Identity | `service.name`, namespace/app label, task/function/service name |
| Environment | `deployment.environment`, `deployment.region`, `cloud.region`, realm, region, zone, cluster, namespace |
| Platform | `deployment.platform`, platform/source, runtime workload type, orchestrator, cloud provider, cluster/namespace |
| Release/config | `service.version`, `container.image.tag`, image tag/digest, artifact version, config version, rollout/canary/batch id |
| Dependency config | dependency endpoint alias, dependency type/name, timeout, retry, circuit breaker, pool/concurrency, provider region/deployment, config ref/version |
| Dependency health | dependency endpoint health, target health, dependency availability, error/timeout/rate-limit counts, unhealthy target count |
| Export path | OTLP endpoint/protocol/headers, collector gateway, OTel Operator instrumentation |
| Health | readiness/liveness/startup checks, healthcheck command, target group health |
| Capacity | CPU/memory/disk limits, filesystem pressure, concurrency, queue workers, autoscaling, quotas, throttles |
| Runtime health | restart count, crash loop, desired vs healthy instances, stopped task reason |
| Edge | TLS/cert expiry, DNS/domain routing, gateway route, upstream target health |
| Jobs | missed runs, late runs, failed runs, duration, retries, oldest queued work |

Never use user, tenant, account, request, session, trace, raw pod, raw container,
raw URL, payload, or secret values as detector group-by dimensions.

Use existing OTel semantic-convention or platform resource attribute names when
the repo already emits them. Treat generic names such as `deployment.region`,
`deployment.platform`, and `container.image.tag` as context aliases, not as a
reason to invent duplicate attributes beside proven names such as `cloud.region`
or platform-provided container image attributes.

## Patch Location Rules

- Patch app code for spans, metrics, SDK initialization, and semantic-convention attributes.
- Patch startup wrappers or Docker Compose for local/runtime env vars.
- Patch Helm templates only when the chart lacks reusable OTel knobs.
- Patch values repos for environment-specific values such as realm, collector
  endpoint, resource attributes, image tag, environment, and rollout metadata.
- Patch GitOps/IaC only when it owns the deployed state or chart values.
- Patch dependency config where it is already owned: app config for local
  defaults, values/tfvars/stack config for environment-specific dependency
  endpoints, and GitOps/IaC only when those sources own the deployed values.
- Patch OTel Operator resources/annotations when auto-instrumentation is the
  platform standard.
- Do not hardcode production tokens or private collector endpoints in tracked files.

## Detector Guidance

Create detectors only from available metrics. Deployment context should usually
shape filters, group-by dimensions, dashboard filters, and prerequisites rather
than create standalone alerts.

Examples:

- Use `deployment.environment`, `deployment.region`, `cloud.region`, or
  `k8s.namespace.name` to split latency/error detectors when those dimensions
  exist.
- Use `deployment.platform` or platform/source dimensions for dashboards and
  detector filters only when the value is stable and low-cardinality.
- Use `service.version`, `container.image.tag`, artifact version, config
  version, or rollout id for dashboards and release correlation, not as a
  standalone alert.
- Use dependency dimensions only when proven and low-cardinality, such as
  dependency type/name, sanitized endpoint alias, provider region, gateway, or
  config version. Do not use full URLs, credentials, raw hosts with tenant/user
  data, request payloads, or secret values.
- Use platform or dependency health metrics for restart, crash-loop,
  desired-vs-running, startup/readiness failure, healthcheck failure,
  unhealthy-target, dependency endpoint health, throttle, quota, disk pressure,
  or capacity detectors when available.
- If health/capacity metrics are not exposed in the audit, list them as
  prerequisites for `otel-instrument` or platform telemetry setup.
