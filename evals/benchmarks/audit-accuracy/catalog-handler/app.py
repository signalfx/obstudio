from __future__ import annotations

import os
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


def read_item(telemetry, item_id="sku-7", customer_email="buyer@example.test", failed=False):
    with telemetry.tracer.start_as_current_span(f"GET /items/{item_id}") as span:
        span.set_attribute("http.route", "/items/{item_id}")
        span.set_attribute("customer.email", customer_email)
        span.set_attribute("http.request.method", "GET")
        telemetry.counter.add(1, {"outcome": "error" if failed else "ok"})
        if failed:
            error = RuntimeError("catalog unavailable")
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, "catalog unavailable"))
            span.set_attribute("http.response.status_code", 503)
            return None
        span.set_attribute("http.response.status_code", 200)
        return {"id": item_id}


if __name__ == "__main__":
    telemetry = Telemetry()
    try:
        read_item(telemetry)
    finally:
        telemetry.close()
