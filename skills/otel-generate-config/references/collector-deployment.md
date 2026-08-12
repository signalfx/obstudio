# Collector deployment contract

Use this contract for every generated Collector configuration.

## Supported outputs

Generate three related deployment paths:

1. `collector-config.yaml`: a standalone Splunk Distribution of the
   OpenTelemetry Collector configuration for receiving OTLP metrics and traces
   and exporting them to Splunk Observability Cloud.
2. `helm/`: a version-pinned wrapper around the official
   `splunk-otel-collector` chart, generated from local templates without
   invoking Helm.
3. `kubernetes/collector.yaml`: plain Kubernetes resources generated directly
   from the public inputs.

Do not generate `helm-rendered.yaml`, render provenance, or any optional
rendered artifact. The application route must be bound to
`kubernetes/collector.yaml`.

Default Collector namespace, release, topology, and cluster domain are
`observability`, `splunk-otel`, `gateway`, and `cluster.local`.

## Helm file contract

Write these files directly from templates:

```text
helm/Chart.yaml
helm/values.yaml
helm/examples/splunk-secret.yaml
```

Do not call `helm`, fetch chart repositories, run `helm dependency update`, or
render chart manifests during generation or validation. Helm is only a
deployment-time option for the user after the files are generated.

Use this chart repository in `helm/Chart.yaml`:

```text
https://signalfx.github.io/splunk-otel-collector-chart
```

Pin an exact released chart version in `helm/Chart.yaml`. Do not use a range,
wildcard, or `latest`.

Configure the values with:

```yaml
splunkObservability:
  realm: <realm>
  metricsEnabled: true
  tracesEnabled: true
secret:
  create: false
  name: <secret-name>
  validateSecret: true
```

The chart values do not use an `existingSecret` key. Do not write a non-empty
`splunkObservability.accessToken`.

## Kubernetes YAML contract

Write `kubernetes/collector.yaml`. It must contain:

- one ConfigMap using the Collector workload name
  (`<release>-collector` for gateway topology or
  `<release>-collector-agent` for agent-service topology);
- one Service named `<release>-collector` for gateway topology or
  `<release>-collector-agent` for agent-service topology;
- one Collector Deployment using a pinned Splunk Collector image tag derived
  from the requested chart version;
- named OTLP ports `otlp` on 4317 and `otlp-http` on 4318;
- `SPLUNK_REALM` as a non-secret environment value;
- `SPLUNK_ACCESS_TOKEN` loaded from the existing Kubernetes Secret key
  `splunk_observability_access_token`.

The generated Kubernetes YAML is deployable, but generation must not deploy it
or query a cluster.

## Secret contract

Never put real token bytes in generated files, command output, logs, or final
responses. Require an ingest-scoped Splunk Observability Cloud organization
token at deployment time.

Pre-create an `Opaque` Secret in the release namespace with exactly this key:

```text
splunk_observability_access_token
```

Generate only example Secrets containing `REPLACE_AT_DEPLOY_TIME`.

Generated handoff commands should prefer `kubectl create secret --from-file` fed
from stdin over `--from-literal` so token bytes are not placed directly in the
kubectl process arguments.

## Endpoint and signal contract

Use the current Observability Cloud domains:

```text
https://ingest.${env:SPLUNK_REALM}.observability.splunkcloud.com/v2/trace/otlp
https://ingest.${env:SPLUNK_REALM}.observability.splunkcloud.com/v2/datapoint/otlp
```

Authenticate the standalone config with:

```yaml
headers:
  X-SF-Token: "${env:SPLUNK_ACCESS_TOKEN}"
```

Default to metrics and traces. Splunk Observability Cloud is not a general
application-log destination. Add logs only when the user separately supplies
the Splunk Platform/Cloud HEC destination, token-secret contract, and index.

Every standalone pipeline must have an OTLP receiver, `memory_limiter` before
`batch`, and the Splunk exporter. Enable `health_check`.

## Output contract

Write:

```text
<output>/
├── collector-config.yaml
├── helm/
│   ├── Chart.yaml
│   ├── values.yaml
│   └── examples/splunk-secret.yaml
├── kubernetes/
│   ├── collector.yaml
│   └── splunk-secret.example.yaml
└── DEPLOYMENT.md
```

Regeneration with `--overwrite` removes stale legacy render artifacts,
`Chart.lock`, and cached dependency archives so they cannot be mistaken for
current generated output.

## Validation contract

Run, in order:

1. Included Collector static validator.
2. Included application static validator.
3. Included coordinated validator for shared inputs and generated-YAML evidence.
4. `kubectl kustomize` as an offline application-overlay render when available.
5. A recursive secret scan across both outputs.

Do not run `kubectl apply` as part of ordinary generation. Static validation
does not prove live Service readiness or Splunk Observability Cloud receipt.

## Local kind smoke handoff

`DEPLOYMENT.md` should include optional user-run kind smoke steps that:

- create or target a local kind cluster;
- create the Collector token Secret from stdin, not from literal command
  arguments;
- apply only `kubernetes/collector.yaml`;
- wait for `deployment/<collector-workload>` to roll out;
- render any generated application overlay separately instead of applying a
  scaffold application;
- send traces and a unique metric through the Collector Service using
  `ghcr.io/open-telemetry/opentelemetry-collector-contrib/telemetrygen:v<version>`;
- inspect Collector logs for `Exporting failed`, `Unauthenticated`, or
  `error exporting`;
- optionally query `https://api.<realm>.observability.splunkcloud.com` with a
  separate API-capable token.

State the boundary clearly: Collector readiness plus no exporter errors is a
local smoke test, not full Splunk Observability Cloud query proof. HTTP 401 from
the ingest endpoint means the Secret token is not accepted for that realm. HTTP
401 from the API endpoint means the query token is not accepted for the Splunk
Observability API.

## Primary references

- Splunk chart repository:
  https://github.com/signalfx/splunk-otel-collector-chart
- Splunk YAML manifest installation:
  https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/collector-for-kubernetes/install-with-yaml-manifests
- Splunk OTLP/HTTP exporter:
  https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/collector-components/exporters/otlphttp-exporter
- OpenTelemetry Collector configuration:
  https://opentelemetry.io/docs/collector/configuration/
