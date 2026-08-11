# Collector deployment contract

Use this contract for every generated Collector configuration.

## Supported outputs

Generate two related deployment paths:

1. `collector-config.yaml`: a standalone Splunk Distribution of the
   OpenTelemetry Collector configuration for receiving OTLP metrics and traces
   and exporting them to Splunk Observability Cloud.
2. `kubernetes/collector.yaml`: plain Kubernetes resources generated directly
   from the public inputs.

Do not generate `helm/`, `helm-rendered.yaml`, render provenance, or any
optional rendered artifact. The application route must be bound to
`kubernetes/collector.yaml`.

Default Collector namespace, release, topology, and cluster domain are
`observability`, `splunk-otel`, `gateway`, and `cluster.local`.

## Kubernetes YAML contract

Write `kubernetes/collector.yaml`. It must contain:

- one ConfigMap using the Collector workload name
  (`<release>-collector` for gateway topology or
  `<release>-collector-agent` for agent-service topology);
- one Service named `<release>-collector` for gateway topology or
  `<release>-collector-agent` for agent-service topology;
- one Collector Deployment using the pinned Splunk Collector image tag requested
  with `--collector-version`;
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
├── kubernetes/
│   ├── collector.yaml
│   └── splunk-secret.example.yaml
└── DEPLOYMENT.md
```

Regeneration with `--overwrite` removes stale legacy render and Helm artifacts
so they cannot be mistaken for current generated output.

## Validation contract

Run, in order:

1. Included Collector static validator.
2. Included application static validator.
3. Included coordinated validator for shared inputs and generated-YAML evidence.
4. `kubectl kustomize` as an offline application-overlay render when available.
5. A recursive secret scan across both outputs.

Do not run `kubectl apply` as part of ordinary generation. Static validation
does not prove live Service readiness or Splunk Observability Cloud receipt.

## Primary references

- Splunk YAML manifest installation:
  https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/collector-for-kubernetes/install-with-yaml-manifests
- Splunk OTLP/HTTP exporter:
  https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/collector-components/exporters/otlphttp-exporter
- OpenTelemetry Collector configuration:
  https://opentelemetry.io/docs/collector/configuration/
