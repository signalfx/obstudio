"""Exercise the real Galileo exporter with patched OTLP on loopback only."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
import asyncio
import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from galileo.otel import GalileoSpanProcessor
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace import TracerProvider
from pydantic import SecretStr

from galileo_compat import create_span_processor


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        requests = self.requests

        class Receiver(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append((self.path, dict(self.headers), ExportTraceServiceRequest.FromString(body)))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.worker.join, 5)
        self.addCleanup(self.server.shutdown)
        config = SimpleNamespace(
            api_url=f"http://127.0.0.1:{self.server.server_port}/vendor/",
            api_key=SecretStr("synthetic-galileo-key"),
        )
        config_patch = patch("galileo.otel.GalileoPythonConfig.get", return_value=config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        variables = {key: value for key, value in os.environ.items()
                     if not key.startswith("OTEL_") and key.lower() not in {
                         "http_proxy", "https_proxy", "all_proxy", "no_proxy",
                     }}
        variables.update(GALILEO_PROJECT="deployment-project", GALILEO_LOG_STREAM="production",
                         NO_PROXY="127.0.0.1", NETRC=os.devnull)
        environment = patch.dict(os.environ, variables, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def pipeline(self):
        processor = create_span_processor("deployment-project")
        self.assertIsInstance(processor, GalileoSpanProcessor)
        provider = TracerProvider()
        provider.add_span_processor(processor)
        self.addCleanup(provider.shutdown)
        return provider, processor

    def emit(self, provider, **attributes):
        with provider.get_tracer("fixture-regression").start_as_current_span("fixture-span") as span:
            for name, value in attributes.items():
                span.set_attribute(name, value)
        self.assertTrue(provider.force_flush())
        path, raw_headers, payload = self.requests[-1]
        self.assertEqual(path, "/vendor/otel/traces")
        headers = {name.lower(): value for name, value in raw_headers.items()}
        self.assertEqual(headers["galileo-api-key"], "synthetic-galileo-key")
        self.assertEqual(payload.resource_spans[0].scope_spans[0].spans[0].name, "fixture-span")
        return headers

    def test_default_and_per_batch_destinations_reach_the_real_receiver(self):
        provider, _ = self.pipeline()
        default = self.emit(provider)
        self.assertEqual((default["project"], default["logstream"]), ("deployment-project", "production"))
        selected = self.emit(provider, **{
            "galileo.project.name": "selected-project",
            "galileo.logstream.name": "selected-stream",
        })
        self.assertEqual((selected["project"], selected["logstream"]), ("selected-project", "selected-stream"))
        self.assertEqual(len(self.requests), 2)

    def test_actual_app_and_replay_preserve_existing_operations(self):
        import app
        import agent

        self.addCleanup(app.provider.shutdown)

        async def consume_stream():
            response = await app.chat_stream(app.ChatRequest(prompt="offline fixture input"))
            return "".join([chunk async for chunk in response.body_iterator])

        self.assertEqual(asyncio.run(consume_stream()), "answer complete")
        answer = agent.run_agent(agent.ReplayModel(), [{"role": "user", "content": "Find returns docs"}])
        self.assertEqual(answer, "Documentation for returns")
        self.assertTrue(app.provider.force_flush())
        spans = [span for _, _, payload in self.requests
                 for resource in payload.resource_spans for scope in resource.scope_spans
                 for span in scope.spans]
        names = [span.name for span in spans]
        self.assertEqual(len(spans), 7)
        self.assertEqual(names.count("chat replay-model"), 2)
        self.assertEqual(names.count("execute_tool search_docs"), 2)
        self.assertEqual(names.count("invoke_workflow support_turn"), 1)
        self.assertEqual(names.count("chat gpt-4o-mini"), 1)
        self.assertEqual(names.count("invoke_agent support-agent"), 1)
        workflow = next(span for span in spans if span.name == "invoke_workflow support_turn")
        turn = next(span for span in spans if span.name == "invoke_agent support-agent")
        self.assertFalse(workflow.parent_span_id)
        self.assertFalse(turn.parent_span_id)
        self.assertNotEqual(workflow.trace_id, turn.trace_id)
        for span in spans:
            if span.name == "chat gpt-4o-mini":
                self.assertEqual(span.parent_span_id, workflow.span_id)
            elif span.name == "chat replay-model":
                self.assertEqual(span.parent_span_id, turn.span_id)
        tool_parents = {span.parent_span_id for span in spans if span.name == "execute_tool search_docs"}
        self.assertEqual(tool_parents, {workflow.span_id, turn.span_id})

    def test_experiment_and_stream_transitions_do_not_keep_stale_headers(self):
        provider, _ = self.pipeline()
        experiment = self.emit(provider, **{"galileo.experiment.id": "experiment-7"})
        self.assertEqual(experiment["experimentid"], "experiment-7")
        self.assertNotIn("logstream", experiment)
        normal = self.emit(provider)
        self.assertEqual(normal["logstream"], "production")
        self.assertNotIn("experimentid", normal)

    def test_shutdown_closes_the_same_session_and_does_not_export_twice(self):
        provider, processor = self.pipeline()
        session = processor.exporter._session
        self.emit(provider)
        with patch.object(session, "close", wraps=session.close) as close:
            provider.shutdown()
            self.assertEqual(close.call_count, 1)
        self.assertEqual(len(self.requests), 1)

    def test_failed_construction_closes_the_owned_session(self):
        with patch("galileo_compat._GalileoSession") as session:
            with patch("galileo_compat.GalileoSpanProcessor", side_effect=ValueError("missing configuration")):
                with self.assertRaisesRegex(ValueError, "missing configuration"):
                    create_span_processor("deployment-project")
            session.return_value.close.assert_called_once_with()

    def test_empty_certificate_environment_keeps_tls_verification_enabled(self):
        for certificate_variables in (
            {"OTEL_EXPORTER_OTLP_CERTIFICATE": ""},
            {"OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE": ""},
            {"OTEL_EXPORTER_OTLP_CERTIFICATE": "", "OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE": ""},
        ):
            with self.subTest(variables=certificate_variables):
                with patch.dict(os.environ, {**certificate_variables,
                                             "REQUESTS_CA_BUNDLE": "", "CURL_CA_BUNDLE": ""}):
                    provider, processor = self.pipeline()
                    session = processor.exporter._session
                    with patch.object(session, "send", wraps=session.send) as send:
                        self.emit(provider)
                        self.assertIs(send.call_args.kwargs["verify"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
