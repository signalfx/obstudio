import copy
import hashlib
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

from logging_workflow_check import configured_service_name, drain_output, local_url, source_hashes, stop_owned, validate_receipts
from run_logging_workflow import bind_model_metadata


@pytest.fixture(scope="module")
def report_helper_and_sample():
    import importlib.util

    source = Path(__file__).resolve().parents[1] / "skills/references/tests/observe_report_fixtures.py"
    spec = importlib.util.spec_from_file_location("logging_inventory_report_fixtures", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MODULE, module.sample_report


def test_control_inventory_keeps_each_promised_item_and_field(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    report["findings"][0]["expected_telemetry"] = [
        {"type": "resource", "name": "Service identity", "attributes": ["service.name", "service.version"],
         "product_view": "Consistent filtering"},
        {"type": "log", "name": "request completed", "attributes": ["TraceId", "SpanId"],
         "product_view": "Exact operation correlation"},
    ]
    inventory = helper.audit_control_inventory(report)
    assert inventory["promise_count"] == 3
    assert inventory["attribute_count"] == 5
    assert [(row["finding_id"], row["telemetry_index"], row["name"], row["attributes"])
            for row in inventory["promises"][:2]] == [
        ("OTEL-001", 0, "Service identity", ["service.name", "service.version"]),
        ("OTEL-001", 1, "request completed", ["TraceId", "SpanId"]),
    ]


def test_control_inventory_does_not_merge_same_names_across_owners(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    for finding in report["findings"]:
        finding["expected_telemetry"][0].update(name="shared operation", attributes=["shared.field"])
    inventory = helper.audit_control_inventory(report)
    assert [(row["finding_id"], row["name"], row["attributes"])
            for row in inventory["promises"]] == [
        ("OTEL-001", "shared operation", ["shared.field"]),
        ("OTEL-002", "shared operation", ["shared.field"]),
    ]


def test_control_inventory_filters_in_canonical_order_without_approving_dependencies(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    assert helper.audit_control_inventory(sample(), ["OTEL-002", "OTEL-001"])["finding_ids"] == ["OTEL-001", "OTEL-002"]
    assert helper.audit_control_inventory(sample(), ["OTEL-002"])["finding_ids"] == ["OTEL-002"]


def test_control_inventory_rejects_unknown_ids(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    with pytest.raises(helper.ReportError, match="unknown finding IDs"):
        helper.audit_control_inventory(sample(), ["OTEL-999"])


def test_control_inventory_rejects_duplicate_and_empty_explicit_ids(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    for ids in ([], ["OTEL-001", "OTEL-001"]):
        with pytest.raises(helper.ReportError):
            helper.audit_control_inventory(sample(), ids)


def test_control_inventory_keeps_promises_without_attributes(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    report["findings"][0]["expected_telemetry"][0]["attributes"] = []
    inventory = helper.audit_control_inventory(report)
    assert inventory["promise_count"] == 2
    assert inventory["promises"][0]["attributes"] == []


def test_control_inventory_does_not_mutate_or_claim_coverage(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    before = copy.deepcopy(report)
    inventory = helper.audit_control_inventory(report)
    assert report == before
    assert inventory["audit_sha256"] == helper.audit_digest(helper.normalize_audit_report(report))
    assert inventory["inventory_scope"] == "audit_expected_telemetry"
    assert inventory["source_clause_controls_included"] is False
    assert inventory["acceptance_controls_included"] is False
    assert inventory["coverage_evaluated"] is False
    assert inventory["runtime_evaluated"] is False
    assert inventory["promises"][0]["candidate_scenario_ids"] == ["http.checkout.success"]


def test_control_inventory_surfaces_missing_acceptance_literals(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    report["findings"][0]["expected_telemetry"][0]["attributes"] = ["service.name", "service.version"]
    scenario = report["verification"]["scenarios"][0]
    scenario["acceptance_criteria"] = "Assert service.name equals the supplied identity."
    inventory = helper.audit_control_inventory(report, ["OTEL-001"])
    checks = {row["attribute"]: row for row in inventory["acceptance_literal_checks"]}
    assert checks["service.name"]["matching_scenario_ids"] == [scenario["id"]]
    assert checks["service.version"]["matching_scenario_ids"] == []
    assert [row["attribute"] for row in inventory["unmatched_attribute_literals"]] == ["service.version"]
    assert inventory["coverage_evaluated"] is False


def test_control_inventory_does_not_borrow_unbound_acceptance(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    report["findings"][0]["expected_telemetry"][0]["attributes"] = ["service.version"]
    report["verification"]["scenarios"][0]["acceptance_criteria"] = "Assert request completion."
    unrelated = copy.deepcopy(report["verification"]["scenarios"][0])
    unrelated.update(id="other.operation", acceptance_criteria="Assert service.version equals the supplied version.")
    report["verification"]["scenarios"].append(unrelated)
    inventory = helper.audit_control_inventory(report, ["OTEL-001"])
    assert inventory["acceptance_literal_checks"][0]["matching_scenario_ids"] == []
    assert inventory["unmatched_attribute_literals"][0]["attribute"] == "service.version"


def test_control_inventory_literal_hit_is_not_semantic_acceptance(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    report["findings"][0]["expected_telemetry"][0]["attributes"] = ["service.version"]
    scenario = report["verification"]["scenarios"][0]
    scenario["acceptance_criteria"] = "This scenario does not assert service.version."
    inventory = helper.audit_control_inventory(report, ["OTEL-001"])
    assert inventory["acceptance_literal_checks"][0]["matching_scenario_ids"] == [scenario["id"]]
    assert inventory["acceptance_literal_check_mode"] == "case_sensitive_substring_only"
    assert inventory["acceptance_controls_included"] is False
    assert inventory["coverage_evaluated"] is False
    assert inventory["runtime_evaluated"] is False


def test_control_inventory_literals_preserve_case_and_ignore_trigger_mentions(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    report["findings"][0]["expected_telemetry"][0]["attributes"] = ["Case.Field"]
    scenario = report["verification"]["scenarios"][0]
    scenario["trigger"] = "Send Case.Field in the input."
    scenario["acceptance_criteria"] = "Assert case.field is present."
    inventory = helper.audit_control_inventory(report, ["OTEL-001"])
    assert inventory["acceptance_literal_checks"][0]["matching_scenario_ids"] == []
    assert inventory["unmatched_attribute_literals"][0]["attribute"] == "Case.Field"


def test_control_inventory_cli_reads_audit_without_writing_reports(tmp_path, report_helper_and_sample):
    helper, sample = report_helper_and_sample
    audit = tmp_path / "otel-audit.json"
    audit.write_text(json.dumps(sample()))
    original = audit.read_bytes()
    command = [sys.executable, "-I", str(Path(helper.__file__)), "required-controls", str(audit)]
    success = subprocess.run(command + ["--ids", "OTEL-002"], capture_output=True, text=True)
    assert success.returncode == 0, success.stderr
    assert json.loads(success.stdout)["finding_ids"] == ["OTEL-002"]
    assert json.loads(success.stdout)["source_clause_controls_included"] is False
    assert json.loads(success.stdout)["acceptance_controls_included"] is False
    failure = subprocess.run(command + ["--ids", "OTEL-999"], capture_output=True, text=True)
    assert failure.returncode == 1
    assert not failure.stdout and "FAIL:" in failure.stderr
    assert audit.read_bytes() == original
    assert list(tmp_path.iterdir()) == [audit]


@pytest.mark.parametrize("configuration,expected", [
    ({"OTEL_SERVICE_NAME": "explicit-operator"}, "explicit-operator"),
    ({"OTEL_RESOURCE_ATTRIBUTES": "service.name=resource%20operator"}, "resource operator"),
    ({"OTEL_SERVICE_NAME": "explicit-operator", "OTEL_RESOURCE_ATTRIBUTES": "service.name=resource-operator"},
     "explicit-operator"),
    ({"OTEL_SERVICE_NAME": "", "OTEL_RESOURCE_ATTRIBUTES": "service.name=resource-operator"}, "resource-operator"),
    ({}, None),
])
def test_configured_identity_uses_sdk_decoding_and_precedence(monkeypatch, configuration, expected):
    for name in ("OTEL_SERVICE_NAME", "OTEL_RESOURCE_ATTRIBUTES"):
        monkeypatch.delenv(name, raising=False)
    for name, value in configuration.items():
        monkeypatch.setenv(name, value)
    if expected is None:
        with pytest.raises(ValueError, match="Configure expected service identity"):
            configured_service_name()
    else:
        assert configured_service_name() == expected


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


def test_live_receipts_are_saved_before_producer_exit_eviction(tmp_path, monkeypatch):
    """Model explorer lifetime, not SDK emission; real SDK proof is separate."""
    import datetime as dt
    import socket
    import logging_workflow_check as workflow

    requests, logs, details, name, native = receipts()
    for record in logs:
        record["timeUnixNano"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
    state = {"running": True, "live_queries": 0}
    native_ready = threading.Event()

    class NativeOutput(io.StringIO):
        def close(self):
            super().close()
            native_ready.set()

    class Process:
        pid = 999999
        returncode = None

        def __init__(self, *args, **kwargs):
            self.stdout = NativeOutput(native + "\n")

        def poll(self):
            return self.returncode

    def stop(process, *, drained=None, **kwargs):
        state["running"] = False
        process.returncode = -15
        return drained.wait(timeout=1)

    def query(url):
        if url.endswith("/health"):
            return {"status": "ok"}
        assert native_ready.wait(timeout=1)
        if state["running"]:
            state["live_queries"] += 1
            return logs if "/api/query/logs" in url else details["trace"]
        return [] if "/api/query/logs" in url else {"spans": details["trace"]["spans"][:1]}

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.chdir(tmp_path)
    for key, value in {"PORT": str(port), "OTEL_SERVICE_NAME": name,
                       "LOGGING_WORKFLOW_STUDIO_URL": "http://127.0.0.1:1",
                       "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://127.0.0.1:1/v1/traces"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["checker", "--start-command-json", '["fixture","dev"]'])
    monkeypatch.setattr(workflow.subprocess, "Popen", Process)
    monkeypatch.setattr(workflow, "stop_owned", stop)
    monkeypatch.setattr(workflow, "traced_requests", lambda *_: requests)
    monkeypatch.setattr(workflow, "get_json", query)
    clock = iter(range(1000))
    monkeypatch.setattr(workflow.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(workflow.time, "sleep", lambda _: None)
    assert workflow.main() == 0
    proof = next((tmp_path / ".observe/logging-workflow-proof").glob("*/result.json"))
    result = json.loads(proof.read_text())
    assert state["live_queries"] and not state["running"]
    assert result["status"] == "passed" and len(result["joins"]) == 4
    assert (proof.parent / "receiver-logs.json").is_file()
    assert (proof.parent / "receiver-traces.json").is_file()


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


def test_logging_tasks_are_direct_skill_invocations_with_visible_operator_policy(tmp_path):
    from pytest_codex_evals.runner import prepare_side_workspace
    from run_logging_workflow import case_for

    definitions = list(Path(__file__).parent.glob("*/*/eval/qual/logging-*-contract.json"))
    assert len(definitions) == 12
    for path in definitions:
        data = json.loads(path.read_text())
        assert len(data["rubric"]) == 14
        assert len(data["prompts"]) == 3
        for prompt in data["prompts"]:
            assert prompt["task"] == "$" + data["skill"] + " ./service"
            assert prompt["eval_inputs"] == []

    root = Path(__file__).resolve().parents[1]
    for role in ("audit", "instrument", "verify"):
        case = case_for(root, "python", role, 1)
        workspace = tmp_path / role
        prepare_side_workspace(root, case, "with_skill", workspace)
        readme = workspace / "service/README.md"
        assert readme.read_bytes() == (case.fixture_dir / "README.md").read_bytes()
        assert "must not interrupt that work" in readme.read_text()
        assert "application policy, not an OpenTelemetry signal-handler" in readme.read_text()
        definition = json.loads((case.fixture_dir / f"eval/qual/logging-{role}-contract.json").read_text())
        lifecycle = definition["rubric"][9]
        assert "documented Graceful-stop contract in README.md" in lifecycle
        assert "not an OTel signal-handler requirement" in lifecycle
        assert "repeated-SystemExit" not in lifecycle
        assert not (workspace / "service/eval").exists()


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


def test_source_settings_preserves_names_and_multiple_source_readers(tmp_path, report_helper_and_sample):
    helper, _ = report_helper_and_sample
    first, second = tmp_path / "first.py", tmp_path / "second.go"
    first.write_text('name = "OTEL_TEST_SHARED"\n')
    second.write_text('// OTEL_TEST_SHARED documents a candidate, not a consumption fact.\n')
    before = {p: p.read_bytes() for p in (first, second)}
    result = helper.source_settings_inventory([first, second])
    assert [c["name"] for c in result["candidates"]] == ["OTEL_TEST_SHARED"]
    assert len(result["candidates"][0]["source_locations"]) == 2
    assert result["candidates"][0]["report_spelling_matches"] is None
    assert result["report_comparison_performed"] is False
    assert result["owners_resolved"] is result["consumption_evaluated"] is False
    assert {p: p.read_bytes() for p in (first, second)} == before


def test_source_settings_empty_app_scan_retains_actual_scope(tmp_path, report_helper_and_sample):
    helper, _ = report_helper_and_sample
    app = tmp_path / "app.py"
    app.write_text('print("uninstrumented application")\n')
    result = helper.source_settings_inventory([app])
    assert result["source_roots"] == [str(app)]
    assert result["scanned_text_files"] == 1
    assert result["candidates"] == result["matching_sources"] == []
    assert result["complete_configuration_inventory"] is False
    assert result["consumption_evaluated"] is False


def test_source_settings_omission_hint_does_not_match_a_longer_key(tmp_path, report_helper_and_sample):
    helper, _ = report_helper_and_sample
    source, report = tmp_path / "config.py", tmp_path / "report.md"
    source.write_text('"OTEL_TEST_TIMEOUT"\n"OTEL_TEST_TIMEOUT_EXTRA"\n')
    report.write_text('OTEL_TEST_TIMEOUT_EXTRA is not asserted.\n')
    result = helper.source_settings_inventory([source], report)
    assert result["unmentioned_names"] == ["OTEL_TEST_TIMEOUT"]
    assert result["candidates"][1]["report_spelling_matches"] == ["OTEL_TEST_TIMEOUT_EXTRA"]
    assert result["coverage_evaluated"] is result["runtime_evaluated"] is False


def test_source_settings_normalization_is_a_hint_not_a_verified_alias(tmp_path, report_helper_and_sample):
    helper, _ = report_helper_and_sample
    source, report = tmp_path / "config.java", tmp_path / "report.json"
    source.write_text('"otel.test.default-enabled"; "OTEL_TEST_DEFAULT_ENABLED";\n')
    report.write_text('{"note":"OTEL_TEST_DEFAULT_ENABLED is not tested"}')
    result = helper.source_settings_inventory([source], report)
    assert len(result["candidates"]) == 2
    assert {c["normalization_hint"] for c in result["candidates"]} == {"OTEL_TEST_DEFAULT_ENABLED"}
    assert result["normalization_mapping_verified"] is False
    assert result["complete_configuration_inventory"] is False
    assert result["dynamic_names_resolved"] is False


def test_source_settings_records_binary_skips_and_rejects_invalid_inputs(tmp_path, report_helper_and_sample):
    helper, _ = report_helper_and_sample
    binary = tmp_path / "sdk.bin"
    binary.write_bytes(b"\xffOTEL_TEST_BINARY")
    result = helper.source_settings_inventory([binary])
    assert result["scanned_text_files"] == 0 and result["candidates"] == []
    assert result["skipped_paths"][0]["reason"] == "non_utf8_not_scanned"
    assert result["complete_configuration_inventory"] is False
    with pytest.raises(helper.ReportError, match="source path does not exist"):
        helper.source_settings_inventory([tmp_path / "missing"])
    with pytest.raises(helper.ReportError, match="report must be UTF-8"):
        helper.source_settings_inventory([binary], binary)


def test_source_settings_does_not_follow_directory_or_file_symlinks(tmp_path, report_helper_and_sample):
    helper, _ = report_helper_and_sample
    source, outside = tmp_path / "selected", tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    (source / "config.js").write_text('"OTEL_TEST_SELECTED";\n')
    (outside / "config.js").write_text('"OTEL_TEST_UNSELECTED";\n')
    try:
        (source / "linked-dir").symlink_to(outside, target_is_directory=True)
        (source / "linked-file.js").symlink_to(outside / "config.js")
    except OSError:
        pytest.skip("Host cannot create test symlinks")
    result = helper.source_settings_inventory([source])
    assert [c["name"] for c in result["candidates"]] == ["OTEL_TEST_SELECTED"]
    assert len([p for p in result["skipped_paths"] if p["reason"] == "symlink_not_followed"]) == 2


def test_source_settings_deduplicates_paths_keeps_lines_and_excludes_report(tmp_path, report_helper_and_sample):
    helper, _ = report_helper_and_sample
    source, report = tmp_path / "config.py", tmp_path / "report.md"
    source.write_text('"OTEL_TEST_SOURCE"\n# not a value\n"OTEL_TEST_SOURCE"\n')
    report.write_text('"OTEL_TEST_REPORT_ONLY"\n')
    result = helper.source_settings_inventory([tmp_path, source], report)
    assert result["scanned_text_files"] == 1 and len(result["matching_sources"]) == 1
    assert result["matching_sources"][0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["candidates"][0]["source_locations"] == [{"source_id": 0, "lines": [1, 3]}]
    assert result["unmentioned_names"] == ["OTEL_TEST_SOURCE"]
    assert result["skipped_paths"][0]["reason"] == "report_input_excluded"


def test_source_settings_cli_omits_unrelated_content_and_writes_no_input(tmp_path, report_helper_and_sample):
    helper, _ = report_helper_and_sample
    source, report = tmp_path / "config.py", tmp_path / "report.md"
    source.write_text('key = "OTEL_TEST_SECRET"; value = "sensitive-fixture-value"\n')
    report.write_text('No accepted configuration assertions.\n')
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    command = [sys.executable, "-I", str(Path(helper.__file__)), "source-settings", "--source", str(source), "--report", str(report)]
    success = subprocess.run(command, capture_output=True, text=True)
    assert success.returncode == 0, success.stderr
    assert json.loads(success.stdout)["unmentioned_names"] == ["OTEL_TEST_SECRET"]
    assert "sensitive-fixture-value" not in success.stdout
    failure = subprocess.run(command + ["--source", str(tmp_path / "missing")], capture_output=True, text=True)
    assert failure.returncode == 1 and "FAIL:" in failure.stderr and not failure.stdout
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before
