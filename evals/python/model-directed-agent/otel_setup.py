"""OpenTelemetry setup for SmashBot.

Configures one provider per signal (traces, metrics, logs) with OTLP exporters,
a shared resource identifying the service, and a stdlib logging bridge that
defaults to the local Splunk Observability Studio receiver. Kept separate from
application code so the wiring lives in one place.

Call `configure_opentelemetry()` once at process startup, before the Flask app
is instrumented. It returns `(install_logging_bridge, shutdown)`:

- call `install_logging_bridge()` after the app's console/file handlers exist,
- register `shutdown` with the process's graceful-exit path.

Environment (operator-owned):
    OTEL_SERVICE_NAME              default "smashbot"
    OTEL_EXPORTER_OTLP_ENDPOINT    default http://localhost:4318 (traces/metrics)
    OTEL_LOGS_EXPORTER             "otlp" (default) or "none" to opt out
    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT  default http://localhost:4318/v1/logs
    OTEL_METRIC_EXPORT_INTERVAL    default 1000 (ms, tuned for local runs)
    OTEL_METRIC_EXPORT_TIMEOUT     default 500 (ms)
"""

from __future__ import annotations

import os
import threading

from requests import Session

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

LOCAL_OBSERVER_LOGS_ENDPOINT = "http://localhost:4318/v1/logs"


class _LocalLogSession(Session):
    """Keep SDK-inherited destination headers out of the local log request."""

    def __init__(self):
        super().__init__()
        self.trust_env = False

    def prepare_request(self, request):
        prepared = super().prepare_request(request)
        transport_headers = {
            "accept", "accept-encoding", "connection", "content-encoding",
            "content-length", "content-type", "user-agent",
        }
        for name in list(prepared.headers):
            if name.lower() not in transport_headers:
                del prepared.headers[name]
        return prepared


def _use_default_local_log_export() -> bool:
    """Decide whether to own the local OTLP log pipeline.

    We own it only when the exporter is absent or explicitly ``otlp`` and the
    logs endpoint is absent or exactly the detected local receiver. Any other
    explicit exporter stays operator-owned; a non-local endpoint on the
    otlp/absent branch is a fail-closed boundary conflict.
    """
    configured = os.environ.get("OTEL_LOGS_EXPORTER")
    if configured is not None and configured.strip():
        if configured.strip().lower() != "otlp":
            return False

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "").strip()
    if endpoint and endpoint != LOCAL_OBSERVER_LOGS_ENDPOINT:
        raise RuntimeError(
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT is not the detected local "
            "Splunk Observability Studio receiver; refusing to create a log "
            "provider or bridge."
        )
    return True


def _local_log_exporter() -> OTLPLogExporter:
    protocol = (
        os.environ.get("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", "http/protobuf")
        .strip()
        .lower()
    )
    if protocol != "http/protobuf":
        raise RuntimeError(
            "select the official exporter matching "
            f"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL={protocol!r}"
        )
    if os.environ.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS", "").strip():
        raise RuntimeError(
            "remove log-specific OTLP headers before enabling local logs; "
            "keep remote credentials in their selected signal configuration."
        )
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "").strip()
    # SDK versions differ in whether explicit headers replace or merge generic
    # values. The supported session boundary isolates the final local request.
    return OTLPLogExporter(
        endpoint=endpoint or LOCAL_OBSERVER_LOGS_ENDPOINT,
        headers={"Content-Type": "application/x-protobuf"},
        session=_LocalLogSession(),
    )


def _validate_export_headers(signal: str) -> None:
    """Require an explicit destination before the SDK consumes header values."""
    prefix = f"OTEL_EXPORTER_OTLP_{signal}_"
    headers = any(os.environ.get(key, "").strip() for key in (
        "OTEL_EXPORTER_OTLP_HEADERS", prefix + "HEADERS",
    ))
    endpoint = (os.environ.get(prefix + "ENDPOINT", "").strip()
                or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())
    if headers and not endpoint:
        raise RuntimeError(
            f"set an explicit {prefix}ENDPOINT or OTEL_EXPORTER_OTLP_ENDPOINT "
            "before using headers; refusing the SDK's implicit local destination."
        )


def configure_opentelemetry():
    """Configure providers and return ``(install_logging_bridge, shutdown)``."""
    # Validate destinations before constructing exporters or publishing providers.
    _validate_export_headers("TRACES")
    _validate_export_headers("METRICS")
    use_local_log_export = _use_default_local_log_export()
    log_exporter = _local_log_exporter() if use_local_log_export else None

    resource = Resource.create(
        {"service.name": os.environ.get("OTEL_SERVICE_NAME", "smashbot")}
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(),
        export_interval_millis=int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", "1000")),
        export_timeout_millis=int(os.environ.get("OTEL_METRIC_EXPORT_TIMEOUT", "500")),
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])

    logger_provider = None
    logging_instrumentor = None
    if log_exporter is not None:
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

    # Publish one provider per signal only after construction/validation passed.
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    if logger_provider is not None:
        set_logger_provider(logger_provider)

    shutdown_lock = threading.Lock()
    shutdown_complete = False

    def install_logging_bridge() -> None:
        nonlocal logging_instrumentor
        if logger_provider is None or logging_instrumentor is not None:
            return
        # Additional stdlib->OTel handler; preserves existing console/file sinks.
        logging_instrumentor = LoggingInstrumentor()
        logging_instrumentor.instrument(
            set_logging_format=False,
            inject_trace_context=True,
        )

    def shutdown() -> None:
        nonlocal shutdown_complete
        with shutdown_lock:
            if shutdown_complete:
                return
            shutdown_complete = True

            actions = []
            if logging_instrumentor is not None:
                actions.append(("logging bridge", logging_instrumentor.uninstrument))
            if logger_provider is not None:
                actions.append(("log provider", logger_provider.shutdown))
            actions.extend(
                (
                    ("meter provider", meter_provider.shutdown),
                    ("tracer provider", tracer_provider.shutdown),
                )
            )
            failures = []
            for owner, action in actions:
                try:
                    action()
                except Exception as exc:  # noqa: BLE001 - collect all failures
                    failures.append((owner, exc))
            if failures:
                owners = ", ".join(owner for owner, _ in failures)
                raise RuntimeError(
                    f"OpenTelemetry shutdown failed for: {owners}"
                ) from failures[0][1]

    return install_logging_bridge, shutdown
