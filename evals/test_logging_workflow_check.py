import copy
import json
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from logging_workflow_check import drain_output, local_url, source_hashes, stop_owned, validate_receipts
from run_logging_workflow import bind_model_metadata


def receipts():
    spans = [{"spanId": "parent", "traceId": "trace", "resource": {"serviceName": "driver"}}]
    requests, logs, native = [], [], []
    for slot in ("left", "right"):
        client, server, handler = (slot + name for name in ("-client", "-server", "-handler"))
        requests.append({"slot": slot, "trace_id": "trace", "client_span_id": client, "parent_span_id": "parent"})
        spans += [{"spanId": client, "parentSpanId": "parent", "traceId": "trace", "resource": {"serviceName": "driver"}},
                  {"spanId": server, "parentSpanId": client, "traceId": "trace", "kind": "SERVER", "resource": {"serviceName": "app"}},
                  {"spanId": handler, "parentSpanId": server, "traceId": "trace", "kind": "INTERNAL", "resource": {"serviceName": "app"}}]
        for kind in ("sync", "async"):
            body = f"workflow {kind} completed {slot}"
            logs.append({"body": body, "traceId": "trace", "spanId": handler, "severityNumber": 13, "resource": {"serviceName": "app"}})
            native.append(body)
    logs.append({"body": "workflow outside completed", "resource": {"serviceName": "app"}})
    native.append("workflow outside completed")
    return requests, logs, {"trace": {"spans": spans}}, "app", "\n".join(native)


def test_joins_exact_internal_handler_and_worker_to_its_real_request_tree():
    assert len(validate_receipts(*receipts())) == 4


@pytest.mark.parametrize("fault", ["wrong-request", "missing-span", "duplicate", "resource", "severity", "native-duplicate", "outside-leak"])
def test_rejects_consequential_correlation_and_sink_failures(fault):
    values = list(copy.deepcopy(receipts()))
    logs = values[1]
    if fault == "wrong-request":
        logs[1]["spanId"] = "right-handler"
    elif fault == "missing-span":
        logs[1]["spanId"] = "not-received"
    elif fault == "duplicate":
        logs.append(copy.deepcopy(logs[1]))
    elif fault == "resource":
        logs[1]["resource"]["serviceName"] = "other"
    elif fault == "severity":
        logs[1]["severityNumber"] = 8
    elif fault == "native-duplicate":
        values[4] += "\nworkflow async completed left"
    else:
        logs[-1]["traceId"], logs[-1]["spanId"] = "trace", "left-handler"
    with pytest.raises(AssertionError):
        validate_receipts(*values)


@pytest.mark.parametrize("value", ["https://127.0.0.1:4318", "http://example.com:4318", "http://user:secret@127.0.0.1:4318", "http://127.0.0.1:4318?token=secret"])
def test_rejects_remote_or_credential_urls(value):
    with pytest.raises(ValueError):
        local_url(value)


def test_source_binding_tracks_launch_and_code_but_not_generated_proof(tmp_path):
    (tmp_path / "app.py").write_text("print('app')\n")
    (tmp_path / ".env").write_text("PORT=8000\n")
    (tmp_path / ".observe").mkdir()
    before = source_hashes(tmp_path)
    (tmp_path / ".observe/result.json").write_text(json.dumps({"passed": True}))
    assert source_hashes(tmp_path) == before
    (tmp_path / ".env").write_text("PORT=9000\n")
    assert source_hashes(tmp_path) != before


def test_logging_tasks_are_direct_skill_invocations():
    definitions = list(Path(__file__).parent.glob("*/*/eval/qual/logging-*-contract.json"))
    assert len(definitions) == 12
    for path in definitions:
        data = json.loads(path.read_text())
        assert len(data["rubric"]) == 14
        assert len(data["prompts"]) == 3
        for prompt in data["prompts"]:
            assert prompt["task"] == "$" + data["skill"] + " ./service"
            assert prompt["eval_inputs"] == []


@pytest.mark.skipif(os.name != "posix", reason="The host workflow uses owned POSIX process groups")
def test_shutdown_waits_for_owned_child_after_foreground_parent_exits(tmp_path, monkeypatch):
    def blocked_inspection(*_args, **_kwargs):
        raise PermissionError("Process inspection is unavailable in the eval sandbox")
    monkeypatch.setattr(subprocess, "check_output", blocked_inspection)
    child = "import signal,time,pathlib; signal.signal(signal.SIGTERM,lambda *_:(time.sleep(.3),pathlib.Path('flushed').touch(),exit(0))); pathlib.Path('ready').touch(); time.sleep(30)"
    parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); time.sleep(30)"
    process = subprocess.Popen([sys.executable, "-c", parent, child], cwd=tmp_path,
                               stdout=subprocess.PIPE, text=True, start_new_session=True)
    drained = threading.Event()
    pump = threading.Thread(target=drain_output, args=(process, io.StringIO(), drained), daemon=True)
    pump.start()
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "ready").exists():
            assert time.monotonic() < deadline
            time.sleep(.01)
        assert stop_owned(process, timeout=5, drained=drained)
        pump.join(timeout=1)
        assert (tmp_path / "flushed").exists()
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        process.wait(timeout=5)


@pytest.mark.parametrize("effort,accepted", [("high", True), ("xhigh", False)])
def test_model_proof_uses_executed_session_metadata(tmp_path, effort, accepted):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(json.dumps({"type": "thread.started", "thread_id": "actual-thread"}) + "\n")
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    events = [{"type": "session_meta", "payload": {"id": "actual-thread", "cwd": str(tmp_path), "timestamp": "now"}},
              {"type": "turn_context", "payload": {"model": "gpt-6.1-sol", "effort": effort, "cwd": str(tmp_path)}}]
    (sessions / "rollout-actual-thread.jsonl").write_text("\n".join(json.dumps(event) for event in events))
    if accepted:
        assert bind_model_metadata(trace, tmp_path, tmp_path)["reasoning_effort"] == "high"
    else:
        with pytest.raises(AssertionError):
            bind_model_metadata(trace, tmp_path, tmp_path)


def test_failed_real_startup_retains_output_command_source_and_outcome(tmp_path):
    import socket
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {**os.environ, "PORT": str(port), "OTEL_SERVICE_NAME": "startup-negative",
                   "LOGGING_WORKFLOW_STUDIO_URL": "http://127.0.0.1:1",
                   "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://127.0.0.1:1/v1/traces"}
    command = [sys.executable, "-c", "print('real startup failed'); raise SystemExit(3)"]
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("logging_workflow_check.py")),
                             "--start-command-json", json.dumps(command)],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    proof = next((tmp_path / ".observe/logging-workflow-proof").glob("*/result.json"))
    receipt = json.loads(proof.read_text())
    assert receipt["status"] == "failed" and "exited during startup: 3" in receipt["error"]
    assert receipt["command"] == command and receipt["source_before"] == receipt["source_after"]
    assert (proof.parent / "native-output.log").read_text() == "real startup failed\n"
