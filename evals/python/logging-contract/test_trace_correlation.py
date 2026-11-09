"""Join real SDK spans and bridged application logs at the OTLP receiver."""

import asyncio
import io
import json
import logging
import os
from urllib.parse import urlsplit
from urllib.request import urlopen

import pytest
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF


def test_real_spans_join_caller_and_async_logs_without_fabricated_ids():
    base = os.environ.get("LOGGING_CONTRACT_RECEIVER_URL")
    if not base:
        pytest.skip("Use run_logging_contract.py for the owned loopback receiver")
    assert urlsplit(base).hostname == "127.0.0.1"
    resource = Resource.create({"service.name": "python-correlation"})
    providers = [TracerProvider(resource=resource), TracerProvider(resource=resource, sampler=ALWAYS_OFF)]
    for provider in providers:
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{base}/correlation/v1/traces", timeout=1),
            max_queue_size=128, max_export_batch_size=64, schedule_delay_millis=60000,
            export_timeout_millis=3000,
        ))
    logs = LoggerProvider(resource=resource, shutdown_on_exit=False)
    logs.add_log_record_processor(BatchLogRecordProcessor(
        OTLPLogExporter(endpoint=f"{base}/correlation/v1/logs", timeout=1),
        max_queue_size=128, max_export_batch_size=64, schedule_delay_millis=60000,
        export_timeout_millis=3000,
    ))
    sink = io.StringIO()
    logger = logging.getLogger("real-trace-correlation")
    logger.handlers = [logging.StreamHandler(sink), LoggingHandler(logger_provider=logs)]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    tracer = providers[0].get_tracer("correlation")
    expected = {}

    def work(index):
        with tracer.start_as_current_span(f"work-{index}") as span:
            expected[f"child-{index}"] = span.get_span_context()
            logger.info("child-%d", index)

    async def request(index):
        with tracer.start_as_current_span(f"request-{index}") as span:
            await asyncio.to_thread(work, index)
            expected[f"parent-{index}"] = span.get_span_context()
            logger.info("parent-%d", index)

    async def requests():
        await asyncio.gather(*(request(i) for i in range(10)))

    try:
        asyncio.run(requests())
        with providers[1].get_tracer("correlation").start_as_current_span("unsampled") as span:
            unsampled = span.get_span_context()
            assert unsampled.is_valid and not span.is_recording()
            assert not unsampled.trace_flags.sampled
            logger.info("unsampled")
        logger.info("outside")
        assert logs.force_flush(timeout_millis=4000)
        assert all(p.force_flush(timeout_millis=4000) for p in providers)
        origin, key = base.rsplit("/", 1)

        def receipt(suffix):
            with urlopen(f"{origin}/evidence/{key}/correlation{suffix}", timeout=2) as response:
                return json.load(response)

        received_logs, received_spans = receipt(""), receipt("/traces")
        assert received_logs["accepted"] == 22
        assert received_spans["accepted"] == 20
        assert received_logs["requests"] == received_spans["requests"] == 1
        spans = {(s["trace_id"], s["span_id"]): s for s in received_spans["spans"]}
        assert len(spans) == 20
        records = {r["body"]["stringValue"]: r for r in received_logs["records"]}
        assert len(records) == 22
        for body, context in expected.items():
            assert context.trace_flags.sampled
            record = records[body]
            pair = (format(context.trace_id, "032x"), format(context.span_id, "016x"))
            assert (record["trace_id"], record["span_id"], record["flags"] & 0xff) == (*pair, int(context.trace_flags))
            assert pair in spans
            assert record["resource"]["service.name"] == spans[pair]["resource"]["service.name"] == {"stringValue": "python-correlation"}
            if body.startswith("child-"):
                parent = expected[body.replace("child-", "parent-")]
                assert spans[pair]["parent_span_id"] == format(parent.span_id, "016x")
                assert context.trace_id == parent.trace_id
        record = records["unsampled"]
        assert (record["trace_id"], record["span_id"], record["flags"] & 0xff) == (format(unsampled.trace_id, "032x"), format(unsampled.span_id, "016x"), int(unsampled.trace_flags))
        assert (record["trace_id"], record["span_id"]) not in spans
        assert (records["outside"]["trace_id"], records["outside"]["span_id"]) == ("", "")
        assert len(sink.getvalue().splitlines()) == 22
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
        logs.shutdown()
        for provider in providers:
            provider.shutdown()
