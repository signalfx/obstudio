"""Focused real SDK/stdlib-bridge tests; no application or receiver claim."""

import asyncio
import io
import logging
import os
import time
import unittest
from unittest.mock import patch

from opentelemetry import trace
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider, LogRecordLimits
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    InMemoryLogRecordExporter,
    LogRecordExporter,
    LogRecordExportResult,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.resources import Resource


class FailedExporter(LogRecordExporter):
    def __init__(self):
        self.calls = 0

    def export(self, batch):
        self.calls += 1
        return LogRecordExportResult.FAILURE

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


class LoggingContract(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemoryLogRecordExporter()
        self.provider = LoggerProvider(
            resource=Resource.create({"service.name": "python-logging-contract"}),
            log_record_limits=LogRecordLimits(
                max_log_record_attributes=8, max_log_record_attribute_length=32,
            ),
        )
        self.provider.add_log_record_processor(SimpleLogRecordProcessor(self.exporter))
        self.logger = logging.getLogger(self.id())
        self.logger.handlers.clear()
        self.logger.propagate = False
        self.logger.setLevel(logging.DEBUG)
        self.sink = io.StringIO()
        self.logger.addHandler(logging.StreamHandler(self.sink))
        self.logger.addHandler(LoggingHandler(logger_provider=self.provider))

    def tearDown(self):
        self.logger.handlers.clear()
        self.provider.shutdown()

    def records(self):
        return [r.log_record for r in self.exporter.get_finished_logs()]

    def test_severity_and_occurrence_timestamp(self):
        record = self.logger.makeRecord(self.logger.name, logging.ERROR, __file__, 1, "failed", (), None)
        record.created = 1730000000.125
        self.logger.handle(record)
        result = self.records()[0]
        self.assertEqual(result.severity_number.value, 17)
        self.assertEqual(result.timestamp, int(record.created * 1e9))
        self.assertGreater(result.observed_timestamp, result.timestamp)
        self.assertEqual(self.sink.getvalue().count("failed"), 1)

    def test_sampled_unsampled_and_detached_context(self):
        for flags in (0, 1):
            ctx = trace.SpanContext(0x11, 0x22, False, trace.TraceFlags(flags))
            with trace.use_span(trace.NonRecordingSpan(ctx)):
                self.logger.error("inside")
        self.logger.info("outside")
        first, second, outside = self.records()
        for flags, record in enumerate((first, second)):
            self.assertEqual((record.trace_id, record.span_id, int(record.trace_flags)), (0x11, 0x22, flags))
        self.assertEqual((outside.trace_id, outside.span_id), (0, 0))

    def test_preserves_meaningful_zero_false_and_empty_attributes(self):
        self.logger.info("falsy-values", extra={"zero": 0, "disabled": False, "empty": "", "items": []})
        self.assertEqual(len(self.records()), 1)
        attributes = self.records()[0].attributes
        self.assertIs(type(attributes["zero"]), int)
        self.assertEqual(attributes["zero"], 0)
        self.assertIs(attributes["disabled"], False)
        self.assertEqual(attributes["empty"], "")
        self.assertIsInstance(attributes["items"], (list, tuple))
        self.assertEqual(len(attributes["items"]), 0)
        self.assertEqual(self.sink.getvalue(), "falsy-values\n")

    def test_async_context_isolation(self):
        async def task(value):
            ctx = trace.SpanContext(value, value, False, trace.TraceFlags(1))
            with trace.use_span(trace.NonRecordingSpan(ctx)):
                await asyncio.sleep(0)
                self.logger.info(str(value))

        async def run():
            await asyncio.gather(task(17), task(34))

        asyncio.run(run())
        self.assertEqual({(r.body, r.trace_id) for r in self.records()}, {("17", 17), ("34", 34)})

    def test_limits_and_explicit_privacy_policy(self):
        # The producer owns this allowlist; SDK truncation is tested separately.
        self.logger.error("request failed", extra={"exception.type": "ValueError"})
        safe = self.records()[0]
        self.assertEqual(safe.attributes["exception.type"], "ValueError")
        self.assertNotIn("exception.message", safe.attributes)
        self.assertNotIn("exception.stacktrace", safe.attributes)
        self.provider.get_logger("limits").emit(body="x" * 400, attributes={f"k{i}": "v" * 100 for i in range(20)})
        result = self.records()[-1]
        self.assertEqual(len(result.attributes), 8)
        self.assertTrue(all(len(v) == 32 for v in result.attributes.values()))
        self.assertEqual(self.exporter.get_finished_logs()[-1].dropped_attributes, 12)
        self.assertEqual(len(result.body), 400, "attribute limits must not be mistaken for a Body bound")

    def test_log_specific_environment_precedence(self):
        environment = {
            "OTEL_LOGRECORD_ATTRIBUTE_COUNT_LIMIT": "128",
            "OTEL_LOGRECORD_ATTRIBUTE_VALUE_LENGTH_LIMIT": "64",
        }
        with patch.dict(os.environ, environment):
            configurations = (
                ("generic_fallback", LogRecordLimits(max_attributes=8, max_attribute_length=32), 20, 64, 0),
                ("selected_log_specific", LogRecordLimits(
                    max_log_record_attributes=8, max_log_record_attribute_length=32,
                ), 8, 32, 12),
            )
            for name, limits, count, length, dropped in configurations:
                with self.subTest(configuration=name):
                    exporter = InMemoryLogRecordExporter()
                    provider = LoggerProvider(
                        resource=self.provider.resource, log_record_limits=limits,
                        shutdown_on_exit=False,
                    )
                    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
                    try:
                        provider.get_logger("precedence").emit(
                            body="limit-probe",
                            attributes={f"a{i}": "x" * 80 for i in range(20)},
                        )
                        record = exporter.get_finished_logs()[0]
                        self.assertEqual(len(record.log_record.attributes), count)
                        self.assertEqual({len(v) for v in record.log_record.attributes.values()}, {length})
                        self.assertEqual(record.dropped_attributes, dropped)
                        self.assertEqual(record.resource, self.provider.resource)
                    finally:
                        provider.shutdown()

    def test_export_failure_is_bounded_and_keeps_original_sink(self):
        failed = FailedExporter()
        provider = LoggerProvider(shutdown_on_exit=False)
        provider.add_log_record_processor(BatchLogRecordProcessor(failed, max_queue_size=8, max_export_batch_size=8, schedule_delay_millis=1000, export_timeout_millis=100))
        handler = LoggingHandler(logger_provider=provider)
        self.logger.handlers[-1] = handler
        start = time.monotonic()
        self.logger.error("receiver unavailable")
        provider.force_flush(timeout_millis=1000)
        provider.shutdown()
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(failed.calls, 1)
        self.assertEqual(self.sink.getvalue().count("receiver unavailable"), 1)
        self.assertEqual(len(self.records()), 0)

    def test_explicit_bridge_opt_out_keeps_original_sink(self):
        self.logger.removeHandler(self.logger.handlers[-1])
        self.logger.error("disabled")
        self.assertEqual(len(self.records()), 0)
        self.assertEqual(self.sink.getvalue().count("disabled"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
