from __future__ import annotations

import atexit
import os

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


# Intentionally wrong for the Gunicorn preload model: importing the app in the
# master creates provider threads that are then inherited by forked workers.
PROVIDER_PID = os.getpid()
RESOURCE = Resource.create(
    {"service.name": os.getenv("OTEL_SERVICE_NAME", "customer-python")}
)

TRACER_PROVIDER = TracerProvider(resource=RESOURCE)
TRACER_PROVIDER.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(TRACER_PROVIDER)

METRIC_READER = PeriodicExportingMetricReader(
    ConsoleMetricExporter(),
    export_interval_millis=60_000,
)
METER_PROVIDER = MeterProvider(resource=RESOURCE, metric_readers=[METRIC_READER])
metrics.set_meter_provider(METER_PROVIDER)

tracer = trace.get_tracer(__name__)


def shutdown() -> None:
    METER_PROVIDER.shutdown()
    TRACER_PROVIDER.shutdown()


atexit.register(shutdown)
