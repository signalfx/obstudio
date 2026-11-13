import copy
import datetime as dt
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
import logging_workflow_check as workflow

from logging_workflow_check import configured_service_name, drain_output, local_url, source_hashes, stop_owned, validate_receipts
from run_logging_workflow import bind_model_metadata


@pytest.fixture(scope="module")
def report_fixture_module():
    import importlib.util

    source = Path(__file__).resolve().parents[1] / "skills/references/tests/observe_report_fixtures.py"
    spec = importlib.util.spec_from_file_location("logging_inventory_report_fixtures", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report_helper_and_sample(report_fixture_module):
    return report_fixture_module.MODULE, report_fixture_module.sample_report


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
    assert inventory == helper.audit_control_inventory(report, view="telemetry")
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


def test_control_inventory_surfaces_stale_text_ids_without_selecting_other_findings(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    index = len(report["evidence"])
    report["evidence"].append({"check": "Text mapping", "finding": "OTEL-001, OTEL-002, OTEL-999 and OTEL-999",
                               "source": "existing source"})
    before = copy.deepcopy(report)
    inventory = helper.audit_control_inventory(report, ["OTEL-001"])
    assert inventory["finding_ids"] == ["OTEL-001"]
    assert inventory["unknown_finding_id_literals"] == [
        {"finding_id": "OTEL-999", "source_literal": "OTEL-999", "report_path": f"/evidence/{index}/finding"}]
    assert inventory["finding_id_literal_scope"] == "entire_canonical_report"
    assert inventory["finding_references_evaluated"] is False
    assert inventory["coverage_evaluated"] is False
    assert report == before


def test_control_inventory_literal_ids_do_not_match_a_known_numeric_prefix(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    report["evidence"].append({"check": "Numeric token hints", "finding": "OTEL-0010 XOTEL-999 otel-998 OTEL-997_suffix",
                               "source": "existing source"})
    inventory = helper.audit_control_inventory(report)
    assert [r["finding_id"] for r in inventory["unknown_finding_id_literals"]] == ["OTEL-0010"]
    assert inventory["finding_id_literal_check_mode"] == "OTEL_numeric_tokens_and_slash_shorthand_only"
    assert inventory["finding_references_evaluated"] is False


def test_control_inventory_retains_slash_shorthand_for_stale_id_hint(report_helper_and_sample):
    helper, sample = report_helper_and_sample
    report = sample()
    index = len(report["evidence"])
    report["evidence"].append({"check": "Renumbered text mapping", "finding": "Mapping: OTEL-001/004 -> owned.operation",
                               "source": "existing source"})
    inventory = helper.audit_control_inventory(report)
    assert inventory["unknown_finding_id_literals"] == [
        {"finding_id": "OTEL-004", "source_literal": "OTEL-001/004", "report_path": f"/evidence/{index}/finding"}]
    assert inventory["finding_references_evaluated"] is False


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


def test_control_contracts_complete_contract_preserves_distinct_promises_and_boundaries(report_fixture_module):
    factories = report_fixture_module
    helper = factories.MODULE
    report = factories.sample_report()
    finding = report["findings"][1]
    finding["required_fix"] = "Preserve the selected input and emit a bounded safe diagnostic."
    finding["acceptance_criteria"] = ["Check activation.", "Check diagnostic output separately."]
    finding["constraints"] = ["Keep original writer ownership and Unicode: λ."]
    scenario = report["verification"]["scenarios"][0]
    scenario.update(trigger="Use the actual initializer; inspect native output.",
                    acceptance_criteria="Assert enabled outcome. Diagnostic oracle still missing.",
                    proof_level="focused call-site")
    original = copy.deepcopy(report)
    normalized = helper.normalize_audit_report(report)
    view = helper.audit_control_inventory(report, ["OTEL-002"], view="contracts")
    assert report == original
    assert [row["finding"] for row in view["findings"]] == normalized["findings"]
    assert [row["scenario"] for row in view["scenarios"]] == normalized["verification"]["scenarios"]
    assert [row["environment"] for row in view["environments"]] == normalized["verification"]["environments"]
    assert view["finding_ids"] == ["OTEL-002"]
    assert view["prerequisite_context_ids"] == ["OTEL-001"]
    assert view["scenarios"][0]["declared_by_included_finding_ids"] == ["OTEL-001", "OTEL-002"]
    assert view["scenarios"][0]["source_pointer"] == "/verification/scenarios/0"
    assert view["audit_sha256"] == helper.audit_digest(normalized)
    for key in ("selection_evaluated", "finding_references_evaluated", "source_clause_completeness_evaluated", "coverage_evaluated", "runtime_evaluated"):
        assert view[key] is False
    assert "overall_pass" not in view and "missing_assertions" not in view


@pytest.mark.parametrize("state", ["done", "deferred", "manual decision", "external follow-up"])
def test_control_contracts_prerequisite_context_does_not_approve_or_skip_nonexecutables(state, report_fixture_module):
    factories = report_fixture_module
    helper = factories.MODULE
    report = factories.sample_report()
    dependency = report["findings"][0]
    if state == "manual decision":
        factories.make_manual_decision(dependency)
    elif state == "external follow-up":
        factories.make_external_follow_up(dependency)
    else:
        dependency["status"] = state
    normalized = helper.normalize_audit_report(report)
    view = helper.audit_control_inventory(report, ["OTEL-002"], view="contracts")
    assert view["finding_ids"] == ["OTEL-002"]
    assert view["prerequisite_context_ids"] == ["OTEL-001"]
    assert view["findings"][0]["finding"] == normalized["findings"][0]
    assert view["selection_evaluated"] is False


def test_control_contracts_unique_shared_records_follow_canonical_order(report_fixture_module):
    factories = report_fixture_module
    helper = factories.MODULE
    report = factories.sample_report()
    view = helper.audit_control_inventory(report, ["OTEL-002", "OTEL-001"], view="contracts")
    assert view["finding_ids"] == ["OTEL-001", "OTEL-002"]
    assert view["prerequisite_context_ids"] == []
    assert len(view["scenarios"]) == len(view["environments"]) == 1
    assert [row["source_pointer"] for row in view["findings"]] == ["/findings/0", "/findings/1"]


def test_control_contracts_transitive_context_and_unbound_records_are_kept_distinct(report_fixture_module):
    factories = report_fixture_module
    helper = factories.MODULE
    report = factories.sample_splunk_agent_observability_report()
    report["findings"][2]["dependencies"] = ["OTEL-002"]
    environment = copy.deepcopy(report["verification"]["environments"][0])
    environment["id"] = "unused.environment"
    report["verification"]["environments"].append(environment)
    scenario = copy.deepcopy(report["verification"]["scenarios"][0])
    scenario.update(id="unused.scenario", environments=[environment["id"]])
    report["verification"]["scenarios"].append(scenario)
    view = helper.audit_control_inventory(report, ["AO-002"], view="contracts")
    assert view["finding_ids"] == ["AO-002"]
    assert view["prerequisite_context_ids"] == ["OTEL-001", "OTEL-002", "AO-001"]
    assert [row["finding"]["id"] for row in view["findings"]] == ["OTEL-001", "OTEL-002", "AO-001", "AO-002"]
    assert all(row["scenario"]["id"] != "unused.scenario" for row in view["scenarios"])
    assert all(row["environment"]["id"] != "unused.environment" for row in view["environments"])


def test_control_contracts_shared_evidence_retains_promises_outside_finding_fields(report_fixture_module):
    factories = report_fixture_module
    helper = factories.MODULE
    report = factories.sample_report()
    report["evidence"].append({"check": "Selected invalid input",
                               "finding": "Invalid input leaves telemetry enabled and produces a bounded safe diagnostic.",
                               "source": "actual reader and diagnostic call site"})
    scenario = report["verification"]["scenarios"][0]
    scenario.update(trigger="Use the Audit Evidence invalid-input contract.",
                    acceptance_criteria="Assert telemetry is enabled.")
    normalized = helper.normalize_audit_report(report)
    view = helper.audit_control_inventory(report, ["OTEL-002"], view="contracts")
    assert view["shared_evidence_context"]["evidence"] == normalized["evidence"]
    assert view["shared_evidence_context"]["source_pointer"] == "/evidence"
    assert view["shared_evidence_context"]["finding_ownership_inferred"] is False
    assert view["scenarios"][0]["scenario"]["acceptance_criteria"] == "Assert telemetry is enabled."
    assert "recommendation" in view["unprojected_report_fields"]
    assert view["coverage_evaluated"] is False


def test_control_contracts_invalid_view_or_roots_remain_errors(report_fixture_module):
    factories = report_fixture_module
    helper = factories.MODULE
    for ids in ([], ["OTEL-999"], ["OTEL-001", "OTEL-001"]):
        with pytest.raises(helper.ReportError):
            helper.audit_control_inventory(factories.sample_report(), ids, view="contracts")
    with pytest.raises(helper.ReportError):
        helper.audit_control_inventory(factories.sample_report(), view="approval")


def test_control_contracts_cli_is_stdout_only_and_legacy_default_is_unchanged(tmp_path, report_fixture_module):
    factories = report_fixture_module
    helper = factories.MODULE
    path = tmp_path / "otel-audit.json"
    path.write_text(json.dumps(factories.sample_report()))
    original = path.read_bytes()
    command = [sys.executable, "-I", str(Path(helper.__file__)), "required-controls", str(path), "--ids", "OTEL-002"]
    contracts = subprocess.run(command + ["--view", "contracts"], capture_output=True, text=True)
    assert contracts.returncode == 0, contracts.stderr
    assert json.loads(contracts.stdout)["prerequisite_context_ids"] == ["OTEL-001"]
    default = subprocess.run(command, capture_output=True, text=True)
    assert default.returncode == 0, default.stderr
    assert json.loads(default.stdout) == factories.MODULE.audit_control_inventory(factories.sample_report(), ["OTEL-002"])
    invalid = subprocess.run(command + ["--view", "approval"], capture_output=True, text=True)
    assert invalid.returncode != 0 and not invalid.stdout
    assert path.read_bytes() == original and list(tmp_path.iterdir()) == [path]



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


def identity_receipts(name="app", *, version="operator-v1", retained="kept"):
    attributes = {"service.name": name, "service.version": version, "obstudio.eval.preserved": retained}
    resource = {"serviceName": name, "attributes": attributes}
    spans = [{"spanId": "parent", "traceId": "trace", "resource": {"serviceName": "driver"}}]
    requests, logs, native = [], [], []
    for slot in ("left", "right"):
        client, server, handler = (slot + suffix for suffix in ("-client", "-server", "-handler"))
        requests.append({"slot": slot, "trace_id": "trace", "client_span_id": client, "parent_span_id": "parent"})
        spans += [{"spanId": client, "parentSpanId": "parent", "traceId": "trace", "resource": {"serviceName": "driver"}},
                  {"spanId": server, "parentSpanId": client, "traceId": "trace", "kind": "SERVER", "resource": copy.deepcopy(resource)},
                  {"spanId": handler, "parentSpanId": server, "traceId": "trace", "kind": "INTERNAL", "resource": copy.deepcopy(resource)}]
        for kind in ("sync", "async"):
            body = f"workflow {kind} completed {slot}"
            logs.append({"body": body, "traceId": "trace", "spanId": handler, "severityNumber": 13, "resource": copy.deepcopy(resource)})
            native.append(body)
    logs.append({"body": "workflow outside completed", "resource": copy.deepcopy(resource)})
    native.append("workflow outside completed")
    return requests, logs, {"trace": {"spans": spans}}, name, "\n".join(native)


def test_host_profile_inputs_and_expected_values_are_explicit_independent_copies(monkeypatch):
    monkeypatch.setattr(workflow.secrets, "token_hex", lambda _: "unique")
    base = {"OTEL_SERVICE_NAME": "old-name", "OTEL_RESOURCE_ATTRIBUTES": "old.input=value",
            "PORT": "1234", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:555/v1/logs"}
    before = dict(base)
    profiles = workflow.identity_profiles(base)
    assert base == before
    assert [p[0] for p in profiles] == ["resource-only", "explicit-override", "resource-whitespace"]
    _, resource_child, resource_expected = profiles[0]
    assert "OTEL_SERVICE_NAME" not in resource_child
    assert resource_expected == {"service.name": "operator-resource-resource-only-unique",
                                 "service.version": "operator-version-unique", "obstudio.eval.preserved": "kept-unique"}
    _, explicit_child, explicit_expected = profiles[1]
    assert explicit_child["OTEL_SERVICE_NAME"] == explicit_expected["service.name"] == "operator-explicit-unique"
    assert "service.name=operator-resource-explicit-override-unique" in explicit_child["OTEL_RESOURCE_ATTRIBUTES"]
    assert explicit_expected["service.name"] not in explicit_child["OTEL_RESOURCE_ATTRIBUTES"]
    for _, child, _ in profiles:
        assert child["PORT"] == "1234"
        assert child["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"] == base["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"]
    resource_expected["service.name"] = "changed"
    assert resource_child["OTEL_RESOURCE_ATTRIBUTES"].startswith("service.name=operator-resource-resource-only-unique,")
    assert explicit_expected["service.name"] == "operator-explicit-unique"


def test_profile_names_are_fresh_between_invocations():
    first, second = workflow.identity_profiles({}), workflow.identity_profiles({})
    assert first[0][2]["service.name"] != second[0][2]["service.name"]
    assert first[1][2]["service.name"] != second[1][2]["service.name"]


def test_actual_rest_shape_preserves_operator_attributes_and_existing_joins():
    data = identity_receipts()
    expected = {"service.name": "app", "service.version": "operator-v1", "obstudio.eval.preserved": "kept"}
    assert len(workflow.validate_receipts(*data, expected_resource=expected)) == 4
    # Existing unflagged compatibility does not manufacture new requirements.
    old_shape = list(copy.deepcopy(data))
    for span in old_shape[2]["trace"]["spans"]:
        span["resource"].pop("attributes", None)
    for record in old_shape[1]:
        record["resource"].pop("attributes", None)
    assert len(workflow.validate_receipts(*old_shape)) == 4


@pytest.mark.parametrize("target,key", [
    ("record", "service.version"), ("record", "obstudio.eval.preserved"),
    ("server", "service.version"), ("server", "obstudio.eval.preserved"),
    ("owner", "service.version"), ("owner", "obstudio.eval.preserved"),
    ("startup", "service.version"), ("startup", "obstudio.eval.preserved"),
    ("record", "service.name"), ("server", "service.name"),
    ("owner", "service.name"), ("startup", "service.name"),
])
def test_lost_supplied_attribute_rejects_each_selected_owner(target, key):
    data = list(identity_receipts())
    expected = {"service.name": "app", "service.version": "operator-v1", "obstudio.eval.preserved": "kept"}
    if target == "record": resource = data[1][0]["resource"]
    elif target == "startup": resource = data[1][-1]["resource"]
    else:
        suffix = "-server" if target == "server" else "-handler"
        resource = next(s["resource"] for s in data[2]["trace"]["spans"] if s["spanId"] == "left" + suffix)
    resource["attributes"].pop(key)
    with pytest.raises(AssertionError, match="Resource attribute lost/changed"):
        workflow.validate_receipts(*data, expected_resource=expected)


@pytest.mark.parametrize("actual", ["hardcoded-service", "lower-priority-resource"])
def test_wrong_effective_identity_rejects_hardcoded_or_reversed_precedence(actual):
    data = list(identity_receipts(actual))
    expected = {"service.name": "operator-winner", "service.version": "operator-v1", "obstudio.eval.preserved": "kept"}
    with pytest.raises(AssertionError, match="application server span"):
        workflow.validate_receipts(*data[:3], expected["service.name"], data[4], expected_resource=expected)


def mock_identity_run(monkeypatch, tmp_path, *, profiles, mutant=None, bake=False):
    """Drive actual checker role loop; substitute only process, wire and clock seams."""
    environment = {"PORT": "3333", "OTEL_SERVICE_NAME": "baseline", "OTEL_RESOURCE_ATTRIBUTES": "deployment.environment.name=eval",
                   "LOGGING_WORKFLOW_STUDIO_URL": "http://127.0.0.1:5555", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://127.0.0.1:5556/v1/traces"}
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("# no application is executed\n")
    for key in ("PORT", "OTEL_SERVICE_NAME", "OTEL_RESOURCE_ATTRIBUTES", "LOGGING_WORKFLOW_STUDIO_URL", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        monkeypatch.setenv(key, environment[key])
    ambient = dict(os.environ)
    state = {"launches": [], "current": None}
    monkeypatch.setattr(workflow, "configured_service_name", lambda: "baseline")
    monkeypatch.setattr(workflow.secrets, "token_hex", lambda _: "fixture-nonce")
    clock = iter(range(10000))
    monkeypatch.setattr(workflow.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(workflow.time, "sleep", lambda _: None)

    class Probe:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def connect_ex(self, _): return 1
    monkeypatch.setattr(workflow.socket, "socket", lambda *_: Probe())
    monkeypatch.setattr(workflow.urllib.request, "urlopen", lambda *_a, **_kw: pytest.fail("No network permitted in mock prototype"))

    class Process:
        pid = 987654
        returncode = None
        def __init__(self, command, **kwargs):
            assert command == ["make", "dev"]
            assert kwargs["cwd"] == tmp_path and kwargs["start_new_session"] is True
            child = dict(kwargs["env"])
            state["launches"].append(child)
            # Fixture-only source-supported model of the three plain key/value pairs.
            # This does not execute an SDK or establish parser conformance.
            raw = child["OTEL_RESOURCE_ATTRIBUTES"]
            if mutant == "whitespace-broken-fallback" and len(state["launches"]) == 4:
                # A generated startup substring fallback misses the supported spaces.
                if "service.name=" not in raw:
                    raw += ",service.name=broken-launch-default"
            attrs = {key.strip(): value.strip() for piece in raw.split(",")
                     for key, value in [piece.split("=", 1)]}
            name = child.get("OTEL_SERVICE_NAME") or attrs.get("service.name")
            data = list(identity_receipts(name, version=attrs.get("service.version", "baseline-v"), retained=attrs.get("obstudio.eval.preserved", "baseline-kept")))
            if mutant and len(state["launches"]) == 2:
                if mutant == "hardcoded":
                    data = list(identity_receipts("hardcoded"))
                elif mutant == "lost-version":
                    data[1][0]["resource"]["attributes"].pop("service.version")
                elif mutant == "lost-attribute":
                    data[2]["trace"]["spans"][2]["resource"]["attributes"].pop("obstudio.eval.preserved")
            if mutant == "reversed-precedence" and len(state["launches"]) == 3:
                # Incorrect generated app honors the lower-priority Resource name.
                data = list(identity_receipts(attrs["service.name"], version=attrs["service.version"],
                                   retained=attrs["obstudio.eval.preserved"]))
            if bake:
                # Canonical ID formatting for the real adapter/core path; the legacy
                # synthetic wire fixtures intentionally use readable placeholder IDs.
                source_trace = data[0][0]["trace_id"]
                trace_id = "1" * 32
                spans = data[2][source_trace]["spans"]
                ids = {span["spanId"]: format(i + 1, "016x") for i, span in enumerate(spans)}
                for span in spans:
                    span["traceId"] = trace_id
                    span["spanId"] = ids[span["spanId"]]
                    if span.get("parentSpanId"):
                        span["parentSpanId"] = ids[span["parentSpanId"]]
                data[2] = {trace_id: {"spans": spans}}
                for request in data[0]:
                    request.update(trace_id=trace_id, client_span_id=ids[request["client_span_id"]],
                                   parent_span_id=ids[request["parent_span_id"]], method="GET",
                                   path="/logging-workflow/" + request["slot"], http_status=200)
                for log in data[1]:
                    if log.get("traceId"):
                        log["traceId"] = trace_id
                        log["spanId"] = ids[log["spanId"]]
            timestamp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
            if mutant == "stale" and len(state["launches"]) == 2:
                timestamp -= dt.timedelta(days=2)
            for record in data[1]: record["timeUnixNano"] = timestamp.isoformat()
            state["current"] = data
            self.stdout = io.StringIO(data[4] + "\n")
        def poll(self): return self.returncode
    monkeypatch.setattr(workflow.subprocess, "Popen", Process)
    monkeypatch.setattr(workflow, "traced_requests", lambda *_: state["current"][0])
    def stop(process, *, drained=None, **_):
        process.returncode = 0
        return drained.wait(timeout=1)
    monkeypatch.setattr(workflow, "stop_owned", stop)
    def query(url):
        if url.endswith("/health"): return {"status": "ok"}
        return state["current"][1] if "/api/query/logs" in url else state["current"][2][url.rsplit("/", 1)[-1]]
    monkeypatch.setattr(workflow, "get_json", query)
    args = ["checker", "--start-command-json", '["make","dev"]']
    if profiles: args.append("--operator-identity-profiles")
    if bake: args.append("--bake-evidence")
    monkeypatch.setattr(sys, "argv", args)
    # The real pump thread writes the complete fresh captured sink before validation.
    real_capture = workflow.capture_live_receipts
    def capture(process, studio, requests, name, started, output, expected):
        deadline = dt.datetime.now() + dt.timedelta(seconds=1)
        while not (output / "native-output.log").read_text().endswith("workflow outside completed\n"):
            assert dt.datetime.now() < deadline
            threading.Event().wait(.001)
        return real_capture(process, studio, requests, name, started, output, expected)
    monkeypatch.setattr(workflow, "capture_live_receipts", capture)
    status = workflow.main()
    assert dict(os.environ) == ambient
    paths = list((tmp_path / ".observe/logging-workflow-proof").glob("*/result.json"))
    results = [json.loads(p.read_text()) for p in paths]
    return status, state, paths, results


def test_unflagged_checker_keeps_one_normal_launch_and_existing_evidence(monkeypatch, tmp_path):
    status, state, paths, results = mock_identity_run(monkeypatch, tmp_path, profiles=False)
    assert status == 0 and len(state["launches"]) == len(results) == 1
    result = results[0]
    assert result["status"] == "passed" and len(result["joins"]) == 4
    assert "identity_profile" not in result and result["shutdown_drain_proven"] is False
    assert (paths[0].parent / "receiver-traces.json").is_file()
    assert (paths[0].parent / "native-output-at-receipt.log").is_file()


def test_opt_in_profiles_reach_actual_child_and_retain_independent_raw_results(monkeypatch, tmp_path):
    status, state, paths, results = mock_identity_run(monkeypatch, tmp_path, profiles=True)
    assert status == 0 and len(state["launches"]) == len(results) == 4
    assert "OTEL_SERVICE_NAME" not in state["launches"][1]
    assert state["launches"][2]["OTEL_SERVICE_NAME"] == "operator-explicit-fixture-nonce"
    assert len({r["proof_directory"] for r in results}) == 4
    tagged = {r["identity_profile"]: r for r in results if "identity_profile" in r}
    assert set(tagged) == {"resource-only", "explicit-override", "resource-whitespace"}
    for result in results:
        assert result["status"] == "passed" and len(result["joins"]) == 4
        assert result["source_before"] == result["source_after"]
    for result in tagged.values():
        assert result["expected_resource"]["service.version"] == "operator-version-fixture-nonce"
        index = {"resource-only": 1, "explicit-override": 2, "resource-whitespace": 3}[result["identity_profile"]]
        assert result["launch_resource_inputs"] == {k: v for k, v in state["launches"][index].items() if k in {"OTEL_SERVICE_NAME", "OTEL_RESOURCE_ATTRIBUTES"}}
        if result["identity_profile"] == "resource-whitespace":
            assert "space-padded Resource entry/key/value inputs" in result["scope"]
            assert "no absent/default identity, metrics Resource, percent-encoding or header proof" in result["scope"]
        else:
            assert "no absent/default identity, metrics Resource, encoding or header proof" in result["scope"]


@pytest.mark.parametrize("mutant", ["hardcoded", "lost-version", "lost-attribute", "stale"])
def test_profile_fault_keeps_failed_raw_evidence_and_cannot_be_erased_by_later_pass(monkeypatch, tmp_path, mutant):
    status, state, paths, results = mock_identity_run(monkeypatch, tmp_path, profiles=True, mutant=mutant)
    assert status == 1 and len(state["launches"]) == len(results) == 4
    failed = next(r for r in results if r.get("identity_profile") == "resource-only")
    assert failed["status"] == "failed" and failed["error"]
    assert failed["source_before"] == failed["source_after"]
    raw = Path(failed["proof_directory"])
    for name in ("receiver-logs.json", "receiver-traces.json", "requests.json", "native-output.log"):
        assert (raw / name).is_file()
    assert next(r for r in results if r.get("identity_profile") == "explicit-override")["status"] == "passed"


def test_third_explicit_override_launch_rejects_reversed_precedence_without_erasing_first_passes(monkeypatch, tmp_path):
    status, state, paths, results = mock_identity_run(monkeypatch, tmp_path, profiles=True, mutant="reversed-precedence")
    assert status == 1 and len(state["launches"]) == len(results) == 4
    failed = next(r for r in results if r.get("identity_profile") == "explicit-override")
    assert failed["status"] == "failed" and "application server span" in failed["error"]
    assert failed["launch_resource_inputs"]["OTEL_SERVICE_NAME"] == "operator-explicit-fixture-nonce"
    assert "service.name=operator-resource-explicit-override-fixture-nonce" in failed["launch_resource_inputs"]["OTEL_RESOURCE_ATTRIBUTES"]
    assert failed["expected_resource"]["service.name"] == "operator-explicit-fixture-nonce"
    assert all(r["status"] == "passed" for r in results if r is not failed)
    raw = Path(failed["proof_directory"])
    logs = json.loads((raw / "receiver-logs.json").read_text())
    assert logs == []  # Wrong-name receipts cannot be selected as the operator winner.
    traces = json.loads((raw / "receiver-traces.json").read_text())
    assert any(s.get("kind") == "SERVER" and s["resource"]["serviceName"] ==
               "operator-resource-explicit-override-fixture-nonce"
               for trace in traces.values() for s in trace["spans"])
    assert failed["source_before"] == failed["source_after"]
    for name in ("receiver-logs.json", "receiver-traces.json", "requests.json", "native-output.log"):
        assert (raw / name).is_file()


def test_fourth_whitespace_profile_keeps_raw_spaces_and_independent_expected_values(monkeypatch, tmp_path):
    status, state, paths, results = mock_identity_run(monkeypatch, tmp_path, profiles=True)
    assert status == 0 and len(state["launches"]) == len(results) == 4
    row = next(r for r in results if r.get("identity_profile") == "resource-whitespace")
    assert "OTEL_SERVICE_NAME" not in state["launches"][3]
    assert row["launch_resource_inputs"]["OTEL_RESOURCE_ATTRIBUTES"] == (
        " service.name = operator-resource-resource-whitespace-fixture-nonce , "
        "service.version = operator-version-fixture-nonce , obstudio.eval.preserved = kept-fixture-nonce ")
    assert row["expected_resource"] == {"service.name": "operator-resource-resource-whitespace-fixture-nonce",
        "service.version": "operator-version-fixture-nonce", "obstudio.eval.preserved": "kept-fixture-nonce"}
    assert sum(len(r["joins"]) for r in results) == 16
    assert all(r["status"] == "passed" and r["source_before"] == r["source_after"] for r in results)
    raw = Path(row["proof_directory"])
    logs = json.loads((raw / "receiver-logs.json").read_text())
    assert len(logs) == 5
    for record in logs:
        assert all(record["resource"]["attributes"][k] == v for k, v in row["expected_resource"].items())


def test_fourth_whitespace_launch_rejects_substring_fallback_despite_three_plain_passes(monkeypatch, tmp_path):
    status, state, paths, results = mock_identity_run(monkeypatch, tmp_path, profiles=True,
                                            mutant="whitespace-broken-fallback")
    assert status == 1 and len(state["launches"]) == len(results) == 4
    failed = next(r for r in results if r.get("identity_profile") == "resource-whitespace")
    assert failed["status"] == "failed" and "application server span" in failed["error"]
    assert all(r["status"] == "passed" for r in results if r is not failed)
    assert failed["source_before"] == failed["source_after"]
    raw = Path(failed["proof_directory"])
    assert json.loads((raw / "receiver-logs.json").read_text()) == []
    traces = json.loads((raw / "receiver-traces.json").read_text())
    assert any(s.get("kind") == "SERVER" and s["resource"]["serviceName"] == "broken-launch-default"
               for trace in traces.values() for s in trace["spans"])
    assert failed["launch_resource_inputs"]["OTEL_RESOURCE_ATTRIBUTES"].startswith(" service.name = ")
    assert "OTEL_SERVICE_NAME" not in failed["launch_resource_inputs"]
    assert failed["expected_resource"]["service.name"].startswith("operator-resource-resource-whitespace-")
    for name in ("receiver-logs.json", "receiver-traces.json", "requests.json", "native-output.log"):
        assert (raw / name).is_file()


@pytest.fixture
def captured_workflow(tmp_path):
    """Saved REST/native fixture data; adapter tests do not claim a live SDK run."""
    service, output = tmp_path / "service", tmp_path / "run-captured"
    service.mkdir()
    output.mkdir()
    (service / "app.py").write_text("# source binding fixture\n")
    requests, logs, details, native = [], [], {}, []
    for number, slot in enumerate(("left", "right"), 1):
        tid = format(number, "032x")
        parent, client, server, handler = [format(number * 10 + i, "016x") for i in range(4)]
        requests.append({"slot": slot, "method": "GET", "path": "/logging-workflow/" + slot,
                         "http_status": 200, "trace_id": tid, "client_span_id": client, "parent_span_id": parent,
                         "sdk_trace_flags": 1})
        spans = [
            {"spanId": parent, "traceId": tid, "resource": {"serviceName": "driver"}},
            {"spanId": client, "traceId": tid, "parentSpanId": parent, "resource": {"serviceName": "driver"}},
            {"spanId": server, "traceId": tid, "parentSpanId": client, "kind": "SERVER", "resource": {"serviceName": "app"}},
            {"spanId": handler, "traceId": tid, "parentSpanId": server, "kind": "INTERNAL", "resource": {"serviceName": "app"}},
        ]
        details[tid] = {"spans": spans}
        for kind in ("sync", "async"):
            body = f"workflow {kind} completed {slot}"
            logs.append({"body": body, "traceId": tid, "spanId": handler,
                         "severityNumber": 13, "resource": {"serviceName": "app"}})
            native.append(body)
    logs.append({"body": workflow.OUTSIDE, "resource": {"serviceName": "app"}})
    native.append(workflow.OUTSIDE)
    for name, value in [("requests.json", requests), ("receiver-logs.json", logs), ("receiver-traces.json", details)]:
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    (output / "native-output-at-receipt.log").write_text("\n".join(native) + "\n")
    result = {"source_before": workflow.source_hashes(service), "expected_service_name": "app",
              "started": "2026-11-12T00:00:00+00:00", "verifier_sha256": "host-verifier-fixture"}
    workflow.capture_evidence_context(output, service, result)
    return output, service


def test_capture_adapter_bakes_only_four_actual_own_operation_joins(captured_workflow, report_helper_and_sample):
    output, service = captured_workflow
    helper, _ = report_helper_and_sample
    before = {name: (output / name).read_bytes() for name in workflow.CAPTURE_ARTIFACTS}
    # Cleanup/result changes and the final output sink are deliberately outside capture hashes.
    (output / "result.json").write_text('{"status":"running"}')
    (output / "native-output.log").write_text("later cleanup output\n")
    summary = workflow.bake_capture_evidence(output)
    assert summary["status"] == "working"
    report = json.loads((output / summary["report"]).read_text())
    manifest = json.loads((output / "evidence-bake-manifest.json").read_text())
    observations = json.loads((output / "evidence-bake-observations.json").read_text())
    assert len(observations) == 4 and len(manifest["controls"]) == 2
    assert {row["operation_id"] for row in observations} == {
        "workflow.left.sync", "workflow.left.async", "workflow.right.sync", "workflow.right.async"}
    for row in observations:
        number = 1 if ".left." in row["operation_id"] else 2
        assert row["trace_context"]["trace_id"] == format(number, "032x")
        assert row["trace_context"]["span_id"] == format(number * 10 + 3, "016x")
        assert row["provenance"] == "captured" and row["phase"] == "source_alive"
        assert row["run_id"] == output.name
        assert row["facts"]["received_records"] == row["facts"]["native_records"] == 1
        assert row["facts"]["sdk_trace_flags"] == "unknown"  # Driver flags are not source flags.
        assert all(row["facts"][fact] == "unknown" for fact in (
            "acknowledged_records", "accepted_records", "acknowledgement", "persisted_records", "persistence"))
        assert {reference["path"] for reference in row["artifacts"]} == set(workflow.CAPTURE_ARTIFACTS) | {"evidence-bake-context.json"}
        for reference in row["artifacts"]:
            assert hashlib.sha256((output / reference["path"]).read_bytes()).hexdigest() == reference["sha256"]
    assert report["producer"]["source_root"] == str(service.resolve())
    assert report["scenarios"][0]["id"] == "workflow.logs.concurrent"
    assert report["scenarios"][0]["trace_ids"] == [format(1, "032x"), format(2, "032x")]
    assert all(len(control["operation_ids"]) == 2 for control in report["controls"])
    rebaked = helper.bake_evidence_report(manifest, observations, output)
    assert rebaked["controls"] == report["controls"] and rebaked["scenarios"] == report["scenarios"]
    assert "No metrics" in (output / summary["markdown"]).read_text()
    assert {name: (output / name).read_bytes() for name in workflow.CAPTURE_ARTIFACTS} == before
    sidecars = {p.name: p.read_bytes() for p in output.glob("evidence-bake-*")}
    (output / "result.json").write_text('{"status":"passed","cleanup":true}')
    workflow.bake_capture_evidence(output)
    assert {p.name: p.read_bytes() for p in output.glob("evidence-bake-*")} == sidecars


@pytest.mark.parametrize("fault", ["tampered", "wrong-owner", "missing-record", "invalid-sdk-id", "wrong-phase", "span-trace-mismatch"])
def test_capture_adapter_rejects_changed_or_invalid_raw_proof(captured_workflow, fault):
    output, service = captured_workflow
    context_path = output / "evidence-bake-context.json"
    context = json.loads(context_path.read_text())
    if fault == "tampered":
        path = output / "requests.json"
        path.write_text(path.read_text() + "\n")
    elif fault == "wrong-phase":
        context["phase"] = "after_cleanup"
        context_path.write_text(json.dumps(context))
    else:
        path = output / "receiver-logs.json"
        logs = json.loads(path.read_text())
        if fault == "span-trace-mismatch":
            details_path = output / "receiver-traces.json"
            details = json.loads(details_path.read_text())
            next(iter(details.values()))["spans"][-1]["traceId"] = "f" * 32
            details_path.write_text(json.dumps(details))
        elif fault == "wrong-owner":
            logs[0]["spanId"] = logs[2]["spanId"]
        elif fault == "missing-record":
            logs.pop(0)
        else:
            requests_path = output / "requests.json"
            requests = json.loads(requests_path.read_text())
            old = requests[0]["trace_id"]
            requests[0]["trace_id"] = "invalid"
            requests_path.write_text(json.dumps(requests))
            details_path = output / "receiver-traces.json"
            details = json.loads(details_path.read_text())
            details["invalid"] = details.pop(old)
            details_path.write_text(json.dumps(details))
            for log in logs:
                if log.get("traceId") == old:
                    log["traceId"] = "invalid"
        path.write_text(json.dumps(logs))
        # Source-import a self-consistent fixture to exercise adapter/core validation,
        # separately from the immutable-hash rejection above.
        for reference in context["artifacts"]:
            reference["sha256"] = hashlib.sha256((output / reference["path"]).read_bytes()).hexdigest()
        context_path.write_text(json.dumps(context))
    with pytest.raises((AssertionError, ValueError, KeyError)):
        workflow.bake_capture_evidence(output)
    assert not (output / "evidence-bake-report.json").exists()
    assert not (output / "evidence-bake-report.md").exists()


def test_bake_flag_forwards_to_normal_and_all_identity_profiles(monkeypatch, tmp_path):
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["checker", "--start-command-json", '["make","dev"]',
                                     "--operator-identity-profiles", "--bake-evidence"])
    monkeypatch.setattr(workflow, "run_check", lambda *args, **kwargs: calls.append(kwargs) or 0)
    assert workflow.main() == 0 and len(calls) == 4
    assert all(call["bake_evidence"] is True for call in calls)


def test_bake_failure_after_live_capture_cannot_replace_runtime_outcome_or_skip_cleanup(monkeypatch, tmp_path):
    def fail_bake(output):
        assert (output / "native-output-at-receipt.log").is_file()
        assert (output / "evidence-bake-context.json").is_file()
        raise ValueError("captured source data cannot be baked")
    monkeypatch.setattr(workflow, "bake_capture_evidence", fail_bake)
    real_run = workflow.run_check
    monkeypatch.setattr(workflow, "run_check", lambda *args, **kwargs: real_run(*args, **kwargs, bake_evidence=True))
    status, state, paths, results = mock_identity_run(monkeypatch, tmp_path, profiles=False)
    assert status == 1 and len(state["launches"]) == 1
    assert results[0]["status"] == "failed" and results[0]["graceful_stop"] is True
    assert "captured source data cannot be baked" in results[0]["error"]
    assert results[0]["source_before"] == results[0]["source_after"]
    assert not (paths[0].parent / "evidence-bake-report.json").exists()


def test_flagged_checker_runs_real_capture_adapter_for_each_profile(monkeypatch, tmp_path):
    status, state, paths, results = mock_identity_run(monkeypatch, tmp_path, profiles=True, bake=True)
    assert status == 0 and len(state["launches"]) == len(results) == 4
    for path, result in zip(paths, results):
        assert result["status"] == "passed" and result["graceful_stop"] is True
        assert result["evidence_bake"]["status"] == "working"
        output = path.parent
        report = json.loads((output / "evidence-bake-report.json").read_text())
        context = json.loads((output / "evidence-bake-context.json").read_text())
        assert len(report["controls"]) == 2 and len(report["scenarios"]) == 1
        assert len({row["operation_id"] for control in report["controls"] for row in control["observations"]}) == 4
        assert context["source_sha256"] == result["source_before"] == result["source_after"]
        assert context["service_name"] == result["expected_service_name"]
        assert "result.json" not in {r["path"] for r in context["artifacts"]}
        assert (output / "evidence-bake-report.md").is_file()


def test_failed_runtime_capture_gets_no_baked_credit_while_later_profiles_continue(monkeypatch, tmp_path):
    status, _, _, results = mock_identity_run(monkeypatch, tmp_path, profiles=True,
                                             mutant="lost-version", bake=True)
    assert status == 1 and len(results) == 4
    failed = next(result for result in results if result.get("identity_profile") == "resource-only")
    assert failed["status"] == "failed" and "evidence_bake" not in failed
    assert not (Path(failed["proof_directory"]) / "evidence-bake-report.json").exists()
    assert all(result["status"] == "passed" and result["evidence_bake"]["status"] == "working"
               for result in results if result is not failed)
