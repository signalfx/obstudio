"""Caller-owned OTel with deliberately incomplete agent operation coverage."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import time
from collections.abc import Callable, Iterator
from typing import Any

import requests
from opentelemetry import trace
from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

MODES = ("generic", "genai", "metrics", "logs", "none")
SERVICE_NAME = "existing-otel-agent-demo"
RESOURCE = Resource.create({"service.name": SERVICE_NAME, "legacy.resource": "keep-resource"})
_reserved_span_id = contextvars.ContextVar("legacy_span_id", default=None)
_reserved_trace_id = contextvars.ContextVar("legacy_trace_id", default=None)


class LegacyIdGenerator(RandomIdGenerator):
    """Reserve repeatable fixture IDs for existing spans; new spans remain random."""

    def generate_span_id(self) -> int:
        return _reserved_span_id.get() or super().generate_span_id()

    def generate_trace_id(self) -> int:
        return _reserved_trace_id.get() or super().generate_trace_id()


class ExistingTraceProducer:
    """Existing producer's supported span enrichment hooks run before export."""

    def __init__(self, provider: TracerProvider, mode: str) -> None:
        self.provider = provider
        self.mode = mode
        self.tracer = provider.get_tracer("legacy.agent.producer", "1.0")
        self.span_hooks: list[Callable[[Any, str, dict[str, Any]], None]] = []

    @contextlib.contextmanager
    def operation(self, operation: str, metadata: dict[str, Any]) -> Iterator[Any]:
        names = {"workflow": "POST /agent", "model": "POST /model"}
        attributes = {
            "legacy.operation": operation,
            "legacy.sentinel": "keep-span",
            "legacy.request": metadata["request_id"],
        }
        if self.mode == "genai":
            names = {"workflow": "invoke_workflow support_turn", "model": "chat demo-model"}
            attributes.update({
                "gen_ai.operation.name": "invoke_workflow" if operation == "workflow" else "chat",
                "gen_ai.workflow.name" if operation == "workflow" else "gen_ai.request.model":
                    "support_turn" if operation == "workflow" else "demo-model",
            })
        number = metadata["request_index"] * 16 + (1 if operation == "workflow" else 2)
        span_token = _reserved_span_id.set(0xB000 + number)
        trace_token = _reserved_trace_id.set(0xA000 + metadata["request_index"])
        try:
            span = self.tracer.start_span(names[operation], attributes=attributes)
        finally:
            _reserved_span_id.reset(span_token)
            _reserved_trace_id.reset(trace_token)
        with trace.use_span(span, end_on_exit=True):
            span.add_event("legacy.started", {"legacy.event": "keep-event"})
            for hook in self.span_hooks:
                hook(span, operation, metadata)
            yield span


class AgentDemo:
    """A local support agent with existing telemetry owned by the application.

    Integration modules may register operation_hooks for uncovered operations,
    enrich existing spans through span_hooks, and customize the trace-only
    requests.Session through its public headers API. No global OTel provider
    is installed or replaced by this fixture.
    """

    def __init__(self, mode: str, endpoint: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown telemetry mode: {mode}")
        self.mode = mode
        self.endpoint = endpoint.rstrip("/")
        self.trace_session = requests.Session()
        self.trace_session.headers["x-legacy-trace"] = "keep-trace-header"
        self.trace_provider = None
        self.trace_processor = None
        self.trace_exporter = None
        self.trace_producer = None
        self.metric_provider = None
        self.metric_reader = None
        self.metric_exporter = None
        self.request_counter = None
        self.log_provider = None
        self.log_processor = None
        self.log_exporter = None
        self.audit_logger = None
        self.operation_hooks: list[Callable[[str, dict[str, Any]], Any]] = []
        self.started = False
        self.closed = False
        self.request_index = 0
        self.shutdown_callbacks: list[Callable[[], None]] = []

        if mode in ("generic", "genai"):
            self.trace_exporter = OTLPSpanExporter(
                endpoint=f"{self.endpoint}/v1/traces", session=self.trace_session,
                headers={"x-exporter-owner": "legacy-traces"}, timeout=2,
            )
            self.trace_processor = BatchSpanProcessor(
                self.trace_exporter, schedule_delay_millis=3_600_000,
            )
            self.trace_provider = TracerProvider(resource=RESOURCE, id_generator=LegacyIdGenerator())
            self.trace_provider.add_span_processor(self.trace_processor)
            self.trace_producer = ExistingTraceProducer(self.trace_provider, mode)
        if mode in ("generic", "genai", "metrics"):
            self.metric_exporter = OTLPMetricExporter(
                endpoint=f"{self.endpoint}/v1/metrics",
                headers={"x-exporter-owner": "legacy-metrics"}, timeout=2,
            )
            self.metric_reader = PeriodicExportingMetricReader(
                self.metric_exporter, export_interval_millis=float("inf"),
            )
            self.metric_provider = MeterProvider(resource=RESOURCE, metric_readers=[self.metric_reader])
            self.request_counter = self.metric_provider.get_meter("legacy.agent.metrics").create_counter(
                "legacy.agent.requests", unit="{request}", description="Existing support requests",
            )
        if mode in ("generic", "genai", "logs"):
            self.log_exporter = OTLPLogExporter(
                endpoint=f"{self.endpoint}/v1/logs",
                headers={"x-exporter-owner": "legacy-logs"}, timeout=2,
            )
            self.log_processor = BatchLogRecordProcessor(
                self.log_exporter, schedule_delay_millis=3_600_000,
            )
            self.log_provider = LoggerProvider(resource=RESOURCE)
            self.log_provider.add_log_record_processor(self.log_processor)
            self.audit_logger = self.log_provider.get_logger("legacy.agent.audit")

    def owned_objects(self) -> dict[str, Any]:
        return {
            key: value for key, value in vars(self).items()
            if key.endswith(("_provider", "_processor", "_exporter", "_producer", "_reader"))
            or key in ("trace_session", "request_counter", "audit_logger")
        }

    def start(self) -> None:
        if self.closed:
            raise RuntimeError("agent is shut down")
        self.started = True

    @contextlib.contextmanager
    def operation(self, name: str, metadata: dict[str, Any]) -> Iterator[dict[str, Any]]:
        metadata["result_available"] = False
        with contextlib.ExitStack() as stack:
            if self.trace_producer is not None and name in ("workflow", "model"):
                stack.enter_context(self.trace_producer.operation(name, metadata))
            for hook in self.operation_hooks:
                stack.enter_context(hook(name, metadata))
            yield metadata

    def retrieve_documents(self, metadata: dict[str, Any]) -> list[str]:
        operation = {**metadata, "data_source": "knowledge_base", "inputs": {"query": metadata["prompt"]}}
        with self.operation("retrieval", operation) as state:
            documents = ["Policy: orders can be checked with lookup_order."]
            state.update(result=documents, result_available=True)
            return documents

    def run_tool(self, metadata: dict[str, Any]) -> dict[str, str]:
        operation = {**metadata, "tool_name": "lookup_order", "inputs": {"order_id": "demo-order-7"}}
        with self.operation("tool", operation) as state:
            if metadata["scenario"] == "tool_error":
                raise RuntimeError("synthetic tool unavailable")
            if metadata["scenario"] == "cancel":
                raise asyncio.CancelledError("synthetic client cancellation")
            result = {"state": "shipped"}
            state.update(result=result, result_available=True)
            return result

    def call_model(self, metadata: dict[str, Any], documents: list[str], order: dict[str, str]) -> str:
        operation = {
            **metadata, "model": "demo-model",
            "inputs": {"prompt": metadata["prompt"], "documents": documents, "order": order},
        }
        with self.operation("model", operation) as state:
            if metadata["scenario"] == "provider_error":
                raise RuntimeError("synthetic model unavailable")
            result = f"Your order is {order['state']}; used {len(documents)} policy document."
            state.update(result=result, result_available=True)
            return result

    def run_agent(self, prompt: str = "Where is my order?", scenario: str = "success") -> str:
        if not self.started or self.closed:
            raise RuntimeError("start the agent before running a turn")
        self.request_index += 1
        metadata = {
            "request_id": f"turn-{self.request_index}", "request_index": self.request_index,
            "scenario": scenario, "prompt": prompt, "inputs": {"prompt": prompt},
        }
        if self.request_counter is not None:
            self.request_counter.add(7, {"legacy.metric": "keep-metric", "scenario": scenario})
        if self.audit_logger is not None:
            self.audit_logger.emit(LogRecord(
                timestamp=time.time_ns(), severity_number=SeverityNumber.INFO,
                severity_text="INFO", body="legacy audit record",
                attributes={"legacy.log": "keep-log", "scenario": scenario},
            ))
        print(f"support request {metadata['request_id']}: {scenario}")
        with self.operation("workflow", metadata) as workflow_state:
            with self.operation("agent", {**metadata, "agent_name": "support_agent"}) as agent_state:
                documents = self.retrieve_documents(metadata)
                order = self.run_tool(metadata)
                result = self.call_model(metadata, documents, order)
                agent_state.update(result=result, result_available=True)
                workflow_state.update(result=result, result_available=True)
                return result

    def shutdown(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            for callback in self.shutdown_callbacks:
                callback()
        finally:
            if self.metric_provider is not None:
                self.metric_provider.force_flush()
            for provider in (self.trace_provider, self.metric_provider, self.log_provider):
                if provider is not None:
                    provider.shutdown()
            self.trace_session.close()
