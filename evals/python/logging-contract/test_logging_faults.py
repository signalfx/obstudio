"""Real exception inputs, queue overload and SDK diagnostic routing boundaries."""

from contextlib import contextmanager
import io
import json
import logging
import subprocess
import sys
import threading
import time
import uuid

from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    BatchLogRecordProcessor,
    InMemoryLogRecordExporter,
    LogRecordExporter,
    LogRecordExportResult,
    SimpleLogRecordProcessor,
)


@contextmanager
def logging_path(exporter, batch=False):
    provider = LoggerProvider(shutdown_on_exit=False)
    processor = (
        BatchLogRecordProcessor(
            exporter, max_queue_size=8, max_export_batch_size=4,
            schedule_delay_millis=60000,
        )
        if batch else SimpleLogRecordProcessor(exporter)
    )
    provider.add_log_record_processor(processor)
    logger = logging.getLogger(f"logging-fault-{uuid.uuid4()}")
    sink = io.StringIO()
    logger.handlers = [logging.StreamHandler(sink), LoggingHandler(logger_provider=provider)]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield logger, provider, sink
    finally:
        logger.handlers.clear()
        provider.shutdown()


def log_failure(logger, error, fields):
    # Fixture-owned policy: fixed category and explicitly permitted fields only.
    logger.error("request failed", extra={
        "exception.type": type(error).__name__, "request.id": fields["request.id"],
    })


def test_real_exception_is_minimized_before_bridge_and_original_sink():
    exporter = InMemoryLogRecordExporter()
    canary = "password=synthetic-private-canary"
    fields = {"request.id": "request-1", "payload": {"token": canary}, "error.kind": "ValueError"}
    with logging_path(exporter) as (logger, _, sink):
        try:
            raise ValueError(canary)
        except ValueError as error:
            logger.error("unsafe control", exc_info=True, extra=fields)
            unsafe = exporter.get_finished_logs()[0].log_record
            assert canary in unsafe.attributes["exception.message"]
            assert canary in unsafe.attributes["exception.stacktrace"]
            assert unsafe.attributes["error.kind"] == "ValueError"
            assert canary in sink.getvalue()
            sink.seek(0)
            sink.truncate()
            log_failure(logger, error, fields)
        safe = exporter.get_finished_logs()[1].log_record
        assert safe.attributes["exception.type"] == "ValueError"
        assert safe.attributes["request.id"] == "request-1"
        assert safe.body == "request failed"
        assert "exception.message" not in safe.attributes
        assert "exception.stacktrace" not in safe.attributes
        assert "payload" not in safe.attributes
        assert "error.kind" not in safe.attributes
        assert canary not in json.dumps({"body": safe.body, "attributes": dict(safe.attributes)})
        assert sink.getvalue() == "request failed\n"


class BlockingExporter(LogRecordExporter):
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.bodies = []
        self.batch_sizes = []

    def export(self, batch):
        self.entered.set()
        if not self.release.wait(2):
            raise RuntimeError("controlled exporter release deadline")
        self.batch_sizes.append(len(batch))
        self.bodies.extend(item.log_record.body for item in batch)
        return LogRecordExportResult.SUCCESS

    def shutdown(self):
        self.release.set()

    def force_flush(self, timeout_millis=30000):
        return True


def test_overload_has_bounded_batches_and_observable_local_loss():
    exporter = BlockingExporter()
    attempted = 24
    started = time.monotonic()
    with logging_path(exporter, batch=True) as (logger, provider, sink):
        try:
            for i in range(4):
                logger.info("record-%d", i)
            assert exporter.entered.wait(1)
            for i in range(4, attempted):
                logger.info("record-%d", i)
            assert len(sink.getvalue().splitlines()) == attempted
        finally:
            exporter.release.set()
        assert provider.force_flush(timeout_millis=2000)
        exported = len(exporter.bodies)
        assert 4 <= exported < attempted
        assert len(set(exporter.bodies)) == exported
        assert max(exporter.batch_sizes) <= 4 <= 8
        inferred_local_drops = attempted - exported
        assert inferred_local_drops > 0
    assert time.monotonic() - started < 3


class RaisingExporter(LogRecordExporter):
    def __init__(self):
        self.calls = 0
        self.bodies = []

    def export(self, batch):
        self.calls += 1
        self.bodies.extend(item.log_record.body for item in batch)
        raise RuntimeError("synthetic receiver unavailable")

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


def _sdk_diagnostic_route_trial(mode):
    # A child interpreter keeps SDK filters and global logging state isolated.
    root = logging.getLogger()
    diagnostic_logger = logging.getLogger("opentelemetry.sdk._shared_internal")
    assert not root.handlers
    assert not diagnostic_logger.handlers and diagnostic_logger.propagate
    exporter = RaisingExporter()
    with logging_path(exporter, batch=True) as (logger, provider, sink):
        bridge = next(handler for handler in logger.handlers if isinstance(handler, LoggingHandler))
        if mode != "fallback":
            bridge.addFilter(lambda record: not (
                record.name == "opentelemetry" or record.name.startswith("opentelemetry.")
            ))
            root.addHandler(bridge)
        if mode == "native":
            diagnostic_logger.addHandler(logging.StreamHandler())
            diagnostic_logger.propagate = False
        elif mode == "suppressed":
            diagnostic_logger.setLevel(logging.CRITICAL)
        enabled = diagnostic_logger.isEnabledFor(logging.ERROR)
        logger.error("first failure")
        assert provider.force_flush(timeout_millis=2000)
        logger.info("application continued")
        assert provider.force_flush(timeout_millis=2000)
        native = sink.getvalue().splitlines()
    return {"calls": exporter.calls, "bodies": exporter.bodies,
            "native": native, "diagnostic_error_enabled": enabled}


def test_sdk_failure_diagnostics_are_visible_outside_application_bridge():
    exporter = RaisingExporter()
    diagnostic_logger = logging.getLogger("opentelemetry.sdk._shared_internal")
    previous = diagnostic_logger.handlers[:], diagnostic_logger.level, diagnostic_logger.propagate
    diagnostics = io.StringIO()
    diagnostic_logger.handlers = [logging.StreamHandler(diagnostics)]
    diagnostic_logger.setLevel(logging.ERROR)
    diagnostic_logger.propagate = False
    try:
        with logging_path(exporter, batch=True) as (logger, provider, sink):
            logger.error("first failure")
            assert provider.force_flush(timeout_millis=2000)
            logger.info("application continued")
            assert provider.force_flush(timeout_millis=2000)
            assert exporter.calls == 2
            assert 1 <= diagnostics.getvalue().count("Exception while exporting") <= 2
            assert sink.getvalue().splitlines() == ["first failure", "application continued"]
    finally:
        diagnostic_logger.handlers, diagnostic_logger.level, diagnostic_logger.propagate = previous

    script = (
        "import json,runpy,sys; "
        "trial=runpy.run_path(sys.argv[1])['_sdk_diagnostic_route_trial']; "
        "print(json.dumps(trial(sys.argv[2])))"
    )
    for mode in ("fallback", "filtered", "native", "suppressed"):
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script, __file__, mode],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr
        observation = json.loads(result.stdout)
        assert observation["calls"] == 2
        assert observation["bodies"] == ["first failure", "application continued"]
        assert observation["native"] == ["first failure", "application continued"]
        assert observation["diagnostic_error_enabled"] is (mode != "suppressed")
        diagnostic_count = result.stderr.count("Exception while exporting")
        if mode in {"fallback", "native"}:
            assert 1 <= diagnostic_count <= 2, result.stderr
        else:
            assert diagnostic_count == 0, result.stderr
