import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from threading import Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from galileo import otel
except ModuleNotFoundError as exc:
    if exc.name != "galileo":
        raise
    raise unittest.SkipTest("Requires the galileo-agent-demo fixture dependencies") from exc
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace import TracerProvider
from pydantic import SecretStr
from requests import Response

spec = importlib.util.spec_from_file_location("galileo_compat", Path(__file__).resolve().parents[1] / "galileo_compat.py")
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        requests = self.requests

        class Receiver(BaseHTTPRequestHandler):
            def do_POST(self):
                self.connection.settimeout(5)
                body = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append((self.headers, ExportTraceServiceRequest.FromString(body)))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        config = SimpleNamespace(api_url=f"http://127.0.0.1:{server.server_port}", api_key=SecretStr("test-key"))
        self.config = patch.object(otel.GalileoPythonConfig, "get", return_value=config)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.processor = compat.create_span_processor(project="initial-project")
        self.provider = TracerProvider()
        self.provider.add_span_processor(self.processor)
        self.addCleanup(self.provider.shutdown)
        self.tracer = self.provider.get_tracer("compat-test")

    def export_turn(self, project, stream=None, experiment=None):
        contexts = (
            (otel._project_context, project),
            (otel._log_stream_context, stream),
            (otel._experiment_id_context, experiment),
        )
        tokens = [(context, context.set(value)) for context, value in contexts]
        try:
            with self.tracer.start_as_current_span("workflow") as parent:
                with self.tracer.start_as_current_span("tool"):
                    pass
        finally:
            for context, token in reversed(tokens):
                context.reset(token)
        self.assertTrue(self.provider.force_flush(timeout_millis=5000))
        headers, request = self.requests[-1]
        spans = [
            span
            for resource in request.resource_spans
            for scope in resource.scope_spans
            for span in scope.spans
        ]
        self.assertEqual(len(spans), 2)
        child = next(span for span in spans if span.name == "tool")
        self.assertEqual(int.from_bytes(child.parent_span_id, "big"), parent.context.span_id)
        return headers

    def test_batch_destinations_and_authentication_reach_real_receiver(self):
        for project, stream in (("project-one", "stream-one"), ("project-two", "stream-two")):
            headers = self.export_turn(project, stream)
            self.assertEqual(headers["project"], project)
            self.assertEqual(headers["logstream"], stream)
            self.assertEqual(headers["Galileo-API-Key"], "test-key")

    def test_experiment_then_stream_clears_stale_destination(self):
        headers = self.export_turn("experiment-project", experiment="experiment-one")
        self.assertEqual(headers["experimentid"], "experiment-one")
        self.assertNotIn("logstream", headers)
        headers = self.export_turn("stream-project", "stream-one")
        self.assertEqual(headers["logstream"], "stream-one")
        self.assertNotIn("experimentid", headers)

    def test_shutdown_closes_owned_session_without_duplicate_export(self):
        self.export_turn("project-one", "stream-one")
        session = self.processor.exporter._session
        with patch.object(session, "close", wraps=session.close) as close:
            self.provider.shutdown()
            close.assert_called_once()
        self.assertEqual(len(self.requests), 1)

    def test_failed_construction_closes_owned_session(self):
        session = compat._GalileoSession()
        with patch.object(compat, "_GalileoSession", return_value=session), patch.object(
            compat, "GalileoSpanProcessor", side_effect=ValueError("invalid configuration")
        ), patch.object(session, "close", wraps=session.close) as close:
            with self.assertRaisesRegex(ValueError, "invalid configuration"):
                compat.create_span_processor(project="project-one")
            close.assert_called_once()

    def test_empty_certificate_setting_keeps_tls_verification(self):
        response = Response()
        response.status_code = 200
        response._content = b""
        with patch.dict("os.environ", {"OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE": ""}), patch.object(
            compat._GalileoSession, "send", return_value=response
        ) as send:
            processor = compat.create_span_processor(project="project-one")
            provider = TracerProvider()
            provider.add_span_processor(processor)
            try:
                with provider.get_tracer("tls-test").start_as_current_span("workflow"):
                    pass
                self.assertTrue(provider.force_flush(timeout_millis=5000))
                self.assertIs(send.call_args.kwargs["verify"], True)
            finally:
                provider.shutdown()

    def test_actual_app_exports_workflow_model_and_tool(self):
        from fastapi.testclient import TestClient

        fixture = Path(__file__).resolve().parents[1]
        with patch.object(sys, "path", [str(fixture), *sys.path]):
            app_spec = importlib.util.spec_from_file_location("galileo_compat_app", fixture / "app.py")
            app = importlib.util.module_from_spec(app_spec)
            app_spec.loader.exec_module(app)
        self.addCleanup(app.provider.shutdown)
        with TestClient(app.app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            response = client.post("/v1/chat/stream", json={"prompt": "hello"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, "answer complete")
        self.assertTrue(app.provider.force_flush(timeout_millis=5000))
        spans = [
            span
            for _, request in self.requests
            for resource in request.resource_spans
            for scope in resource.scope_spans
            for span in scope.spans
            if any(attribute.key == "gen_ai.operation.name" for attribute in span.attributes)
        ]
        self.assertEqual(
            {span.name for span in spans},
            {"invoke_workflow support_turn", "execute_tool search_docs", "chat gpt-4o-mini"},
        )
        self.assertEqual(len(spans), 3)


if __name__ == "__main__":
    unittest.main()
