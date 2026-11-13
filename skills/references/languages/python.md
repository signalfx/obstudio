# Python OpenTelemetry Guide

Language-specific instrumentation guidance for Python services.

For a logging path, first resolve the effective configuration and collection
owner using [the shared logging reference](../logging-readiness.md#source-and-applicability).
The environment-based setup recipes below apply only after that check; they
do not supersede an active supported declarative loader, an intentional SDK
opt-out, or an established operator-owned forwarding route.

---

## Auto-Instrumentation Library Map

Install auto-instrumentation packages matching the frameworks and clients
detected in the codebase. Only install what the project actually uses.

| Dependency | Auto-instrumentation Package | What It Covers |
|------------|------------------------------|----------------|
| `flask` | `opentelemetry-instrumentation-flask` | HTTP server spans with route, method, status |
| `django` | `opentelemetry-instrumentation-django` | HTTP spans, middleware, DB spans |
| `fastapi` / `starlette` | `opentelemetry-instrumentation-fastapi` | HTTP server spans with route, method, status |
| `requests` | `opentelemetry-instrumentation-requests` | Outbound HTTP client spans |
| `httpx` | `opentelemetry-instrumentation-httpx` | Outbound HTTP client spans (sync and async) |
| `urllib3` | `opentelemetry-instrumentation-urllib3` | Outbound HTTP client spans |
| `aiohttp` | `opentelemetry-instrumentation-aiohttp-client` | Async outbound HTTP spans |
| `psycopg2` | `opentelemetry-instrumentation-psycopg2` | SQL query spans |
| `sqlalchemy` | `opentelemetry-instrumentation-sqlalchemy` | ORM query spans |
| `pymongo` | `opentelemetry-instrumentation-pymongo` | MongoDB command spans |
| `redis` | `opentelemetry-instrumentation-redis` | Redis command spans |
| `celery` | `opentelemetry-instrumentation-celery` | Task execution spans |
| `grpcio` | `opentelemetry-instrumentation-grpc` | gRPC client/server spans |
| `kafka-python` / `confluent-kafka` | `opentelemetry-instrumentation-kafka-python` / `opentelemetry-instrumentation-confluent-kafka` | Producer/consumer spans |
| `boto3` / `botocore` | `opentelemetry-instrumentation-botocore` | AWS service call spans |
| `logging` (stdlib) | `opentelemetry-instrumentation-logging` | Export LogRecords while preserving existing handlers; optional trace-context injection into original records |

---

## Dependencies

Resolve the latest compatible published packages at task time, using the
project's selected Python runtime, dependency constraints, and lockfile. Check
`Requires-Python`, `Requires-Dist`, and the resolved SDK/exporter/instrumentor
APIs together; do not override an operator constraint or upgrade the runtime
just to copy an example. Record exact resolved releases, metadata/source
receipts, and the compatibility probe in run evidence, not as fixed skill
defaults. Retain a compatible locked setup when its ownership and APIs are
already proven.

Apply the checked candidate set through the project resolver and lockfile, or
use exact resolved release specs for every added package. Replace the release
placeholders below with task-time values before running the command; preserve
operator constraints and verify the installed graph/APIs. Do not re-resolve a
floating latest tag after checking another candidate.

```bash
pip install \
  'opentelemetry-api==<resolved-api-release>' \
  'opentelemetry-sdk==<resolved-sdk-release>' \
  'opentelemetry-exporter-otlp==<resolved-exporter-release>'
```

Or in `requirements.txt`:
```
opentelemetry-api==<resolved-api-release>
opentelemetry-sdk==<resolved-sdk-release>
opentelemetry-exporter-otlp==<resolved-exporter-release>
opentelemetry-instrumentation-flask==<resolved-flask-bridge-release>      # if Flask
opentelemetry-instrumentation-fastapi==<resolved-fastapi-bridge-release>    # if FastAPI
opentelemetry-instrumentation-django==<resolved-django-bridge-release>     # if Django
opentelemetry-instrumentation-requests==<resolved-requests-bridge-release>   # if using requests
opentelemetry-instrumentation-sqlalchemy==<resolved-sqlalchemy-bridge-release> # if using SQLAlchemy
```

Use `opentelemetry-distro` and `opentelemetry-bootstrap -a install` only as an
additional convenience when the project explicitly wants broad CLI
auto-discovery. For code changes, keep the explicit `opentelemetry-api` and
`opentelemetry-sdk` dependencies in the project manifest and wire a setup file.

Install the official stdlib bridge when the resolved instrumentation package
owns the stdlib-to-OTel handler:

```bash
pip install 'opentelemetry-instrumentation-logging==<resolved-logging-bridge-release>'
```

```python
from opentelemetry.instrumentation.logging import LoggingInstrumentor

# Install only after the application has established its console/file handlers.
LoggingInstrumentor().instrument(
    set_logging_format=False,
    inject_trace_context=True,
)
```

Inspect the resolved instrumentor's documentation/source and run a bounded
probe before using this example: establish whether it installs and guards the
handler across later `basicConfig`, `dictConfig`, and `fileConfig` calls while
preserving the application's console/file handlers. Pass
`inject_trace_context=True` only when that API supports it, to add
`otelTraceID`, `otelSpanID`, `otelTraceSampled`, and `otelServiceName` to the
original stdlib `LogRecord` without changing its format. The example selects
native-format preservation with `set_logging_format=False`; that explicit
option overrides `OTEL_PYTHON_LOG_CORRELATION`; the formatting activation
gates `OTEL_PYTHON_LOG_FORMAT` and `OTEL_PYTHON_LOG_LEVEL`. Independent bridge
controls, such as handler level, retain their own readers and policy. Apply the common policy/precedence decision before
claiming those operator controls remain effective. If the resolved API lacks injection,
omit the unsupported `inject_trace_context` argument and prove canonical OTLP
correlation independently. When
the selected native formatter needs injected fields or operator formatting,
resolve the supported activation and existing formatter path; `basicConfig`
may leave existing handlers unchanged and does not enable OTLP export. If the constrained SDK
instead owns the supported `LoggingHandler` path, retain and test that path;
do not install a second handler or upgrade dependencies solely to copy the
instrumentor example.

---

## Auto-Instrumentation (CLI Wrapper)

Reuse the current app command and wrap it with the OTel auto-instrumentation agent. Do not introduce Docker just for observability.

The normal generated profile and launch command enable `OTEL_LOGS_EXPORTER=otlp`
and route application logs to the resolved local Studio receiver. Use `none`
only for an explicit user opt-out, preserving its provenance; an unavailable
bridge, conflict, or failed verification is a reported incomplete log path,
not permission to persist `none` as the normal configuration.

```bash
#!/bin/sh
set -eu

logs_exporter="${OTEL_LOGS_EXPORTER:-}"
if [ -z "$logs_exporter" ]; then
  logs_exporter=otlp
  export OTEL_LOGS_EXPORTER=otlp
fi
# Match the selected Python SDK's list reader: strip each member, preserve
# case, and recognize none only as the whole value. Do not repair invalid lists.
logs_class="$(python -I - <<'PY_EXPORTERS'
import os

value = os.environ["OTEL_LOGS_EXPORTER"]
if value.lower().strip() == "none":
    print("none")
elif any(name.strip() in ("otlp", "otlp_proto_http", "otlp_proto_grpc")
         for name in value.split(",")):
    print("otlp")
else:
    print("operator")
PY_EXPORTERS
)"
effective_logs_exporter="$logs_exporter"
if [ "$logs_class" = otlp ]; then
  # Use the selected project Python. Validate before the CLI constructs any
  # local log exporter; never print endpoint/header values on failure.
  if logs_configuration="$(python -I - <<'PY_LOGS'
import os
import sys
from urllib.parse import urlsplit, urlunsplit

# Replace these literals with the protocol and complete logs URL resolved in
# preflight. The conventional values apply only when no receiver was found.
approved_logs_protocol = "http/protobuf"
approved_logs_endpoint = "http://127.0.0.1:4318/v1/logs"


def local_endpoint(raw, protocol, *, signal=False):
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ValueError("control character")
    value = raw.strip()
    if any(char.isspace() for char in value):
        raise ValueError("whitespace")
    parsed = urlsplit(value)
    port = parsed.port  # Validate numeric port syntax and range.
    if (parsed.scheme != "http" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or "?" in value or "#" in value
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("non-local or ambiguous endpoint")
    if protocol == "grpc" and parsed.path not in ("", "/"):
        raise ValueError("gRPC endpoint path")
    if signal and protocol == "http/protobuf" and not parsed.path.endswith("/v1/logs"):
        raise ValueError("HTTP logs signal path")
    return parsed


try:
    if os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").strip():
        raise ValueError("generic local log headers")
    generic_protocol = (os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL") or "http/protobuf").strip()
    configured_protocol = (os.environ.get("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL")
                           or os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL")
                           or (generic_protocol if "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL" in os.environ
                               else approved_logs_protocol)).strip()
    transports = set()
    for name in os.environ["OTEL_LOGS_EXPORTER"].split(","):
        name = name.strip()
        if name == "otlp":
            transports.add(configured_protocol)
        elif name == "otlp_proto_http":
            transports.add("http/protobuf")
        elif name == "otlp_proto_grpc":
            transports.add("grpc")
    if transports != {approved_logs_protocol}:
        raise ValueError("selected OTLP transports differ from approval")
    logs_protocol = approved_logs_protocol
    logs_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "")
    generic_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if any(ord(char) < 32 or ord(char) == 127 for char in logs_endpoint):
        raise ValueError("control character")
    if logs_endpoint.strip():
        resolved = local_endpoint(logs_endpoint, logs_protocol, signal=True)
    else:
        generic = None
        if any(ord(char) < 32 or ord(char) == 127 for char in generic_endpoint):
            raise ValueError("control character")
        if generic_endpoint.strip():
            generic = local_endpoint(generic_endpoint, generic_protocol)
        if generic is not None and logs_protocol == generic_protocol:
            if logs_protocol == "http/protobuf":
                path = generic.path
                if not path.endswith("/"):
                    path += "/"
                generic = generic._replace(path=path + "v1/logs")
            resolved = generic
        else:
            resolved = local_endpoint(approved_logs_endpoint, logs_protocol, signal=True)
    approved = local_endpoint(approved_logs_endpoint, approved_logs_protocol, signal=True)
    if (logs_protocol != approved_logs_protocol
            or (resolved.scheme, resolved.hostname, resolved.port or 80, resolved.path)
            != (approved.scheme, approved.hostname, approved.port or 80, approved.path)):
        raise ValueError("logs tuple differs from preflight approval")
    print(logs_protocol + " " + urlunsplit(resolved))
except Exception:
    sys.exit(1)
PY_LOGS
)"; then
    logs_protocol="${logs_configuration%% *}"
    logs_endpoint="${logs_configuration#* }"
    if [ "${OTEL_EXPORTER_OTLP_LOGS_PROTOCOL+x}" != x ]; then
      export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL="$logs_protocol"
    fi
    export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="$logs_endpoint"
  else
    # This invocation skips only the added CLI log path. Preserve the intended
    # profile and all trace/metric/header settings; do not persist an opt-out.
    printf '%s\n' 'local OTLP log export skipped; check receiver, protocol and header configuration' >&2
    # Remove only OTLP members; retain the other exporters and their bridge.
    # The suffix preserves trailing whitespace through shell substitution.
    effective_logs_exporter="$(python -I - <<'PY_WITHOUT_OTLP'
import os
import sys

members = [name for name in os.environ["OTEL_LOGS_EXPORTER"].split(",")
           if name.strip() not in ("otlp", "otlp_proto_http", "otlp_proto_grpc")]
value = ",".join(members) if members else "none"
# A mixed list's empty/none member must still reach SDK component lookup,
# rather than accidentally becoming the SDK's special whole-value opt-out.
if members and (not value or value.lower().strip() == "none"):
    value += "," + members[0]
sys.stdout.write(value + "X")
PY_WITHOUT_OTLP
)"
    effective_logs_exporter="${effective_logs_exporter%X}"
  fi
fi
if [ "$logs_class" = none ] || [ "$effective_logs_exporter" = none ]; then
  # Ensure the explicit opt-out cannot inherit the zero-code default bridge.
  export OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION=false
fi

exec opentelemetry-instrument \
  --logs_exporter "$effective_logs_exporter" \
  --exporter_otlp_endpoint "${OTEL_EXPORTER_OTLP_ENDPOINT:-http://127.0.0.1:4318}" \
  --exporter_otlp_protocol "${OTEL_EXPORTER_OTLP_PROTOCOL:-http/protobuf}" \
  -- \
  "$@"
```

Before saving the wrapper, replace its `approved_logs_protocol` and
`approved_logs_endpoint` literals with the receiver resolved during preflight,
including its authority, port and signal path. Keep the conventional literals
only when existing signal/generic settings, receiver status and project topology
supply no receiver. An explicit approved signal endpoint wins even when the
generic endpoint differs; a compatible generic base is considered only without
a signal endpoint. Loopback membership alone does not approve a tuple. These
literals record the preflight decision, not new runtime environment controls.

Save the checked-in wrapper as `otel-entrypoint.sh`, make it executable, and
pass the same command the project already uses, for example
`./otel-entrypoint.sh python app.py`, `uv run`, `poetry run`, `gunicorn`, or
`uvicorn`. Do not inline only the final `opentelemetry-instrument` command and
drop the policy checks. Arguments after the wrapper are the application command
and its arguments; the `--` boundary prevents additional OTel CLI options from
overriding configuration after it has been checked.

The wrapper leaves service and resource selection to the existing SDK/configuration
owner. Do not add higher-precedence wrapper or CLI defaults over operator
values. Source deployment identity from the effective project configuration;
use `deployment.environment.name` for a supplied environment identity, with its
actual configured value. An absent identity retains the SDK fallback
and needs a source-backed service-name decision; it is not evidence that an
arbitrary application default was configured.

If the project already runs in Docker:
```dockerfile
COPY otel-entrypoint.sh /usr/local/bin/otel-entrypoint
RUN chmod 0755 /usr/local/bin/otel-entrypoint
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
ENV OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
ENV OTEL_LOGS_EXPORTER=otlp
ENV OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf
ENV OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://otel-collector:4318/v1/logs
ENTRYPOINT ["/usr/local/bin/otel-entrypoint"]
CMD ["python", "app.py"]
```

Set the exact local Splunk Observability Studio service address detected in the
project topology through the standard `OTEL_EXPORTER_OTLP_ENDPOINT` and
signal-specific logs endpoint. Do not add an Obstudio-specific runtime selector
or endpoint lookup to application startup. The entrypoint must run
the same exporter, endpoint, protocol, and generic-header checks before every
runtime override; Docker `ENV` defaults alone do not enforce the local-only
boundary.

With current `opentelemetry-instrumentation-logging`, zero-code instrumentation
installs the log handler by default. The wrapper disables that bridge for
`none`. For every other explicit non-OTLP exporter, preserve the operator's
`OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION` value and require runtime proof of its
one provider/exporter/bridge; do not silently disable or supplement it. Do not
also run the programmatic setup below;
choose the zero-code owner or the application-owned provider/bridge, never both.
Use the CLI-owned log path only after a runtime check proves the application's
original console/file handlers are still installed and receive the record. In
particular, a root OTel handler installed before Flask creates `app.logger` can
make Flask skip its default console handler. If the original sink is missing,
do not ship the zero-code log path; route the service to the split
provider/late-bridge programmatic setup below.
Every selected SDK-supported OTLP member (`otlp`, `otlp_proto_http`, or
`otlp_proto_grpc`) requires the approved local tuple and header isolation,
including in mixed lists. Explicit transport aliases win over protocol selectors;
incompatible selected transports skip OTLP. On a conflict, remove only OTLP
members for that invocation, preserving other exporters and their bridge. Keep
the SDK's case-sensitive member lookup, duplicate handling, whole-value `none`
and invalid-list behavior; do not turn mixed `none` or empty members into a valid
opt-out. With no OTLP member, operator-owned exporters bypass the added checks, so generic
trace/metric cloud settings cannot make an opted-out application fail startup.
At instrumentation time, persist the detected Splunk Observability Studio
service address through the standard OTel endpoint variables for
Docker/Compose. A signal-specific logs endpoint wins; otherwise a compatible
generic local endpoint is inherited with its configured port, and only an
unresolved destination uses the conventional fallback. Classify and report a
direct-cloud or otherwise ambiguous endpoint during preflight instead of adding
an Obstudio lookup or route-selection call to application startup.

---

## SDK Initialization (Programmatic)

Create a separate file for OTel setup. Configure providers before creating the
application object (Flask app, FastAPI app, etc.), but install the logging
bridge only after the application has established its existing console/file
handlers and before it begins serving.
For Python services, this explicit setup file is the default implementation
path; a Makefile or Docker command that only wraps the process with
`opentelemetry-instrument` is not enough by itself.

### Existing provider reconciliation

Before using the new-process example below, search for explicit or lazy
`TracerProvider`, `MeterProvider`, `LoggerProvider`, `set_*_provider`, exporter,
resource, and no-op branches. A provider initialized by a metrics wrapper on
first counter/gauge access is an existing provider even when the entrypoint has
no OTel call.

- Keep one global provider per signal.
- Preserve existing metric views, observable callbacks, file-export modes, and
  wrapper APIs while moving or adapting provider construction to shared setup.
- When auto-instrumentation will install providers, suppress that signal's
  auto-provider or let the shared app setup own it; never call
  `metrics.set_meter_provider` or `trace.set_tracer_provider` twice.
- Use one shared resource identity across traces, metrics, and logs. An existing
  resource that lacks `service.name`, service version, or deployment
  environment must be repaired, not replaced by a parallel provider.
- Merge operator-provided resource values before app defaults. Preserve
  `OTEL_SERVICE_NAME` and keys from `OTEL_RESOURCE_ATTRIBUTES`; defaults may
  fill missing environment/version fields but must not replace supplied values.
- Add a focused regression test proving existing instruments still record
  through the selected provider after reconciliation.

The following example is for a process with no existing providers. Adapt it
rather than copying it when provider ownership already exists.

**File**: `otel_setup.py`

```python
import os
import threading
import warnings
from urllib.parse import urlsplit, urlunsplit

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import OTELResourceDetector, Resource


# Replace with the complete logs URL resolved in preflight; use this
# conventional fallback only when no existing receiver evidence is available.
PREFLIGHT_APPROVED_LOCAL_OTLP_LOGS_ENDPOINT = "http://127.0.0.1:4318/v1/logs"


def _local_http_endpoint(endpoint):
    try:
        parsed = urlsplit(endpoint)
        approved = urlsplit(PREFLIGHT_APPROVED_LOCAL_OTLP_LOGS_ENDPOINT)
        return (parsed.scheme == approved.scheme == "http"
                and bool(parsed.hostname) and parsed.username is None
                and parsed.password is None and "?" not in endpoint
                and "#" not in endpoint
                and not any(char.isspace() or ord(char) < 32 or ord(char) == 127
                            for char in endpoint)
                and (parsed.port is None or 1 <= parsed.port <= 65535)
                and (parsed.hostname, parsed.port or 80, parsed.path)
                == (approved.hostname, approved.port or 80, approved.path))
    except ValueError:
        return False


def _skip_local_logs(reason):
    warnings.warn(f"local OTLP logs disabled: {reason}", RuntimeWarning)
    return None


def _http_logs_endpoint_from_base(endpoint):
    parsed = urlsplit(endpoint)
    path = parsed.path
    if not path.endswith("/"):
        path += "/"
    return urlunsplit(parsed._replace(path=path + "v1/logs"))


def _use_default_local_log_export():
    configured = os.environ.get("OTEL_LOGS_EXPORTER")
    if configured is not None and configured.strip():
        if configured.strip().lower() != "otlp":
            # Preserve `none` and every other operator-owned exporter without
            # interpreting its OTLP endpoint.
            return False

    return True


def _local_log_exporter():
    generic_protocol = os.environ.get(
        "OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"
    ).strip().lower()
    protocol = os.environ.get(
        "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", generic_protocol
    ).strip().lower()
    if protocol != "http/protobuf":
        return _skip_local_logs(
            "select the official exporter matching the configured logs protocol"
        )

    # Reject generic credentials; preserve signal-specific local log headers
    # for the official exporter to parse without an empty headers override.
    if os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").strip():
        return _skip_local_logs(
            "move generic OTLP headers to trace/metric signal variables"
        )
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "").strip()
    if not endpoint:
        generic_endpoint = os.environ.get(
            "OTEL_EXPORTER_OTLP_ENDPOINT", ""
        ).strip()
        # Preserve a compatible local OTLP/HTTP receiver, including its
        # non-default port. A cloud generic endpoint may still serve traces
        # and metrics, but must never become the application-log endpoint.
        if generic_protocol == protocol and generic_endpoint:
            try:
                endpoint = _http_logs_endpoint_from_base(generic_endpoint)
            except ValueError:
                return _skip_local_logs("invalid generic logs endpoint")
        else:
            endpoint = PREFLIGHT_APPROVED_LOCAL_OTLP_LOGS_ENDPOINT
    if not _local_http_endpoint(endpoint):
        return _skip_local_logs("logs endpoint differs from the preflight-approved receiver")
    return OTLPLogExporter(endpoint=endpoint)


def _application_resource():
    return Resource.create({
        "service.name": "my-service",
        **OTELResourceDetector().detect().attributes,
    })


def configure_opentelemetry():
    # Resolve log policy before registering globals. A conflicting log route
    # disables only this local log branch; traces, metrics, and the application
    # keep their operator-owned configuration.
    use_local_log_export = _use_default_local_log_export()
    log_exporter = _local_log_exporter() if use_local_log_export else None

    resource = _application_resource()

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(),
        export_interval_millis=int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", "1000")),
        export_timeout_millis=int(os.environ.get("OTEL_METRIC_EXPORT_TIMEOUT", "500")),
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])

    logger_provider = None
    logging_instrumentor = None
    shutdown_lock = threading.Lock()
    shutdown_complete = False
    if log_exporter is not None:
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(log_exporter)
        )

    # Construction and policy validation succeeded. Publish the one provider
    # per signal only now; no later fail-closed log check can leave partial
    # global state installed.
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    if logger_provider is not None:
        set_logger_provider(logger_provider)

    def install_logging_bridge():
        nonlocal logging_instrumentor
        if logger_provider is None or logging_instrumentor is not None:
            return

        # Current instrumentation owns exactly one stdlib-to-OTel handler and
        # must be installed only after the application's original sinks exist.
        logging_instrumentor = LoggingInstrumentor()
        logging_instrumentor.instrument(
            set_logging_format=False,
            inject_trace_context=True,
        )

    def shutdown():
        nonlocal shutdown_complete
        with shutdown_lock:
            if shutdown_complete:
                return
            shutdown_complete = True

            # Attempt every owner even when an earlier shutdown fails. This
            # function is safe to share between the server lifecycle and the
            # normal-process-exit fallback.
            actions = []
            if logging_instrumentor is not None:
                actions.append(("logging bridge", logging_instrumentor.uninstrument))
            if logger_provider is not None:
                actions.append(("log provider", logger_provider.shutdown))
            actions.extend((
                ("meter provider", meter_provider.shutdown),
                ("tracer provider", tracer_provider.shutdown),
            ))
            failures = []
            for owner, action in actions:
                try:
                    action()
                except Exception as exc:
                    failures.append((owner, exc))
            if failures:
                owners = ", ".join(owner for owner, _ in failures)
                raise RuntimeError(f"OpenTelemetry shutdown failed for: {owners}") \
                    from failures[0][1]

    return install_logging_bridge, shutdown
```

### Local log preflight approval

This new-process example defaults only an absent or explicit `otlp` log
exporter with an absent or detected-local endpoint to Splunk Observability Studio. Adapt
the standard `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` launch setting to the receiver
address resolved during instrumentation, including any non-default port and
Docker/Compose service name. Set `PREFLIGHT_APPROVED_LOCAL_OTLP_LOGS_ENDPOINT`
to that complete approved URL in the checked-in setup. Keep its conventional
value only when no existing configuration, receiver status or project topology
supplies a receiver; do not add a runtime Obstudio lookup. The shown exporter
supports HTTP/protobuf only. Compare the resolved protocol, authority, port and
path with preflight approval rather than treating any loopback URL as approved.
An explicit approved signal endpoint is independent of a differing or invalid
generic endpoint; consult a compatible generic base only when the signal endpoint
is absent. Report a source-proven non-local endpoint
as an operator-owned boundary conflict before copying this pattern. A
conflict disables only local log export and emits a value-free warning; it
must not abort application startup or operator-owned trace/metric export. If
`OTEL_LOGS_EXPORTER=none`, or another explicit exporter is selected, the helper
leaves logging untouched without validating that operator-owned endpoint. Do
not broaden the condition to install local OTLP alongside another exporter.
Call the returned `install_logging_bridge` exactly once after the application's
logging configuration has established its original sinks. Attach `shutdown`
to the existing server/worker graceful lifecycle after it stops accepting work
and emits final application logs. Keep `atexit` only as a normal-exit fallback;
it is not invoked by the default SIGTERM action. When no lifecycle owner
exists, install one signal owner that requests the service to stop, wait for
the serving loop to return, and then call `shutdown`. Do not create a second
provider or signal handler during reloads or per worker request.
Follow the shared-role [lifecycle checks](#launcher-and-lifecycle)
for repeated stop requests and final-record proof.

`LoggingInstrumentor` is the current stdlib-to-OTel bridge. Its handler is an
additional path, and its guarded configuration wrappers let later application
logging setup proceed before reattaching the OTel handler. Do not use
`logging.basicConfig(force=True)`. Check the resolved instrumentor's API and
handler ownership before copying the setup. When supported,
`inject_trace_context=True` injects the OTel fields without changing the
existing text format. Treat this example's `set_logging_format=False` as an
explicit native-format policy, not a guarantee that correlation/format/level
environment controls remain effective. Resolve authority and precedence as
above. If the injection API is unsupported, omit it and prove the OTLP
handler's context mapping independently; inspect existing formatter setup
when selected text-field or operator-formatting behavior requires it.
Inspect filters, formatters, adapters,
Flask/Django access logs, exception rendering, and structured logger wrappers.
Apply the same project redaction policy to the final OTel record and prove
sensitive values cannot be reintroduced later in the pipeline.

The explicit `export_interval_millis` and `export_timeout_millis` are required
for local and eval runs. Do not rely on metric reader defaults; they can be too
slow for short-lived runtime checks, causing valid HTTP metrics to never reach
the collector before the process stops.

### Loading the SDK

**Option 1** -- integrate with the existing bootstrap (preferred):

Use the detected application's actual startup owners in this order:

1. Initialize the selected providers before their framework instrumentation
   binds them, preserving any existing provider ownership.
2. Establish the original native sinks for each selected application, framework
   and server producer through its supported logging configuration or startup
   hook. Name that producer's concrete public setup mechanism and expected handler,
   stream, format and level; a generic instruction to initialize handlers is not
   a repair mechanism. Preserve multiplicity. Creating an application logger or
   attaching a filter does not initialize a sibling producer's lazy native sink.
   Public standard-library logging configuration is valid when it preserves that
   detected producer's destination, format, level and multiplicity. Inspecting
   dependency internals can explain lazy behavior; calling an underscored
   initializer solely for its lazy setup side effects does not establish a
   supported bootstrap mechanism.
3. Call the returned `install_logging_bridge()` only after those sinks are
   established and before the selected records are emitted. Some producers test
   ancestor handlers by level alone: a root OTel handler can suppress their
   native-handler installation even if its filter rejects their records.
   Reconcile that producer's actual initialization rather than adding a handler
   indiscriminately or treating an application handler as its native sink.
4. Register the returned shutdown function with the existing graceful lifecycle
   owner. `atexit.register(shutdown_opentelemetry)` is only a normal-exit fallback.

Register `shutdown_opentelemetry` with the process's existing graceful hook,
such as the ASGI lifespan shutdown, Gunicorn worker/server exit hook, or the
project's server-close callback. The owner must first stop intake and let the
serving loop return, then call the idempotent shutdown function. For a
standalone process that has no such owner, use its stop primitive rather than
running telemetry shutdown directly inside the signal handler:

```python
import signal
import threading

stop_requested = threading.Event()

for signum in (signal.SIGTERM, signal.SIGINT):
    signal.signal(signum, lambda _signum, _frame: stop_requested.set())

try:
    run_service_until_stopped(stop_requested)  # existing graceful server loop
finally:
    shutdown_opentelemetry()
```

Do not install this standalone handler when Gunicorn, Uvicorn, a framework
lifespan, or another supervisor already owns signals; integrate with that
owner's post-stop hook instead.

**Option 2** -- CLI auto-instrumentation via `opentelemetry-instrument`:

```bash
opentelemetry-instrument python app.py
```

This uses `opentelemetry-distro` to auto-discover and activate all installed
instrumentations. Prefer Option 1 for explicit control over which
instrumentations are active.

### Instrumenting frameworks

Each framework instrumentation is activated by calling `.instrument_app(app)`
or `.instrument()` after the SDK is configured:

```python
# Flask
FlaskInstrumentor().instrument_app(app)

# FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
FastAPIInstrumentor.instrument_app(app)

# Django -- add to settings.py INSTALLED_APPS or call:
from opentelemetry.instrumentation.django import DjangoInstrumentor
DjangoInstrumentor().instrument()

# Client libraries (instrument globally)
from opentelemetry.instrumentation.requests import RequestsInstrumentor
RequestsInstrumentor().instrument()
```

For FastAPI/Starlette, call `instrument_app(app)` immediately after creating
the app and before lifespan/startup is entered. Installing instrumentation for
the first time inside lifespan is too late because Starlette rejects middleware
changes after startup.

---

## Custom Spans

Use the `@tracer.start_as_current_span` decorator for clean instrumentation.
For more control, use the context manager form.

```python
from opentelemetry import trace

tracer = trace.get_tracer("my-service.orders")


@tracer.start_as_current_span("orders.process")
def process_order(order_id: str) -> Order:
    span = trace.get_current_span()
    span.set_attribute("order.id", order_id)
    try:
        order = db.get_order(order_id)
        span.set_attribute("order.total", order.total)
        charge_payment(order)
        return order
    except Exception as exc:
        span.record_exception(exc)
        span.set_status(trace.StatusCode.ERROR, str(exc))
        raise
```

**Context manager form** (when you need the span reference immediately):

```python
with tracer.start_as_current_span("orders.validate") as span:
    span.set_attribute("order.id", order_id)
    validate(order)
```

**Async functions**:

```python
@tracer.start_as_current_span("orders.process")
async def process_order(order_id: str) -> Order:
    span = trace.get_current_span()
    # ... same pattern as sync
```

---

## Custom Metrics

Before adding a custom counter or histogram for an outcome that happens
inside a request the ASGI/WSGI instrumentation already covers, check
whether it belongs as an attribute on `http.server.request.duration`
instead. When implementing a change, also follow the loaded instrumentation
skill's Implementation Rules and Python Language-Specific Musts. The instrumentation
already sets `http.response.status_code` on that metric for every request,
and `error.type` for a 5xx (or otherwise invalid) status, with no extra code
-- a plain 4xx client-error response does not set `error.type` on a server
span. Define a new instrument when the signal does not correlate 1:1 with a
single request (a queue-depth gauge or background job outcome), or cannot
be represented by those automatically emitted attributes -- for example a
same-status-different-cause outcome (a 200 that is a logical failure, several
distinct 4xx causes, or several distinct 5xx causes) that `http.response.status_code`
and `error.type` cannot distinguish on their own and that needs its own
dimension.

```python
from opentelemetry import metrics

meter = metrics.get_meter("my-service")

# Counter
orders_processed = meter.create_counter(
    "orders.processed.count",
    description="Total orders processed",
    unit="{orders}",
)

# Histogram
order_duration = meter.create_histogram(
    "orders.process.duration",
    description="Order processing duration",
    unit="s",
)

# Observable Gauge (callback-based)
from opentelemetry.metrics import Observation

def get_queue_depth(_options):
    yield Observation(current_queue_depth())

meter.create_observable_gauge(
    "orders.queue.depth",
    callbacks=[get_queue_depth],
    description="Current order queue depth",
    unit="{orders}",
)

# Usage
orders_processed.add(1, {"order.type": "standard"})
order_duration.record(elapsed_seconds, {"order.type": "standard"})
```

---

## Error Handling

APM backends identify errors by `otel.status_code = ERROR`. Always set error status on exceptions:

```python
from opentelemetry.trace import StatusCode

span.set_status(StatusCode.ERROR, "Description of what failed")
span.record_exception(exception)
```

For Flask/FastAPI, unhandled 5xx responses automatically set ERROR status via the auto-instrumentation.

---

## OTLP Export Configuration

Use environment variables for operator-owned configuration. Resolve the local
receiver before launch and write its actual endpoints into the standard OTel
variables. Endpoint literals below are conventional no-discovery fallbacks,
not fixed-port equality checks.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | resolved local receiver; fallback `http://127.0.0.1:4318` | Common OTLP endpoint; protocol must match and a configured non-default port is preserved |
| `OTEL_EXPORTER_OTLP_HEADERS` | unset | Move cloud credentials to trace/metric signal headers and remove this generic value before enabling the Splunk Observability Studio-owned local log path, even when logs headers are set |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | Common protocol when using port 4318 |
| `OTEL_EXPORTER_OTLP_<SIGNAL>_ENDPOINT` | unset | Per-signal endpoint, including `/v1/<signal>` for HTTP exporters |
| `OTEL_EXPORTER_OTLP_<SIGNAL>_PROTOCOL` | unset | Per-signal `grpc` or `http/protobuf` |
| `OTEL_LOGS_EXPORTER` | `otlp` only when the logs endpoint is absent or detected-local | `none` disables the added local log pipeline; another explicit value remains operator-owned |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | resolved local receiver; fallback `http://127.0.0.1:4318/v1/logs` | Signal-specific local application-log destination |
| `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL` | `http/protobuf` for the shown local baseline | Select a matching official exporter for another explicit protocol |
| `OTEL_EXPORTER_OTLP_LOGS_HEADERS` | unset | Signal-specific operator log headers; generic cloud headers are rejected from the log path |
| `OTEL_SERVICE_NAME` | unset | Optional service-name override; preserve identity supplied through resource attributes or the active resource configuration |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metric export interval (ms) |
| `OTEL_METRIC_EXPORT_TIMEOUT` | `30000` | Metric export timeout (ms) |
| `OTEL_BSP_SCHEDULE_DELAY` | `5000` | Span batch export delay (ms) |

For local development with Splunk Observability Studio, substitute the resolved
receiver port when it differs from the conventional fallback:

    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
    OTEL_LOGS_EXPORTER=otlp \
    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4318/v1/logs \
    OTEL_METRIC_EXPORT_INTERVAL=1000 \
    OTEL_METRIC_EXPORT_TIMEOUT=500 \
    OTEL_BSP_SCHEDULE_DELAY=100 \
    python app.py

When creating `PeriodicExportingMetricReader`, pass
`export_interval_millis=int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", "1000"))`
and `export_timeout_millis=int(os.environ.get("OTEL_METRIC_EXPORT_TIMEOUT", "500"))`.
This makes HTTP metrics from Flask/FastAPI instrumentation, including
`http.server.request.duration` or the older `http.server.duration` name,
export promptly to Splunk Observability Studio.

Resolve the effective endpoint/protocol per signal. The conventional gRPC
fallback is `127.0.0.1:4317`; the conventional HTTP/protobuf fallback is
`http://127.0.0.1:4318/v1/traces`, `/v1/metrics`, or `/v1/logs`. A trace exporter can
succeed while a separately constructed metrics exporter fails, so exercise
each configured signal.

### Local Splunk Observability Studio application logs and cloud boundary

Local OTLP application logs are the default for a detected Python logging
stack only when the exporter is absent/`otlp` and preflight resolves an intended
local receiver. A signal-specific endpoint wins; a compatible generic local
endpoint is inherited with its non-default port and signal path. `none` disables the added
provider and handler while existing stdout/file logging continues; another
non-OTLP exporter remains operator-owned and its endpoint is not interpreted.
When traces or metrics use direct-cloud signal endpoints, keep the logs
endpoint on local Splunk Observability Studio. Never copy a Splunk ingest URL, realm, access token,
generic cloud header, cloud exporter, or forwarding flag into the log pipeline.
For the absent/`otlp` branch, classify a non-local explicit logs endpoint during
instrumentation preflight, preserve it as operator configuration, report the
boundary conflict, and require the operator to resolve it. Reject any generic
OTLP header on the local branch even when signal-specific logs headers exist.
Resolve moving generic credentials to trace/metric variables and removing the
generic setting through operator-approved configuration during preflight.
Application startup must not pop or rewrite those settings to activate local
logs. Splunk Observability Studio cloud forwarding remains traces and metrics
only.

Verify one sanitized record at each required severity both outside and inside
an active span. Assert its body/category, severity, shared `service.name`,
trace/span IDs when a span is active, presence in the original stdout/file
sink, one received record on a healthy path in Splunk Observability Studio, and zero OTLP records with
`OTEL_LOGS_EXPORTER=none`. This runtime check also detects duplicate handlers.
In fault/retry scenarios distinguish transport copies from SDK emission and
handler ownership; an unavailable receiver can receive zero records.

---

## Framework-Specific Notes

### FastAPI
Auto-instrumentation covers all route handlers. Add `opentelemetry-instrumentation-fastapi` to get request/response attributes.

### Flask
Add `opentelemetry-instrumentation-flask`. For Gunicorn, use the `post_fork` hook to initialize the tracer in each worker.

### Django
Add `opentelemetry-instrumentation-django`. Add `opentelemetry.instrumentation.django` to `INSTALLED_APPS` if using explicit programmatic setup instead of automatic module loading.

---

## Logging Readiness Checks

Apply the [common logging rules](../logging-readiness.md) to the detected Python
logger, bridge and runtime. Resolve the existing provider and configuration
owner; preserve native handlers, operator settings and verified propagation.
Setup recipes elsewhere in this guide are conditional examples, not requirements
to adopt their framework, packages or API shape.
For selected bootstrap or local-log work, retrieve the complete
[bootstrap ordering](#loading-the-sdk),
[preflight approval](#local-log-preflight-approval) and
[local log credential boundary](#local-splunk-observability-studio-application-logs-and-cloud-boundary)
sections separately. A truncated whole-guide read does not supply a missing
linked section. Apply these ownership and policy decisions to the selected
path while keeping setup recipes conditional.

### Context and asynchronous work

Inspect the actual task, thread, executor and logging-queue boundaries. Context
inheritance differs by scheduler; verify it rather than assuming all asynchronous
APIs propagate contextvars. Where an explicit transfer is needed, capture an
independent context per work item before dispatch and restore/detach state on
success, failure and cancellation. Do not enter one context copy concurrently.
Keep context capture before a logging queue unless its supported integration
already preserves the caller's context.

Use the common real-span join contract on the worker's actual native logging
path. A direct SDK emit or context-copy test does not establish bridge or
application-runtime coverage. Distinguish native severity from OTel severity and
preserve the source timestamp's actual precision, formatters and supported
structured values.

### Configuration and limits

Resolve public options, signatures, units and configuration precedence from the
installed provider/exporter path. Bind a selected local-receiver policy to the
complete URL approved during preflight; neither loopback locality nor the current
generic endpoint grants approval. A signal-specific endpoint wins independently
of a differing unused generic endpoint. Test the selected policy with relevant
operator overrides present while preserving independent settings.

Distinguish an eagerly evaluated default argument from the value ultimately
selected by a configuration lookup. Trace sentinels and helper results through
outer constructor defaults; an intermediate `None` need not mean unlimited.
Keep source-known behavior separate from unexecuted runtime checks.
For representability claims, follow Python's integer parsing into the actual
container, scheduler or native extension constructor. Accepting an integer does
not establish that the terminal consumer can use it; retain that boundary and
avoid allocating an unsafe size merely to probe the limit.

For limits, replay the original payload and test its boundaries. Derive expected
retained values and drops from actual input, accounting for bridge-added fields
and reviewed processors.

Where the selected Python SDK keeps limits and accumulated drops on a mutable
attribute container, replacing it with a plain mapping can erase earlier drop
accounting. Use that owner's supported mutation or snapshot mechanism while
preserving its limits and existing drop state. Check the downstream count as
well as sanitized values; do not synthesize counters or assume another
SDK/version has the same container semantics.

Direct SDK and native-bridge controls prove different paths; keep either missing
control unproven. Attribute limits do not define Body or exception-capture
policy. Use native enablement only to avoid expensive work; lazy formatting does
not defer argument-producing expressions already evaluated.

### Launcher and lifecycle

Resolve the actual launcher, CLI/environment precedence, worker model and reload
behavior before claiming a process or shutdown profile. Validate the effective
command and process identities; an environment assignment alone cannot override
an explicit higher-priority runner setting. Preserve existing development and
operator policy, and scope proof to the processes actually exercised.
Inspect effective handler ownership after the runner initializes: supervisors,
reloaders or workers can replace an earlier handler or stop a different process.
A flag in an application handler proves nothing if that handler is no longer
installed. Retain the selected graceful-stop contract on the actual process.

Use the runtime's supported stop mechanism. Repeated stop requests must respect
the selected shutdown policy and not accidentally interrupt active final logging
or drain. Prove required event ordering and final-record receipt on that same
configured lifecycle path. Keep exporter completion, flush waiting, cancellation
and receiver acknowledgement distinct. Route SDK/exporter diagnostics through a
supported independent handler or suppression path. When adding a root OTel
bridge, follow the actual
`logging.Logger.callHandlers` route: a found handler can disable `lastResort`
even when its filter rejects the record. Excluding SDK records from the bridge
does not supply native output; handlers on application/framework sibling
loggers do not serve that SDK namespace. Retain an eligible existing native
route or supported suppression policy rather than forcing a new handler or
diagnostic emission. Assess actual diagnostic cadence separately from
successful limit enforcement.

---

## Gotchas

- **Provider first, logging bridge after sinks**: call
  `configure_opentelemetry()` before creating Flask/FastAPI/Django app objects
  so trace/metric providers exist before framework instrumentation. Establish
  the application's original logging handlers next, then call the returned
  `install_logging_bridge()` before serving. Installing the root OTel handler
  first can suppress a framework's lazy default console handler.
- **FastAPI lifespan timing**: construct and instrument the app before lifespan
  startup. Do not first invoke `FastAPIInstrumentor.instrument_app(app)` from
  inside lifespan.
- **`opentelemetry-distro` vs manual**: `opentelemetry-instrument` is
  convenient for quick starts but hides which instrumentations are active.
  Prefer explicit instrumentation for production services.
- **`opentelemetry-bootstrap -a install`**: discovers installed libraries
  and installs matching instrumentation packages. Useful for initial setup
  but review what it installs.
- **Async frameworks**: FastAPI and aiohttp require the async-compatible
  instrumentations. The sync `requests` instrumentation does not cover
  `httpx` async calls -- use `opentelemetry-instrumentation-httpx`.
- **Django middleware order**: DjangoInstrumentor adds middleware
  automatically. If you have custom middleware, ensure OTel middleware
  runs first (outermost in the stack).
- **Gunicorn / uWSGI**: Call `configure_opentelemetry()` in the
  `post_fork` hook (Gunicorn) or `@postfork` (uWSGI) so each worker
  process gets its own SDK instance. After the worker's logging handlers are
  established, call that worker's returned `install_logging_bridge()` and
  register its `shutdown` callback with the worker lifecycle.
- **Singleton providers**: Never call any global `set_*_provider()` more than
  once. If existing OTel setup exists, extend or consolidate it and prove legacy
  instruments still use the selected provider.
- **Duplicate log bridges**: one `LoggingInstrumentor`-managed stdlib handler is
  enough. Do not add it when an existing OTel handler/provider already owns the
  same records, and do not combine it with a second framework bridge that
  exports those records.
- **Metric export interval and timeout**: Always set
  `export_interval_millis` and `export_timeout_millis` on
  `PeriodicExportingMetricReader`. Environment variables alone are not enough
  when constructing the reader manually.
- **Observable gauge callback signature**: The callback receives a
  `CallbackOptions` argument and must **yield `Observation` objects**
  (from `opentelemetry.metrics`). A common mistake is writing
  `result.observe(value)` -- this fails with `AttributeError` at metric
  export time, not at registration, so the error only surfaces after the
  app is running. Correct pattern:
  ```python
  from opentelemetry.metrics import Observation
  def my_callback(_options):
      yield Observation(current_value())
  ```
