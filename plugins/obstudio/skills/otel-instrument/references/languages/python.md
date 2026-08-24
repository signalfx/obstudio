# Python OpenTelemetry Guide

Language-specific instrumentation guidance for Python services.

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

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

Or in `requirements.txt`:
```
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-otlp
opentelemetry-instrumentation-flask      # if Flask
opentelemetry-instrumentation-fastapi    # if FastAPI
opentelemetry-instrumentation-django     # if Django
opentelemetry-instrumentation-requests   # if using requests
opentelemetry-instrumentation-sqlalchemy # if using SQLAlchemy
```

Use `opentelemetry-distro` and `opentelemetry-bootstrap -a install` only as an
additional convenience when the project explicitly wants broad CLI
auto-discovery. For code changes, keep the explicit `opentelemetry-api` and
`opentelemetry-sdk` dependencies in the project manifest and wire a setup file.

Install the official stdlib bridge. OpenTelemetry Python 1.40.0 and later moved
automatic handler ownership from the SDK to this instrumentation package:

```bash
pip install opentelemetry-instrumentation-logging
```

```python
from opentelemetry.instrumentation.logging import LoggingInstrumentor

# Install only after the application has established its console/file handlers.
LoggingInstrumentor().instrument(
    set_logging_format=False,
    inject_trace_context=True,
)
```

The instrumentor installs the stdlib-to-OTel handler by default and protects it
across later `basicConfig`, `dictConfig`, and `fileConfig` calls without
replacing the application's console/file handlers. On
`opentelemetry-instrumentation-logging` 0.64b0+ (paired with Python OTel
1.43.0+), pass `inject_trace_context=True` to add `otelTraceID`, `otelSpanID`,
`otelTraceSampled`, and `otelServiceName` to the original stdlib `LogRecord`
without changing its format. Keep `set_logging_format=False` to preserve the
existing stdout/file format. For an older locked instrumentation version, omit
the unsupported `inject_trace_context` argument; the OTLP handler still derives
correlation from the current OTel context independently. If the older
stdout/file formatter itself must consume those fields, use
`OTEL_PYTHON_LOG_CORRELATION=true` or `set_logging_format=True` and update an
already-created formatter explicitly. That older option also asks
`logging.basicConfig` to install the OTel format, which may be a no-op when
handlers already exist and does not enable OTLP export. For a project pinned
before Python OTel 1.40.0, inspect the installed APIs and retain the older SDK
`LoggingHandler` compatibility path rather than upgrading dependencies solely
to copy this example.

---

## Auto-Instrumentation (CLI Wrapper)

Reuse the current app command and wrap it with the OTel auto-instrumentation agent. Do not introduce Docker just for observability.

```bash
#!/bin/sh
set -eu

logs_exporter="${OTEL_LOGS_EXPORTER:-}"
if [ -z "$logs_exporter" ]; then
  logs_exporter=otlp
  export OTEL_LOGS_EXPORTER="$logs_exporter"
fi
if [ "$OTEL_LOGS_EXPORTER" = otlp ]; then
  logs_protocol="${OTEL_EXPORTER_OTLP_LOGS_PROTOCOL:-http/protobuf}"
  case "${OBSTUDIO_OBSERVER_RUNTIME:-host}:$logs_protocol" in
    host:http/protobuf) local_observer_logs_endpoint=http://localhost:4318/v1/logs ;;
    host:grpc) local_observer_logs_endpoint=http://localhost:4317 ;;
    container:http/protobuf) local_observer_logs_endpoint=http://otel-collector:4318/v1/logs ;;
    container:grpc) local_observer_logs_endpoint=http://otel-collector:4317 ;;
    *) echo "unsupported local Observer runtime/protocol tuple" >&2; exit 1 ;;
  esac
  logs_endpoint="${OTEL_EXPORTER_OTLP_LOGS_ENDPOINT:-}"
  if [ -n "$logs_endpoint" ] && [ "$logs_endpoint" != "$local_observer_logs_endpoint" ]; then
    echo "OTLP logs endpoint is not the detected local Observer; refusing Obstudio log export" >&2
    exit 1
  fi
  export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL="$logs_protocol"
  export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="${logs_endpoint:-$local_observer_logs_endpoint}"
  if [ -n "${OTEL_EXPORTER_OTLP_HEADERS:-}" ]; then
    echo "move generic OTLP headers to trace/metric signal variables and remove the generic value" >&2
    exit 1
  fi
fi
if [ "$OTEL_LOGS_EXPORTER" = none ]; then
  # Ensure the explicit opt-out cannot inherit the zero-code default bridge.
  export OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION=false
fi

exec opentelemetry-instrument \
  --service_name "${OTEL_SERVICE_NAME:-my-service}" \
  --exporter_otlp_endpoint "${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}" \
  --exporter_otlp_protocol "${OTEL_EXPORTER_OTLP_PROTOCOL:-http/protobuf}" \
  --resource_attributes deployment.environment.name=production \
  "$@"
```

Save the checked-in wrapper as `otel-entrypoint.sh`, make it executable, and
pass the same command the project already uses, for example
`./otel-entrypoint.sh python app.py`, `uv run`, `poetry run`, `gunicorn`, or
`uvicorn`. Do not inline only the final `opentelemetry-instrument` command and
drop the policy checks.

If the project already runs in Docker:
```dockerfile
COPY otel-entrypoint.sh /usr/local/bin/otel-entrypoint
RUN chmod 0755 /usr/local/bin/otel-entrypoint
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
ENV OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
ENV OBSTUDIO_OBSERVER_RUNTIME=container
ENV OTEL_LOGS_EXPORTER=otlp
ENV OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf
ENV OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://otel-collector:4318/v1/logs
ENTRYPOINT ["/usr/local/bin/otel-entrypoint"]
CMD ["python", "app.py"]
```

Generate the wrapper's `container` branch with the exact local Observer service
address detected in the project topology, then select that checked-in branch
with `OBSTUDIO_OBSERVER_RUNTIME=container`. Do not accept an arbitrary endpoint
through this helper selector; its two branches are the allowlist. The
entrypoint must run
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
Only the effective `otlp` branch adds or validates the Obstudio local logs
protocol, endpoint, and header isolation. `none` and every other explicit
operator-owned exporter bypass that added log configuration, so generic
trace/metric cloud settings cannot make an opted-out application fail startup.
Set `local_observer_logs_endpoint` to the detected Observer service address for
Docker/Compose. An absent/`otlp` exporter with any other explicit logs endpoint
fails before the agent starts, so it cannot accidentally enable an
Obstudio-owned cloud log path.

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
from opentelemetry.sdk.resources import Resource


LOCAL_OBSERVER_LOGS_ENDPOINT = "http://localhost:4318/v1/logs"


def _use_default_local_log_export():
    configured = os.environ.get("OTEL_LOGS_EXPORTER")
    if configured is not None and configured.strip():
        if configured.strip().lower() != "otlp":
            # Preserve `none` and every other operator-owned exporter without
            # interpreting its OTLP endpoint.
            return False

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "").strip()
    if (
        endpoint
        and endpoint != LOCAL_OBSERVER_LOGS_ENDPOINT
    ):
        raise RuntimeError(
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT is not the detected local "
            "Observer; refusing to create an Obstudio log provider or bridge"
        )
    return True


def _local_log_exporter():
    protocol = os.environ.get(
        "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", "http/protobuf"
    ).strip().lower()
    if protocol != "http/protobuf":
        raise RuntimeError(
            "select the official exporter matching "
            f"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL={protocol!r}"
        )

    # Reject generic headers even when logs headers are present: SDKs may merge
    # both sources and leak a cloud credential into the local log request.
    if os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").strip():
        raise RuntimeError(
            "move generic OTLP headers to trace/metric signal variables and "
            "remove OTEL_EXPORTER_OTLP_HEADERS"
        )
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "").strip()
    if not endpoint:
        endpoint = LOCAL_OBSERVER_LOGS_ENDPOINT
    return OTLPLogExporter(endpoint=endpoint)


def configure_opentelemetry():
    # Resolve every fail-closed log policy check before registering any global
    # provider. A rejected endpoint/header must leave the process retryable and
    # must not strand span/metric worker threads.
    use_local_log_export = _use_default_local_log_export()
    log_exporter = _local_log_exporter() if use_local_log_export else None

    resource = Resource.create({
        "service.name": os.environ.get("OTEL_SERVICE_NAME", "my-service"),
    })

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

This new-process example defaults only an absent or explicit `otlp` log
exporter with an absent or detected-local endpoint to Observer. Adapt
`LOCAL_OBSERVER_LOGS_ENDPOINT` to the checked-in Observer service address for a
Docker/Compose runtime. An explicit non-local endpoint on that branch raises
before the provider or bridge is constructed; report it as an operator-owned
boundary conflict rather than converting it to local or cloud export. If
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

`LoggingInstrumentor` is the current stdlib-to-OTel bridge. Its handler is an
additional path, and its guarded configuration wrappers let later application
logging setup proceed before reattaching the OTel handler. Do not use
`logging.basicConfig(force=True)`. On 0.64b0+/1.43.0+,
`inject_trace_context=True` injects the OTel fields without changing the
existing text format; `set_logging_format=False` preserves that format. On an
older locked version, omit the unsupported injection argument. The OTLP handler
still derives correlation from current context; use
`OTEL_PYTHON_LOG_CORRELATION=true`/`set_logging_format=True` only when the older
stdout/file formatter must receive those fields, and update an already-created
formatter explicitly because `basicConfig` may not replace it.
Inspect filters, formatters, adapters,
Flask/Django access logs, exception rendering, and structured logger wrappers.
Apply the same project redaction policy to the final OTel record and prove
sensitive values cannot be reintroduced later in the pipeline.

The explicit `export_interval_millis` and `export_timeout_millis` are required
for local and eval runs. Do not rely on metric reader defaults; they can be too
slow for short-lived runtime checks, causing valid HTTP metrics to never reach
the collector before the process stops.

### Loading the SDK

**Option 1** -- import at top of entry point (preferred):

```python
# app.py
import atexit

from otel_setup import configure_opentelemetry
install_logging_bridge, shutdown_opentelemetry = configure_opentelemetry()
# This is a normal-exit fallback, not the SIGTERM integration.
atexit.register(shutdown_opentelemetry)

from opentelemetry.instrumentation.flask import FlaskInstrumentor
from flask import Flask

app = Flask(__name__)
# Accessing app.logger establishes Flask's default console handler. If the
# project configures logging explicitly, run that configuration here instead.
_ = app.logger
install_logging_bridge()
FlaskInstrumentor().instrument_app(app)
```

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
instead — see `../../SKILL.md` `#### Implementation Rules` and the
`Python:` entry under `#### Language-Specific Musts`. The instrumentation
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

Use environment variables for operator-owned configuration. The only endpoint
literal in the SDK example is the signal-specific local Observer logs fallback,
which prevents a generic direct-cloud endpoint from becoming the implicit log
destination.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Common OTLP endpoint; protocol must match |
| `OTEL_EXPORTER_OTLP_HEADERS` | unset | Move cloud credentials to trace/metric signal headers and remove this generic value before enabling the Obstudio-owned local log path, even when logs headers are set |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | Common protocol when using port 4318 |
| `OTEL_EXPORTER_OTLP_<SIGNAL>_ENDPOINT` | unset | Per-signal endpoint, including `/v1/<signal>` for HTTP exporters |
| `OTEL_EXPORTER_OTLP_<SIGNAL>_PROTOCOL` | unset | Per-signal `grpc` or `http/protobuf` |
| `OTEL_LOGS_EXPORTER` | `otlp` only when the logs endpoint is absent or detected-local | `none` disables the added local log pipeline; another explicit value remains operator-owned |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | `http://localhost:4318/v1/logs` for host/native Obstudio runs | Signal-specific local application-log destination |
| `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL` | `http/protobuf` for the shown local baseline | Select a matching official exporter for another explicit protocol |
| `OTEL_EXPORTER_OTLP_LOGS_HEADERS` | unset | Signal-specific operator log headers; generic cloud headers are rejected from the log path |
| `OTEL_SERVICE_NAME` | (must be set) | Service identity in telemetry |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metric export interval (ms) |
| `OTEL_METRIC_EXPORT_TIMEOUT` | `30000` | Metric export timeout (ms) |
| `OTEL_BSP_SCHEDULE_DELAY` | `5000` | Span batch export delay (ms) |

For local development with the Observer:

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
export promptly to Observer.

Resolve the effective endpoint/protocol per signal. A gRPC exporter normally
targets `localhost:4317`; an HTTP/protobuf exporter normally targets
`localhost:4318/v1/traces`, `/v1/metrics`, or `/v1/logs`. A trace exporter can
succeed while a separately constructed metrics exporter fails, so exercise
each configured signal.

### Local Observer application logs and cloud boundary

Local OTLP application logs are the default for a detected Python logging
stack only when the exporter is absent/`otlp` and the logs endpoint is absent
or matches the detected local Observer receiver. `none` disables the added
provider and handler while existing stdout/file logging continues; another
non-OTLP exporter remains operator-owned and its endpoint is not interpreted.
When traces or metrics use direct-cloud signal endpoints, keep the logs
endpoint on local Observer. Never copy a Splunk ingest URL, realm, access token,
generic cloud header, cloud exporter, or forwarding flag into the log pipeline.
For the absent/`otlp` branch, reject a non-local explicit logs endpoint before
constructing the provider or handler, preserve it as operator configuration,
report the boundary conflict, and require the operator to resolve it. Also
reject any generic OTLP header on the local branch even when signal-specific
logs headers exist; move the generic credentials to trace/metric variables and
remove the generic setting. Obstudio cloud forwarding remains traces and
metrics only.

Verify one sanitized record at each required severity both outside and inside
an active span. Assert its body/category, severity, shared `service.name`,
trace/span IDs when a span is active, presence in the original stdout/file
sink, one record in Observer, and zero OTLP records with
`OTEL_LOGS_EXPORTER=none`. This runtime check also detects duplicate handlers.

---

## Framework-Specific Notes

### FastAPI
Auto-instrumentation covers all route handlers. Add `opentelemetry-instrumentation-fastapi` to get request/response attributes.

### Flask
Add `opentelemetry-instrumentation-flask`. For Gunicorn, use the `post_fork` hook to initialize the tracer in each worker.

### Django
Add `opentelemetry-instrumentation-django`. Add `opentelemetry.instrumentation.django` to `INSTALLED_APPS` if using explicit programmatic setup instead of automatic module loading.

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
