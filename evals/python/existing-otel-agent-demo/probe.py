"""Capture real loopback OTLP receipts and compare an actor's before/after run.

The receiver is a local transport contract, never proof of cloud visibility.
No instrumentation implementation is supplied by this probe.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from app import AgentDemo, MODES

SCENARIOS = ("success", "tool_error", "provider_error", "cancel")
ROUTING_HEADERS = {"projectid", "logstreamid", "agentstreamid"}


def _value(value: Any) -> Any:
    kind = value.WhichOneof("value")
    if kind == "array_value":
        return [_value(item) for item in value.array_value.values]
    if kind == "kvlist_value":
        return _attributes(value.kvlist_value.values)
    return getattr(value, kind) if kind else None


def _attributes(values: Any) -> dict[str, Any]:
    return {item.key: _value(item.value) for item in values}


def decode(path: str, body: bytes) -> list[dict[str, Any]]:
    if path == "/v1/traces":
        message = ExportTraceServiceRequest.FromString(body)
        return [
            {
                "name": span.name, "trace_id": span.trace_id.hex(), "span_id": span.span_id.hex(),
                "parent_span_id": span.parent_span_id.hex(), "kind": span.kind,
                "attributes": _attributes(span.attributes),
                "resource": _attributes(resource.resource.attributes),
                "scope": scope.scope.name,
                "status": {"code": span.status.code, "message": span.status.message},
                "events": [{"name": event.name, "attributes": _attributes(event.attributes)} for event in span.events],
            }
            for resource in message.resource_spans for scope in resource.scope_spans for span in scope.spans
        ]
    if path == "/v1/metrics":
        message = ExportMetricsServiceRequest.FromString(body)
        return [
            {
                "name": metric.name, "unit": metric.unit, "description": metric.description,
                "attributes": _attributes(point.attributes),
                "value": getattr(point, point.WhichOneof("value")),
                "resource": _attributes(resource.resource.attributes), "scope": scope.scope.name,
            }
            for resource in message.resource_metrics for scope in resource.scope_metrics
            for metric in scope.metrics if metric.WhichOneof("data") == "sum"
            for point in metric.sum.data_points
        ]
    if path == "/v1/logs":
        message = ExportLogsServiceRequest.FromString(body)
        return [
            {
                "body": _value(record.body), "severity_number": record.severity_number,
                "severity_text": record.severity_text, "attributes": _attributes(record.attributes),
                "resource": _attributes(resource.resource.attributes), "scope": scope.scope.name,
                "trace_id": record.trace_id.hex() if any(record.trace_id) else "",
                "span_id": record.span_id.hex() if any(record.span_id) else "",
            }
            for resource in message.resource_logs for scope in resource.scope_logs for record in scope.log_records
        ]
    raise ValueError(f"unexpected OTLP path: {path}")


class Receiver:
    def __init__(self, reject_traces: bool = False) -> None:
        self.requests: list[dict[str, Any]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                status = 400 if reject_traces and self.path == "/v1/traces" else 200
                owner.requests.append({
                    "path": self.path, "headers": {key.lower(): value for key, value in self.headers.items()},
                    "body_sha256": hashlib.sha256(body).hexdigest(), "status": status,
                    "records": decode(self.path, body),
                })
                self.send_response(status)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "Receiver":
        self.thread.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"


def capture(mode: str, instrumentation: Path | None = None, reject_traces: bool = False) -> dict[str, Any]:
    saved_environment = dict(os.environ)
    try:
        # Ambient credentials/endpoints must never turn this local probe into a cloud call.
        for name in list(os.environ):
            if name.startswith(("OTEL_", "SPLUNK_", "GALILEO_")):
                del os.environ[name]
        with Receiver(reject_traces) as receiver:
            for signal in ("TRACES", "METRICS", "LOGS"):
                os.environ[f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT"] = f"{receiver.endpoint}/v1/{signal.lower()}"
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = receiver.endpoint
            os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
            app = AgentDemo(mode, receiver.endpoint)
            originals = {key: value for key, value in app.owned_objects().items() if value is not None}
            original_types = {key: f"{type(value).__module__}.{type(value).__qualname__}" for key, value in originals.items()}
            setup_errors = []
            outcomes = []
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    if instrumentation is not None:
                        spec = importlib.util.spec_from_file_location("actor_instrumentation", instrumentation)
                        if spec is None or spec.loader is None:
                            raise ValueError("cannot load instrumentation module")
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        module.configure(app)
                        module.configure(app)
                except Exception as exc:
                    setup_errors.append(f"{type(exc).__name__}: {exc}")
                try:
                    app.start()
                    app.start()
                    for scenario in SCENARIOS:
                        try:
                            app.run_agent("private-prompt-sentinel", scenario)
                            outcomes.append({"scenario": scenario, "outcome": "success"})
                        except (RuntimeError, asyncio.CancelledError) as exc:
                            outcomes.append({"scenario": scenario, "outcome": type(exc).__name__})
                except Exception as exc:
                    setup_errors.append(f"{type(exc).__name__}: {exc}")
                finally:
                    retained = {key: getattr(app, key) is value for key, value in originals.items()}
                    app.shutdown()
                    request_count_after_shutdown = len(receiver.requests)
                    app.shutdown()
            return {
                "proof_mode": "local_otlp_contract", "cloud_visibility": "not_proven", "mode": mode,
                "instrumentation": str(instrumentation) if instrumentation else None,
                "setup_errors": setup_errors, "outcomes": outcomes,
                "original_types": original_types, "original_objects_retained": retained,
                "second_shutdown_requests": len(receiver.requests) - request_count_after_shutdown,
                "header_environment": {key: value for key, value in os.environ.items() if key.startswith("OTEL_") and key.endswith("HEADERS")},
                "requests": list(receiver.requests),
            }
    finally:
        os.environ.clear()
        os.environ.update(saved_environment)


def records(receipt: dict[str, Any], signal: str) -> list[dict[str, Any]]:
    return [record for request in receipt["requests"] if request["path"] == f"/v1/{signal}" for record in request["records"]]


def compare(before: dict[str, Any], after: dict[str, Any], contract: str, project_id: str, stream_id: str) -> list[str]:
    """Return concrete failures; only actor-generated after captures prove skill behavior."""
    failures = []

    def require(condition: bool, description: str) -> None:
        if not condition:
            failures.append(description)

    require(before["mode"] == after["mode"], "before/after telemetry modes differ")
    require(not before["setup_errors"] and not after["setup_errors"], "setup failed")
    require(after["outcomes"] == before["outcomes"], "application success/error/cancellation behavior changed")
    require(all(after["original_objects_retained"].values()), "existing provider/producer/processor/exporter/instrument was replaced")
    require(after["original_types"] == before["original_types"], "existing telemetry startup types changed")
    require(after["second_shutdown_requests"] == 0, "repeated shutdown exported again")
    require(after["header_environment"].get("OTEL_EXPORTER_OTLP_HEADERS") == before["header_environment"].get("OTEL_EXPORTER_OTLP_HEADERS"), "global OTLP headers changed")
    for signal in ("METRICS", "LOGS"):
        key = f"OTEL_EXPORTER_OTLP_{signal}_HEADERS"
        require(after["header_environment"].get(key) == before["header_environment"].get(key), f"{signal.lower()} header environment changed")

    old_spans = records(before, "traces")
    spans = records(after, "traces")
    for old in old_spans:
        matches = [span for span in spans if span["span_id"] == old["span_id"] and span["trace_id"] == old["trace_id"]]
        require(len(matches) == 1, f"existing span missing or duplicated: {old['span_id']}")
        if len(matches) == 1:
            current = matches[0]
            for key in ("name", "kind", "resource", "scope", "status"):
                missing_cancellation_status_filled = (
                    key == "status" and old["status"] == {"code": 0, "message": ""}
                    and old["attributes"].get("legacy.request") == "turn-4"
                    and old["attributes"].get("legacy.operation") == "workflow"
                    and {"scenario": "cancel", "outcome": "CancelledError"} in before["outcomes"]
                    and current["status"]["code"] == 2
                    and current["attributes"].get("error.type") in {"CancelledError", "asyncio.CancelledError"}
                )
                require(current[key] == old[key] or missing_cancellation_status_filled, f"existing span {key} changed: {old['span_id']}")
            require(all(current["attributes"].get(key) == value for key, value in old["attributes"].items()), f"existing span attributes changed: {old['span_id']}")
            require(all(event in current["events"] for event in old["events"] if event["name"].startswith("legacy.")), f"existing span events lost: {old['span_id']}")

    prior_metrics = records(before, "metrics")
    retained_metrics = [record for record in records(after, "metrics") if "legacy.metric" in record["attributes"]]
    require(Counter(json.dumps(record, sort_keys=True) for record in prior_metrics) == Counter(json.dumps(record, sort_keys=True) for record in retained_metrics), "existing metrics values/fields missing or duplicated")

    prior_logs = records(before, "logs")
    retained_logs = [record for record in records(after, "logs") if "legacy.log" in record["attributes"]]
    require(len(prior_logs) == len(retained_logs), "existing logs values/fields missing or duplicated")
    unmatched_logs = list(retained_logs)
    actual_spans = {(span["trace_id"], span["span_id"]): span for span in spans}
    request_scenarios = {f"turn-{index + 1}": scenario for index, scenario in enumerate(SCENARIOS)}
    for prior in prior_logs:
        def preserves_log(current: dict[str, Any]) -> bool:
            for key, value in prior.items():
                if key not in {"attributes", "trace_id", "span_id"} and current.get(key) != value:
                    return False
            if not all(current["attributes"].get(key) == value for key, value in prior["attributes"].items()):
                return False
            old_context = (prior.get("trace_id", ""), prior.get("span_id", ""))
            context = (current.get("trace_id", ""), current.get("span_id", ""))
            if any(old_context):
                return context == old_context
            if not any(context):
                return True
            span = actual_spans.get(context)
            if span is None:
                return False
            attributes = span["attributes"]
            scenario = attributes.get("app.scenario") or request_scenarios.get(attributes.get("legacy.request"))
            return scenario is not None and scenario == prior["attributes"].get("scenario")

        matched = next((index for index, current in enumerate(unmatched_logs) if preserves_log(current)), None)
        require(matched is not None, "existing logs values/fields missing or duplicated")
        if matched is not None:
            unmatched_logs.pop(matched)

    by_id = {(span["trace_id"], span["span_id"]): span for span in spans}
    legacy_ids = {(span["trace_id"], span["span_id"]) for span in old_spans}
    require(len(by_id) == len(spans), "duplicate span IDs exported")
    expected = {"invoke_workflow": 4, "invoke_agent": 4, "retrieval": 4, "execute_tool": 4, "chat": 2}
    counts = Counter(span["attributes"].get("gen_ai.operation.name") for span in spans)
    for operation, count in expected.items():
        require(counts[operation] == count, f"expected exactly {count} {operation} operations, got {counts[operation]}")
        for scenario in SCENARIOS:
            scenario_count = sum(
                span["attributes"].get("gen_ai.operation.name") == operation
                and span["attributes"].get("app.scenario") == scenario for span in spans
            )
            expected_count = int(operation != "chat" or scenario in {"success", "provider_error"})
            require(scenario_count == expected_count, f"expected {expected_count} {operation} operation for {scenario}, got {scenario_count}")
    for span in spans:
        attributes = span["attributes"]
        operation = attributes.get("gen_ai.operation.name")
        if operation in expected:
            scenario = attributes.get("app.scenario")
            require(scenario in SCENARIOS, f"missing safe scenario identity for {operation}")
            require(attributes.get("app.request_id") == f"turn-{SCENARIOS.index(scenario) + 1}" if scenario in SCENARIOS else False, f"missing safe request identity for {operation}")
            failed = (
                scenario in {"tool_error", "cancel"} and operation in {"invoke_workflow", "invoke_agent", "execute_tool"}
                or scenario == "provider_error" and operation in {"invoke_workflow", "invoke_agent", "chat"}
            )
            if failed:
                if (span["trace_id"], span["span_id"]) not in legacy_ids or scenario == "cancel":
                    require(span["status"]["code"] == 2, f"missing error status for {scenario} {operation}")
                    require(bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]*", str(attributes.get("error.type", "")))), f"missing sanitized error.type for {scenario} {operation}")
                require("gen_ai.output.messages" not in attributes and not any(key.startswith("gen_ai.usage.") for key in attributes), f"fabricated output/usage for failed {operation}")
            if operation != "chat":
                require(not any(key.startswith("gen_ai.usage.") for key in attributes), f"fabricated model usage for {operation}")
        if operation in {"invoke_agent", "retrieval", "execute_tool", "chat"}:
            parent = by_id.get((span["trace_id"], span["parent_span_id"]))
            expected_parent = "invoke_workflow" if operation == "invoke_agent" else "invoke_agent"
            require(parent is not None and parent["attributes"].get("gen_ai.operation.name") == expected_parent, f"wrong parent or disconnected trace for {operation}")
            if parent is not None:
                require(parent["attributes"].get("app.request_id") == attributes.get("app.request_id") and parent["attributes"].get("app.scenario") == attributes.get("app.scenario"), f"operation parent belongs to a different request: {operation}")
    for request in after["requests"]:
        require(request["status"] == 200, f"OTLP export rejected: {request['path']}")
        headers = request["headers"]
        if request["path"] == "/v1/traces":
            stream_header = "logstreamid" if contract == "studio" else "agentstreamid"
            other_header = "agentstreamid" if contract == "studio" else "logstreamid"
            require(headers.get("projectid") == project_id and headers.get(stream_header) == stream_id, "selected project/stream headers missing or incorrect")
            require(other_header not in headers, "mixed Studio/public stream header contract")
            if old_spans:
                require(headers.get("x-legacy-trace") == "keep-trace-header" and headers.get("x-exporter-owner") == "legacy-traces", "existing trace transport headers lost")
        else:
            require(not ROUTING_HEADERS.intersection(headers), f"trace routing leaked into {request['path']}")
    trace_requests = [request for request in after["requests"] if request["path"] == "/v1/traces"]
    require(len(trace_requests) == 1, "expected one trace batch and one upstream request after shutdown")
    require("private-prompt-sentinel" not in json.dumps(after["requests"]), "raw prompt leaked into telemetry")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--mode", choices=MODES, required=True)
    capture_parser.add_argument("--instrumentation", type=Path)
    capture_parser.add_argument("--reject-traces", action="store_true")
    capture_parser.add_argument("--output", type=Path, required=True)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("before", type=Path)
    compare_parser.add_argument("after", type=Path)
    compare_parser.add_argument("--target-contract", choices=("studio", "public"), required=True)
    compare_parser.add_argument("--project-id", required=True)
    compare_parser.add_argument("--stream-id", required=True)
    args = parser.parse_args()
    if args.command == "capture":
        result = capture(args.mode, args.instrumentation, args.reject_traces)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"mode": args.mode, "requests": len(result["requests"]), "proof_mode": result["proof_mode"]}))
        raise SystemExit(bool(result["setup_errors"]))
    else:
        failures = compare(json.loads(args.before.read_text()), json.loads(args.after.read_text()), args.target_contract, args.project_id, args.stream_id)
        print(json.dumps({"passed": not failures, "failures": failures, "cloud_visibility": "not_proven"}, indent=2))
        raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
