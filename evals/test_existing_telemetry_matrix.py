from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "python/existing-otel-agent-demo"
sys.path.insert(0, str(FIXTURE))
spec = importlib.util.spec_from_file_location("existing_telemetry_probe", FIXTURE / "probe.py")
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
prior_app = sys.modules.pop("app", None)
try:
    spec.loader.exec_module(probe)
finally:
    sys.path.pop(0)
    sys.modules.pop("app", None)
    if prior_app is not None:
        sys.modules["app"] = prior_app


@pytest.fixture(scope="module")
def baseline_receipts() -> dict:
    # Actual SDK exporters encode protobuf and send to the loopback HTTP receiver.
    return {mode: probe.capture(mode) for mode in probe.MODES}


@pytest.mark.parametrize("mode,signals", [
    ("generic", {"traces", "metrics", "logs"}),
    ("genai", {"traces", "metrics", "logs"}),
    ("metrics", {"metrics"}),
    ("logs", {"logs"}),
    ("none", set()),
])
def test_real_existing_signal_modes_and_lifecycle(baseline_receipts: dict, mode: str, signals: set[str]) -> None:
    receipt = baseline_receipts[mode]
    assert receipt["setup_errors"] == []
    assert receipt["outcomes"] == [
        {"scenario": "success", "outcome": "success"},
        {"scenario": "tool_error", "outcome": "RuntimeError"},
        {"scenario": "provider_error", "outcome": "RuntimeError"},
        {"scenario": "cancel", "outcome": "CancelledError"},
    ]
    assert {request["path"].removeprefix("/v1/") for request in receipt["requests"]} == signals
    assert len(receipt["requests"]) == len(signals), "one actual HTTP request per signal batch"
    assert all(request["status"] == 200 for request in receipt["requests"])
    assert all(receipt["original_objects_retained"].values())
    assert receipt["second_shutdown_requests"] == 0
    assert receipt["proof_mode"] == "local_otlp_contract"
    assert receipt["cloud_visibility"] == "not_proven"


@pytest.mark.parametrize("mode", ["generic", "genai"])
def test_existing_spans_have_known_ids_fields_and_real_failure_status(baseline_receipts: dict, mode: str) -> None:
    spans = probe.records(baseline_receipts[mode], "traces")
    assert len(spans) == 6
    assert {span["span_id"] for span in spans} == {
        "000000000000b011", "000000000000b012", "000000000000b021",
        "000000000000b031", "000000000000b032", "000000000000b041",
    }
    assert {span["trace_id"] for span in spans} == {f"{0xA000 + index:032x}" for index in range(1, 5)}
    assert all(span["attributes"]["legacy.sentinel"] == "keep-span" for span in spans)
    assert all(span["resource"]["legacy.resource"] == "keep-resource" for span in spans)
    assert all({"name": "legacy.started", "attributes": {"legacy.event": "keep-event"}} in span["events"] for span in spans)
    assert sum(span["status"]["code"] == 2 for span in spans) == 3
    if mode == "generic":
        assert {span["name"] for span in spans} == {"POST /agent", "POST /model"}
        assert not any("gen_ai.operation.name" in span["attributes"] for span in spans)
    else:
        assert {span["attributes"]["gen_ai.operation.name"] for span in spans} == {"invoke_workflow", "chat"}


@pytest.mark.parametrize("mode", ["generic", "genai", "metrics"])
def test_existing_counter_values_are_real_not_fixture_claims(baseline_receipts: dict, mode: str) -> None:
    metrics = probe.records(baseline_receipts[mode], "metrics")
    assert len(metrics) == 4
    assert {record["attributes"]["scenario"] for record in metrics} == set(probe.SCENARIOS)
    assert all(record["name"] == "legacy.agent.requests" and record["value"] == 7 for record in metrics)
    assert all(record["unit"] == "{request}" for record in metrics)


@pytest.mark.parametrize("mode", ["generic", "genai", "logs"])
def test_existing_logs_are_otel_records_not_stdout(baseline_receipts: dict, mode: str) -> None:
    logs = probe.records(baseline_receipts[mode], "logs")
    assert len(logs) == 4
    assert all(record["body"] == "legacy audit record" and record["severity_text"] == "INFO" for record in logs)
    assert all(record["attributes"]["legacy.log"] == "keep-log" for record in logs)
    assert probe.records(baseline_receipts["none"], "logs") == []


def test_public_trace_session_and_span_hooks_preserve_actual_exporters(tmp_path: Path, baseline_receipts: dict) -> None:
    # This tiny handwritten integration tests the fixture's extension contract.
    # It deliberately leaves all operation gaps open, so it cannot be skill proof.
    integration = tmp_path / "hook_contract.py"
    integration.write_text(
        "def configure(app):\n"
        "    app.trace_session.headers.update({'projectid': 'selected-project', 'logstreamid': 'selected-stream'})\n"
        "    if getattr(app, '_contract_hook_added', False):\n"
        "        return\n"
        "    app._contract_hook_added = True\n"
        "    def enrich(span, operation, metadata):\n"
        "        span.set_attribute('hook.seen', operation)\n"
        "    app.trace_producer.span_hooks.append(enrich)\n",
    )
    receipt = probe.capture("generic", integration)
    assert receipt["setup_errors"] == []
    assert all(receipt["original_objects_retained"].values())
    assert len(probe.records(receipt, "traces")) == 6
    assert all(span["attributes"]["hook.seen"] == span["attributes"]["legacy.operation"] for span in probe.records(receipt, "traces"))
    assert receipt["outcomes"] == baseline_receipts["generic"]["outcomes"]
    for request in receipt["requests"]:
        if request["path"] == "/v1/traces":
            assert request["headers"]["projectid"] == "selected-project"
            assert request["headers"]["logstreamid"] == "selected-stream"
            assert request["headers"]["x-legacy-trace"] == "keep-trace-header"
        else:
            assert not probe.ROUTING_HEADERS.intersection(request["headers"])
    failures = probe.compare(baseline_receipts["generic"], receipt, "studio", "selected-project", "selected-stream")
    assert "expected exactly 4 invoke_agent operations, got 0" in failures


def test_supported_hooks_receive_actual_inputs_and_completed_results(tmp_path: Path) -> None:
    integration = tmp_path / "input_contract.py"
    observed = tmp_path / "observed.json"
    integration.write_text(
        "import contextlib, copy, json\n"
        "from pathlib import Path\n"
        "def configure(app):\n"
        "    if getattr(app, '_observer_added', False):\n"
        "        return\n"
        "    app._observer_added = True\n"
        "    observed = []\n"
        "    @contextlib.contextmanager\n"
        "    def observe(operation, metadata):\n"
        "        assert metadata['result_available'] is False\n"
        "        try:\n"
        "            yield\n"
        "        finally:\n"
        "            observed.append({'operation': operation, **copy.deepcopy(metadata)})\n"
        "    app.operation_hooks.append(observe)\n"
        f"    app.shutdown_callbacks.append(lambda: Path({str(observed)!r}).write_text(json.dumps(observed)))\n",
    )
    receipt = probe.capture("generic", integration)
    assert receipt["setup_errors"] == []
    observed_operations = json.loads(observed.read_text())
    retrieval = next(row for row in observed_operations if row["operation"] == "retrieval" and row["scenario"] == "success")
    assert retrieval["inputs"] == {"query": "private-prompt-sentinel"}
    assert retrieval["result_available"] is True
    assert retrieval["result"] == ["Policy: orders can be checked with lookup_order."]
    tool = next(row for row in observed_operations if row["operation"] == "tool" and row["scenario"] == "success")
    assert tool["inputs"] == {"order_id": "demo-order-7"}
    assert tool["result"] == {"state": "shipped"}
    model = next(row for row in observed_operations if row["operation"] == "model" and row["scenario"] == "success")
    assert model["inputs"] == {"prompt": "private-prompt-sentinel", "documents": retrieval["result"], "order": tool["result"]}
    assert model["result"] == "Your order is shipped; used 1 policy document."
    cancelled = next(row for row in observed_operations if row["operation"] == "tool" and row["scenario"] == "cancel")
    assert cancelled["result_available"] is False and "result" not in cancelled
    assert "private-prompt-sentinel" not in json.dumps(receipt["requests"])


def test_real_log_context_and_safe_attributes_can_enrich_existing_records(tmp_path: Path, baseline_receipts: dict) -> None:
    # This observer tests the log decoder and preservation rule, not a skill solution.
    integration = tmp_path / "log_context_contract.py"
    integration.write_text(
        "import contextlib\n"
        "from opentelemetry import trace\n"
        "def configure(app):\n"
        "    if getattr(app, '_log_contract_added', False):\n"
        "        return\n"
        "    app._log_contract_added = True\n"
        "    original_emit = app.audit_logger.emit\n"
        "    pending = []\n"
        "    app.audit_logger.emit = pending.append\n"
        "    @contextlib.contextmanager\n"
        "    def observe(operation, metadata):\n"
        "        if operation == 'workflow':\n"
        "            context = trace.get_current_span().get_span_context()\n"
        "            for record in pending:\n"
        "                record.trace_id = context.trace_id\n"
        "                record.span_id = context.span_id\n"
        "                record.trace_flags = context.trace_flags\n"
        "                record.attributes = {**record.attributes, 'safe.correlation': 'added'}\n"
        "                original_emit(record)\n"
        "            pending.clear()\n"
        "        yield\n"
        "    app.operation_hooks.append(observe)\n",
    )
    actual = probe.capture("generic", integration)
    assert actual["setup_errors"] == []
    assert all(actual["original_objects_retained"].values())
    logs = probe.records(actual, "logs")
    spans = probe.records(actual, "traces")
    assert len(logs) == 4
    for record in logs:
        context = (record["trace_id"], record["span_id"])
        assert all(context)
        span = next(span for span in spans if (span["trace_id"], span["span_id"]) == context)
        expected_request = f"turn-{probe.SCENARIOS.index(record['attributes']['scenario']) + 1}"
        assert span["attributes"]["legacy.request"] == expected_request
        assert record["attributes"]["safe.correlation"] == "added"
    failures = probe.compare(baseline_receipts["generic"], actual, "studio", "project", "stream")
    assert not any("existing logs" in failure for failure in failures), failures
    # A source-proven nonempty context then becomes immutable.
    changed = copy.deepcopy(actual)
    probe.records(changed, "logs")[0]["trace_id"] = "f" * 32
    failures = probe.compare(actual, changed, "studio", "project", "stream")
    assert "existing logs values/fields missing or duplicated" in failures


@pytest.mark.parametrize("mutation", [
    "unknown-context", "other-request-context", "partial-context", "attribute", "body",
    "severity_number", "severity_text", "resource", "scope", "duplicate", "drop",
])
def test_log_subset_preservation_rejects_lost_fields_bad_context_and_cardinality(baseline_receipts: dict, mutation: str) -> None:
    before = baseline_receipts["generic"]
    after = copy.deepcopy(before)
    request = next(request for request in after["requests"] if request["path"] == "/v1/logs")
    record = request["records"][0]
    if mutation == "unknown-context":
        record.update(trace_id="f" * 32, span_id="f" * 16)
    elif mutation == "other-request-context":
        other = next(span for span in probe.records(after, "traces") if span["attributes"]["legacy.request"] == "turn-2")
        record.update(trace_id=other["trace_id"], span_id=other["span_id"])
    elif mutation == "partial-context":
        span = probe.records(after, "traces")[0]
        record.update(trace_id=span["trace_id"], span_id="")
    elif mutation == "attribute":
        record["attributes"]["scenario"] = "changed"
    elif mutation == "duplicate":
        request["records"].append(copy.deepcopy(record))
    elif mutation == "drop":
        request["records"].pop()
    elif mutation == "severity_number":
        record[mutation] = 17
    elif mutation == "resource":
        record[mutation]["service.name"] = "changed-service"
    else:
        record[mutation] = "changed"
    failures = probe.compare(before, after, "studio", "project", "stream")
    assert "existing logs values/fields missing or duplicated" in failures


def test_rejected_transport_is_not_promoted_to_working(baseline_receipts: dict) -> None:
    rejected = probe.capture("generic", reject_traces=True)
    trace_requests = [request for request in rejected["requests"] if request["path"] == "/v1/traces"]
    assert len(trace_requests) == 1
    assert trace_requests[0]["status"] == 400
    assert "OTLP export rejected: /v1/traces" in probe.compare(
        baseline_receipts["generic"], rejected, "studio", "project", "stream",
    )
    assert {request["path"] for request in rejected["requests"]} == {"/v1/traces", "/v1/metrics", "/v1/logs"}


def test_configure_failure_keeps_original_telemetry_running_and_fails_cli(tmp_path: Path) -> None:
    integration = tmp_path / "broken.py"
    integration.write_text("def configure(app):\n    raise RuntimeError('synthetic hook failure')\n")
    output = tmp_path / "failed.json"
    result = subprocess.run(
        [sys.executable, str(FIXTURE / "probe.py"), "capture", "--mode", "generic",
         "--instrumentation", str(integration), "--output", str(output)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 1, result.stderr
    receipt = json.loads(output.read_text())
    assert receipt["setup_errors"] == ["RuntimeError: synthetic hook failure"]
    assert len(probe.records(receipt, "traces")) == 6
    assert len(probe.records(receipt, "metrics")) == 4
    assert len(probe.records(receipt, "logs")) == 4
    assert all(receipt["original_objects_retained"].values())


@pytest.mark.parametrize("mode", ["generic", "genai", "metrics", "logs", "none"])
def test_unchanged_baseline_cannot_claim_completed_gap_instrumentation(baseline_receipts: dict, mode: str) -> None:
    failures = probe.compare(baseline_receipts[mode], baseline_receipts[mode], "studio", "project", "stream")
    assert any("invoke_agent" in failure for failure in failures)
    assert any("retrieval" in failure for failure in failures)
    assert any("execute_tool" in failure for failure in failures)


def _synthetic_completed_receipt(before: dict, contract: str = "studio") -> dict:
    """Comparator test data only; this is never an emitted or skill-produced receipt."""
    after = copy.deepcopy(before)
    request = next(item for item in after["requests"] if item["path"] == "/v1/traces")
    request["headers"].update({"projectid": "project", "logstreamid" if contract == "studio" else "agentstreamid": "stream"})
    spans = request["records"]
    for span in spans:
        if span["attributes"].get("legacy.operation") not in {"workflow", "model"}:
            continue
        span["attributes"]["gen_ai.operation.name"] = "invoke_workflow" if span["attributes"]["legacy.operation"] == "workflow" else "chat"
        index = int(span["attributes"]["legacy.request"].split("-")[1])
        span["attributes"].update({"app.request_id": f"turn-{index}", "app.scenario": probe.SCENARIOS[index - 1]})
        if index == 4 and span["attributes"]["legacy.operation"] == "workflow":
            span["status"] = {"code": 2, "message": ""}
            span["attributes"]["error.type"] = "CancelledError"
    for index in range(1, 5):
        workflow = next(span for span in spans if span["attributes"].get("legacy.request") == f"turn-{index}" and span["attributes"].get("legacy.operation") == "workflow")
        agent_id = f"{0xC000 + index * 16:016x}"
        for offset, operation in enumerate(("invoke_agent", "retrieval", "execute_tool")):
            scenario = probe.SCENARIOS[index - 1]
            failed = scenario in {"tool_error", "cancel"} and operation in {"invoke_agent", "execute_tool"} or scenario == "provider_error" and operation == "invoke_agent"
            spans.append({
                "name": operation, "trace_id": workflow["trace_id"], "span_id": f"{0xC000 + index * 16 + offset:016x}",
                "parent_span_id": workflow["span_id"] if operation == "invoke_agent" else agent_id,
                "kind": 1, "attributes": {
                    "gen_ai.operation.name": operation, "app.request_id": f"turn-{index}", "app.scenario": scenario,
                    **({"error.type": "CancelledError" if scenario == "cancel" else "RuntimeError"} if failed else {}),
                },
                "resource": copy.deepcopy(workflow["resource"]), "scope": "synthetic-comparator-data",
                "status": {"code": 2 if failed else 0, "message": ""}, "events": [],
            })
        for span in spans:
            if span["attributes"].get("legacy.request") == f"turn-{index}" and span["attributes"].get("legacy.operation") == "model":
                span["parent_span_id"] = agent_id
    return after


@pytest.mark.parametrize("contract", ["studio", "public"])
def test_comparator_accepts_complete_synthetic_contract_without_calling_it_skill_proof(baseline_receipts: dict, contract: str) -> None:
    before = baseline_receipts["generic"]
    assert probe.compare(before, _synthetic_completed_receipt(before, contract), contract, "project", "stream") == []


def test_actual_supported_hook_can_fill_proven_missing_cancellation_status(tmp_path: Path, baseline_receipts: dict) -> None:
    integration = tmp_path / "cancel_hook_contract.py"
    integration.write_text(
        "import asyncio, contextlib\n"
        "from opentelemetry import trace\n"
        "from opentelemetry.trace import Status, StatusCode\n"
        "def configure(app):\n"
        "    if getattr(app, '_cancel_hook_added', False):\n"
        "        return\n"
        "    app._cancel_hook_added = True\n"
        "    @contextlib.contextmanager\n"
        "    def observe(operation, metadata):\n"
        "        try:\n"
        "            yield\n"
        "        except asyncio.CancelledError:\n"
        "            if operation == 'workflow':\n"
        "                span = trace.get_current_span()\n"
        "                span.set_attribute('error.type', 'CancelledError')\n"
        "                span.set_status(Status(StatusCode.ERROR))\n"
        "            raise\n"
        "    app.operation_hooks.append(observe)\n",
    )
    actual = probe.capture("generic", integration)
    cancelled = next(span for span in probe.records(actual, "traces") if span["attributes"]["legacy.request"] == "turn-4")
    assert cancelled["status"]["code"] == 2
    assert cancelled["attributes"]["error.type"] == "CancelledError"
    # Gap nodes below remain synthetic comparator data, not skill output.
    completed = _synthetic_completed_receipt(actual)
    assert probe.compare(baseline_receipts["generic"], completed, "studio", "project", "stream") == []


@pytest.mark.parametrize("mutation", ["cancel-ok", "cancel-cleared", "error-cleared", "unrelated-error"])
def test_status_enrichment_does_not_allow_clearing_or_unrelated_status_changes(baseline_receipts: dict, mutation: str) -> None:
    before = baseline_receipts["generic"]
    after = _synthetic_completed_receipt(before)
    spans = probe.records(after, "traces")
    if mutation.startswith("cancel-"):
        span = next(span for span in spans if span["attributes"].get("legacy.request") == "turn-4")
        span["status"]["code"] = 1 if mutation == "cancel-ok" else 0
    elif mutation == "error-cleared":
        span = next(span for span in spans if span["attributes"].get("legacy.request") == "turn-2")
        span["status"] = {"code": 0, "message": ""}
    else:
        span = next(span for span in spans if span["attributes"].get("legacy.request") == "turn-1")
        span["status"] = {"code": 2, "message": "unrelated mutation"}
    failures = probe.compare(before, after, "studio", "project", "stream")
    assert any("status" in failure for failure in failures), failures


@pytest.mark.parametrize("mutation,expected", [
    ("disconnected", "wrong parent or disconnected trace for retrieval"),
    ("duplicate-operation", "expected exactly 4 execute_tool operations, got 5"),
    ("missing-operation", "expected exactly 4 invoke_agent operations, got 3"),
    ("legacy-field", "existing span attributes changed"),
    ("cancel-success", "missing error status for cancel execute_tool"),
    ("error-output", "fabricated output/usage for failed invoke_agent"),
])
def test_comparator_rejects_wrong_graphs_and_changed_legacy_fields(baseline_receipts: dict, mutation: str, expected: str) -> None:
    before = baseline_receipts["generic"]
    after = _synthetic_completed_receipt(before)
    spans = next(request for request in after["requests"] if request["path"] == "/v1/traces")["records"]
    if mutation == "disconnected":
        next(span for span in spans if span["attributes"].get("gen_ai.operation.name") == "retrieval")["parent_span_id"] = "0000000000000000"
    elif mutation == "duplicate-operation":
        span = copy.deepcopy(next(span for span in spans if span["attributes"].get("gen_ai.operation.name") == "execute_tool"))
        span["span_id"] = "000000000000d001"
        spans.append(span)
    elif mutation == "missing-operation":
        spans.remove(next(span for span in spans if span["attributes"].get("gen_ai.operation.name") == "invoke_agent"))
    elif mutation == "legacy-field":
        spans[0]["attributes"]["legacy.sentinel"] = "lost"
    elif mutation == "cancel-success":
        next(span for span in spans if span["attributes"].get("gen_ai.operation.name") == "execute_tool" and span["attributes"].get("app.scenario") == "cancel")["status"]["code"] = 0
    elif mutation == "error-output":
        next(span for span in spans if span["attributes"].get("gen_ai.operation.name") == "invoke_agent" and span["attributes"].get("app.scenario") == "provider_error")["attributes"]["gen_ai.output.messages"] = "fabricated"
    assert any(expected in failure for failure in probe.compare(before, after, "studio", "project", "stream"))


@pytest.mark.parametrize("mutation,expected", [
    ("replacement", "existing provider/producer/processor/exporter/instrument was replaced"),
    ("metric-loss", "existing metrics values/fields missing or duplicated"),
    ("log-duplicate", "existing logs values/fields missing or duplicated"),
    ("span-loss", "existing span missing or duplicated"),
    ("mixed-route", "mixed Studio/public stream header contract"),
    ("global-route", "global OTLP headers changed"),
    ("metric-route", "trace routing leaked into /v1/metrics"),
    ("double-batch", "expected one trace batch and one upstream request after shutdown"),
    ("raw-content", "raw prompt leaked into telemetry"),
])
def test_comparison_rejects_preservation_and_routing_regressions(baseline_receipts: dict, mutation: str, expected: str) -> None:
    # Receipt mutations validate the comparator, not emitted instrumentation.
    before = baseline_receipts["generic"]
    after = copy.deepcopy(before)
    trace_request = next(request for request in after["requests"] if request["path"] == "/v1/traces")
    if mutation == "replacement":
        after["original_objects_retained"]["trace_exporter"] = False
    elif mutation == "metric-loss":
        next(request for request in after["requests"] if request["path"] == "/v1/metrics")["records"].pop()
    elif mutation == "log-duplicate":
        request = next(request for request in after["requests"] if request["path"] == "/v1/logs")
        request["records"].append(copy.deepcopy(request["records"][0]))
    elif mutation == "span-loss":
        trace_request["records"].pop()
    elif mutation == "mixed-route":
        trace_request["headers"].update({"projectid": "project", "logstreamid": "stream", "agentstreamid": "stream"})
    elif mutation == "global-route":
        after["header_environment"]["OTEL_EXPORTER_OTLP_HEADERS"] = "projectid=project"
    elif mutation == "metric-route":
        next(request for request in after["requests"] if request["path"] == "/v1/metrics")["headers"]["projectid"] = "project"
    elif mutation == "double-batch":
        after["requests"].append(copy.deepcopy(trace_request))
    elif mutation == "raw-content":
        trace_request["records"][0]["attributes"]["gen_ai.input.messages"] = "private-prompt-sentinel"
    failures = probe.compare(before, after, "studio", "project", "stream")
    assert any(expected in failure for failure in failures), failures


def test_fixture_manifest_has_no_vendor_producer_dependency() -> None:
    import tomllib

    manifest = tomllib.loads((FIXTURE / "pyproject.toml").read_text())
    assert all("splunk" not in dependency.lower() and "galileo" not in dependency.lower() for dependency in manifest["project"]["dependencies"])


def test_capture_and_compare_cli_write_reviewable_receipts(tmp_path: Path) -> None:
    output = tmp_path / "before.json"
    result = subprocess.run(
        [sys.executable, str(FIXTURE / "probe.py"), "capture", "--mode", "metrics", "--output", str(output)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["requests"][0]["path"] == "/v1/metrics"
    result = subprocess.run(
        [sys.executable, str(FIXTURE / "probe.py"), "compare", str(output), str(output),
         "--target-contract", "studio", "--project-id", "project", "--stream-id", "stream"],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["cloud_visibility"] == "not_proven"


def _capture_process(output: Path, fixture: Path = FIXTURE, resource_attributes: str | None = None) -> dict:
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("OTEL_", "SPLUNK_", "GALILEO_"))}
    if resource_attributes is not None:
        environment["OTEL_RESOURCE_ATTRIBUTES"] = resource_attributes
    result = subprocess.run(
        [sys.executable, str(fixture / "probe.py"), "capture", "--mode", "generic", "--output", str(output)],
        env=environment, check=False, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(output.read_text())


def _resource_failures(before: dict, after: dict) -> list[str]:
    return [failure for failure in probe.compare(before, after, "studio", "project", "stream")
            if "resource" in failure or "existing metrics" in failure or "existing logs" in failure]


def test_real_unchanged_cross_process_resources_preserve_original_values(tmp_path: Path) -> None:
    before = _capture_process(tmp_path / "before.json")
    after = _capture_process(tmp_path / "after.json")
    for receipt in (before, after):
        proof = receipt["resource_proof"]
        assert proof["sdk_generated_service_instance_id"] is True
        assert set(proof["signals"]) == {"traces", "metrics", "logs"}
        assert all(owner["original_values_preserved"] for owner in proof["signals"].values())
    first = before["resource_proof"]["signals"]["traces"]["original"].get("service.instance.id")
    second = after["resource_proof"]["signals"]["traces"]["original"].get("service.instance.id")
    if first is not None and second is not None:
        assert first != second, "these are actual separate SDK process instances"
    assert _resource_failures(before, after) == []


def test_operator_instance_ids_are_immutable_across_real_processes(tmp_path: Path) -> None:
    before = _capture_process(tmp_path / "operator-before.json", resource_attributes="service.instance.id=operator-instance")
    same = _capture_process(tmp_path / "operator-same.json", resource_attributes="service.instance.id=operator-instance")
    changed = _capture_process(tmp_path / "operator-changed.json", resource_attributes="service.instance.id=changed-instance")
    assert before["resource_proof"]["sdk_generated_service_instance_id"] is False
    assert "service.instance.id" in before["resource_proof"]["explicit_resource_keys"]
    assert _resource_failures(before, same) == []
    assert any("existing span resource changed" in failure for failure in _resource_failures(before, changed))


def test_literal_application_instance_id_cannot_be_treated_as_sdk_generated(tmp_path: Path) -> None:
    service = tmp_path / "source"
    service.mkdir()
    shutil.copyfile(FIXTURE / "probe.py", service / "probe.py")
    original = (FIXTURE / "app.py").read_text()
    source = original.replace('"legacy.resource": "keep-resource"', '"legacy.resource": "keep-resource", "service.instance.id": "application-instance"', 1)
    (service / "app.py").write_text(source)
    before = _capture_process(tmp_path / "application-before.json", fixture=service)
    (service / "app.py").write_text(source.replace('"application-instance"', '"changed-application-instance"'))
    after = _capture_process(tmp_path / "application-after.json", fixture=service)
    assert before["resource_proof"]["sdk_generated_service_instance_id"] is False
    assert after["resource_proof"]["sdk_generated_service_instance_id"] is False
    assert _resource_failures(before, after)


def test_dynamic_application_resource_mapping_does_not_get_volatile_id_exemption(tmp_path: Path) -> None:
    service = tmp_path / "dynamic-source"
    service.mkdir()
    shutil.copyfile(FIXTURE / "probe.py", service / "probe.py")
    source = (FIXTURE / "app.py").read_text()
    source = source.replace('RESOURCE = Resource.create(', 'RESOURCE_VALUES = {"service.instance" + ".id": "dynamic-instance"}\nRESOURCE = Resource.create(', 1)
    source = source.replace('"legacy.resource": "keep-resource"', '"legacy.resource": "keep-resource", **RESOURCE_VALUES', 1)
    (service / "app.py").write_text(source)
    before = _capture_process(tmp_path / "dynamic-before.json", fixture=service)
    (service / "app.py").write_text(source.replace('"dynamic-instance"', '"changed-dynamic-instance"'))
    after = _capture_process(tmp_path / "dynamic-after.json", fixture=service)
    assert before["resource_proof"]["sdk_generated_service_instance_id"] is False
    assert after["resource_proof"]["sdk_generated_service_instance_id"] is False
    assert _resource_failures(before, after)


def test_real_source_declared_missing_resource_field_may_be_filled(tmp_path: Path) -> None:
    before = _capture_process(tmp_path / "before.json")
    service = tmp_path / "source"
    service.mkdir()
    shutil.copyfile(FIXTURE / "probe.py", service / "probe.py")
    source = (FIXTURE / "app.py").read_text().replace('"legacy.resource": "keep-resource"', '"legacy.resource": "keep-resource", "service.version": "0.1.0"', 1)
    (service / "app.py").write_text(source)
    after = _capture_process(tmp_path / "after.json", fixture=service)
    assert "service.version" in after["resource_proof"]["source_resource_keys"]
    assert _resource_failures(before, after) == []


@pytest.mark.parametrize("mutation", ["drop-field", "changed-field", "changed-instance", "unproven-addition", "missing-proof", "within-process-proof-false"])
def test_resource_proof_rejects_mutation_or_missing_ownership_evidence(baseline_receipts: dict, mutation: str) -> None:
    before = baseline_receipts["generic"]
    after = copy.deepcopy(before)
    resource = probe.records(after, "traces")[0]["resource"]
    if mutation == "drop-field":
        del resource["legacy.resource"]
    elif mutation == "changed-field":
        resource["service.name"] = "changed"
    elif mutation == "changed-instance":
        resource["service.instance.id"] = "changed-within-process"
    elif mutation == "unproven-addition":
        resource["unproven.resource"] = "invented"
    elif mutation == "missing-proof":
        del after["resource_proof"]
        resource["service.instance.id"] = "changed-without-proof"
    else:
        after["resource_proof"]["signals"]["traces"]["original_values_preserved"] = False
    assert _resource_failures(before, after)


@pytest.mark.parametrize("mutation", ["point-dimension", "point-value"])
def test_resource_enrichment_cannot_change_metric_point_contract(baseline_receipts: dict, mutation: str) -> None:
    before = baseline_receipts["generic"]
    after = copy.deepcopy(before)
    metric = probe.records(after, "metrics")[0]
    if mutation == "point-dimension":
        metric["attributes"]["invented.dimension"] = "extra"
    else:
        metric["value"] += 1
    assert "existing metrics values/fields missing or duplicated" in probe.compare(before, after, "studio", "project", "stream")


@pytest.mark.parametrize("taxonomy", ["cancelled", "CancelledError", "asyncio.CancelledError", "asyncio.exceptions.CancelledError"])
def test_actual_cancel_status_accepts_bounded_source_taxonomy(baseline_receipts: dict, taxonomy: str) -> None:
    before = baseline_receipts["generic"]
    after = _synthetic_completed_receipt(before)
    cancelled = next(span for span in probe.records(after, "traces") if span["attributes"].get("legacy.request") == "turn-4")
    cancelled["attributes"]["error.type"] = taxonomy
    assert probe.compare(before, after, "studio", "project", "stream") == []


@pytest.mark.parametrize("mutation", ["drop", "rename", "wrong-type", "duplicate", "missing-message", "missing-stacktrace"])
def test_existing_sdk_exception_event_identity_and_fields_cannot_be_lost(baseline_receipts: dict, mutation: str) -> None:
    before = baseline_receipts["generic"]
    after = _synthetic_completed_receipt(before)
    span = next(span for span in probe.records(after, "traces") if any(event["name"] == "exception" for event in span["events"]))
    event = next(event for event in span["events"] if event["name"] == "exception")
    if mutation == "drop":
        span["events"].remove(event)
    elif mutation == "rename":
        event["name"] = "renamed-error"
    elif mutation == "wrong-type":
        event["attributes"]["exception.type"] = "ValueError"
    elif mutation == "duplicate":
        span["events"].append(copy.deepcopy(event))
    else:
        del event["attributes"]["exception.message" if mutation == "missing-message" else "exception.stacktrace"]
    failures = probe.compare(before, after, "studio", "project", "stream")
    assert any("exception event" in failure for failure in failures), failures


def test_exception_event_safe_redaction_and_dynamic_traceback_text_are_allowed(baseline_receipts: dict) -> None:
    before = baseline_receipts["generic"]
    after = _synthetic_completed_receipt(before)
    for span in probe.records(after, "traces"):
        for event in span["events"]:
            if event["name"] == "exception":
                event["attributes"]["exception.message"] = "[REDACTED]"
                event["attributes"]["exception.stacktrace"] = "Traceback: /different/process/source.py:123\nRuntimeError: [REDACTED]"
    assert probe.compare(before, after, "studio", "project", "stream") == []


def test_real_cross_process_sdk_exception_events_are_preserved(tmp_path: Path) -> None:
    before = _capture_process(tmp_path / "exception-before.json")
    after = _capture_process(tmp_path / "exception-after.json")
    events = [event for span in probe.records(before, "traces") for event in span["events"] if event["name"] == "exception"]
    assert len(events) == 3
    assert all(event["attributes"]["exception.type"] == "RuntimeError" for event in events)
    failures = probe.compare(before, after, "studio", "project", "stream")
    assert not any("exception event" in failure for failure in failures), failures


@pytest.mark.parametrize("operation", [None, "", "unknown.wrapper", "http.request"])
@pytest.mark.parametrize("scope", ["accidental.model.wrapper", "legacy.agent.producer"])
def test_comparator_rejects_after_only_unrecognized_wrapper_spans(baseline_receipts: dict, operation: str | None, scope: str) -> None:
    # Contract mutations only, never skill-produced or emitted extra-span proof.
    before = baseline_receipts["generic"]
    after = _synthetic_completed_receipt(before)
    spans = next(request for request in after["requests"] if request["path"] == "/v1/traces")["records"]
    original = next(span for span in spans if span["attributes"].get("gen_ai.operation.name") == "chat")
    wrapper = copy.deepcopy(original)
    wrapper["span_id"] = "00000000000de001"
    wrapper["scope"] = scope
    wrapper["attributes"] = {key: value for key, value in wrapper["attributes"].items() if key in {"app.request_id", "app.scenario"}}
    if operation is not None:
        wrapper["attributes"]["gen_ai.operation.name"] = operation
    spans.append(wrapper)
    failures = probe.compare(before, after, "studio", "project", "stream")
    assert len(spans) == 19
    assert failures == [f"unexpected after-only span operation: {wrapper['name']} ({operation or 'missing'})"]


def test_real_baseline_transport_spans_remain_supported(tmp_path: Path) -> None:
    # Real source-bound original transport spans, plus synthetic gap completion.
    # This validates comparator compatibility, not a skill instrumentation run.
    service = tmp_path / "source"
    service.mkdir()
    shutil.copyfile(FIXTURE / "probe.py", service / "probe.py")
    source = (FIXTURE / "app.py").read_text()
    old = '''        with trace.use_span(span, end_on_exit=True):
            span.add_event("legacy.started", {"legacy.event": "keep-event"})
'''
    new = '''        with trace.use_span(span, end_on_exit=True):
            with self.tracer.start_as_current_span("legacy.http.transport", attributes={"transport.sentinel": "keep-transport"}):
                pass
            span.add_event("legacy.started", {"legacy.event": "keep-event"})
'''
    assert source.count(old) == 1
    (service / "app.py").write_text(source.replace(old, new))
    before = _capture_process(tmp_path / "transport-before.json", fixture=service)
    transport_spans = [span for span in probe.records(before, "traces") if span["name"] == "legacy.http.transport"]
    assert len(transport_spans) == 6
    assert all("gen_ai.operation.name" not in span["attributes"] for span in transport_spans)
    after = _synthetic_completed_receipt(before)
    assert len(probe.records(after, "traces")) == 24
    assert probe.compare(before, after, "studio", "project", "stream") == []
    for original in transport_spans:
        current = next(span for span in probe.records(after, "traces") if span["span_id"] == original["span_id"])
        assert current == original
    damaged = copy.deepcopy(after)
    next(span for span in probe.records(damaged, "traces") if span["name"] == "legacy.http.transport")["attributes"]["transport.sentinel"] = "lost"
    assert any("existing span attributes changed" in failure for failure in probe.compare(before, damaged, "studio", "project", "stream"))
