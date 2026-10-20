import json
import logging
import os
from pathlib import Path

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def configure():
    resource = Resource.create({"service.name": "agent-connection-demo"})
    spans = InMemorySpanExporter()
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(SimpleSpanProcessor(spans))
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tp)
    reader = InMemoryMetricReader()
    mp = MeterProvider(resource=resource, metric_readers=[reader, PeriodicExportingMetricReader(OTLPMetricExporter())])
    metrics.set_meter_provider(mp)
    logs = InMemoryLogRecordExporter()
    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(SimpleLogRecordProcessor(logs))
    lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    logger = logging.getLogger("connection-agent")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())
    logger.addHandler(LoggingHandler(logger_provider=lp))

    def finish():
        try:
            tp.force_flush()
            mp.force_flush()
            lp.force_flush()
            native = reader.get_metrics_data()
            record = {
                "providers_retained": {"traces": trace.get_tracer_provider() is tp,
                                       "metrics": metrics.get_meter_provider() is mp},
                "spans": [{"name": s.name, "trace_id": f"{s.context.trace_id:032x}", "span_id": f"{s.context.span_id:016x}",
                           "parent_id": f"{s.parent.span_id:016x}" if s.parent else None, "attributes": dict(s.attributes)}
                          for s in spans.get_finished_spans()],
                "metrics": [{"name": m.name, "values": [p.value for p in m.data.data_points]}
                            for r in native.resource_metrics for scope in r.scope_metrics for m in scope.metrics],
                "logs": [{"body": r.log_record.body, "trace_id": f"{r.log_record.trace_id:032x}"}
                         for r in logs.get_finished_logs()],
            }
            if os.getenv("LOCAL_CAPTURE_FILE"):
                Path(os.environ["LOCAL_CAPTURE_FILE"]).write_text(json.dumps(record, indent=2))
        finally:
            tp.shutdown()
            mp.shutdown()
            lp.shutdown()

    return finish
