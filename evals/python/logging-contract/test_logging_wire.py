"""Replay bridge-produced SDK records through the real OTLP/HTTP exporter."""

import io
import json
import logging
import os
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

import pytest
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, LogRecordExportResult, SimpleLogRecordProcessor


@pytest.mark.parametrize("scenario", ["healthy", "partial", "stall"])
def test_otlp_wire_record_receipt_partial_success_and_timeout(scenario):
    base = os.environ.get("LOGGING_CONTRACT_RECEIVER_URL")
    if not base:
        pytest.skip("Use run_logging_contract.py for the owned loopback receiver")
    assert urlsplit(base).hostname == "127.0.0.1"
    origin, key = base.rsplit("/", 1)

    def get(path):
        with urlopen(f"{origin}/{path}", timeout=2) as response:
            return json.load(response)

    memory = InMemoryLogRecordExporter()
    provider = LoggerProvider(shutdown_on_exit=False)
    provider.add_log_record_processor(SimpleLogRecordProcessor(memory))
    sink = io.StringIO()
    logger = logging.getLogger(f"wire-{scenario}")
    logger.handlers = [logging.StreamHandler(sink), LoggingHandler(logger_provider=provider)]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    exporter = OTLPLogExporter(endpoint=f"{base}/{scenario}/v1/logs", timeout=0.2)
    try:
        expected = 1 if scenario == "stall" else 3
        context = trace.SpanContext(int("11" * 16, 16), int("22" * 8, 16), False, trace.TraceFlags(0))
        with trace.use_span(trace.NonRecordingSpan(context)):
            for i in range(expected):
                logger.error("wire-%d", i)
        started = time.monotonic()
        batch = memory.get_finished_logs()
        result = exporter.export(batch)
        assert time.monotonic() - started < 2
        receipt = get(f"evidence/{key}/{scenario}")
        assert receipt["received"] == expected
        for i, record in enumerate(receipt["records"]):
            assert record["body"] == {"stringValue": f"wire-{i}"}
            assert (record["trace_id"], record["span_id"], record["flags"] & 0xff, record["severity"]) == ("11" * 16, "22" * 8, 0, 17)
            assert int(record["timestamp_unix_nano"]) == batch[i].log_record.timestamp
        if scenario == "stall":
            assert result == LogRecordExportResult.FAILURE
            assert receipt["accepted"] == 0 and receipt["pending"] == 1
            get(f"release-stall/{key}/{scenario}")
            deadline = time.monotonic() + 1
            while get(f"evidence/{key}/{scenario}")["pending"] and time.monotonic() < deadline:
                time.sleep(0.01)
            assert get(f"evidence/{key}/{scenario}")["accepted"] == 1
        else:
            assert result == LogRecordExportResult.SUCCESS
            assert receipt["requests"] == 1
            assert (receipt["accepted"], receipt["rejected"]) == ((1, 2) if scenario == "partial" else (3, 0))
        assert len(sink.getvalue().splitlines()) == expected
        logger.info("application continued")
        assert sink.getvalue().endswith("application continued\n")
    finally:
        if scenario == "stall":
            get(f"release-stall/{key}/{scenario}")
        exporter.shutdown()
        logger.handlers.clear()
        provider.shutdown()
