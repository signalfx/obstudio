"""Run with the fixture's SDK environment; all HTTP endpoints are loopback."""

import importlib.util
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


FIXTURE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("connection_probe", FIXTURE / "probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

PUBLIC_EXPORTER = '''
import os
from requests import Session
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.trace import SpanContext

PROJECT = "00000000-0000-4000-8000-000000000001"
STREAM = "00000000-0000-4000-8000-000000000002"

class RoutingSession(Session):
    def prepare_request(self, request):
        prepared = super().prepare_request(request)
        prepared.headers.update(projectid=PROJECT, logstreamid=STREAM)
        return prepared

class PublicExporter(SpanExporter):
    def __init__(self):
        # The supported request hook supplies routing; static SDK headers do not.
        headers = os.environ.pop("OTEL_EXPORTER_OTLP_TRACES_HEADERS")
        try:
            self.wrapped = OTLPSpanExporter(
                headers={"X-App-Tenant": "keep-marker"}, session=RoutingSession())
        finally:
            os.environ["OTEL_EXPORTER_OTLP_TRACES_HEADERS"] = headers

    def export(self, spans):
        views = [ReadableSpan(
            name=s.name, context=s.context, parent=s.parent,
            resource=s.resource.merge(Resource({
                "splunk_ao.project.id": PROJECT, "splunk_ao.logstream.id": STREAM})),
            attributes=s.attributes, events=s.events, links=s.links, kind=s.kind,
            status=s.status, start_time=s.start_time, end_time=s.end_time,
            instrumentation_scope=s.instrumentation_scope,
        ) for s in spans]
        return self.wrapped.export(views)

    def shutdown(self):
        self.wrapped.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self.wrapped.force_flush(timeout_millis)
'''


class ProbeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.service = self.root / "service"
        self.service.mkdir()
        for name in ["app.py", "launch.py", "telemetry.py"]:
            shutil.copy2(FIXTURE / name, self.service / name)
        telemetry = self.service / "telemetry.py"
        telemetry.write_text(telemetry.read_text().replace(
            "BatchSpanProcessor(OTLPSpanExporter())",
            "BatchSpanProcessor(PublicExporter())",
        ) + "\nfrom public_exporter import PublicExporter\n")
        (self.service / "public_exporter.py").write_text(PUBLIC_EXPORTER)
        self.root_patch = patch.object(probe, "ROOT", self.service)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        bytecode = patch.dict("os.environ", {"PYTHONDONTWRITEBYTECODE": "1"})
        bytecode.start()
        self.addCleanup(bytecode.stop)
        self.gateway = probe.Gateway()
        self.addCleanup(self.gateway.close)
        self.profile = self.root / "profile"
        self.profile.mkdir()

    def test_public_wrapper_and_request_hook_use_actual_wire_binding(self):
        self.gateway.resource_available = False
        _, native = probe.run(self.gateway, self.profile)
        self.assertEqual(self.gateway.forwarded, 1)
        self.assertEqual(len(self.gateway.traces), 1)
        probe.assert_binding(self.gateway.traces, True, native)
        self.assertFalse(any(path.startswith("/ao/api/") for _, path in self.gateway.requests))
        self.assertTrue(self.gateway.metrics and self.gateway.logs)

    def test_cached_restart_forwards_without_resource_lookup(self):
        self.gateway.connected = False
        _, native = probe.run(self.gateway, self.profile)
        self.assertEqual(self.gateway.forwarded, 0)
        probe.assert_binding(self.gateway.traces, True, native)
        self.gateway.connected = True
        self.gateway.resource_available = False
        _, restarted_native = probe.run(self.gateway, self.profile, reuse_profile=True)
        self.assertEqual(self.gateway.forwarded, 1)
        self.assertEqual(len(self.gateway.traces), 2)
        probe.assert_binding(self.gateway.traces[1:], True, restarted_native)
        self.assertFalse(any(path.startswith("/ao/api/") for _, path in self.gateway.requests))

    def test_wire_oracle_still_rejects_missing_headers_and_resource_mismatch(self):
        _, native = probe.run(self.gateway, self.profile)
        headers, request = self.gateway.traces[-1]
        for name in ["projectid", "logstreamid"]:
            with self.subTest(missing=name), self.assertRaises(AssertionError):
                probe.assert_binding([({k: v for k, v in headers.items() if k != name}, request)], True, native)
        for resource in request.resource_spans:
            for attribute in resource.resource.attributes:
                if attribute.key == "splunk_ao.project.id":
                    attribute.value.string_value = "different-project"
        with self.assertRaises(AssertionError):
            probe.assert_binding([(headers, request)], True, native)

    def test_public_views_cannot_rewrite_identity_topology_or_operations(self):
        context = "SpanContext(trace_id=s.context.trace_id{trace}, span_id=s.context.span_id{span}, is_remote=False, trace_flags=s.context.trace_flags, trace_state=s.context.trace_state)"
        changes = [
            ("trace_id", "context=s.context", "context=" + context.format(trace=" ^ 1", span="")),
            ("span_id", "context=s.context", "context=" + context.format(trace="", span=" ^ 1")),
            ("parent", "parent=s.parent", "parent=None"),
            ("name", "name=s.name", 'name="rewritten " + s.name'),
            ("operation", "attributes=s.attributes", 'attributes={**s.attributes, "gen_ai.operation.name": "rewritten"}'),
        ]
        for label, original, replacement in changes:
            with self.subTest(corruption=label):
                (self.service / "public_exporter.py").write_text(PUBLIC_EXPORTER.replace(original, replacement))
                start = len(self.gateway.traces)
                _, native = probe.run(self.gateway, self.profile)
                with self.assertRaises(AssertionError):
                    probe.assert_binding(self.gateway.traces[start:], True, native)

    def test_split_wire_batches_are_collected_for_the_native_turn(self):
        for size in [1, 2]:
            with self.subTest(split=f"{size}+{4 - size}"):
                (self.service / "public_exporter.py").write_text(PUBLIC_EXPORTER.replace(
                    "return self.wrapped.export(views)",
                    f"self.wrapped.export(views[:{size}])\n        return self.wrapped.export(views[{size}:])",
                ))
                start = len(self.gateway.traces)
                _, native = probe.run(self.gateway, self.profile)
                packets = self.gateway.traces[start:]
                self.assertEqual([len(probe.packet_spans(p, True)) for p in packets], [size, 4 - size])
                probe.assert_binding(packets, True, native)
                self.gateway.traces = []

                def deliver():
                    self.gateway.traces.append(packets[0])
                    time.sleep(0.65)
                    self.gateway.traces.append(packets[1])

                sender = threading.Thread(target=deliver)
                sender.start()
                try:
                    self.assertTrue(probe.wait_for_turn(
                        self.gateway, 0, True, native["spans"], time.monotonic() + 1))
                finally:
                    sender.join()

    def test_missing_overlapping_and_duplicate_spans_are_rejected(self):
        _, native = probe.run(self.gateway, self.profile)
        headers, original = self.gateway.traces[-1]
        spans = [s for r in original.resource_spans for scope in r.scope_spans for s in scope.spans]

        def packet(selected):
            request = probe.ExportTraceServiceRequest()
            resource = request.resource_spans.add()
            resource.resource.CopyFrom(original.resource_spans[0].resource)
            resource.scope_spans.add().spans.extend(selected)
            return headers, request

        for packets in [[packet(spans[:3])], [packet(spans + spans[:1])],
                        [packet(spans[:2]), packet(spans[1:])]]:
            with self.subTest(sizes=[len(probe.packet_spans(p, True)) for p in packets]):
                with self.assertRaises(AssertionError):
                    probe.assert_binding(packets, True, native)
        self.assertFalse(probe.wait_for_turn(
            type("Receiver", (), {"traces": [packet(spans[:3])]})(), 0, True,
            native["spans"], time.monotonic()))
        probe.assert_binding([packet(spans[:2]), packet(spans[:2]), packet(spans[2:])], True, native)

    def test_same_pid_selects_the_native_turn_from_a_multi_turn_batch(self):
        _, earlier = probe.run(self.gateway, self.profile)
        _, current = probe.run(self.gateway, self.profile, reuse_profile=True)
        headers, combined = self.gateway.traces[0]
        combined.MergeFrom(self.gateway.traces[1][1])
        receiver = type("Receiver", (), {"traces": [(headers, combined)]})()
        self.assertTrue(probe.wait_for_turn(receiver, 0, True, current["spans"], time.monotonic()))
        with self.assertRaises(AssertionError):
            probe.assert_binding(receiver.traces, True, earlier)

    def test_complete_unbound_turn_allows_another_recovery_attempt(self):
        _, native = probe.run(self.gateway, self.profile)
        headers, original = self.gateway.traces[-1]
        unbound = probe.ExportTraceServiceRequest()
        unbound.CopyFrom(original)
        for resource in unbound.resource_spans:
            retained = [a for a in resource.resource.attributes
                        if not a.key.startswith("splunk_ao.")]
            del resource.resource.attributes[:]
            resource.resource.attributes.extend(retained)
        headers = {k: v for k, v in headers.items() if k not in {"projectid", "logstreamid"}}
        receiver = type("Receiver", (), {"traces": [(headers, unbound)]})()
        self.assertFalse(probe.wait_for_turn(receiver, 0, True, native["spans"], time.monotonic() + 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
