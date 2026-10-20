"""Independent native SDK/HTTP oracle. No cloud or model credentials required."""

import gzip
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

PROJECT = "00000000-0000-4000-8000-000000000001"
STREAM = "00000000-0000-4000-8000-000000000002"
ROOT = Path(__file__).resolve().parent


class Gateway:
    def __init__(self, connected=True, existing=True, uncertain=False):
        self.connected = connected
        self.project = existing
        self.stream = existing
        self.uncertain = uncertain
        self.bound = False
        self.requests = []
        self.traces = []
        self.metrics = []
        self.logs = []
        self.forwarded = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def handle_request(self):
                path = urlsplit(self.path).path
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                owner.requests.append((self.command, path))
                if path.startswith("/ao/api/"):
                    if self.headers.get("X-SF-Token") != "local-gateway":
                        return self.reply(401, {})
                    if not owner.connected:
                        return self.reply(503, {"error": "cloud disconnected"})
                    project = {"id": PROJECT, "name": "original-project"}
                    stream = {"id": STREAM, "name": "production", "project_id": PROJECT}
                    if self.command == "GET" and path == "/ao/api/projects/all":
                        return self.reply(200, [project] if owner.project else [])
                    if self.command == "GET" and path == f"/ao/api/projects/{PROJECT}":
                        return self.reply(200 if owner.project else 404, project if owner.project else {})
                    if self.command == "POST" and path == "/ao/api/projects":
                        owner.project = True
                        if owner.uncertain:
                            owner.uncertain = False
                            self.close_connection = True
                            self.connection.shutdown(socket.SHUT_RDWR)
                            self.connection.close()
                            return
                        return self.reply(201, project)
                    if path.startswith(f"/ao/api/projects/{PROJECT}/log_streams"):
                        if self.command == "POST":
                            owner.stream = True
                            return self.reply(201, stream)
                        owner.bound = owner.project and owner.stream
                        if path.endswith("/paginated"):
                            return self.reply(200, {"log_streams": [stream] if owner.stream else [], "paginated": False, "next_starting_token": None})
                        return self.reply(200 if owner.stream else 404, stream if owner.stream else {})
                    return self.reply(404, {})
                headers = {k.lower(): v for k, v in self.headers.items()}
                if path in ("/v1/metrics", "/v1/logs"):
                    if "projectid" in headers or "logstreamid" in headers:
                        return self.reply(400, {"error": "routing leaked across signals"})
                    if self.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    if path.endswith("metrics"):
                        owner.metrics.append(ExportMetricsServiceRequest.FromString(body))
                    else:
                        owner.logs.append(ExportLogsServiceRequest.FromString(body))
                    return self.reply(200, {})
                if path == "/v1/traces":
                    pair = (headers.get("projectid"), headers.get("logstreamid"))
                    if any(pair) and pair != (PROJECT, STREAM):
                        return self.reply(409, {"error": "invalid route"})
                    if self.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    owner.traces.append((headers, ExportTraceServiceRequest.FromString(body)))
                    if any(pair) and not owner.connected:
                        return self.reply(503, {"error": "cloud disconnected; retained locally"})
                    owner.forwarded += int(pair == (PROJECT, STREAM))
                    return self.reply(200, {})
                return self.reply(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def run(gateway, directory, *, seeded=True, reuse_profile=False):
    profile = directory / "runtime.env"
    capture = directory / "native.json"
    observed = directory / "exporter.json"
    if not reuse_profile:
        pair = f"projectid={PROJECT},logstreamid={STREAM}," if seeded else ""
        profile.write_text(
            f"AGENT_RESOURCE_API_URL={gateway.origin}\nAGENT_PROJECT=original-project\nAGENT_STREAM=production\n"
            f"OTEL_EXPORTER_OTLP_ENDPOINT={gateway.origin}\n"
            f"OTEL_EXPORTER_OTLP_TRACES_HEADERS={pair}X-App-Tenant=keep-marker\n"
            "OTEL_EXPORTER_OTLP_TRACES_TIMEOUT=0.2\nOTEL_EXPORTER_OTLP_METRICS_TIMEOUT=0.2\n"
            "OTEL_EXPORTER_OTLP_LOGS_TIMEOUT=0.2\nOTEL_METRIC_EXPORT_TIMEOUT=200\n"
            f"LOCAL_CAPTURE_FILE={capture}\nAPPLICATION_KEEP_SETTING=preserve-me\n"
        )
    wrapper = directory / "run.py"
    wrapper.write_text(
        "import atexit,json,runpy,sys\nfrom pathlib import Path\n"
        "from opentelemetry import trace\n"
        f"sys.path.insert(0,{str(ROOT)!r})\n"
        "def observe():\n"
        " p=trace.get_tracer_provider(); result=[]\n"
        " for processor in getattr(getattr(p,'_active_span_processor',None),'_span_processors',()):\n"
        "  exporter=getattr(processor,'span_exporter',None)\n"
        "  seen=set()\n"
        "  while exporter is not None and id(exporter) not in seen:\n"
        "   seen.add(id(exporter))\n"
        "   if type(exporter).__name__=='OTLPSpanExporter':\n"
        "    result.append({str(k).lower():v for k,v in exporter._headers.items() if str(k).lower() in ('projectid','logstreamid','x-app-tenant')}); break\n"
        "   exporter=getattr(exporter,'delegate',getattr(exporter,'_delegate',None))\n"
        f" Path({str(observed)!r}).write_text(json.dumps(result))\n"
        "atexit.register(observe)\n"
        f"sys.argv=['launch.py','--profile',{str(profile)!r}]\n"
        f"runpy.run_path({str(ROOT / 'launch.py')!r},run_name='__main__')\n"
    )
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("OTEL_", "SPLUNK_AO_", "GALILEO_", "AGENT_", "LOCAL_CAPTURE_FILE"))}
    process = subprocess.run([sys.executable, str(wrapper)], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr[-1500:]
    assert json.loads(process.stdout.strip().splitlines()[-1]) == {"answer": "Documentation for returns"}
    native = json.loads(capture.read_text())
    assert len(native["spans"]) == 4
    agent = next(s for s in native["spans"] if s["attributes"].get("gen_ai.operation.name") == "invoke_agent")
    assert all(s["parent_id"] == agent["span_id"] for s in native["spans"] if s is not agent)
    assert native["metrics"] == [{"name": "agent.turns", "values": [1]}]
    assert len(native["logs"]) == 1 and native["logs"][0]["trace_id"] == agent["trace_id"]
    config = json.loads(observed.read_text())
    assert len(config) == 1 and config[0].get("x-app-tenant") == "keep-marker"
    assert dotenv_values(profile)["APPLICATION_KEEP_SETTING"] == "preserve-me"
    return profile, config[0], native


def assert_binding(packet, expected):
    headers, request = packet
    pair = (headers.get("projectid"), headers.get("logstreamid"))
    assert pair == ((PROJECT, STREAM) if expected else (None, None))
    spans = []
    for resource in request.resource_spans:
        attributes = {a.key: a.value.string_value for a in resource.resource.attributes}
        assert (attributes.get("splunk_ao.project.id"), attributes.get("splunk_ao.logstream.id")) == pair
        spans.extend(s for scope in resource.scope_spans for s in scope.spans)
    assert len(spans) == 4
    assert headers.get("x-app-tenant") == "keep-marker"


def same_pid_probe():
    gateway = Gateway(connected=False)
    process = None
    try:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            profile = directory / "runtime.env"
            profile.write_text(
                f"AGENT_RESOURCE_API_URL={gateway.origin}\nAGENT_PROJECT=original-project\nAGENT_STREAM=production\n"
                f"OTEL_EXPORTER_OTLP_ENDPOINT={gateway.origin}\n"
                "OTEL_EXPORTER_OTLP_TRACES_HEADERS=X-App-Tenant=keep-marker\n"
                "OTEL_EXPORTER_OTLP_TRACES_TIMEOUT=0.2\nOTEL_BSP_SCHEDULE_DELAY=100\n"
                "OTEL_METRIC_EXPORT_INTERVAL=100\nAGENT_INTERACTIVE=1\n"
                f"LOCAL_CAPTURE_FILE={directory / 'native.json'}\n"
            )
            environment = {k: v for k, v in os.environ.items() if not k.startswith(
                ("OTEL_", "SPLUNK_AO_", "GALILEO_", "AGENT_", "LOCAL_CAPTURE_FILE"))}
            stdout_path = directory / "stdout"
            with stdout_path.open("w") as stdout, (directory / "stderr").open("w") as stderr:
                process = subprocess.Popen(
                    [sys.executable, "launch.py", "--profile", str(profile)], cwd=ROOT,
                    env=environment, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, text=True,
                )
                turns = 0

                def turn():
                    nonlocal turns
                    assert process.poll() is None
                    turns += 1
                    process.stdin.write("turn\n")
                    process.stdin.flush()
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        if len(stdout_path.read_text().splitlines()) == turns:
                            assert json.loads(stdout_path.read_text().splitlines()[-1]) == {"answer": "Documentation for returns"}
                            return
                        assert process.poll() is None
                        time.sleep(0.02)
                    raise AssertionError("interactive business turn did not finish")

                def phase(expected):
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        start = len(gateway.traces)
                        turn()
                        wait_until = time.monotonic() + 0.5
                        while len(gateway.traces) == start and time.monotonic() < wait_until:
                            time.sleep(0.02)
                        if len(gateway.traces) > start:
                            packet = gateway.traces[-1]
                            if bool(packet[0].get("projectid")) == expected:
                                assert_binding(packet, expected)
                                return {"pid": process.pid, "binding": expected, "turns": turns}
                        time.sleep(0.1)
                    raise AssertionError("running launcher never activated the expected complete binding")

                states = [phase(False)]
                gateway.connected = True
                states.append(phase(True))
                gateway.connected = False
                states.append(phase(True))
                gateway.connected = True
                states.append(phase(True))
                assert process.poll() is None
                process.stdin.write("quit\n")
                process.stdin.flush()
                assert process.wait(timeout=15) == 0
            assert len({state["pid"] for state in states}) == 1
            assert not [path for method, path in gateway.requests if method == "POST" and path.startswith("/ao/api/")]
            assert gateway.metrics and gateway.logs
            native = json.loads((directory / "native.json").read_text())
            assert len(native["spans"]) == 4 * turns
            assert native["metrics"] == [{"name": "agent.turns", "values": [turns]}]
            assert len(native["logs"]) == turns
            return {"case": "names-only-same-pid", "pass": True, "states": states,
                    "zero_creates": True, "resource_calls": gateway.requests, "live_cloud_proof": False}
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        gateway.close()


def main():
    results = []
    for label, connected, existing, uncertain in (
        ("connected-existing", True, True, False),
        ("connected-create", True, False, False),
        ("lost-create-response", True, False, True),
        ("disconnected", False, True, False),
        ("reconnect", False, True, False),
        ("unavailable", False, True, False),
    ):
        gateway = Gateway(connected, existing, uncertain)
        stopped = label == "unavailable"
        try:
            if stopped:
                gateway.close()
            with tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                profile, headers, native = run(gateway, directory, seeded=existing)
                if connected:
                    assert headers.get("projectid") == PROJECT and headers.get("logstreamid") == STREAM
                    assert gateway.forwarded == 1 and gateway.bound
                    assert len(gateway.traces) == 1
                    assert_binding(gateway.traces[0], True)
                    spans = [s for _, p in gateway.traces for r in p.resource_spans for scope in r.scope_spans for s in scope.spans]
                    assert len(spans) == 4
                    assert f"projectid={PROJECT}" in dotenv_values(profile)["OTEL_EXPORTER_OTLP_TRACES_HEADERS"]
                    creates = [p for method, p in gateway.requests if method == "POST" and p.startswith("/ao/api/")]
                    assert len(creates) == (0 if existing else 2)
                else:
                    assert headers.get("projectid") == PROJECT and headers.get("logstreamid") == STREAM
                    assert f"projectid={PROJECT}" in dotenv_values(profile)["OTEL_EXPORTER_OTLP_TRACES_HEADERS"]
                    assert gateway.forwarded == 0
                    assert not [p for method, p in gateway.requests if method == "POST" and p.startswith("/ao/api/")]
                    if stopped:
                        assert not gateway.traces
                    else:
                        assert gateway.traces
                        assert_binding(gateway.traces[-1], True)
                if not stopped:
                    assert gateway.metrics and gateway.logs
                if label == "reconnect":
                    gateway.connected = True
                    gateway.bound = False
                    _, headers, _ = run(gateway, directory, reuse_profile=True)
                    assert headers.get("projectid") == PROJECT and gateway.forwarded == 1 and gateway.bound
                    assert not [p for method, p in gateway.requests if method == "POST" and p.startswith("/ao/api/")]
                results.append({"case": label, "pass": True, "native_spans": len(native["spans"]), "resource_calls": gateway.requests,
                                "local_receipt": not stopped, "synthetic_forwarded_batches": gateway.forwarded})
        finally:
            if not stopped:
                gateway.close()
    results.append(same_pid_probe())
    destination = ROOT / ".observe" / "connection-probe.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps({"status": "PASS", "cases": results, "live_cloud_proof": False}, indent=2))
    print(destination.read_text())


if __name__ == "__main__":
    main()
