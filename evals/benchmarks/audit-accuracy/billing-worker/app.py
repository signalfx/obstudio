from __future__ import annotations

import os
import asyncio
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


async def charge(telemetry, failed):
    with telemetry.tracer.start_as_current_span("charge", kind=SpanKind.CLIENT) as span:
        span.set_attribute("server.address", "billing.internal")
        await asyncio.sleep(0)
        if failed:
            error = RuntimeError("payment unavailable")
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, "payment unavailable"))
            return False
        return True


async def invoice(telemetry, failed=False):
    with telemetry.tracer.start_as_current_span("invoice") as span:
        result = await asyncio.create_task(charge(telemetry, failed))
        telemetry.counter.add(1, {"outcome": "ok" if result else "error"})
        if not result:
            span.set_status(Status(StatusCode.ERROR, "payment unavailable"))
        return result


if __name__ == "__main__":
    telemetry = Telemetry()
    try:
        asyncio.run(invoice(telemetry))
    finally:
        telemetry.close()
