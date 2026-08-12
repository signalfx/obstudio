---
name: otel-generate-config
description: >-
  Generate a coordinated OpenTelemetry configuration set for Splunk
  Observability Cloud: token-free, version-pinned Collector Helm files,
  plain Kubernetes YAML, a standalone Collector config, and a matching
  non-secret Kubernetes application Kustomize overlay or workload scaffold. Use when
  a user invokes $otel-generate-config, asks for Collector Helm files or YAML plus
  application configuration, needs the correct in-cluster OTLP endpoint, or
  wants deploy-ready configuration files without deploying them.
---

# Generate OpenTelemetry configuration

Generate one reviewable configuration set for the Collector and application.
The Collector generator writes Helm files from local templates, plain
Kubernetes YAML directly, and a standalone Collector config. The application
configuration targets the Service proven by the generated Kubernetes YAML. If
the app has no Kubernetes base, generate a reviewable workload scaffold instead
of stopping before writing configuration.

This skill only generates and validates local files. Never deploy resources,
create or inspect Secrets, query Splunk Observability Cloud, or claim live
connectivity.

## Accept the request

Accept this user-facing invocation:

```text
$otel-generate-config \
  --app ./checkout \
  --platform kubernetes \
  --realm us0 \
  --cluster-name checkout-prod \
  --environment production \
  --distribution other \
  --chart-version 0.157.0 \
  --existing-secret splunk-otel-token
```

`--app` is optional. Resolve it in this order:

1. Use the explicit path relative to the invocation directory.
2. Use the application already established by the task context.
3. Use the current directory only when it contains one unambiguous runnable
   application.
4. Ask the user when a repository contains multiple possible applications.

Resolve `<workspace>` as the containing repository root when one exists.
Otherwise use the resolved application root. Do not treat an orchestration,
temporary, or parent runner directory as the workspace merely because it is
the process working directory. With no explicit `--app` and no repository
root, both default output trees therefore live under the current application.

Treat every flag as generation intent, never as permission to access a cluster
or cloud service. Accept a Kubernetes Secret name, not a token. Never accept a
`--token` flag or ask for, read, print, copy, decode, or write token bytes.
Default omitted Collector routing values to namespace `observability`, release
`splunk-otel`, topology `gateway`, and cluster domain `cluster.local`. Accept
explicit overrides only when the user supplies them or the repository/environment
clearly requires them.

## Inspect before writing

Read the repository and application `AGENTS.md` files plus existing Helm,
Kubernetes, and GitOps sources. Prefer an existing application target:

- Kubernetes `Deployment`, `StatefulSet`, or `DaemonSet`;
- workload namespace and name;
- exactly one application container after ignoring known sidecars;
- a raw workload manifest or an existing Kustomization base;

When no raw workload manifest, Helm chart, or Kustomization base exists, do not
block all generation. Generate the Collector configuration and generate an
application scaffold when one application identity can be resolved from repo
evidence such as a service manifest, Dockerfile, Java main class, README, open
ports, or package metadata. Infer workload/container names only from concrete
repo evidence; otherwise use the repo/service name and clearly mark the output
as a scaffold requiring review. Ask only if multiple applications or conflicting
names are present.

Resolve these public inputs before generating:

- Splunk realm, cluster name, environment, Collector namespace and release;
- Kubernetes distribution and exact Collector chart version;
- `gateway` or `agent-service` topology;
- Collector-only Secret name.

Collector release names are limited to 47 characters. The generated Service
suffixes must still fit Kubernetes' 63-character DNS-label limit.

Inspect existing `OTEL_EXPORTER_*`, `OTEL_SERVICE_NAME`, and `SPLUNK_*`
environment entries. Report material conflicts instead of silently producing
duplicate settings. Do not overwrite an existing generated configuration until
its changes have been inspected and replacement is explicitly in scope.

Read both contracts before continuing:

- [references/collector-deployment.md](references/collector-deployment.md)
- [references/application-connection.md](references/application-connection.md)

## Generate the Collector configuration

Default the Collector output to `<workspace>/deploy/otel-collector`. Run the
included generator rather than rewriting templates:

```bash
python3 <skill-dir>/scripts/generate_collector.py \
  --output <workspace>/deploy/otel-collector \
  --realm <realm> \
  --cluster-name <cluster-name> \
  --environment <environment> \
  --existing-secret <secret-name> \
  --distribution <distribution> \
  --chart-version <exact-chart-version> \
  --topology <topology>
```

`--collector-version` is accepted as an alias for `--chart-version`; prefer
`--chart-version` when generating Helm files.

Omit `--namespace`, `--release-name`, and `--topology` when using the defaults:
`observability`, `splunk-otel`, and `gateway`. Pass `--topology agent-service`
only when the application will route to the generated agent Service. Use
`--overwrite` only after confirming the existing generator-managed files may be
replaced. Regeneration deliberately removes stale legacy render artifacts and
Helm dependency artifacts such as `Chart.lock` and cached chart archives.

Run the static validator after generation:

```bash
python3 <skill-dir>/scripts/validate_collector.py \
  <workspace>/deploy/otel-collector
```

The Collector Kubernetes manifest is generated directly at:

```text
<workspace>/deploy/otel-collector/kubernetes/collector.yaml
```

Do not run Helm to generate the Helm files or Kubernetes YAML. The generator
must write `helm/Chart.yaml`, `helm/values.yaml`, and
`helm/examples/splunk-secret.yaml` from local templates. Do not create
`helm-rendered.yaml`, `helm-rendered.provenance.json`, or any equivalent
optional render artifact.

The generated `DEPLOYMENT.md` must include optional local kind smoke-test
commands for users to run after generation. Keep those commands user-run only:
the skill must not create kind clusters, create Secrets, apply Kubernetes YAML,
send telemetry, query Splunk, or treat absence of collector log errors as cloud
query proof.

## Generate the matching application configuration

Default application output to `<app>/deploy/otel-config`. For gateway topology,
the default Service is `<collector-release>-collector`; for agent-service it is
`<collector-release>-collector-agent`.

Pass the generated Collector YAML as Collector evidence.
The generator requires one matching Service and named OTLP port, then records
the evidence SHA-256 in the connection contract:

```bash
python3 <skill-dir>/scripts/generate_application.py \
  --app <resolved-app> \
  --workspace-root <workspace> \
  --platform kubernetes \
  --realm <realm> \
  --existing-secret <secret-name> \
  --collector-evidence <workspace>/deploy/otel-collector/kubernetes/collector.yaml \
  --base <application-base> \
  --application-namespace <application-namespace> \
  --workload-kind <kind> \
  --workload-name <name> \
  --container <container>
```

If there is no application base, run the same generator without `--base` or pass
`--scaffold-workload` explicitly:

```bash
python3 <skill-dir>/scripts/generate_application.py \
  --app <resolved-app> \
  --workspace-root <workspace> \
  --platform kubernetes \
  --realm <realm> \
  --existing-secret <secret-name> \
  --collector-evidence <workspace>/deploy/otel-collector/kubernetes/collector.yaml \
  --scaffold-workload \
  --application-namespace <namespace> \
  --workload-kind Deployment \
  --workload-name <name> \
  --container <container> \
  --image <reviewed-image-or-placeholder> \
  --container-port <port>
```

For scaffold mode, use the best repo evidence for namespace, workload name,
container, image, and port. If the image is not knowable from the repo, use a
clear non-secret placeholder such as
`example.invalid/<service>:replace-at-deploy-time` and report that the scaffold
is not production-ready until image and platform settings are reviewed.

The Secret name is recorded only in the non-deployable connection contract as
Collector-boundary metadata. It must never appear in the application patch or
Pod configuration. Add `--collector-service` only when a verified generated
Collector YAML override changes the Service name. Omit `--collector-namespace`,
`--collector-release`, `--topology`, and `--cluster-domain` when using the
defaults. Default to OTLP/HTTP on port 4318.

For a Kustomization base, the generator performs a local `kubectl kustomize`
render before writing and requires exactly one matching workload with exactly
one existing target container. This command reads local files only; it does not
read a kubectl context or contact a cluster. A missing, ambiguous, or invented
container is a blocking error for existing-base mode.

For scaffold mode, the generator writes `kubernetes/workload.yaml` plus the
same OTel environment patch and records `overlayMode: "scaffold"` in
`otel-connection.yaml`. Treat scaffold output as a reviewable starting point:
the user must confirm image, resources, probes, service account, secrets,
rollout settings, and any platform-specific scheduling constraints before
deployment.

Run the application validator:

```bash
python3 <skill-dir>/scripts/validate_application.py \
  <app>/deploy/otel-config
```

Then run the coordinated validator against both output trees:

```bash
python3 <skill-dir>/scripts/validate_config.py \
  --collector <workspace>/deploy/otel-collector \
  --application <app>/deploy/otel-config
```

When the selected base is a Kustomization directory, run `kubectl kustomize`
against the generated overlay as an offline render only. Do not run any
`kubectl apply` or cluster-reading command.

## Validate the coordinated result

Before finishing, verify all of these invariants:

- realm, namespace, release, topology, and Secret name agree across contracts;
- the generated Collector Service name and named OTLP port match the application contract;
- OTLP/HTTP endpoints use
  `service.namespace.svc.cluster.local:4318`, `/v1/traces`, and `/v1/metrics`
  unless a custom cluster domain is supplied;
- the generated Collector YAML evidence hash in `otel-connection.yaml` matches
  `kubernetes/collector.yaml`;
- the application patch contains no realm, Secret name/key, token, `X-SF-Token`,
  `secretKeyRef`, or TLS-verification bypass;
- only example Secret files contain `REPLACE_AT_DEPLOY_TIME`;
- no generated file contains a literal token or unresolved placeholder;
- application source and base deployment files remain unchanged, except for
  generated scaffold files under `<app>/deploy/otel-config` when scaffold mode
  is used.

Any failed generator, validator, Kustomize build, or secret scan is a blocking
defect. Do not describe an incomplete output as
deploy-ready.

## Output and handoff

The completed configuration is:

```text
<workspace>/deploy/otel-collector/
├── collector-config.yaml
├── DEPLOYMENT.md
├── helm/
│   ├── Chart.yaml
│   ├── values.yaml
│   └── examples/splunk-secret.yaml
└── kubernetes/
    ├── collector.yaml
    └── splunk-secret.example.yaml

<app>/deploy/otel-config/
├── otel-connection.yaml
└── kubernetes/
    ├── kustomization.yaml
    ├── otel-env-patch.yaml
    └── workload.yaml          # scaffold mode only
```

Report the resolved application, workload/container, Collector endpoint, chart
version, output paths, checks run, and whether the application output is
existing-base mode or scaffold mode. Mention that the generated
`DEPLOYMENT.md` includes optional user-run kind smoke steps. End with this
explicit boundary:

```text
Configuration files were generated and validated locally. No resources were
deployed, and live Collector or Splunk Observability Cloud delivery was not
verified.
```

Do not instrument application code, deploy either configuration, create
Secrets, query Splunk, or create dashboards and detectors as part of this skill.
