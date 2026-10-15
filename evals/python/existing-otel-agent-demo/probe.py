"""Capture real loopback OTLP receipts and compare an actor's before/after run.

The receiver is a local transport contract, never proof of cloud visibility.
No instrumentation implementation is supplied by this probe.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import hashlib
import importlib.util
import io
import inspect
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

from app import AgentDemo, MODES, RESOURCE

SCENARIOS = ("success", "tool_error", "provider_error", "cancel")
ROUTING_HEADERS = {"projectid", "logstreamid", "agentstreamid"}
CANCELLATION_TYPES = {"cancelled", "CancelledError", "asyncio.CancelledError", "asyncio.exceptions.CancelledError"}


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


def snapshot_resources(app: AgentDemo, environment: dict[str, str]) -> dict[str, Any]:
    """Read caller-owned resources before integration; do not change SDK state."""
    source = Path(inspect.getsourcefile(type(app).__init__)).read_text()
    tree = ast.parse(source)
    explicit_keys = {
        field.partition("=")[0].strip()
        for field in environment.get("OTEL_RESOURCE_ATTRIBUTES", "").split(",") if "=" in field
    }
    if environment.get("OTEL_SERVICE_NAME"):
        explicit_keys.add("service.name")
    source_keys = set(explicit_keys)
    known_constructors = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_resource = isinstance(node.func, ast.Name) and node.func.id == "Resource"
        is_resource_create = isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "Resource" and node.func.attr == "create"
        if is_resource or is_resource_create:
            arguments = list(node.args) + [keyword.value for keyword in node.keywords if keyword.arg == "attributes"]
            known_mapping = len(node.args) <= 1 and all(keyword.arg in {"attributes", "schema_url"} for keyword in node.keywords)
            for argument in arguments:
                if isinstance(argument, ast.Dict):
                    source_keys.update(key.value for key in argument.keys if isinstance(key, ast.Constant) and isinstance(key.value, str))
                    known_mapping &= all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in argument.keys)
                elif not (isinstance(argument, ast.Constant) and argument.value is None):
                    known_mapping = False
            if known_mapping:
                known_constructors.add(id(node))

    def known_resource_expression(node: ast.AST) -> bool:
        if isinstance(node, ast.Name) and node.id == "RESOURCE":
            return True
        if id(node) in known_constructors:
            return True
        return (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "merge"
            and len(node.args) == 1 and not node.keywords
            and known_resource_expression(node.func.value) and known_resource_expression(node.args[0])
        )

    declarations = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "RESOURCE" for target in node.targets)
    ]
    source_origin_known = bool(declarations) and all(known_resource_expression(node) for node in declarations)
    # A literal application instance ID is explicit even when constructed indirectly.
    application_instance_id = any(isinstance(node, ast.Constant) and node.value == "service.instance.id" for node in ast.walk(tree))
    signals = {}
    for signal, provider in (("traces", app.trace_provider), ("metrics", app.metric_provider), ("logs", app.log_provider)):
        if provider is None:
            continue
        resource = getattr(provider, "resource", None)
        ownership = "provider.resource"
        if signal == "metrics" and resource is None:
            # MeterProvider has no public resource getter. This fixture passes its
            # application-owned RESOURCE directly; verify that source binding.
            bound = any(
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "MeterProvider"
                and any(keyword.arg == "resource" and isinstance(keyword.value, ast.Name) and keyword.value.id == "RESOURCE" for keyword in node.keywords)
                for node in ast.walk(tree)
            )
            if bound:
                resource = RESOURCE
                ownership = "app.RESOURCE passed to MeterProvider"
        if resource is not None:
            signals[signal] = {"original": dict(resource.attributes), "ownership": ownership}
    return {
        "signals": signals, "source_resource_keys": sorted(source_keys),
        "explicit_resource_keys": sorted(explicit_keys),
        "sdk_generated_service_instance_id": source_origin_known and not application_instance_id and "service.instance.id" not in explicit_keys,
    }


def finalize_resource_proof(snapshot: dict[str, Any], requests: list[dict[str, Any]]) -> dict[str, Any]:
    sentinels = {"traces": "legacy.sentinel", "metrics": "legacy.metric", "logs": "legacy.log"}
    for signal, proof in snapshot["signals"].items():
        exported = [
            record["resource"] for request in requests if request["path"] == f"/v1/{signal}"
            for record in request["records"] if sentinels[signal] in record["attributes"]
        ]
        proof["exported_legacy_resources"] = exported
        proof["original_values_preserved"] = bool(exported) and all(
            all(resource.get(key) == value for key, value in proof["original"].items()) for resource in exported
        )
    return snapshot


def capture(mode: str, instrumentation: Path | None = None, reject_traces: bool = False) -> dict[str, Any]:
    saved_environment = dict(os.environ)
    try:
        # Ambient credentials/endpoints/proxies must not redirect local capture.
        for name in list(os.environ):
            if name.startswith(("OTEL_", "SPLUNK_", "GALILEO_")) or name.casefold() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}:
                del os.environ[name]
        with Receiver(reject_traces) as receiver:
            for signal in ("TRACES", "METRICS", "LOGS"):
                os.environ[f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT"] = f"{receiver.endpoint}/v1/{signal.lower()}"
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = receiver.endpoint
            os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
            app = AgentDemo(mode, receiver.endpoint)
            resource_snapshot = snapshot_resources(app, saved_environment)
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
                "resource_proof": finalize_resource_proof(resource_snapshot, receiver.requests),
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
    for receipt in (before, after):
        for signal, proof in receipt.get("resource_proof", {}).get("signals", {}).items():
            sentinel = {"traces": "legacy.sentinel", "metrics": "legacy.metric", "logs": "legacy.log"}[signal]
            exported = [record["resource"] for record in records(receipt, signal) if sentinel in record["attributes"]]
            require(
                proof.get("original_values_preserved") is True and bool(exported)
                and all(all(resource.get(key) == value for key, value in proof["original"].items()) for resource in exported)
                and Counter(json.dumps(resource, sort_keys=True) for resource in exported)
                == Counter(json.dumps(resource, sort_keys=True) for resource in proof.get("exported_legacy_resources", [])),
                f"original {signal} resource changed during process",
            )

    def preserves_resource(prior: dict[str, Any], current: dict[str, Any], signal: str) -> bool:
        prior_proof = before.get("resource_proof", {})
        current_proof = after.get("resource_proof", {})
        prior_owner = prior_proof.get("signals", {}).get(signal, {})
        current_owner = current_proof.get("signals", {}).get(signal, {})
        within_process_proven = (
            prior_owner.get("original_values_preserved") is True
            and current_owner.get("original_values_preserved") is True
            and prior in prior_owner.get("exported_legacy_resources", [])
            and current in current_owner.get("exported_legacy_resources", [])
        )
        for key, value in prior.items():
            if current.get(key) == value:
                continue
            generated_instance = (
                key == "service.instance.id" and within_process_proven
                and prior_proof.get("sdk_generated_service_instance_id") is True
                and current_proof.get("sdk_generated_service_instance_id") is True
                and "service.instance.id" not in prior_proof.get("explicit_resource_keys", [])
                and "service.instance.id" not in current_proof.get("explicit_resource_keys", [])
                and value == prior_owner.get("original", {}).get(key)
                and current.get(key) == current_owner.get("original", {}).get(key)
            )
            if not generated_instance:
                return False
        for key in current.keys() - prior.keys():
            if not (
                within_process_proven and key in current_proof.get("source_resource_keys", [])
                and current[key] == current_owner.get("original", {}).get(key)
            ):
                return False
        return True

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
                    and current["attributes"].get("error.type") in CANCELLATION_TYPES
                )
                resource_preserved = key == "resource" and preserves_resource(old["resource"], current["resource"], "traces")
                require(current[key] == old[key] or missing_cancellation_status_filled or resource_preserved, f"existing span {key} changed: {old['span_id']}")
            require(all(current["attributes"].get(key) == value for key, value in old["attributes"].items()), f"existing span attributes changed: {old['span_id']}")
            require(all(event in current["events"] for event in old["events"] if event["name"].startswith("legacy.")), f"existing span events lost: {old['span_id']}")
            prior_exceptions = [event for event in old["events"] if event["name"] == "exception"]
            current_exceptions = [event for event in current["events"] if event["name"] == "exception"]
            prior_types = Counter(event["attributes"].get("exception.type") for event in prior_exceptions)
            current_types = Counter(event["attributes"].get("exception.type") for event in current_exceptions)
            missing_cancel_event_filled = (
                not prior_exceptions and len(current_exceptions) == 1
                and old["attributes"].get("legacy.request") == "turn-4"
                and old["attributes"].get("legacy.operation") == "workflow"
                and {"scenario": "cancel", "outcome": "CancelledError"} in before["outcomes"]
                and current_exceptions[0]["attributes"].get("exception.type") in CANCELLATION_TYPES
            )
            require(prior_types == current_types or missing_cancel_event_filled, f"existing span exception event name/type/cardinality changed: {old['span_id']}")
            for exception_type in prior_types:
                prior_group = [event for event in prior_exceptions if event["attributes"].get("exception.type") == exception_type]
                current_group = [event for event in current_exceptions if event["attributes"].get("exception.type") == exception_type]
                for key in ("exception.message", "exception.stacktrace"):
                    required = sum(isinstance(event["attributes"].get(key), str) and bool(event["attributes"][key]) for event in prior_group)
                    present = sum(isinstance(event["attributes"].get(key), str) and bool(event["attributes"][key]) for event in current_group)
                    require(present >= required, f"existing span exception event {key} missing: {old['span_id']}")

    prior_metrics = records(before, "metrics")
    retained_metrics = [record for record in records(after, "metrics") if "legacy.metric" in record["attributes"]]
    require(len(prior_metrics) == len(retained_metrics), "existing metrics values/fields missing or duplicated")
    unmatched_metrics = list(retained_metrics)
    for prior in prior_metrics:
        matched = next((
            index for index, current in enumerate(unmatched_metrics)
            if {key: value for key, value in prior.items() if key != "resource"} == {key: value for key, value in current.items() if key != "resource"}
            and preserves_resource(prior["resource"], current["resource"], "metrics")
        ), None)
        require(matched is not None, "existing metrics values/fields missing or duplicated")
        if matched is not None:
            unmatched_metrics.pop(matched)

    prior_logs = records(before, "logs")
    retained_logs = [record for record in records(after, "logs") if "legacy.log" in record["attributes"]]
    require(len(prior_logs) == len(retained_logs), "existing logs values/fields missing or duplicated")
    unmatched_logs = list(retained_logs)
    actual_spans = {(span["trace_id"], span["span_id"]): span for span in spans}
    request_scenarios = {f"turn-{index + 1}": scenario for index, scenario in enumerate(SCENARIOS)}
    for prior in prior_logs:
        def preserves_log(current: dict[str, Any]) -> bool:
            for key, value in prior.items():
                if key == "resource":
                    if not preserves_resource(value, current.get(key, {}), "logs"):
                        return False
                    continue
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
        require(
            (span["trace_id"], span["span_id"]) in legacy_ids or operation in expected,
            f"unexpected after-only span operation: {span['name']} ({operation or 'missing'})",
        )
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
