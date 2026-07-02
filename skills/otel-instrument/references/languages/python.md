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
| `logging` (stdlib) | `opentelemetry-instrumentation-logging` | Inject trace context into log records |

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

---

## Auto-Instrumentation (CLI Wrapper)

Reuse the current app command and wrap it with the OTel auto-instrumentation agent. Do not introduce Docker just for observability.

```bash
opentelemetry-instrument \
  --service_name my-service \
  --exporter_otlp_endpoint http://localhost:4318 \
  --resource_attributes deployment.environment.name=production \
  python app.py
```

Wrap the same command the project already uses, such as `python`, `uv run`, `poetry run`, `gunicorn`, or `uvicorn`.

If the project already runs in Docker:
```dockerfile
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
CMD ["opentelemetry-instrument", "--service_name", "my-service", "python", "app.py"]
```

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
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
import os


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
```

The explicit `export_interval_millis` and `export_timeout_millis` are required
for local and eval runs. Do not rely on metric reader defaults; they can be too
slow for short-lived runtime checks, causing valid HTTP metrics to never reach
the collector before the process stops.

### Loading the SDK

**Option 1** -- import at top of entry point (preferred):

```python
# app.py
from otel_setup import configure_opentelemetry
configure_opentelemetry()

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

All configuration is via environment variables. Do not hardcode endpoints.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Common OTLP endpoint; protocol must match |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | Common protocol when using port 4318 |
| `OTEL_EXPORTER_OTLP_<SIGNAL>_ENDPOINT` | unset | Per-signal endpoint, including `/v1/<signal>` for HTTP exporters |
| `OTEL_EXPORTER_OTLP_<SIGNAL>_PROTOCOL` | unset | Per-signal `grpc` or `http/protobuf` |
| `OTEL_SERVICE_NAME` | (must be set) | Service identity in telemetry |
| `OTEL_METRIC_EXPORT_INTERVAL` | `60000` | Metric export interval (ms) |
| `OTEL_METRIC_EXPORT_TIMEOUT` | `30000` | Metric export timeout (ms) |
| `OTEL_BSP_SCHEDULE_DELAY` | `5000` | Span batch export delay (ms) |

For local development with the Observer:

    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
    OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
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
