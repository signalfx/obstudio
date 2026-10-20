"""Run with the fixture's SDK environment; all HTTP endpoints are loopback."""

import importlib.util
from pathlib import Path
import shutil
import tempfile
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
        self.gateway = probe.Gateway()
        self.addCleanup(self.gateway.close)
        self.profile = self.root / "profile"
        self.profile.mkdir()

    def test_public_wrapper_and_request_hook_use_actual_wire_binding(self):
        self.gateway.resource_available = False
        probe.run(self.gateway, self.profile)
        self.assertEqual(self.gateway.forwarded, 1)
        self.assertEqual(len(self.gateway.traces), 1)
        probe.assert_binding(self.gateway.traces[0], True)
        self.assertFalse(any(path.startswith("/ao/api/") for _, path in self.gateway.requests))
        self.assertTrue(self.gateway.metrics and self.gateway.logs)

    def test_cached_restart_forwards_without_resource_lookup(self):
        self.gateway.connected = False
        probe.run(self.gateway, self.profile)
        self.assertEqual(self.gateway.forwarded, 0)
        probe.assert_binding(self.gateway.traces[-1], True)
        self.gateway.connected = True
        self.gateway.resource_available = False
        probe.run(self.gateway, self.profile, reuse_profile=True)
        self.assertEqual(self.gateway.forwarded, 1)
        self.assertEqual(len(self.gateway.traces), 2)
        probe.assert_binding(self.gateway.traces[-1], True)
        self.assertFalse(any(path.startswith("/ao/api/") for _, path in self.gateway.requests))

    def test_wire_oracle_still_rejects_missing_headers_and_resource_mismatch(self):
        probe.run(self.gateway, self.profile)
        headers, request = self.gateway.traces[-1]
        for name in ["projectid", "logstreamid"]:
            with self.subTest(missing=name), self.assertRaises(AssertionError):
                probe.assert_binding(({k: v for k, v in headers.items() if k != name}, request), True)
        for resource in request.resource_spans:
            for attribute in resource.resource.attributes:
                if attribute.key == "splunk_ao.project.id":
                    attribute.value.string_value = "different-project"
        with self.assertRaises(AssertionError):
            probe.assert_binding((headers, request), True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
