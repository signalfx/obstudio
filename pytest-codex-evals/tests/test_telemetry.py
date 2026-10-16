from __future__ import annotations

import json
import dataclasses
import logging
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from pytest_codex_evals import runner
from pytest_codex_evals.definitions import GradeCheckResult, GradeResult, RubricEvalCase, TokenUsage
from pytest_codex_evals.telemetry import Run, configure_telemetry
from test_core import RecordingBackend, FailingJudgeBackend


def run_case(tmp_path, monkeypatch, backend=None, *, rubric=False, side="with_skill"):
    fixture = tmp_path / "fixture"
    fixture.mkdir(exist_ok=True)
    skill = tmp_path / "skills" / "sample-skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("name: sample-skill\n")
    case = RubricEvalCase(id="sample/service/rubric/direct", base_id="sample/service/rubric", prompt_id="direct", skill="sample-skill", language="sample", service="service", task="credential=secret-sentinel email=private@example.test", fixture_dir=fixture, rubric=["Must pass."])
    monkeypatch.setattr(runner, "grade_side", lambda **kw: GradeResult(checks=[GradeCheckResult(id="ok", description="ok", passed=True)]))
    return runner.run_case(repo_root=tmp_path, run_root=tmp_path / "artifacts", case=case, skill_dir=skill, backend=backend or RecordingBackend(), sides=(side,), rubric=rubric)


@pytest.fixture
def signals(monkeypatch):
    with monkeypatch.context() as local:
        local.setenv("OTEL_SDK_DISABLED", "false")
        for signal in ("TRACES", "METRICS", "LOGS"):
            local.setenv(f"OTEL_{signal}_EXPORTER", "otlp")
        spans = InMemorySpanExporter()
        tp = TracerProvider(shutdown_on_exit=False)
        tp.add_span_processor(SimpleSpanProcessor(spans))
        reader = InMemoryMetricReader()
        mp = MeterProvider(metric_readers=[reader], shutdown_on_exit=False)
        logs = InMemoryLogRecordExporter()
        lp = LoggerProvider(shutdown_on_exit=False)
        lp.add_log_record_processor(SimpleLogRecordProcessor(logs))
        telemetry = configure_telemetry(enabled=True, allowed_skills={"sample-skill"}, tracer_provider=tp, meter_provider=mp, logger_provider=lp)
        restore = telemetry.activate()
        yield telemetry, spans, reader, logs
        restore()
        telemetry.shutdown()
        # Supplied providers are caller-owned and remain usable until this cleanup.
        tp.shutdown()
        mp.shutdown()
        lp.shutdown()


def points(reader):
    data = reader.get_metrics_data()
    return {m.name: m for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics} if data else {}


@pytest.mark.parametrize("side", ["with_skill", "baseline"])
def test_eval_run_emits_only_administrative_tree_and_observed_usage(tmp_path, monkeypatch, signals, side):
    telemetry, exporter, reader, logs = signals
    result = run_case(tmp_path, monkeypatch, side=side)
    spans = exporter.get_finished_spans()
    assert sorted(s.name for s in spans) == ["skill.eval.agent", "skill.eval.run"]
    root = next(s for s in spans if s.name == "skill.eval.run")
    child = next(s for s in spans if s.name == "skill.eval.agent")
    assert child.parent.span_id == root.context.span_id
    assert root.attributes["eval.side"] == side
    assert not any(k.startswith("gen_ai.") for s in spans for k in s.attributes)
    metrics = points(reader)
    assert set(metrics) == {"obstudio.skill.eval.run.count", "obstudio.skill.eval.run.duration", "obstudio.skill.eval.run.tokens"}
    assert metrics["obstudio.skill.eval.run.count"].data.data_points[0].value == 1
    assert metrics["obstudio.skill.eval.run.duration"].unit == "s"
    assert all(p.sum > 0 for p in metrics["obstudio.skill.eval.run.duration"].data.data_points)
    tokens = metrics["obstudio.skill.eval.run.tokens"].data.data_points
    assert any(p.attributes["token.type"] == "provider_total_tokens" and p.sum == 1 for p in tokens)
    records = logs.get_finished_logs()
    assert len(records) == 1
    record = records[0].log_record
    assert record.body == "obstudio.skill.eval.run.completed"
    assert record.trace_id == root.context.trace_id and record.span_id == root.context.span_id
    assert record.attributes["usage.coverage"] == "measured"
    assert result.with_skill if side == "with_skill" else result.baseline
    assert "secret-sentinel" not in repr([(s.attributes, s.events) for s in spans]) + repr(records)
    assert "private@example.test" not in repr(records)
    assert telemetry.owners == []


@pytest.mark.parametrize("error,outcome", [(RuntimeError("secret-sentinel"), "error"), (subprocess.TimeoutExpired("secret-sentinel", 1), "timeout"), (KeyboardInterrupt(), "cancelled")])
def test_eval_failure_ends_each_span_once_and_preserves_exception(tmp_path, monkeypatch, signals, error, outcome):
    _, exporter, reader, logs = signals
    backend = RecordingBackend()
    def fail(**kwargs):
        raise error
    backend.run_agent = fail
    with pytest.raises(type(error)) as caught:
        run_case(tmp_path, monkeypatch, backend)
    assert caught.value is error
    spans = exporter.get_finished_spans()
    assert len(spans) == 2 and all(s.status.status_code == StatusCode.ERROR for s in spans)
    assert all(s.end_time for s in spans)
    assert logs.get_finished_logs()[0].log_record.attributes["outcome"] == outcome
    assert "secret-sentinel" not in repr([(s.attributes, s.events) for s in spans]) + repr(logs.get_finished_logs())
    assert "obstudio.skill.eval.run.tokens" not in points(reader)


def test_judge_usage_stays_separate_and_grade_failure_is_not_execution_failure(tmp_path, monkeypatch, signals):
    _, exporter, reader, logs = signals
    result = run_case(tmp_path, monkeypatch, FailingJudgeBackend(), rubric=True)
    assert result.with_skill.errors
    record = logs.get_finished_logs()[0].log_record
    assert record.attributes["execution.outcome"] == "success"
    assert record.attributes["grade.outcome"] == "failed"
    assert len(exporter.get_finished_spans()) == 2
    assert all(p.attributes["phase"] in {"agent", "judge"} for p in points(reader)["obstudio.skill.eval.run.tokens"].data.data_points)


def test_failed_rubric_verdict_is_a_grade_failure(tmp_path, monkeypatch, signals):
    _, _, reader, logs = signals
    backend = RecordingBackend()
    original = backend.run_judge
    def judge(**kwargs):
        result = original(**kwargs)
        verdict = json.loads(result.final_message_path.read_text())
        verdict["overall_pass"] = False
        result.final_message_path.write_text(json.dumps(verdict))
        return result
    backend.run_judge = judge
    result = run_case(tmp_path, monkeypatch, backend, rubric=True)
    assert not result.with_skill.errors
    record = logs.get_finished_logs()[0].log_record
    assert record.attributes["execution.outcome"] == "success"
    assert record.attributes["outcome"] == "grade_failed"
    assert record.attributes["grade.outcome"] == "failed"
    assert {p.attributes["phase"] for p in points(reader)["obstudio.skill.eval.run.tokens"].data.data_points} == {"agent", "judge"}


def test_unknown_usage_is_absent_and_observed_zero_is_measured(signals):
    telemetry, _, reader, _ = signals
    run = Run(telemetry, {"skill.name": "sample-skill"})
    run.usage(TokenUsage(), "agent")
    assert not points(reader)
    run.usage(TokenUsage(observed=True, input_tokens=0, output_tokens=0, provider_total_tokens=0), "agent")
    data = points(reader)["obstudio.skill.eval.run.tokens"].data.data_points
    assert data and all(p.sum == 0 and p.count == 1 for p in data)
    assert run.usage_coverage == "measured"


def test_telemetry_sink_failures_preserve_eval_and_later_runs(tmp_path, monkeypatch, signals):
    telemetry, _, _, _ = signals
    class BrokenSink:
        def fail(self, *args, **kwargs):
            raise RuntimeError("sink unavailable")
        start_as_current_span = add = record = handle = fail
    broken = BrokenSink()
    telemetry.tracer = telemetry.count = telemetry.duration = telemetry.tokens = telemetry.handler = broken
    for _ in range(2):
        result = run_case(tmp_path, monkeypatch)
        assert result.with_skill.exit_code == 0
    telemetry.handler = None


@pytest.mark.parametrize("mode", ["nonzero", "parse_error"])
def test_late_failures_preserve_exit_and_close_root(tmp_path, monkeypatch, signals, mode):
    _, exporter, reader, logs = signals
    backend = RecordingBackend()
    if mode == "nonzero":
        original = backend.run_agent
        backend.run_agent = lambda **kw: dataclasses.replace(original(**kw), returncode=7)
        result = run_case(tmp_path, monkeypatch, backend)
        assert result.with_skill.exit_code == 7
        assert logs.get_finished_logs()[0].log_record.attributes["grade.outcome"] == "passed"
    else:
        def fail(path):
            raise ValueError("secret-sentinel")
        backend.parse_trace = fail
        with pytest.raises(ValueError, match="secret-sentinel"):
            run_case(tmp_path, monkeypatch, backend)
    spans = exporter.get_finished_spans()
    assert len(spans) == 2 and all(s.end_time for s in spans)
    root = next(s for s in spans if s.name == "skill.eval.run")
    assert root.status.status_code == StatusCode.ERROR
    assert logs.get_finished_logs()[0].log_record.attributes["execution.outcome"] == "error"
    assert "secret-sentinel" not in repr([(s.attributes, s.events) for s in spans])
    assert points(reader)["obstudio.skill.eval.run.count"].data.data_points[0].attributes["outcome"] == "error"


def test_parent_profile_exports_all_signals_on_nondefault_port_and_drains(tmp_path, monkeypatch):
    received = []
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    with monkeypatch.context() as local:
        local.setenv("OTEL_SDK_DISABLED", "false")
        local.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", base)
        local.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
        local.setenv("OTEL_SERVICE_NAME", "operator-eval")
        local.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment.name=test,service.version=operator-version")
        local.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
        for signal in ("TRACES", "METRICS", "LOGS"):
            local.setenv(f"OTEL_{signal}_EXPORTER", "otlp")
            local.setenv(f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT", base + "/v1/" + signal.lower())
            local.setenv(f"OTEL_EXPORTER_OTLP_{signal}_PROTOCOL", "http/protobuf")
        telemetry = configure_telemetry(enabled=True, allowed_skills={"sample-skill"})
        assert len(telemetry.owners) == 3
        restore = telemetry.activate()
        try:
            run_case(tmp_path, monkeypatch)
        finally:
            restore()
            telemetry.shutdown()
            telemetry.shutdown()
            server.shutdown()
            server.server_close()
            thread.join()
    assert set(p for p, _ in received) == {"/v1/traces", "/v1/metrics", "/v1/logs"}
    resources = []
    spans, logs = [], []
    for path, wire in received:
        assert b"secret-sentinel" not in wire and b"private@example.test" not in wire
        if path == "/v1/traces":
            obj = ExportTraceServiceRequest.FromString(wire)
            for r in obj.resource_spans:
                resources.append(r.resource)
                spans.extend(s for scope in r.scope_spans for s in scope.spans)
        elif path == "/v1/logs":
            obj = ExportLogsServiceRequest.FromString(wire)
            for r in obj.resource_logs:
                resources.append(r.resource)
                logs.extend(s for scope in r.scope_logs for s in scope.log_records)
        else:
            obj = ExportMetricsServiceRequest.FromString(wire)
            resources.extend(r.resource for r in obj.resource_metrics)
    assert len(spans) == 2 and len(logs) == 1
    root = next(s for s in spans if s.name == "skill.eval.run")
    assert logs[0].trace_id == root.trace_id and logs[0].span_id == root.span_id
    for resource in resources:
        attrs = {a.key: a.value.string_value for a in resource.attributes}
        assert attrs["service.name"] == "operator-eval"
        assert attrs["deployment.environment.name"] == "test"
        assert attrs["service.version"] == "operator-version"


@pytest.mark.parametrize("exporter,endpoint,headers", [("none", "invalid", ""), ("console", "invalid", ""), ("otlp", "https://external.example/v1/logs", ""), ("otlp", "http://127.0.0.1:14318/v1/logs", "secret-sentinel")])
def test_log_ownership_fails_closed_without_touching_original_sinks(monkeypatch, exporter, endpoint, headers):
    with monkeypatch.context() as local:
        local.setenv("OTEL_SDK_DISABLED", "false")
        local.setenv("OTEL_LOGS_EXPORTER", exporter)
        local.setenv("OTEL_TRACES_EXPORTER", "none")
        local.setenv("OTEL_METRICS_EXPORTER", "none")
        local.setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", endpoint)
        local.setenv("OTEL_EXPORTER_OTLP_HEADERS", headers)
        before = list(logging.getLogger().handlers)
        telemetry = configure_telemetry(enabled=True)
        assert telemetry.handler is None
        assert logging.getLogger().handlers == before
        telemetry.shutdown()


def test_disabled_sdk_and_default_import_do_not_enable_telemetry(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert configure_telemetry(enabled=True).owners == []
    assert configure_telemetry().handler is None


@pytest.mark.parametrize("failure", [None, "RuntimeError", "TimeoutExpired", "KeyboardInterrupt"])
def test_real_pytest_launch_loads_profile_before_exporter_setup(tmp_path, failure):
    received = []
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    skill = tmp_path / "skills" / "sample-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("name: sample-skill\n")
    script = '''
import json
from pytest_codex_evals import runner
from pytest_codex_evals.backends import AgentResult
from pytest_codex_evals.definitions import RubricEvalCase, GradeResult
from pytest_codex_evals.trace import parse_trace

class Backend:
    name = "codex"
    def run_agent(self, *, exec_dir, **kwargs):
        trace = exec_dir / "trace.jsonl"
        final = exec_dir / "last_message.md"
        error = exec_dir / "stderr.txt"
        trace.write_text(json.dumps({"type":"turn.completed","usage":{"total_tokens":1}})+"\\n")
        final.write_text("done")
        error.write_text("")
        return AgentResult(0, trace, final, error)
    def parse_trace(self, path):
        return parse_trace(path)

def test_run(tmp_path, monkeypatch):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    skill = __import__("pathlib").Path.cwd() / "skills" / "sample-skill"
    case = RubricEvalCase(id="sample/service/rubric/direct",base_id="sample/service/rubric",prompt_id="direct",skill="sample-skill",language="sample",service="service",task="secret-sentinel",fixture_dir=fixture,rubric=["ok"])
    monkeypatch.setattr(runner, "grade_side", lambda **kw: GradeResult())
    result = runner.run_case(repo_root=skill.parent.parent,run_root=tmp_path/"results",case=case,skill_dir=skill,backend=Backend(),sides=("with_skill",),rubric=False)
    assert result.with_skill.exit_code == 0
'''
    if failure:
        expression = "__import__('subprocess').TimeoutExpired('synthetic',1)" if failure == "TimeoutExpired" else failure + "()"
        script = script.replace('        trace = exec_dir / "trace.jsonl"', '        raise ' + expression + '\n        trace = exec_dir / "trace.jsonl"')
    (tmp_path / "test_run.py").write_text(script)
    endpoint = f"http://127.0.0.1:{server.server_port}"
    profile = tmp_path / "telemetry.env"
    profile.write_text((Path(__file__).parents[1] / "telemetry.env.example").read_text().replace("http://127.0.0.1:4318", endpoint).replace("OTEL_SERVICE_NAME=obstudio-skill-evals", "OTEL_SERVICE_NAME=profile-eval"))
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("OTEL_EXPORTER_OTLP") or name in {"OTEL_SERVICE_NAME", "OTEL_RESOURCE_ATTRIBUTES", "OTEL_TRACES_EXPORTER", "OTEL_METRICS_EXPORTER", "OTEL_LOGS_EXPORTER"}:
            env.pop(name)
    env["OTEL_SDK_DISABLED"] = "false"
    env.pop("PYTEST_ADDOPTS", None)
    try:
        result = subprocess.run([shutil.which("uv"), "run", "--locked", "--project", str(Path(__file__).parents[1]), "--env-file", str(profile), "python", "-m", "pytest", "--codex-eval-telemetry", "--skill", str(skill), "test_run.py", "-q"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == (2 if failure == "KeyboardInterrupt" else 1 if failure else 0), result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert set(p for p, _ in received) == {"/v1/traces", "/v1/metrics", "/v1/logs"}
    spans = [s for path, data in received if path == "/v1/traces" for r in ExportTraceServiceRequest.FromString(data).resource_spans for scope in r.scope_spans for s in scope.spans]
    logs = [s for path, data in received if path == "/v1/logs" for r in ExportLogsServiceRequest.FromString(data).resource_logs for scope in r.scope_logs for s in scope.log_records]
    assert sorted(s.name for s in spans) == ["skill.eval.agent", "skill.eval.run"]
    assert len(logs) == 1
    assert all(b"secret-sentinel" not in data for _, data in received)
