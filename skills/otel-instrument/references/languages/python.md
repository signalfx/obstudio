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

LoggingInstrumentor().instrument(
    set_logging_format=False,
    inject_trace_context=False,
)
```

The instrumentor installs the stdlib-to-OTel handler by default and protects it
across later `basicConfig`, `dictConfig`, and `fileConfig` calls without
replacing the application's console/file handlers. Set
`inject_trace_context=True` only when the existing formatter also needs the
`otelTraceID`, `otelSpanID`, and `otelTraceSampled` fields. For a project pinned
before Python OTel 1.40.0, inspect the installed APIs and retain the older SDK
`LoggingHandler` compatibility path rather than upgrading dependencies solely
to copy this example.

---

## Auto-Instrumentation (CLI Wrapper)

Reuse the current app command and wrap it with the OTel auto-instrumentation agent. Do not introduce Docker just for observability.

```bash
export OTEL_LOGS_EXPORTER="${OTEL_LOGS_EXPORTER:-otlp}"
if [ "$OTEL_LOGS_EXPORTER" = otlp ]; then
  export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL="${OTEL_EXPORTER_OTLP_LOGS_PROTOCOL:-http/protobuf}"
  if [ -z "${OTEL_EXPORTER_OTLP_LOGS_ENDPOINT:-}" ]; then
    case "$OTEL_EXPORTER_OTLP_LOGS_PROTOCOL" in
      http/protobuf) export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4318/v1/logs ;;
      grpc) export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4317 ;;
      *) echo "unsupported OTLP logs protocol: $OTEL_EXPORTER_OTLP_LOGS_PROTOCOL" >&2; exit 1 ;;
    esac
  fi
  if [ -n "${OTEL_EXPORTER_OTLP_HEADERS:-}" ] && \
     [ -z "${OTEL_EXPORTER_OTLP_LOGS_HEADERS:-}" ]; then
    echo "move generic OTLP headers to trace/metric signal variables, or set explicit logs headers" >&2
    exit 1
  fi
fi
if [ "$OTEL_LOGS_EXPORTER" = none ]; then
  export OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION=false
fi

opentelemetry-instrument \
  --service_name my-service \
  --exporter_otlp_endpoint http://localhost:4318 \
  --resource_attributes deployment.environment.name=production \
  python app.py
```

Wrap the same command the project already uses, such as `python`, `uv run`, `poetry run`, `gunicorn`, or `uvicorn`.

If the project already runs in Docker:
```dockerfile
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
ENV OTEL_EXPORTER_OTLP_HEADERS=""
ENV OTEL_LOGS_EXPORTER=otlp
ENV OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://otel-collector:4318/v1/logs
CMD ["opentelemetry-instrument", "--service_name", "my-service", "python", "app.py"]
```

With current `opentelemetry-instrumentation-logging`, zero-code instrumentation
installs the log handler by default. Pair
`OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION=false` with
`OTEL_LOGS_EXPORTER=none` to omit that no-op handler as well. Do not also run the programmatic setup below;
choose the zero-code owner or the application-owned provider/bridge, never both.
Only the effective `otlp` branch adds or validates the Obstudio local logs
protocol, endpoint, and header isolation. `none` and every other explicit
operator-owned exporter bypass that added log configuration, so generic
trace/metric cloud settings cannot make an opted-out application fail startup.

---

## SDK Initialization (Programmatic)

Create a separate file for OTel setup. Call the setup function before
creating the application object (Flask app, FastAPI app, etc.).
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
    if configured is None or not configured.strip():
        return True
    return configured.strip().lower() == "otlp"


def _local_log_exporter():
    protocol = os.environ.get(
        "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", "http/protobuf"
    ).strip().lower()
    if protocol != "http/protobuf":
        raise RuntimeError(
            "select the official exporter matching "
            f"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL={protocol!r}"
        )

    # A signal-specific endpoint/header wins. Reject generic headers here so a
    # direct-cloud credential cannot leak into the local application-log path.
    if (
        os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").strip()
        and not os.environ.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS", "").strip()
    ):
        raise RuntimeError(
            "move generic OTLP headers to trace/metric signal variables, or "
            "set an explicit OTEL_EXPORTER_OTLP_LOGS_HEADERS value"
        )
    endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", LOCAL_OBSERVER_LOGS_ENDPOINT
    )
    return OTLPLogExporter(endpoint=endpoint)


def configure_opentelemetry():
    resource = Resource.create({
        "service.name": os.environ.get("OTEL_SERVICE_NAME", "my-service"),
    })

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(),
        export_interval_millis=int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", "1000")),
        export_timeout_millis=int(os.environ.get("OTEL_METRIC_EXPORT_TIMEOUT", "500")),
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    logger_provider = None
    logging_instrumentor = None
    if _use_default_local_log_export():
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(_local_log_exporter())
        )
        set_logger_provider(logger_provider)

        # Current instrumentation owns exactly one stdlib-to-OTel handler and
        # preserves handlers established before or after this call.
        logging_instrumentor = LoggingInstrumentor()
        logging_instrumentor.instrument(
            set_logging_format=False,
            inject_trace_context=False,
        )

    def shutdown():
        # The log provider owns the batch processor/exporter and flushes it.
        if logging_instrumentor is not None:
            logging_instrumentor.uninstrument()
        if logger_provider is not None:
            logger_provider.shutdown()
        meter_provider.shutdown()
        tracer_provider.shutdown()

    return shutdown
```

This new-process example defaults only an absent or explicit `otlp` log
exporter to local Observer. If `OTEL_LOGS_EXPORTER=none`, or another explicit
exporter is selected, it leaves logging untouched so the operator-owned setup
can take effect. Do not broaden the condition to install local OTLP alongside
another exporter. Register the returned `shutdown` callback with the app's
existing lifecycle or `atexit`; do not create a second provider during reloads
or per worker request.

`LoggingInstrumentor` is the current stdlib-to-OTel bridge. Its handler is an
additional path, and its guarded configuration wrappers let later application
logging setup proceed before reattaching the OTel handler. Do not use
`logging.basicConfig(force=True)`. Inspect filters, formatters, adapters,
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
shutdown_opentelemetry = configure_opentelemetry()
atexit.register(shutdown_opentelemetry)

from opentelemetry.instrumentation.flask import FlaskInstrumentor
from flask import Flask

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
```

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
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | Common protocol when using port 4318 |
| `OTEL_EXPORTER_OTLP_<SIGNAL>_ENDPOINT` | unset | Per-signal endpoint, including `/v1/<signal>` for HTTP exporters |
| `OTEL_EXPORTER_OTLP_<SIGNAL>_PROTOCOL` | unset | Per-signal `grpc` or `http/protobuf` |
| `OTEL_LOGS_EXPORTER` | `otlp` for Obstudio instrumentation | `none` disables the added local log pipeline; another explicit value remains operator-owned |
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
stack. An explicit `OTEL_LOGS_EXPORTER` or
`OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` wins; `none` disables the added provider and
handler while existing stdout/file logging continues. When traces or metrics
use direct-cloud signal endpoints, keep the logs endpoint on the local Observer
receiver. Never copy a Splunk ingest URL, realm, access token, generic cloud
header, cloud exporter, or forwarding flag into the log pipeline. Preserve an
explicit operator-owned logs endpoint without converting it into an additional
local or cloud path. If that endpoint is direct-cloud, do not add or claim an
Obstudio-owned log pipeline: preserve it as external operator configuration,
report the boundary conflict, and require the operator to resolve it. Obstudio
cloud forwarding remains traces and metrics only.

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

- **SDK init before framework**: `configure_opentelemetry()` must be called
  before creating Flask/FastAPI/Django app objects. Auto-instrumentation
  patches happen at import time -- the SDK must be configured first.
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
  process gets its own SDK instance.
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
