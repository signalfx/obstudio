# Existing OTel Agent Demo

This local support agent has incomplete agent, tool, and retrieval coverage.
It exercises the distinction between preserving an existing producer and adding
missing operations. All model, retrieval, and order responses are deterministic
and local. The fixture has no Splunk AO or Galileo dependency.

| Mode | Existing runtime signals |
|---|---|
| `generic` | Generic HTTP-like workflow/model spans, counter, OTel audit logs |
| `genai` | Existing workflow/chat GenAI spans, counter, OTel audit logs |
| `metrics` | Real OTel counter/provider/exporter only |
| `logs` | Real OTel log provider/exporter only |
| `none` | Ordinary stdout only; no OTel producer |

The `generic` and `genai` modes own their tracer, meter, and logger providers,
processors, and OTLP/HTTP exporters. The existing trace producer has a supported
`span_hooks` interface for enriching existing workflow/model spans. Its
`requests.Session` is available as `app.trace_session`; its public headers API
can customize trace transport without replacing an exporter. The agent exposes
`operation_hooks` context managers for uncovered lifecycle operations. Hooks
receive an operation name and metadata, including request identity, scenario,
and the applicable agent, tool, data-source, or model identity.
The mutable metadata also exposes actual `inputs`; successful business calls
set `result` and `result_available=True` before hook exit. A failed or cancelled
call leaves `result_available=False` and has no result. This lets an integration
derive safe structured content from real values after the operation, including
on existing workflow/model spans, without inventing model-to-tool IDs.

No solution instrumentation module is included. An actor must implement its own
`configure(app)` module and choose appropriate hooks for the proven gaps. The
probe invokes configure and start twice, runs successful, tool-error,
provider-error, and cancelled turns, then shuts down twice.

From this directory:

```sh
uv run python probe.py capture --mode generic --output /tmp/existing-before.json
uv run python probe.py capture --mode generic --instrumentation ./instrumentation.py --output /tmp/existing-after.json
uv run python probe.py compare /tmp/existing-before.json /tmp/existing-after.json --target-contract studio --project-id selected-project --stream-id selected-stream
```

`capture` supplies an isolated loopback OTLP receiver and removes ambient OTel
and vendor endpoints/credentials during the run. It records decoded protobuf
receipts, not a mocked exporter invocation. Ambient environment is restored on
return. The comparison requires existing span IDs, names, attributes, events,
resource and status fields; retained original objects; unchanged metric/log
values; exactly one copy of each expected operation; connected parentage; and
one upstream trace request. Existing spans may acquire an intermediate parent
when an uncovered agent operation is added. Trace routing must retain the
existing transport headers and use either Studio `projectid`/`logstreamid` or
public `projectid`/`agentstreamid`, selected explicitly, without routing headers
on metric or log requests or in global OTLP headers.
For deterministic scenario correlation, integration hooks must copy the safe
metadata IDs to `app.request_id` and `app.scenario` on operation spans. Newly
added failed/cancelled operations must have error status and a sanitized
`error.type`; failed operations cannot claim output messages or model usage.
Existing span status fields remain part of the preservation check. The proven
missing cancellation status on the original cancelled workflow may be enriched
from UNSET to ERROR with `error.type=CancelledError` through its supported hook;
other existing statuses cannot be cleared or changed.
Log receipts decode actual trace/span IDs. Existing log body, severity,
resource, scope, and attributes must survive one-for-one; safe attributes may
be added. An empty context may be filled only with a received span from that
same request, while existing nonempty context IDs remain fixed. Existing metric
values and dimensions are compared exactly.

The fixture tests prove baseline exports, lifecycle behavior, hook contracts,
and rejection of intentionally damaged receipts. They do not prove skill
behavior. Only a real actor-generated module followed by passing before/after
captures supports that claim. Even a passing local comparison proves local OTLP
acceptance and routing headers; cloud project/Agent Stream visibility remains
unproven.
