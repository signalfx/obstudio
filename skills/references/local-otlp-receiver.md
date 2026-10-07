# Local OTLP Receiver Contract

Use this reference whenever an audit, instrumentation, or verification workflow
needs a local OTLP destination. Splunk Observability Studio can be the default
local receiver and explorer, and its cloud-compatible gateway may delegate AO
resource and trace requests through its active cloud connection.

## Receiver Receipt Is Not Product Delivery

Sending OTLP to the current Splunk Observability Studio receiver is a local
data-plane transport choice. Receipt alone does not create or select a Splunk
Agent Observability project or Agent Stream or prove cloud delivery. For AO
work, read `splunk-agent-observability.md`: normal SDK calls can resolve or
create resources through the cloud-compatible local gateway, and supported
per-request project/stream headers select the destination for forwarded traces.
Do not substitute a global route-registration setting for those application
bindings. Preserve explicit direct-cloud configuration when selected; do not
require it merely because a local gateway is used.

## Resolve The Effective Receiver

Resolve an endpoint separately for the selected runtime, signal, and protocol.
Use this precedence and stop at the first compatible source:

1. Preserve an explicit signal-specific standard OTel endpoint and protocol
   from application or operator configuration when it is the intended local
   receiver.
2. Preserve a compatible explicit generic `OTEL_EXPORTER_OTLP_ENDPOINT` and
   protocol when it is local or collector-owned. Never let a generic
   direct-cloud endpoint or credential become the implicit application-log
   destination.
3. When the running Obstudio status capability is available, read its
   advertised `endpoints.otlpHttp` and `endpoints.otlpGrpc` values. This is
   configuration-time discovery only; generated application startup must not
   query Studio-specific discovery APIs or MCP. Normal AO SDK calls to the
   configured cloud-compatible API are independent of endpoint discovery.
4. Otherwise inspect checked-in runtime and launch configuration, including
   `OTLP_HOST`, `OTLP_HTTP_PORT` (or legacy `OTLP_PORT`),
   `OTLP_GRPC_HOST`, `OTLP_GRPC_PORT`, Compose/Kubernetes service addresses,
   and editor launch settings. Use the address reachable from the application
   runtime, not necessarily the receiver bind address.
5. Only when no endpoint is configured or discoverable, use the conventional
   host/native fallbacks `http://127.0.0.1:4318` for OTLP/HTTP and
   `127.0.0.1:4317` for OTLP/gRPC.

For OTLP/HTTP, append exactly one `/v1/traces`, `/v1/metrics`, or `/v1/logs`
path when the selected exporter requires a signal-specific URL. Preserve a
configured non-default port and base path; replace a trailing `/v1/<signal>`
leaf instead of stacking a second signal path. Pair gRPC with a gRPC endpoint
and HTTP/protobuf with an HTTP endpoint; never infer one signal's success from
another.

Persist the resolved receiver through standard `OTEL_EXPORTER_OTLP_*`
application or deployment configuration. Do not introduce an Obstudio runtime
library, sidecar discovery call, route-registration call, or startup port probe.
Gateway unavailability can prevent configured cloud export, as with any
collector; distinguish that export failure from application business behavior.
Do not promise an independent direct cloud route unless one was selected and
configured.

## Verification

Exercise the effective endpoint/protocol/path tuple for every configured
signal. At least one deterministic check must use a non-default local port so
hardcoded `4317` or `4318` behavior cannot pass. Prove that:

- the application exports to the resolved non-default endpoint;
- no startup code queries Obstudio to obtain or register a route;
- local receiver evidence is described as local OTLP proof, not cloud Agent
  Observability visibility; and
- any selected AO gateway path exercises normal resource calls and per-request
  routing, then proves the fresh trace in the intended cloud project/stream.
