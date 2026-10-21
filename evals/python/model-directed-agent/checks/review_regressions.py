"""Run with the fixture's compatible environment; no model or cloud calls."""

import contextlib
import copy
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS
import unittest
from unittest.mock import ANY, patch

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest

FIXTURE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FIXTURE))

import otel_setup

with patch("dotenv.load_dotenv", return_value=False), patch.object(
    otel_setup, "configure_opentelemetry", return_value=(lambda: None, lambda: None)
):
    web = importlib.import_module("app")
    cli = importlib.import_module("agent")


class Provider:
    def __init__(self):
        self.inputs = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        messages = kwargs["messages"]
        self.inputs.append(copy.deepcopy(messages))
        user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        tools = None
        if user == "fail" and messages[-1]["role"] == "tool":
            raise RuntimeError("failure after tool feedback")
        if user == "fail":
            tools = [NS(id="call_review", function=NS(
                name="recommend_smash_burgers", arguments='{"city":"Austin"}'
            ))]
        return NS(
            model="gpt-4o-mini", usage=None,
            choices=[NS(message=NS(content=None if tools else "reply " + user, tool_calls=tools))],
        )


class ConversationTests(unittest.TestCase):
    def setUp(self):
        web._CONVERSATIONS.clear()
        web.app.config.update(TESTING=True)

    def assert_recovered_history(self, provider):
        history = provider.inputs[-1]
        self.assertEqual([m["role"] for m in history], ["system", "user", "assistant", "user"])
        self.assertEqual([m["content"] for m in history[1:]], ["before", "reply before", "after"])

    def test_web_rolls_back_entire_failed_tool_round(self):
        provider = Provider()
        with patch.object(web, "build_client", return_value=provider):
            client = web.app.test_client()
            self.assertEqual(client.post("/chat", json={"message": "before"}).status_code, 200)
            self.assertEqual(client.post("/chat", json={"message": "fail"}).status_code, 502)
            response = client.post("/chat", json={"message": "after"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"reply": "reply after"})
        self.assert_recovered_history(provider)

    def test_cli_rolls_back_entire_failed_tool_round(self):
        provider = Provider()
        output = io.StringIO()
        with patch.object(cli, "build_client", return_value=provider), patch.object(
            cli, "load_dotenv", return_value=False
        ), patch("builtins.input", side_effect=["before", "fail", "after", "quit"]), contextlib.redirect_stdout(output):
            cli.main()
        self.assertIn("Sorry, something went wrong", output.getvalue())
        self.assertIn("SmashBot: reply after", output.getvalue())
        self.assert_recovered_history(provider)

    def test_web_rejects_non_object_and_non_string_inputs_as_json(self):
        invalid = [None, [], [1], 123, True, "text", {}, *(
            {"message": value} for value in [None, 123, [1], {}, True, False, "", "   "]
        )]
        client = web.app.test_client()
        with patch.object(web, "build_client") as build:
            for value in invalid:
                with self.subTest(value=value):
                    response = client.post("/chat", data=json.dumps(value), content_type="application/json")
                    self.assertEqual(response.status_code, 400)
                    self.assertTrue(response.is_json)
                    self.assertIn("error", response.json)
            response = client.post("/chat", data="not json", content_type="application/json")
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.is_json)
        build.assert_not_called()

    def test_web_keeps_provider_exception_text_out_of_http_response(self):
        from openai import AuthenticationError

        failures = [RuntimeError("synthetic-private-provider-url"), AuthenticationError(
            "synthetic-private-key", response=NS(
                status_code=401, headers={}, request=NS(url="https://provider.invalid/v1")
            ), body={"error": "synthetic-private-key"},
        )]
        with patch.object(web, "build_client", return_value=object()):
            for failure in failures:
                with self.subTest(failure=type(failure).__name__), patch.object(
                    web, "run_turn", side_effect=failure
                ):
                    response = web.app.test_client().post("/chat", json={"message": "hello"})
                    self.assertEqual(response.status_code, 502)
                    self.assertEqual(response.json, {"error": "The assistant is temporarily unavailable."})

    def test_wrong_city_types_reach_model_feedback_and_native_tool_errors(self):
        script = '''
import json,sys
from types import SimpleNamespace as NS
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
sys.path.insert(0,sys.argv[1])
exporter=InMemorySpanExporter()
provider=TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
import chat_core
for city in [123,["Austin"],{},None,True]:
    exporter.clear()
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        tools=None
        if len(calls)==1:
            tools=[NS(id="invalid-city",type="function",function=NS(
                name="recommend_smash_burgers",arguments=json.dumps({"city":city})))]
        else:
            feedback=kwargs["messages"][-1]
            assert feedback["role"]=="tool"
            assert "Invalid arguments" in json.loads(feedback["content"])["error"]
        return NS(model="test-model",usage=None,choices=[NS(message=NS(
            content=None if tools else "recovered",tool_calls=tools))])
    messages=chat_core.new_conversation()+[{"role":"user","content":"recommend"}]
    assert chat_core.run_turn(NS(chat=NS(completions=NS(create=create))),"test-model",messages)=="recovered"
    assert len(calls)==2
    spans=exporter.get_finished_spans()
    tools=[s for s in spans if s.attributes.get("gen_ai.operation.name")=="execute_tool"]
    assert len(tools)==1
    assert tools[0].status.status_code.name=="ERROR"
    assert tools[0].attributes["error.type"]=="invalid_arguments"
    roots=[s for s in spans if s.parent is None]
    assert len(roots)==1 and roots[0].status.status_code.name!="ERROR"
    assert tools[0].parent.span_id==roots[0].context.span_id
provider.shutdown()
'''
        result = subprocess.run([sys.executable, "-c", script, str(FIXTURE)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_probe_executes_invalid_tool_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(FIXTURE / "probe.py")], cwd=directory,
                text=True, capture_output=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads((Path(directory) / ".observe/probe-native.json").read_text())
        self.assertEqual(len(data["cases"]), 4)
        case = next(c for c in data["cases"] if c["case"] == "tool_failure")
        self.assertEqual(case["actual_model_calls"], 2)
        tools = [s for s in case["spans"] if s["attributes"].get("gen_ai.operation.name") == "execute_tool"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["status"], "ERROR")
        self.assertEqual(tools[0]["attributes"]["error.type"], "invalid_arguments")


class ExportHeaderTests(unittest.TestCase):
    def test_real_startup_and_wire_preserve_selected_destinations_and_headers(self):
        received = []

        class Receiver(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                received.append((self.path, dict(self.headers), body))
                self.send_response(200)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", "0")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            for overrides in [
                {},
                {"OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "false"},
                {"MODEL_DIRECTED_PREINSTRUMENT_LOGGING": "1"},
                {"MODEL_DIRECTED_PREINSTRUMENT_LOGGING": "handler"},
                {"MODEL_DIRECTED_PREINSTALLED_SDK_HANDLER": "1"},
                {"OTEL_EXPORTER_OTLP_TRACES_HEADERS": "Authorization=trace-marker"},
                {"OTEL_EXPORTER_OTLP_METRICS_HEADERS": "Authorization=metric-marker"},
                {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": origin + "/selected/logs"},
                {"OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": origin + "/selected/logs"},
                {"OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": origin + "/selected/logs",
                 "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "Authorization=log-marker,X-Log-Tenant=chosen"},
                {"OTEL_LOGS_EXPORTER": "none", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": origin + "/selected/logs"},
                {"OTEL_EXPORTER_OTLP_LOGS_HEADERS": "Authorization=log-marker,X-Log-Tenant=chosen"},
                {"OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_ENDPOINT": origin + "/collector/",
                 "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "Authorization=log-marker,X-Log-Tenant=chosen"},
                {"OTEL_EXPORTER_OTLP_ENDPOINT": origin + "/collector", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": origin + "/selected/logs",
                 "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "Authorization=log-marker,X-Log-Tenant=chosen"},
            ]:
                with self.subTest(overrides=overrides):
                    received.clear()
                    environment = {k: v for k, v in os.environ.items() if not k.startswith("OTEL_")}
                    environment.update(OTEL_EXPORTER_OTLP_ENDPOINT=origin,
                                       OTEL_EXPORTER_OTLP_HEADERS="Authorization=generic-marker,X-App-Tenant=keep")
                    environment.update(overrides)
                    script = (
                        "import io,logging,os,sys\n"
                        f"sys.path.insert(0,{str(FIXTURE)!r})\n"
                        "import otel_setup\n"
                        f"otel_setup.LOCAL_OBSERVER_LOGS_ENDPOINT={origin + '/v1/logs'!r}\n"
                        "install,shutdown=otel_setup.configure_opentelemetry()\n"
                        "from opentelemetry import trace,metrics\n"
                        "external=None\n"
                        "if os.getenv('MODEL_DIRECTED_PREINSTRUMENT_LOGGING') in ('1','handler'):\n"
                        " from opentelemetry.instrumentation.logging import LoggingInstrumentor\n"
                        " external=LoggingInstrumentor()\n"
                        " external.instrument(set_logging_format=False,enable_log_auto_instrumentation=os.getenv('MODEL_DIRECTED_PREINSTRUMENT_LOGGING')=='handler')\n"
                        "sdk_handler=None\n"
                        "if os.getenv('MODEL_DIRECTED_PREINSTALLED_SDK_HANDLER') == '1':\n"
                        " from opentelemetry.sdk._logs import LoggingHandler\n"
                        " sdk_handler=LoggingHandler()\n"
                        " logging.getLogger().addHandler(sdk_handler)\n"
                        "console=logging.StreamHandler(io.StringIO())\n"
                        "logging.getLogger().addHandler(console)\n"
                        "factory=logging.getLogRecordFactory()\n"
                        "handlers=tuple(logging.getLogger().handlers)\n"
                        "install();install()\n"
                        "with trace.get_tracer('startup-regression').start_as_current_span('startup'):\n"
                        " metrics.get_meter('startup-regression').create_counter('startup.turns').add(1)\n"
                        " logging.getLogger('startup-regression').warning('startup passed')\n"
                        "shutdown();shutdown();install()\n"
                        "assert logging.getLogRecordFactory() is factory\n"
                        "assert tuple(logging.getLogger().handlers) == handlers\n"
                        "assert console.stream.getvalue().count('startup passed') == 1\n"
                        "if external is not None:\n"
                        " assert external.is_instrumented_by_opentelemetry\n"
                        " external.uninstrument()\n"
                        "if sdk_handler is not None:\n"
                        " logging.getLogger().removeHandler(sdk_handler)\n"
                        " sdk_handler.close()\n"
                    )
                    result = subprocess.run([sys.executable, "-c", script], env=environment,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    bypath = {path: {k.lower(): v for k, v in headers.items()} for path, headers, size in received if size}
                    selected = "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT" in overrides or "OTEL_EXPORTER_OTLP_LOGS_HEADERS" in overrides
                    disabled = overrides.get("OTEL_LOGS_EXPORTER") == "none"
                    basepath = "/collector" if "/collector" in environment["OTEL_EXPORTER_OTLP_ENDPOINT"] else ""
                    logpath = ("/selected/logs" if "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT" in overrides
                               else basepath + "/v1/logs" if selected else "/v1/logs")
                    self.assertEqual(set(bypath), {basepath + "/v1/traces", basepath + "/v1/metrics"} | (set() if disabled else {logpath}))
                    for signal_name in ("traces", "metrics"):
                        expected = overrides.get(f"OTEL_EXPORTER_OTLP_{signal_name.upper()}_HEADERS", "Authorization=generic-marker").split("=", 1)[1]
                        self.assertEqual(bypath[basepath + "/v1/" + signal_name]["authorization"], expected)
                    if disabled:
                        continue
                    logs = [record for path, _, payload in received if path == logpath
                            for resource in ExportLogsServiceRequest.FromString(payload).resource_logs
                            for scope in resource.scope_logs for record in scope.log_records]
                    startup = [record for record in logs if record.body.string_value == "startup passed"]
                    self.assertEqual(len(startup), 1)
                    self.assertNotEqual(int.from_bytes(startup[0].trace_id, "big"), 0)
                    self.assertNotEqual(int.from_bytes(startup[0].span_id, "big"), 0)
                    if selected:
                        expected = "log-marker" if "OTEL_EXPORTER_OTLP_LOGS_HEADERS" in overrides else "generic-marker"
                        self.assertEqual(bypath[logpath]["authorization"], expected)
                        if "OTEL_EXPORTER_OTLP_LOGS_HEADERS" in overrides:
                            self.assertEqual(bypath[logpath]["x-log-tenant"], "chosen")
                        else:
                            self.assertEqual(bypath[logpath]["x-app-tenant"], "keep")
                    else:
                        self.assertNotIn("authorization", bypath[logpath])
                        self.assertNotIn("x-app-tenant", bypath[logpath])
                    self.assertNotIn("projectid", bypath[logpath])
                    self.assertNotIn("logstreamid", bypath[logpath])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_local_logs_reject_explicit_log_headers_before_exporter_construction(self):
        for key in ["OTEL_EXPORTER_OTLP_LOGS_HEADERS"]:
            with self.subTest(key=key), patch.dict(os.environ, {key: "Authorization=synthetic"}, clear=True):
                before = dict(os.environ)
                with patch.object(otel_setup, "OTLPLogExporter") as exporter:
                    with self.assertRaises(RuntimeError):
                        otel_setup._local_log_exporter()
                    exporter.assert_not_called()
                self.assertEqual(dict(os.environ), before)

    def test_local_logs_isolate_generic_headers_without_modifying_operator_environment(self):
        with patch.dict(os.environ, {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.invalid",
            "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=synthetic,X-App-Tenant=keep",
        }, clear=True), patch.object(otel_setup, "OTLPLogExporter") as exporter:
            before = dict(os.environ)
            otel_setup._local_log_exporter()
            exporter.assert_called_once_with(
                endpoint=otel_setup.LOCAL_OBSERVER_LOGS_ENDPOINT,
                headers={"Content-Type": "application/x-protobuf"},
                session=ANY,
            )
            self.assertIsInstance(exporter.call_args.kwargs["session"], otel_setup._LocalLogSession)
            self.assertEqual(dict(os.environ), before)

    def test_log_headers_use_explicit_base_without_changing_operator_environment(self):
        with patch.dict(os.environ, {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.invalid/prefix/",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "Authorization=synthetic",
        }, clear=True), patch.object(otel_setup, "OTLPLogExporter") as exporter:
            before = dict(os.environ)
            otel_setup._local_log_exporter()
            exporter.assert_called_once_with()
            self.assertEqual(dict(os.environ), before)

    def test_implicit_trace_metric_destinations_reject_headers_before_any_provider(self):
        for key in ["OTEL_EXPORTER_OTLP_HEADERS", "OTEL_EXPORTER_OTLP_TRACES_HEADERS", "OTEL_EXPORTER_OTLP_METRICS_HEADERS"]:
            with self.subTest(key=key), patch.dict(os.environ, {
                key: "Authorization=synthetic", "OTEL_LOGS_EXPORTER": "none",
            }, clear=True), contextlib.ExitStack() as stack:
                constructors = [stack.enter_context(patch.object(otel_setup, name)) for name in (
                    "OTLPSpanExporter", "OTLPMetricExporter", "OTLPLogExporter",
                    "TracerProvider", "MeterProvider", "LoggerProvider",
                )]
                with self.assertRaises(RuntimeError):
                    otel_setup.configure_opentelemetry()
                for constructor in constructors:
                    constructor.assert_not_called()

    def test_explicit_base_and_signal_endpoints_preserve_valid_configuration(self):
        for signal in ["TRACES", "METRICS"]:
            for endpoint_key in ["OTEL_EXPORTER_OTLP_ENDPOINT", f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT"]:
                for header_key in ["OTEL_EXPORTER_OTLP_HEADERS", f"OTEL_EXPORTER_OTLP_{signal}_HEADERS"]:
                    with self.subTest(signal=signal, endpoint=endpoint_key, header=header_key), patch.dict(os.environ, {
                        endpoint_key: "https://collector.invalid", header_key: "Authorization=synthetic",
                    }, clear=True):
                        before = dict(os.environ)
                        otel_setup._validate_export_headers(signal)
                        self.assertEqual(dict(os.environ), before)

    def test_no_headers_keeps_existing_local_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            otel_setup._validate_export_headers("TRACES")
            otel_setup._validate_export_headers("METRICS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
