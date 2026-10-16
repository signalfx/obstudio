from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.trace import SpanKind, Status, StatusCode


class Telemetry:
    def __init__(self, exporter=None, reader=None):
        self.provider = TracerProvider(resource=Resource.create({}))
        self.provider.add_span_processor(SimpleSpanProcessor(exporter if exporter is not None else OTLPSpanExporter()))
        self.tracer = self.provider.get_tracer("service")
        self.reader = reader if reader is not None else PeriodicExportingMetricReader(OTLPMetricExporter())
        self.meters = MeterProvider(resource=Resource.create({}), metric_readers=[self.reader])
        self.counter = self.meters.get_meter("service").create_counter("jobs.completed", unit="{job}")

    def close(self):
        self.provider.shutdown()
        self.meters.shutdown()


def deliver(telemetry, job_id, failed):
    with telemetry.tracer.start_as_current_span("deliver", kind=SpanKind.CLIENT):
        telemetry.counter.add(1, {"job.id": job_id})
        try:
            if failed:
                raise RuntimeError("delivery unavailable")
        except RuntimeError:
            return False
        return True


def dispatch(telemetry, job_id="job-7", failed=False):
    with telemetry.tracer.start_as_current_span("dispatch"):
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(deliver, telemetry, job_id, failed).result()


if __name__ == "__main__":
    telemetry = Telemetry()
    try:
        dispatch(telemetry, failed=True)
    finally:
        telemetry.close()
