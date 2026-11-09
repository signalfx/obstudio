"""Run a service's real launch command and verify its sync/async log-to-span path."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request


OUTSIDE = "workflow outside completed"
MARKERS = {slot: [f"workflow sync completed {slot}", f"workflow async completed {slot}"]
           for slot in ("left", "right")}
SKIP_DIRS = {".git", ".observe", ".venv", "node_modules", "target", "__pycache__", ".uv-cache", ".pip-cache"}
SOURCE_SUFFIXES = {".py", ".go", ".js", ".mjs", ".cjs", ".java", ".json", ".toml", ".xml", ".sh", ".env", ".lock", ".mod", ".sum", ".properties", ".yaml", ".yml"}


def source_hashes(root: Path) -> dict[str, str]:
    result = {}
    for directory, children, files in os.walk(root):
        children[:] = [name for name in children if name not in SKIP_DIRS]
        for name in files:
            path = Path(directory) / name
            if path.is_symlink() or not (path.suffix in SOURCE_SUFFIXES or name in {"Makefile", ".env"}):
                continue
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(result.items()))


def local_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("A credential-free loopback HTTP URL is required")
    return value.rstrip("/")


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.load(response)


def belongs_to(span: dict, ancestor_id: str, spans: dict[str, dict]) -> bool:
    visited = set()
    while span["spanId"] not in visited:
        if span["spanId"] == ancestor_id:
            return True
        visited.add(span["spanId"])
        span = spans.get(span.get("parentSpanId"))
        if span is None:
            return False
    return False


def validate_receipts(requests: list[dict], logs: list[dict], details: dict,
                      service_name: str, native_output: str) -> list[dict]:
    checks = []
    for request in requests:
        trace_id, client_id = request["trace_id"], request["client_span_id"]
        spans = {span["spanId"]: span for span in details[trace_id]["spans"]}
        client = spans[client_id]
        assert client["parentSpanId"] == request["parent_span_id"], "Client lost its real SDK parent"
        assert request["parent_span_id"] in spans, "Real SDK parent was not received"
        servers = [span for span in spans.values()
                   if span.get("kind", "").upper() == "SERVER"
                   and span.get("parentSpanId") == client_id
                   and span["resource"].get("serviceName") == service_name]
        assert len(servers) == 1, "Expected one real application server span per controlled request"
        server = servers[0]
        for marker in MARKERS[request["slot"]]:
            records = [record for record in logs if record.get("body") == marker
                       and record.get("traceId") == trace_id]
            assert len(records) == 1, f"Expected one received record for {marker}: {len(records)}"
            record = records[0]
            owner = spans.get(record.get("spanId"))
            assert owner is not None, f"No exact received SDK span for {marker}"
            assert belongs_to(owner, server["spanId"], spans), f"Wrong request context for {marker}"
            assert record["resource"].get("serviceName") == owner["resource"].get("serviceName") == service_name
            assert 13 <= record.get("severityNumber", 0) <= 16, f"Wrong WARN mapping for {marker}"
            assert native_output.count(marker) == 1, f"Original native sink lost or duplicated {marker}"
            checks.append({"body": marker, "trace_id": trace_id, "span_id": owner["spanId"],
                           "server_span_id": server["spanId"], "client_span_id": client_id,
                           "parent_span_id": request["parent_span_id"], "received_records": 1,
                           "native_records": 1})
    outside = [record for record in logs if record.get("body") == OUTSIDE
               and record["resource"].get("serviceName") == service_name]
    assert outside, "No fresh outside-span startup record"
    for record in outside:
        assert not record.get("traceId", "").strip("0") and not record.get("spanId", "").strip("0"), "Startup record retained request context"
    assert native_output.count(OUTSIDE) == len(outside), "Outside-span native/receiver counts disagree"
    return checks


def traced_requests(app_url: str, trace_endpoint: str) -> list[dict]:
    from opentelemetry import propagate, trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": "logging-workflow-driver"}))
    provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=trace_endpoint, timeout=2)))
    tracer = provider.get_tracer("logging-workflow-check")
    parent = tracer.start_span("logging-workflow-parent")
    parent_context = trace.set_span_in_context(parent)

    def request(slot: str) -> dict:
        with tracer.start_as_current_span("logging-workflow-request", context=parent_context,
                                         kind=trace.SpanKind.CLIENT) as child:
            headers = {}
            propagate.inject(headers)
            started = time.monotonic()
            with urllib.request.urlopen(urllib.request.Request(app_url + "/logging-workflow/" + slot,
                                                              headers=headers), timeout=8) as response:
                assert response.status == 200 and json.load(response) == {"status": "ok"}
            context = child.get_span_context()
            return {"slot": slot, "trace_id": format(context.trace_id, "032x"),
                    "client_span_id": format(context.span_id, "016x"),
                    "parent_span_id": format(parent.get_span_context().span_id, "016x"),
                    "seconds": time.monotonic() - started}

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = list(pool.map(request, MARKERS))
    finally:
        parent.end()
        provider.force_flush(timeout_millis=5000)
        provider.shutdown()
    return requests


def drain_output(process: subprocess.Popen, output, drained: threading.Event) -> None:
    try:
        for line in process.stdout:
            output.write(line)
            output.flush()
    finally:
        process.stdout.close()
        drained.set()


def stop_owned(process: subprocess.Popen, timeout: float = 10,
               drained: threading.Event | None = None) -> bool:
    if process.poll() is None:
        assert os.getpgid(process.pid) == process.pid
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        if process.poll() is None:
            raise
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # EOF also waits for foreground descendants that inherited the native
        # sink after the launcher exits. No global process inspection is needed.
        if process.poll() is not None and (drained is None or drained.is_set()):
            process.wait(timeout=5)
            return True
        time.sleep(.1)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        if process.poll() is None:
            raise
    process.wait(timeout=5)
    return False


def interrupt_owned_run(*_args) -> None:
    raise KeyboardInterrupt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-command-json", required=True)
    args = parser.parse_args()
    command = json.loads(args.start_command_json)
    if not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
        raise ValueError("The foreground start command must be a nonempty JSON string array")
    service = Path.cwd()
    port = int(os.environ["PORT"])
    studio = local_url(os.environ["LOGGING_WORKFLOW_STUDIO_URL"])
    trace_endpoint = local_url(os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"])
    app_url = f"http://127.0.0.1:{port}"
    output_root = service / ".observe/logging-workflow-proof"
    output_root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="run-", dir=output_root))
    started = dt.datetime.now(dt.timezone.utc)
    result = {"status": "running", "command": command, "cwd": str(service),
              "started": started.isoformat(), "studio": studio, "app_url": app_url,
              "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "source_before": source_hashes(service), "proof_directory": str(output),
              "scope": "Real app startup and two concurrent sync/async worker logs joined to SDK spans; REST does not expose all trace flag bits. Not production/cloud or arbitrary payload proof."}
    process = None
    drained = threading.Event()
    pump = None
    try:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError("Application port already occupied; no existing process was stopped")
        with (output / "native-output.log").open("w") as native:
            try:
                process = subprocess.Popen(command, cwd=service, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, start_new_session=True)
                pump = threading.Thread(target=drain_output, args=(process, native, drained), daemon=True)
                pump.start()
                result["pid"] = process.pid
                (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                deadline = time.monotonic() + 90
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"Foreground application exited during startup: {process.returncode}")
                    try:
                        assert get_json(app_url + "/health") == {"status": "ok"}
                        break
                    except (OSError, AssertionError):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Application startup exceeded90seconds")
                        time.sleep(.2)
                requests = traced_requests(app_url, trace_endpoint)
                (output / "requests.json").write_text(json.dumps(requests, indent=2) + "\n")
                time.sleep(1)
                result["graceful_stop"] = stop_owned(process, drained=drained)
                pump.join(timeout=1)
                result["application_exit_code"] = process.returncode
            finally:
                if process is not None and (process.poll() is None or not drained.is_set()):
                    result["cleanup_graceful"] = stop_owned(process, drained=drained)
                if pump is not None:
                    pump.join(timeout=1)
        assert result["graceful_stop"], "Owned application shutdown exceeded10seconds"
        deadline = time.monotonic() + 15
        while True:
            logs = get_json(studio + "/api/query/logs?limit=10000")
            selected = []
            for record in logs:
                if record.get("resource", {}).get("serviceName") != os.environ["OTEL_SERVICE_NAME"]:
                    continue
                timestamp = dt.datetime.fromisoformat(record["timeUnixNano"].replace("Z", "+00:00"))
                if timestamp >= started:
                    selected.append(record)
            details = {r["trace_id"]: get_json(studio + "/api/query/traces/" + r["trace_id"]) for r in requests}
            (output / "receiver-logs.json").write_text(json.dumps(selected, indent=2) + "\n")
            (output / "receiver-traces.json").write_text(json.dumps(details, indent=2) + "\n")
            try:
                result["joins"] = validate_receipts(requests, selected, details, os.environ["OTEL_SERVICE_NAME"],
                                                     (output / "native-output.log").read_text())
                break
            except (AssertionError, KeyError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.25)
        result["source_after"] = source_hashes(service)
        assert result["source_before"] == result["source_after"], "Runtime source changed during verification"
        result["status"] = "passed"
    except Exception as error:
        result["status"] = "failed"
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        try:
            if process is not None and (process.poll() is None or not drained.is_set()):
                result["cleanup_graceful"] = stop_owned(process, drained=drained)
        except Exception as error:
            result.update(status="failed", cleanup_error=type(error).__name__ + ": " + str(error))
        if pump is not None:
            pump.join(timeout=1)
        if result["status"] == "running":
            result["status"] = "cancelled"
        result["source_after"] = source_hashes(service)
        result["completed"] = dt.datetime.now(dt.timezone.utc).isoformat()
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "proof": str(output / "result.json"), "error": result.get("error")}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt_owned_run)
    raise SystemExit(main())
