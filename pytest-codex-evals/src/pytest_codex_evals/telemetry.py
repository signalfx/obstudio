from __future__ import annotations

import contextlib
import contextvars
import functools
import importlib.metadata
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


_telemetry = contextvars.ContextVar("codex_eval_telemetry", default=None)
_run = contextvars.ContextVar("codex_eval_run", default=None)
_SCOPE = "pytest_codex_evals.skills"


def _observe(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception:
        return None


@contextlib.contextmanager
def _span(tracer, name, attrs):
    stack = contextlib.ExitStack()
    span = None
    if tracer:
        manager = _observe(tracer.start_as_current_span, name, kind=trace.SpanKind.INTERNAL, attributes=attrs, record_exception=False, set_status_on_exception=False)
        if manager is not None:
            span = _observe(stack.enter_context, manager)
    try:
        yield span
    finally:
        _observe(stack.close)


def _endpoint(signal: str) -> str:
    explicit = os.environ.get(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT")
    if explicit:
        return explicit
    base = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    parsed = urlsplit(base)
    path = parsed.path.rstrip("/")
    for leaf in ("/v1/traces", "/v1/metrics", "/v1/logs"):
        if path.endswith(leaf):
            path = path[:-len(leaf)]
            break
    return urlunsplit(parsed._replace(path=path + f"/v1/{signal}"))


def _local_logs(endpoint: str) -> bool:
    try:
        p = urlsplit(endpoint)
        return (
            p.scheme == "http" and p.hostname in {"127.0.0.1", "localhost", "::1"}
            and p.username is None and p.password is None and not p.query and not p.fragment
            and (p.port is None or 0 < p.port < 65536) and p.path.endswith("/v1/logs")
            and not any(c.isspace() or ord(c) < 32 for c in endpoint)
        )
    except ValueError:
        return False


def _resource() -> Resource:
    return Resource.create({
        "service.name": "obstudio-skill-evals",
        "service.version": importlib.metadata.version("pytest-codex-evals"),
        "deployment.environment.name": "local",
    }).merge(OTELResourceDetector().detect())


def _owned_or_existing(signal, supplied, resource, owners):
    exporter = os.environ.get(f"OTEL_{signal.upper()}_EXPORTER", "otlp").strip().lower()
    if exporter != "otlp":
        return None
    if supplied is not None and signal != "logs":
        return supplied
    protocol = os.environ.get(f"OTEL_EXPORTER_OTLP_{signal.upper()}_PROTOCOL", os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"))
    if protocol != "http/protobuf":
        return None
    endpoint = _endpoint(signal)
    if signal == "logs":
        # A generic cloud destination never becomes the local log destination.
        if not os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT") and not _local_logs(endpoint):
            endpoint = "http://127.0.0.1:4318/v1/logs"
        if not _local_logs(endpoint) or os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").strip():
            return None
        if supplied is not None:
            return supplied
        existing = get_logger_provider()
        if type(existing).__name__ != "ProxyLoggerProvider":
            return existing
        provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
        provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint), schedule_delay_millis=int(os.environ.get("OTEL_BLRP_SCHEDULE_DELAY", "100"))))
    elif signal == "traces":
        existing = trace.get_tracer_provider()
        if not isinstance(existing, trace.ProxyTracerProvider):
            return existing
        provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint), schedule_delay_millis=int(os.environ.get("OTEL_BSP_SCHEDULE_DELAY", "100"))))
    else:
        existing = metrics.get_meter_provider()
        if type(existing).__name__ != "_ProxyMeterProvider":
            return existing
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint),
            export_interval_millis=int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", "1000")),
            export_timeout_millis=int(os.environ.get("OTEL_METRIC_EXPORT_TIMEOUT", "500")),
        )
        provider = MeterProvider(resource=resource, metric_readers=[reader], shutdown_on_exit=False)
    owners.append(provider)
    return provider


class EvalTelemetry:
    def __init__(self, *, tracer_provider=None, meter_provider=None, logger_provider=None, owners=(), allowed_skills=()):
        self.owners = list(owners)
        self.allowed_skills = frozenset(allowed_skills)
        self.tracer = tracer_provider.get_tracer(_SCOPE) if tracer_provider else None
        meter = meter_provider.get_meter(_SCOPE) if meter_provider else None
        self.count = meter.create_counter("obstudio.skill.eval.run.count", unit="{run}", description="Evaluated runs by terminal outcome") if meter else None
        self.duration = meter.create_histogram("obstudio.skill.eval.run.duration", unit="s", description="Administrative eval phase duration") if meter else None
        self.tokens = meter.create_histogram("obstudio.skill.eval.run.tokens", unit="{token}", description="Observed normalized tokens per eval phase") if meter else None
        self.handler = LoggingHandler(logger_provider=logger_provider) if logger_provider else None
        self.closed = False
        self.signal_status = {}

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        for provider in self.owners:
            try:
                provider.force_flush()
            except Exception:
                pass
            try:
                provider.shutdown()
            except Exception:
                pass
        if self.handler:
            self.handler.close()

    def activate(self):
        token = _telemetry.set(self)
        return lambda: _telemetry.reset(token)


def configure_telemetry(*, enabled=False, allowed_skills=(), tracer_provider=None, meter_provider=None, logger_provider=None):
    if not enabled or os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return EvalTelemetry()
    owners = []
    providers = {}
    resource = _resource()
    for signal, supplied in (("traces", tracer_provider), ("metrics", meter_provider), ("logs", logger_provider)):
        try:
            providers[signal] = _owned_or_existing(signal, supplied, resource, owners)
        except Exception:
            providers[signal] = None
    telemetry = EvalTelemetry(tracer_provider=providers["traces"], meter_provider=providers["metrics"], logger_provider=providers["logs"], owners=owners, allowed_skills=allowed_skills)
    for signal, provider in providers.items():
        selected = os.environ.get(f"OTEL_{signal.upper()}_EXPORTER", "otlp").strip().lower()
        telemetry.signal_status[signal] = "configured" if provider else "disabled" if selected == "none" else "operator-owned" if selected != "otlp" else "unavailable (check protocol, endpoint and header ownership)"
    return telemetry


def _outcome(exc):
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return "cancelled"
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return "timeout"
    return "error"


def _record_error(span, outcome):
    if span:
        _observe(span.set_attribute, "error.type", outcome)
        _observe(span.set_status, trace.StatusCode.ERROR, outcome)
        _observe(span.record_exception, RuntimeError(outcome), attributes={"exception.stacktrace": ""})


class Run:
    def __init__(self, telemetry, attrs):
        self.telemetry, self.attrs = telemetry, attrs
        self.execution = "unknown"
        self.grade = "unknown"
        self.usage_coverage = "unknown"

    def phase_duration(self, phase, duration, outcome):
        if self.telemetry.duration:
            _observe(self.telemetry.duration.record, duration, {**self.attrs, "phase": phase, "outcome": outcome})

    @contextlib.contextmanager
    def agent(self):
        start = time.monotonic()
        outcome = "success"
        with _span(self.telemetry.tracer, "skill.eval.agent", self.attrs) as span:
            try:
                yield
            except BaseException as exc:
                outcome = _outcome(exc)
                _record_error(span, outcome)
                raise
            finally:
                if self.execution == "error":
                    outcome = "error"
                    _record_error(span, outcome)
                self.phase_duration("agent", time.monotonic() - start, outcome)

    def usage(self, usage, phase):
        if usage is None or not usage.observed:
            return
        if phase == "agent":
            self.usage_coverage = "measured" if usage.total_tokens is not None else "partial"
        if not self.telemetry.tokens:
            return
        for field in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_creation_input_tokens", "reasoning_output_tokens", "provider_total_tokens", "derived_total_tokens"):
            value = getattr(usage, field, None)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                _observe(self.telemetry.tokens.record, value, {**self.attrs, "phase": phase, "token.type": field, "usage.source": usage.source})


def current_run():
    return _run.get()


def _rubric_failed(result):
    if result.rubric_grade_path:
        return json.loads(Path(result.rubric_grade_path).read_text())["overall_pass"] is False
    return False


def instrument_run(function):
    @functools.wraps(function)
    def wrapped(**kwargs):
        telemetry = _telemetry.get()
        if telemetry is None or telemetry.closed:
            return function(**kwargs)
        skill = kwargs["case"].skill
        backend = kwargs["backend"].name
        attrs = {
            "skill.name": skill if skill in telemetry.allowed_skills else "other",
            "eval.side": "baseline" if kwargs["side"] == "baseline" else "with_skill",
            "agent.backend": backend if backend in {"codex", "claude", "cursor"} else "other",
        }
        run = Run(telemetry, attrs)
        token = _run.set(run)
        start = time.monotonic()
        outcome = "success"
        try:
            with _span(telemetry.tracer, "skill.eval.run", attrs) as span:
                try:
                    result = function(**kwargs)
                    run.execution = "success" if result.exit_code == 0 else "error"
                    run.grade = "failed" if any(error.startswith("rubric ") for error in result.errors) or result.grade.passed < result.grade.total or _observe(_rubric_failed, result) else "passed"
                    outcome = "error" if run.execution == "error" else "grade_failed" if run.grade == "failed" else "success"
                    if outcome != "success":
                        _record_error(span, outcome)
                    return result
                except BaseException as exc:
                    outcome = _outcome(exc)
                    run.execution = outcome
                    _record_error(span, outcome)
                    raise
                finally:
                    duration = time.monotonic() - start
                    final = {**attrs, "outcome": outcome, "execution.outcome": run.execution, "grade.outcome": run.grade, "usage.coverage": run.usage_coverage}
                    if span:
                        _observe(span.set_attributes, final)
                    if telemetry.count:
                        _observe(telemetry.count.add, 1, {**attrs, "outcome": outcome})
                    if telemetry.duration:
                        _observe(telemetry.duration.record, duration, {**attrs, "phase": "run", "outcome": outcome})
                    if telemetry.handler:
                        record = logging.makeLogRecord({"name": _SCOPE, "msg": "obstudio.skill.eval.run.completed", "levelno": logging.INFO if outcome == "success" else logging.ERROR, "levelname": "INFO" if outcome == "success" else "ERROR", **final})
                        _observe(telemetry.handler.handle, record)
        finally:
            _run.reset(token)
    return wrapped
