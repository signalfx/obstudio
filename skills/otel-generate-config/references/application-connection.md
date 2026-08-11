# OTel connection contract

## Purpose

`otel-generate-config` separates two trust boundaries:

- Collector-to-Splunk egress owns the Splunk realm and access-token Secret.
- Application-to-Collector routing owns only an in-environment OTLP endpoint.

The application overlay must never receive the Splunk organization token.

## Output contract

The generated `otel-connection.yaml` records:

- schema and generator version;
- application and workspace roots as relative paths from the generated contract
  directory, plus the base resource, workload identity, namespace, and container;
- Collector topology, release, namespace, Service, and collector-side Secret
  reference;
- OTLP protocol, ports, base endpoint, and trace/metric endpoints;
- explicit transport TLS and authentication modes;
- evidence source, evidence SHA-256, and live-verification status.

The Secret reference contains only its Kubernetes name and the chart's expected
key, `splunk_observability_access_token`. It is metadata for the Collector
deployment boundary, not an application credential.

## Service and endpoint rules

With the Splunk OpenTelemetry Collector chart's default naming:

| Topology | Service | Default OTLP/HTTP endpoint |
|---|---|---|
| `gateway` | `<release>-collector` | `http://<service>.<namespace>.svc.cluster.local:4318` |
| `agent-service` | `<release>-collector-agent` | `http://<service>.<namespace>.svc.cluster.local:4318` |

The agent Service uses local traffic policy in current chart releases, so live
verification must ensure every application node has a ready agent endpoint.
Name overrides invalidate derived names; use generated Collector YAML evidence
and pass `--collector-service`.

For OTLP/HTTP, the generic endpoint has no signal suffix. Trace and metric
endpoints append `/v1/traces` and `/v1/metrics`. For gRPC, use port 4317 and no
signal suffixes. Default the cluster domain to `cluster.local`; override it
when the target cluster uses a custom DNS domain.

## Overlay behavior

When the selected base is an existing Kustomization directory, the generated
Kustomize overlay references that base and applies one targeted patch. Before
writing, the generator renders the base locally with `kubectl kustomize` and
requires exactly one matching `apps/v1` workload and exactly one existing
target container. This render does not read a kubectl context or call a cluster.
When the selected base is a raw manifest, the generator validates that manifest
directly and emits a Kustomization `Component` for the application's own overlay
to include; this avoids copying or editing the base and avoids disabling
Kustomize load restrictions. The patch sets:

- `OTEL_SERVICE_NAME`;
- `OTEL_EXPORTER_OTLP_ENDPOINT`;
- `OTEL_EXPORTER_OTLP_PROTOCOL`;
- trace- and metric-specific endpoint/protocol variables.

It does not configure logs unless requested and proven in the Collector
pipeline. It does not include realm, Secret name, Secret key, token headers, TLS
verification bypasses, or Splunk credentials.

## Verification levels

Generation and static validation prove only internal artifact consistency. A
live connection requires separate evidence that:

- the selected Service and named OTLP port exist;
- the Service has ready endpoints for the application placement;
- the Collector receiver listens on that port;
- trace and metric pipelines include the receiver;
- the Collector can export to the requested Splunk realm.

Never claim live connectivity from a syntactically valid DNS name alone.
Static validation requires an exact evidence SHA-256 and matching Service/port
from the generated Collector YAML, but it does not prove a live route.
