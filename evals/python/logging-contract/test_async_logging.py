"""Maintained native async logging probes; no application/receiver claim."""
import asyncio
import contextvars
from concurrent.futures import ThreadPoolExecutor
import logging
from logging.handlers import QueueHandler, QueueListener
import io
import queue
import unittest

from opentelemetry import trace
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor, InMemoryLogRecordExporter, SimpleLogRecordProcessor,
)


def span(value, flags=1):
    return trace.NonRecordingSpan(trace.SpanContext(value, value + 100, False, trace.TraceFlags(flags)))


class AsyncLogging(unittest.TestCase):
    def setUp(self):
        self.exporter = InMemoryLogRecordExporter()
        self.provider = LoggerProvider(shutdown_on_exit=False)
        self.provider.add_log_record_processor(SimpleLogRecordProcessor(self.exporter))
        self.logger = logging.getLogger(self.id())
        self.logger.handlers = [LoggingHandler(logger_provider=self.provider)]
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

    def tearDown(self):
        self.logger.handlers.clear()
        self.provider.shutdown()

    def expect(self, expected):
        records = [x.log_record for x in self.exporter.get_finished_logs()]
        self.assertEqual(len(records), len(expected))
        self.assertEqual(len({r.body for r in records}), len(records))
        for r in records:
            value, flags = expected[r.body]
            self.assertEqual((r.trace_id, r.span_id, int(r.trace_flags)),
                             (value, value + 100 if value else 0, flags))
            self.assertEqual(r.severity_number.value, 9)

    def test_parent_context_at_task_creation_survives_detach(self):
        async def run():
            gate = asyncio.Event()
            async def child(message):
                await gate.wait()
                self.logger.info(message)
            tasks = []
            for flags in (0, 1):
                with trace.use_span(span(11 + flags, flags)):
                    tasks.append(asyncio.create_task(child(f"task-{flags}")))
            self.logger.info("outside")
            gate.set()
            await asyncio.wait_for(asyncio.gather(*tasks), 2)
        asyncio.run(run())
        self.expect({"task-0": (11, 0), "task-1": (12, 1), "outside": (0, 0)})

    def test_concurrent_parent_contexts_match_exact_records(self):
        self.provider.shutdown()
        self.exporter = InMemoryLogRecordExporter()
        self.provider = LoggerProvider(shutdown_on_exit=False)
        self.provider.add_log_record_processor(BatchLogRecordProcessor(self.exporter, schedule_delay_millis=60000))
        self.logger.handlers = [LoggingHandler(logger_provider=self.provider)]
        async def run():
            gate = asyncio.Event()
            async def child(value):
                await gate.wait()
                self.logger.info(f"before-{value}")
                await asyncio.sleep(0)
                self.logger.info(f"after-{value}")
            tasks = []
            for value in range(1, 21):
                with trace.use_span(span(value, value % 2)):
                    tasks.append(asyncio.create_task(child(value)))
            gate.set()
            await asyncio.wait_for(asyncio.gather(*tasks), 2)
        asyncio.run(run())
        self.assertTrue(self.provider.force_flush(timeout_millis=2000))
        self.expect({f"{phase}-{i}": (i, i % 2) for i in range(1, 21) for phase in ("before", "after")})

    def test_thread_handoff_and_reuse_with_negative_control(self):
        async def run():
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor(max_workers=1) as pool:
                with trace.use_span(span(31)):
                    await asyncio.wait_for(asyncio.to_thread(self.logger.info, "to-thread"), 2)
                    await asyncio.wait_for(loop.run_in_executor(pool, self.logger.info, "raw-executor"), 2)
                    copied = contextvars.copy_context()
                await asyncio.wait_for(loop.run_in_executor(pool, copied.run, self.logger.info, "copied-executor"), 2)
                await asyncio.wait_for(loop.run_in_executor(pool, self.logger.info, "reused-clean"), 2)
        asyncio.run(run())
        self.expect({"to-thread": (31, 1), "raw-executor": (0, 0), "copied-executor": (31, 1), "reused-clean": (0, 0)})

    def test_error_and_cancellation_restore_context(self):
        async def run():
            entered = asyncio.Event()
            async def child(cancel):
                try:
                    with trace.use_span(span(42)):
                        if cancel:
                            entered.set()
                            await asyncio.Event().wait()
                        raise ValueError("synthetic failure")
                finally:
                    self.logger.info("cancel-cleanup" if cancel else "error-cleanup")
            with trace.use_span(span(41)):
                failed = asyncio.create_task(child(False))
                cancelled = asyncio.create_task(child(True))
            with self.assertRaises(ValueError):
                await asyncio.wait_for(failed, 2)
            await asyncio.wait_for(entered.wait(), 2)
            cancelled.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(cancelled, 2)
            self.logger.info("outside-after-error-cancel")
        asyncio.run(run())
        self.expect({"error-cleanup": (41, 1), "cancel-cleanup": (41, 1), "outside-after-error-cancel": (0, 0)})

    def test_batch_export_uses_emit_context_after_detach(self):
        self.provider.shutdown()
        self.exporter = InMemoryLogRecordExporter()
        self.provider = LoggerProvider(shutdown_on_exit=False)
        self.provider.add_log_record_processor(BatchLogRecordProcessor(self.exporter, schedule_delay_millis=60000))
        self.logger.handlers = [LoggingHandler(logger_provider=self.provider)]
        with trace.use_span(span(51, 0)):
            self.logger.info("queued")
        with trace.use_span(span(99)):
            self.assertTrue(self.provider.force_flush(timeout_millis=2000))
        self.expect({"queued": (51, 0)})

    def test_bridge_after_queue_listener_is_missing_context_control(self):
        pending = queue.Queue()
        bridge = LoggingHandler(logger_provider=self.provider)
        listener = QueueListener(pending, bridge)
        self.logger.handlers = [QueueHandler(pending)]
        listener.start()
        try:
            with trace.use_span(span(61)):
                self.logger.info("queue-before-bridge")
        finally:
            listener.stop()
        self.expect({"queue-before-bridge": (0, 0)})

    def test_caller_bridge_beside_async_original_sink_retains_context(self):
        pending = queue.Queue()
        sink = io.StringIO()
        listener = QueueListener(pending, logging.StreamHandler(sink))
        self.logger.handlers = [LoggingHandler(logger_provider=self.provider), QueueHandler(pending)]
        listener.start()
        try:
            with trace.use_span(span(62)):
                self.logger.info("bridge-before-queue-sink")
        finally:
            listener.stop()
        self.expect({"bridge-before-queue-sink": (62, 1)})
        self.assertEqual(sink.getvalue().count("bridge-before-queue-sink"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
