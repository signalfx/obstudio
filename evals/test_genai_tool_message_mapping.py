from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import requests
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "evals/python/ai-assistant-demo/eval/inputs"
FIXTURE = INPUTS / "genai-tool-message-mapping.json"
SNAPSHOT = INPUTS / "genai-semconv-source-snapshot.json"
MESSAGE_FIELDS = {
    "input": "gen_ai.input.messages",
    "output": "gen_ai.output.messages",
}


def _same_value(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def review_tool_case(
    case: dict[str, Any],
    schemas: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Check supplied tool records, not SDK execution or cloud delivery."""
    errors: list[str] = []
    fields: dict[str, str] = {}
    owned = [span for span in case["spans"] if span["span_id"] == case["tool_span_id"]]
    if len(owned) != 1:
        return {"pass": False, "errors": ["canonical tool span must be unique"], "fields": {}}
    span = owned[0]
    attrs = span["attributes"]
    call = case["actual_call"]
    duplicates = [other for other in case["spans"]
                  if other["span_id"] != span["span_id"]
                  and other["attributes"].get("gen_ai.operation.name") == "execute_tool"
                  and other["attributes"].get("gen_ai.tool.call.id") == call["call_id"]]
    if duplicates:
        errors.append("duplicate producer for the same actual tool call")
    parents = [other for other in case["spans"]
               if other["span_id"] == span.get("parent_span_id")]
    if parents and any(parent["trace_id"] != span["trace_id"] for parent in parents):
        errors.append("tool parent trace mismatch")
    if type(call.get("produced_result")) is not bool:
        errors.append("produced_result must be explicit boolean")
    if span.get("ended") is not True:
        errors.append("tool span has not ended")
    for key, expected in (
        ("gen_ai.operation.name", "execute_tool"),
        ("gen_ai.tool.name", call["tool_name"]),
        ("gen_ai.tool.call.id", call["call_id"]),
    ):
        if attrs.get(key) != expected:
            errors.append(f"{key}: source mismatch")

    def decode(field: str) -> tuple[bool, Any]:
        if field not in attrs:
            fields[field] = "missing"
            return False, None
        encoded = attrs[field]
        if not isinstance(encoded, str):
            errors.append(f"{field}: structured OTel attribute must be a JSON string")
            fields[field] = "malformed"
            return False, None
        if len(encoded.encode("utf-8")) > policy["max_utf8_bytes_per_attribute"]:
            errors.append(f"{field}: UTF-8 byte budget exceeded")
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError:
            errors.append(f"{field}: malformed JSON")
            fields[field] = "malformed"
            return False, None
        return True, value

    def oi_value(direction: str, expected: Any) -> bool:
        field = f"{direction}.value"
        present, value = decode(field)
        if not present:
            return False
        if attrs.get("openinference.span.kind") != "TOOL":
            errors.append(f"{field}: supported native TOOL mapping not established")
            return False
        if attrs.get(f"{direction}.mime_type") != "application/json":
            errors.append(f"{field}: JSON serialization MIME type not established")
            return False
        if not _same_value(value, expected):
            errors.append(f"{field}: source mismatch")
            fields[field] = "mismatch"
            return False
        fields[field] = "pass"
        return True

    def canonical_value(field: str, expected: Any, schema_name: str) -> bool:
        present, value = decode(field)
        if not present:
            return False
        schema = schemas[f"model/gen-ai/gen-ai-tool-call-{schema_name}.json"]
        if list(jsonschema.Draft202012Validator(schema).iter_errors(value)):
            errors.append(f"{field}: structured schema mismatch")
            fields[field] = "malformed"
            return False
        if not _same_value(value, expected):
            errors.append(f"{field}: source mismatch")
            fields[field] = "mismatch"
            return False
        fields[field] = "pass"
        return True

    def message_value(direction: str, expected: Any) -> bool:
        field = MESSAGE_FIELDS[direction]
        present, payload = decode(field)
        if not present:
            return False
        schema = schemas[f"model/gen-ai/gen-ai-{direction}-messages.json"]
        if list(jsonschema.Draft202012Validator(schema).iter_errors(payload)):
            errors.append(f"{field}: structured schema mismatch")
            fields[field] = "malformed"
            return False
        if len(payload) > policy["max_messages"]:
            errors.append(f"{field}: message budget exceeded")
        wanted_type = "tool_call" if direction == "input" else "tool_call_response"
        wanted_role = "assistant" if direction == "input" else "tool"
        definition = "ToolCallRequestPart" if direction == "input" else "ToolCallResponsePart"
        value_key = "arguments" if direction == "input" else "response"
        matched = []
        for message in payload:
            if len(message["parts"]) > policy["max_parts_per_message"]:
                errors.append(f"{field}: part budget exceeded")
            for part in message["parts"]:
                if part.get("type") == wanted_type:
                    matched.append((message, part))
        if len(matched) != 1:
            errors.append(f"{field}: one actual tool mapping is required")
            fields[field] = "mismatch"
            return False
        message, part = matched[0]
        part_schema = {"$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"}
        valid = True
        if list(jsonschema.Draft202012Validator(part_schema).iter_errors(part)):
            errors.append(f"{field}: typed tool part schema mismatch")
            valid = False
        if message["role"] != wanted_role or value_key not in part:
            errors.append(f"{field}: typed tool role/value missing or mismatched")
            valid = False
        elif not _same_value(part[value_key], expected):
            errors.append(f"{field}: source mismatch")
            valid = False
        if direction == "input" and part.get("name") != call["tool_name"]:
            errors.append(f"{field}: tool name mismatch")
            valid = False
        if part.get("id") != call["call_id"]:
            errors.append(f"{field}: actual tool-call ID mismatch")
            valid = False
        fields[field] = "pass" if valid else "mismatch"
        return valid

    oi_input = oi_value("input", call["arguments"])
    arguments = canonical_value("gen_ai.tool.call.arguments", call["arguments"], "arguments")
    input_message = message_value("input", call["arguments"])
    if not arguments and not oi_input:
        errors.append("gen_ai.tool.call.arguments: missing supported same-span arguments mapping")
    if not input_message and not oi_input:
        errors.append("gen_ai.input.messages: missing valid same-span input mapping")

    if call["produced_result"]:
        if "result" not in call:
            errors.append("produced result observation is absent")
        else:
            oi_output = oi_value("output", call["result"])
            result = canonical_value("gen_ai.tool.call.result", call["result"], "result")
            output_message = message_value("output", call["result"])
            if not result and not oi_output:
                errors.append("gen_ai.tool.call.result: missing supported same-span result mapping")
            if not output_message and not oi_output:
                errors.append("gen_ai.output.messages: missing valid same-span output mapping")
        if call["outcome"] != "success" or span["status"] == "ERROR":
            errors.append("produced successful result disagrees with outcome/status")
    else:
        if call["outcome"] != "error" or span["status"] != "ERROR":
            errors.append("no-result error requires truthful ERROR lifecycle")
        if attrs.get("error.type") != call.get("error_type"):
            errors.append("actual error.type is missing or mismatched")
        if not case.get("output_applicability", {}).get("reason"):
            errors.append("no-result applicability reason is absent")
        for field in ("gen_ai.tool.call.result", "gen_ai.output.messages", "output.value"):
            if field in attrs:
                errors.append(f"{field}: fabricated successful output on no-result error")
            else:
                fields[field] = "not_applicable:no_result_produced"
    return {"pass": not errors, "errors": errors, "fields": fields}


@pytest.fixture(scope="module")
def supplied() -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return fixture, snapshot["otel"]["structured_schemas"]


EXPECTED = {
    "arguments-result-only": (False, "gen_ai.input.messages"),
    "parent-messages-only": (False, "gen_ai.input.messages"),
    "complete-genai-tool-messages": (True, None),
    "malformed-input-messages": (False, "structured schema mismatch"),
    "mismatched-mapped-values": (False, "source mismatch"),
    "mismatched-tool-call-id": (False, "tool-call ID mismatch"),
    "complete-openinference-mapping": (True, None),
    "error-no-produced-result": (True, None),
    "safe-success-missing-output-mapping": (False, "gen_ai.output.messages"),
    "error-fabricated-success-output": (False, "fabricated successful output"),
    "successful-null-result": (True, None),
}


@pytest.mark.parametrize("case_id", EXPECTED)
def test_observed_tool_mapping_contract(supplied, case_id: str) -> None:
    fixture, schemas = supplied
    case = next(row for row in fixture["cases"] if row["case_id"] == case_id)
    expected_pass, reason = EXPECTED[case_id]
    result = review_tool_case(case, schemas, fixture["content_policy"])
    assert result["pass"] is expected_pass, result
    if reason:
        assert any(reason in error for error in result["errors"]), result


@pytest.mark.parametrize("missing_field", [
    "gen_ai.tool.call.arguments", "gen_ai.tool.call.result",
    "gen_ai.input.messages", "gen_ai.output.messages",
])
def test_each_missing_tool_field_fails_despite_parent_messages(supplied, missing_field) -> None:
    fixture, schemas = supplied
    case = copy.deepcopy(next(row for row in fixture["cases"] if row["case_id"] == "complete-genai-tool-messages"))
    tool = case["spans"][1]["attributes"]
    for field in MESSAGE_FIELDS.values():
        case["spans"][0]["attributes"][field] = tool[field]
    del tool[missing_field]
    result = review_tool_case(case, schemas, fixture["content_policy"])
    assert not result["pass"], result
    assert any(missing_field in error for error in result["errors"]), result


def test_null_is_produced_and_dedicated_schema_limit_is_explicit(supplied) -> None:
    fixture, schemas = supplied
    case = next(row for row in fixture["cases"] if row["case_id"] == "successful-null-result")
    assert case["actual_call"]["produced_result"] is True
    assert case["actual_call"]["result"] is None
    tool = case["spans"][1]["attributes"]
    assert json.loads(tool["output.value"]) is None
    assert json.loads(tool["gen_ai.output.messages"])[0]["parts"][0]["response"] is None
    result_schema = schemas["model/gen-ai/gen-ai-tool-call-result.json"]
    assert list(jsonschema.Draft202012Validator(result_schema).iter_errors(None))
    assert "gen_ai.tool.call.result" not in tool
    assert review_tool_case(case, schemas, fixture["content_policy"])["pass"]


@pytest.mark.parametrize("result_value", [False, 0, [], {}])
def test_other_falsy_results_use_produced_flag(supplied, result_value) -> None:
    fixture, schemas = supplied
    case = copy.deepcopy(next(row for row in fixture["cases"] if row["case_id"] == "successful-null-result"))
    case["actual_call"]["result"] = result_value
    tool = case["spans"][1]["attributes"]
    tool["output.value"] = json.dumps(result_value)
    payload = json.loads(tool["gen_ai.output.messages"])
    payload[0]["parts"][0]["response"] = result_value
    tool["gen_ai.output.messages"] = json.dumps(payload)
    assert review_tool_case(case, schemas, fixture["content_policy"])["pass"]


def test_generic_part_schema_does_not_mask_missing_typed_response(supplied) -> None:
    fixture, schemas = supplied
    case = copy.deepcopy(next(row for row in fixture["cases"] if row["case_id"] == "complete-genai-tool-messages"))
    tool = case["spans"][1]["attributes"]
    payload = json.loads(tool["gen_ai.output.messages"])
    del payload[0]["parts"][0]["response"]
    tool["gen_ai.output.messages"] = json.dumps(payload)
    assert not review_tool_case(case, schemas, fixture["content_policy"])["pass"]


def test_source_match_is_type_sensitive(supplied) -> None:
    fixture, schemas = supplied
    case = copy.deepcopy(next(row for row in fixture["cases"] if row["case_id"] == "successful-null-result"))
    case["actual_call"]["result"] = 0
    tool = case["spans"][1]["attributes"]
    tool["output.value"] = "false"
    payload = json.loads(tool["gen_ai.output.messages"])
    payload[0]["parts"][0]["response"] = False
    tool["gen_ai.output.messages"] = json.dumps(payload)
    assert not review_tool_case(case, schemas, fixture["content_policy"])["pass"]


def test_schema_provenance_and_case_inventory_are_bound(supplied) -> None:
    fixture, schemas = supplied
    assert {row["case_id"] for row in fixture["cases"]} == set(EXPECTED)
    assert len(fixture["cases"]) == len(EXPECTED)
    provenance = fixture["source_provenance"]["semantic_snapshot"]
    assert provenance["sha256"] == hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert provenance["resolved_revision"] == snapshot["otel"]["resolved_revision"]
    assert provenance["captured_at_utc"] == snapshot["otel"]["captured_at_utc"]
    assert set(provenance["schemas"]) <= schemas.keys()
    assert all("expected" not in case for case in fixture["cases"])


@pytest.mark.parametrize("budget", ["max_messages", "max_parts_per_message", "max_utf8_bytes_per_attribute"])
def test_concrete_capture_budgets_are_enforced(supplied, budget) -> None:
    fixture, schemas = supplied
    case = next(row for row in fixture["cases"] if row["case_id"] == "complete-genai-tool-messages")
    policy = copy.deepcopy(fixture["content_policy"])
    policy[budget] = 0
    result = review_tool_case(case, schemas, policy)
    assert not result["pass"], result
    assert any("budget exceeded" in error for error in result["errors"]), result


def test_duplicate_producer_does_not_close_actual_tool(supplied) -> None:
    fixture, schemas = supplied
    case = copy.deepcopy(next(row for row in fixture["cases"] if row["case_id"] == "complete-genai-tool-messages"))
    wrapper = copy.deepcopy(case["spans"][1])
    wrapper["span_id"] = "ffffffffffffffff"
    case["spans"].append(wrapper)
    result = review_tool_case(case, schemas, fixture["content_policy"])
    assert not result["pass"]
    assert "duplicate producer for the same actual tool call" in result["errors"]


def test_no_result_error_requires_terminal_error_identity(supplied) -> None:
    fixture, schemas = supplied
    case = copy.deepcopy(next(row for row in fixture["cases"] if row["case_id"] == "error-no-produced-result"))
    case["spans"][1]["ended"] = False
    case["spans"][1]["status"] = "UNSET"
    del case["spans"][1]["attributes"]["error.type"]
    result = review_tool_case(case, schemas, fixture["content_policy"])
    assert not result["pass"]
    assert "tool span has not ended" in result["errors"]
    assert "no-result error requires truthful ERROR lifecycle" in result["errors"]
    assert "actual error.type is missing or mismatched" in result["errors"]


def test_focused_verifier_definition_and_safe_inputs_are_valid() -> None:
    from pytest_codex_evals.definitions.rubric import RubricEvalDefinition

    path = INPUTS.parent / "qual/tool-message-mapping-verify.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    definition = RubricEvalDefinition.model_validate({
        **raw, "id": path.stem, "language": "python", "service": "ai-assistant-demo",
    })
    assert definition.skill == "otel-verify"
    assert len(definition.rubric) == 4
    assert len(definition.prompts) == 1
    assert definition.prompts[0].id == "tool-message-mapping-verify"
    fixture_root = INPUTS.parents[1]
    for relative in definition.prompts[0].eval_inputs:
        assert (fixture_root / relative).is_file()


@pytest.fixture(scope="module")
def enrichment_evidence() -> dict[str, Any]:
    return json.loads((INPUTS / "genai-tool-enrichment-evidence.json").read_text(encoding="utf-8"))


def _supplied_enriched_view(record: dict[str, Any]) -> dict[str, Any]:
    """Project supplied safe records; this is not SDK/exporter execution."""
    view = copy.deepcopy(record["sdk_span"])
    metadata = json.loads(view["attributes"]["splunk_ao.metadata"])
    view["attributes"].update(json.loads(metadata["application.genai.required"]))
    return view


def _observed_enrichment_case(record: dict[str, Any], span: dict[str, Any]) -> dict[str, Any]:
    case = {
        "tool_span_id": record["sdk_span"]["span_id"],
        "actual_call": record["actual_safe_call"],
        "spans": [span],
    }
    if not case["actual_call"]["produced_result"]:
        case["output_applicability"] = {"reason": "Actual error occurred before a result was produced."}
    return case


@pytest.mark.parametrize("scenario", ["success", "error_no_result"])
def test_supplied_sdk_carrier_preserves_own_identity_and_source_values(supplied, enrichment_evidence, scenario) -> None:
    _, schemas = supplied
    record = enrichment_evidence["synthetic_records"][scenario]
    view = _supplied_enriched_view(record)
    for field in enrichment_evidence["adapter_contract"]["preserved_fields"]:
        assert view[field] == record["sdk_span"][field]
    result = review_tool_case(_observed_enrichment_case(record, view), schemas, enrichment_evidence["content_policy"])
    assert result["pass"], result
    call = record["actual_safe_call"]
    assert json.loads(record["native_sdk_record"]["input"]) == call["arguments"]
    if call["produced_result"]:
        assert json.loads(record["native_sdk_record"]["output"]) == call["result"]
        assert all("finish_reason" not in message for message in json.loads(view["attributes"]["gen_ai.output.messages"]))
    else:
        assert record["native_sdk_record"]["output"] is None
        assert "gen_ai.tool.call.result" not in view["attributes"]
        assert "gen_ai.output.messages" not in view["attributes"]
    sentinel = enrichment_evidence["content_policy"]["synthetic_raw_sentinel"]
    assert sentinel not in json.dumps(record["native_sdk_record"])
    maximum = enrichment_evidence["content_policy"]["max_utf8_bytes_per_attribute"]
    assert len(json.dumps(record["native_sdk_record"]["user_metadata"]).encode("utf-8")) <= maximum


def test_unused_adapter_leaves_native_message_gap(supplied, enrichment_evidence) -> None:
    _, schemas = supplied
    record = enrichment_evidence["synthetic_records"]["success"]
    route = next(row for row in enrichment_evidence["route_cases"] if row["case_id"] == "adapter-not-in-sdk-export-path")
    assert route["active_sink_routes_through_adapter"] is False
    result = review_tool_case(_observed_enrichment_case(record, record["sdk_span"]), schemas, enrichment_evidence["content_policy"])
    assert not result["pass"]
    assert any("gen_ai.input.messages" in error for error in result["errors"])
    assert any("gen_ai.output.messages" in error for error in result["errors"])


def test_safe_semantic_companion_cannot_hide_raw_native_original(supplied, enrichment_evidence) -> None:
    _, schemas = supplied
    record = enrichment_evidence["synthetic_records"]["success"]
    view = _supplied_enriched_view(record)
    assert review_tool_case(_observed_enrichment_case(record, view), schemas, enrichment_evidence["content_policy"])["pass"]
    unsafe = next(row for row in enrichment_evidence["route_cases"] if row["case_id"] == "raw-native-original-with-safe-companion")
    sentinel = enrichment_evidence["content_policy"]["synthetic_raw_sentinel"]
    assert sentinel in unsafe["sdk_native_input"]
    assert sentinel not in unsafe["redacted_companion"]
    assert unsafe["semantic_fields_are_safe"] is True
    assert json.loads(unsafe["redacted_companion"]) == record["actual_safe_call"]["arguments"]
    # Native-record safety must be checked separately from semantic-field acceptance.
    assert sentinel not in json.dumps(view["attributes"])


def test_new_wrapper_cannot_replace_original_sdk_identity(supplied, enrichment_evidence) -> None:
    _, schemas = supplied
    record = enrichment_evidence["synthetic_records"]["success"]
    wrapper = _supplied_enriched_view(record)
    route = next(row for row in enrichment_evidence["route_cases"] if row["case_id"] == "new-wrapper-identity")
    wrapper.update(trace_id=route["new_trace_id"], span_id=route["new_span_id"])
    assert not review_tool_case(_observed_enrichment_case(record, wrapper), schemas, enrichment_evidence["content_policy"])["pass"]
    case = _observed_enrichment_case(record, record["sdk_span"])
    case["spans"].append(wrapper)
    result = review_tool_case(case, schemas, enrichment_evidence["content_policy"])
    assert not result["pass"]
    assert "duplicate producer for the same actual tool call" in result["errors"]


def test_generic_hook_and_undocumented_sink_do_not_establish_production_route(enrichment_evidence) -> None:
    routes = {row["case_id"]: row for row in enrichment_evidence["route_cases"]}
    generic = routes["generic-supported-hook-someday"]
    assert generic["metadata_path"] is None
    assert generic["adapter_api"] != "SpanExporter.export"
    assert generic["view_api"] is None
    blocked = routes["concrete-route-unproven-production-registration"]
    assert blocked["adapter_api"] == "SpanExporter.export"
    assert blocked["view_api"] == "ReadableSpan"
    assert blocked["active_sink_routes_through_adapter"] is None
    assert "0.5" in blocked["precise_blocker"] and "registration" in blocked["precise_blocker"]
    assert "Not a universal documented production" in enrichment_evidence["checked_compatibility"]["logger_sink_parameter"]


def test_enrichment_source_receipt_separates_example_signatures_and_runtime(enrichment_evidence) -> None:
    sdk = enrichment_evidence["source_provenance"]["sdk_snapshot"]
    assert sdk["sha256"] == hashlib.sha256((INPUTS / "genai-sdk-source-snapshot.json").read_bytes()).hexdigest()
    assert sdk["physical_example_path"] == "examples/logging-samples/splunk-ao-logger/basic-example.py"
    assert "add_tool_span" not in sdk["example_exercises"]
    assert "flush" not in sdk["example_exercises"]
    assert "terminate" not in sdk["example_exercises"]
    assert {"add_tool_span", "flush", "terminate"} <= set(sdk["separate_signature_apis_not_exercised_by_basic_example"])
    assert sdk["declared_main_version"] == "0.5.0"
    assert enrichment_evidence["checked_compatibility"]["sdk_version"] == "splunk-ao==0.4.0"
    assert "not runtime captures" in enrichment_evidence["scope"]


@pytest.mark.parametrize("scenario, error_fragment", [
    ("invalid_native_null_result", "structured schema mismatch"),
    ("spurious_native_output_on_error", "fabricated successful output"),
])
def test_merge_only_retains_invalid_native_fields_but_owned_removal_repairs(supplied, enrichment_evidence, scenario, error_fragment) -> None:
    _, schemas = supplied
    record = enrichment_evidence["synthetic_records"][scenario]
    merged = _supplied_enriched_view(record)
    failed = review_tool_case(_observed_enrichment_case(record, merged), schemas, enrichment_evidence["content_policy"])
    assert not failed["pass"]
    assert any(error_fragment in error for error in failed["errors"])
    repaired = copy.deepcopy(record["sdk_span"])
    fields = json.loads(json.loads(repaired["attributes"]["splunk_ao.metadata"])["application.genai.required"])
    for field in record["validated_removals"]:
        assert field in enrichment_evidence["adapter_contract"]["removal_allowlist"]
        repaired["attributes"].pop(field, None)
    repaired["attributes"].update(fields)
    accepted = review_tool_case(_observed_enrichment_case(record, repaired), schemas, enrichment_evidence["content_policy"])
    assert accepted["pass"], accepted
    for field in enrichment_evidence["adapter_contract"]["preserved_fields"]:
        assert repaired[field] == record["sdk_span"][field]
    owned = set(record["validated_removals"]) | set(fields)
    for field, value in record["sdk_span"]["attributes"].items():
        if field not in owned:
            assert repaired["attributes"][field] == value
    assert "gen_ai.tool.call.result" not in repaired["attributes"]
    if record["actual_safe_call"]["produced_result"]:
        assert json.loads(repaired["attributes"]["output.value"]) is None
        assert json.loads(repaired["attributes"]["gen_ai.output.messages"])[0]["parts"][0]["response"] is None
    else:
        assert "gen_ai.output.messages" not in repaired["attributes"]
        assert repaired["status"] == "ERROR"
        assert repaired["attributes"]["error.type"] == "WeatherUnavailable"


def test_enrichment_removal_scope_and_drop_counts_are_explicit(enrichment_evidence) -> None:
    contract = enrichment_evidence["adapter_contract"]
    assert set(contract["removal_allowlist"]) == {
        "gen_ai.tool.call.arguments", "gen_ai.tool.call.result",
        "gen_ai.input.messages", "gen_ai.output.messages", "input.value", "output.value",
    }
    assert "gen_ai.provider.name" not in contract["removal_allowlist"]
    assert "input.mime_type" not in contract["removal_allowlist"]
    assert {"dropped_attributes", "dropped_events", "dropped_links"} <= set(contract["preserved_fields"])
    assert "identical original span" in contract["unrelated_span_rule"]


@pytest.fixture(scope="module")
def shipped_tool_adapter():
    source_path = ROOT / "skills/references/splunk-agent-observability.md"
    source = source_path.read_text(encoding="utf-8")
    blocks = [match for match in re.finditer(r"```python\n(.*?)\n```", source, re.DOTALL)
              if "class ToolContentView(ReadableSpan):" in match.group(1)]
    assert len(blocks) == 1
    block = blocks[0]
    code = block.group(1)
    assert {node.name for node in ast.parse(code).body if isinstance(node, ast.ClassDef)} == {
        "ToolContentView", "ToolContentExporter",
    }
    assert all(isinstance(node, (ast.ImportFrom, ast.Assign, ast.ClassDef))
               for node in ast.parse(code).body)
    namespace = {"__name__": "shipped_tool_content_adapter"}
    prefix = "\n" * source.count("\n", 0, block.start(1))
    exec(compile(prefix + code, str(source_path), "exec"), namespace)
    return namespace["ToolContentView"], namespace["ToolContentExporter"]


def _real_sdk_tool_batch(outcome: str):
    capture = InMemorySpanExporter()
    provider = TracerProvider(
        sampler=ALWAYS_ON,
        shutdown_on_exit=False,
        resource=Resource({"service.name": "adapter-contract", "service.test": "sdk"},
                          schema_url="https://example.test/resource-schema"),
        span_limits=SpanLimits(
            max_attributes=16, max_span_attributes=16,
            max_events=1, max_links=1,
            max_event_attributes=1, max_link_attributes=1,
            max_attribute_length=8192, max_span_attribute_length=8192,
        ),
    )
    provider.add_span_processor(SimpleSpanProcessor(capture))
    tracer = provider.get_tracer("adapter-contract", "1.0", "https://example.test/span-schema",
                                 attributes={"scope.test": "preserved"})
    parent = trace.SpanContext(
        trace_id=0x123456789ABCDEF123456789ABCDEF12, span_id=0x123456789ABCDEF1,
        is_remote=True, trace_flags=trace.TraceFlags(trace.TraceFlags.SAMPLED),
        trace_state=trace.TraceState([("contract", "preserved")]),
    )
    context = trace.set_span_in_context(trace.NonRecordingSpan(parent))
    links = [trace.Link(trace.SpanContext(
        trace_id=parent.trace_id + index + 1, span_id=parent.span_id + index + 1,
        is_remote=bool(index), trace_flags=trace.TraceFlags(trace.TraceFlags.SAMPLED),
        trace_state=trace.TraceState([("link", str(index))]),
    ), {"discard": "first", "link.keep": str(index)}) for index in range(2)]
    arguments = {"incident_id": "INC-SYNTHETIC"}
    call_id = "safe-sdk-call"
    fields = {"gen_ai.input.messages": json.dumps([{
        "role": "assistant", "parts": [{"type": "tool_call", "id": call_id,
                                         "name": "lookup_incident", "arguments": arguments}],
    }])}
    removed = {"gen_ai.tool.call.result"}

    def lookup_incident(incident_id):
        assert incident_id == arguments["incident_id"]
        if outcome == "error_no_result":
            raise LookupError("Synthetic dependency failed")
        return None

    try:
        with tracer.start_as_current_span("execute_tool lookup_incident", context=context,
                                         links=links, kind=trace.SpanKind.INTERNAL) as span:
            span.set_attributes({f"discard.{index}": str(index) for index in range(20)})
            span.add_event("discard-event", {"event.discard": "first"})
            span.add_event("kept-event", {"discard": "first", "event.keep": "second"})
            try:
                result = lookup_incident(**arguments)
            except LookupError:
                span.set_status(trace.Status(trace.StatusCode.ERROR, "Synthetic dependency failed"))
                span.set_attribute("error.type", "LookupError")
                removed.update({"gen_ai.output.messages", "output.value"})
            else:
                fields.update({
                    "gen_ai.output.messages": json.dumps([{
                        "role": "tool", "parts": [{"type": "tool_call_response",
                                                    "id": call_id, "response": result}],
                    }]),
                    "openinference.span.kind": "TOOL",
                    "output.mime_type": "application/json",
                    "output.value": json.dumps(result),
                })
            span.set_attributes({
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": "lookup_incident",
                "gen_ai.tool.call.id": call_id,
                "gen_ai.tool.call.arguments": json.dumps(arguments),
                "gen_ai.tool.call.result": "null",
                "gen_ai.input.messages": "[]",
                "gen_ai.output.messages": "[]",
                "output.value": "\"stale\"",
                "input.mime_type": "application/json",
                "application.keep": "preserved",
                "splunk_ao.metadata": json.dumps({"application.genai.required": json.dumps(fields)}),
            })
        with tracer.start_as_current_span("HTTP helper", context=context, kind=trace.SpanKind.CLIENT) as span:
            span.set_attribute("http.request.method", "GET")
        spans = capture.get_finished_spans()
        assert len(spans) == 2
        assert all(count > 0 for count in (
            spans[0].dropped_attributes, spans[0].dropped_events, spans[0].dropped_links,
            spans[0].events[0].dropped_attributes, spans[0].links[0].dropped_attributes,
        ))
        return spans, fields, removed
    finally:
        provider.shutdown()


def _safe_sdk_carrier_fields(span, removed):
    if span.attributes.get("gen_ai.operation.name") != "execute_tool":
        return {}, set()
    metadata = json.loads(span.attributes["splunk_ao.metadata"])
    return json.loads(metadata["application.genai.required"]), removed


class _RecordingSpanExporter(SpanExporter):
    def __init__(self, result):
        self.result = result
        self.batches = []
        self.flush_timeouts = []
        self.shutdown_count = 0

    def export(self, spans):
        self.batches.append(tuple(spans))
        return self.result

    def force_flush(self, timeout_millis=30000):
        self.flush_timeouts.append(timeout_millis)
        return False

    def shutdown(self):
        self.shutdown_count += 1


@pytest.mark.parametrize("delegate_result", [SpanExportResult.SUCCESS, SpanExportResult.FAILURE])
def test_shipped_adapter_preserves_real_sdk_identity_and_export_lifecycle(shipped_tool_adapter, monkeypatch, delegate_result):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    view_class, exporter_class = shipped_tool_adapter
    spans, fields, removed = _real_sdk_tool_batch("successful_null")
    original_attributes = dict(spans[0].attributes)
    delegate = _RecordingSpanExporter(delegate_result)
    adapter = exporter_class(delegate, lambda span: _safe_sdk_carrier_fields(span, removed))
    assert adapter.export(spans) is delegate_result
    assert len(delegate.batches) == 1
    view, unrelated = delegate.batches[0]
    assert isinstance(view, view_class)
    assert unrelated is spans[1]
    for field in ("context", "parent", "resource", "instrumentation_scope", "status"):
        assert getattr(view, field) is getattr(spans[0], field)
    for field in ("name", "kind", "start_time", "end_time", "events", "links",
                  "dropped_attributes", "dropped_events", "dropped_links"):
        assert getattr(view, field) == getattr(spans[0], field)
    assert dict(view.attributes) == {**{key: value for key, value in original_attributes.items()
                                      if key not in removed}, **fields}
    assert dict(spans[0].attributes) == original_attributes
    assert adapter.force_flush(timeout_millis=174) is False
    assert delegate.flush_timeouts == [174]
    adapter.shutdown()
    assert delegate.shutdown_count == 1


@pytest.mark.parametrize("unowned_field", ["gen_ai.provider.name", "input.mime_type", "application.keep"])
def test_shipped_adapter_rejects_unowned_removal_without_export(shipped_tool_adapter, monkeypatch, unowned_field):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    _, exporter_class = shipped_tool_adapter
    spans, _, _ = _real_sdk_tool_batch("successful_null")
    before = [dict(span.attributes) for span in spans]
    delegate = _RecordingSpanExporter(SpanExportResult.SUCCESS)
    adapter = exporter_class(delegate, lambda span: ({}, {unowned_field}))
    with pytest.raises(ValueError, match="limited to owned tool content"):
        adapter.export(spans)
    assert delegate.batches == []
    assert [dict(span.attributes) for span in spans] == before


class _CapturingHTTPSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.posts = []
        self.close_count = 0

    def send(self, request, **kwargs):
        assert request.method == "POST"
        self.posts.append((request.url, request.body))
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response.raw = io.BytesIO(b"")
        return response

    def close(self):
        self.close_count += 1
        super().close()


def _http_exporter(session):
    return OTLPSpanExporter(
        endpoint="http://127.0.0.1:1/v1/traces", session=session,
        compression=Compression.NoCompression, timeout=1,
        headers={"test.adapter": "public-session-injection"},
    )


def _serialized_request(session):
    assert len(session.posts) == 1
    url, body = session.posts[0]
    assert url == "http://127.0.0.1:1/v1/traces"
    assert isinstance(body, bytes)
    message = ExportTraceServiceRequest()
    message.ParseFromString(body)
    return message


@pytest.mark.parametrize("outcome", ["successful_null", "error_no_result"])
def test_shipped_adapter_real_otlp_preserves_metadata_and_selective_content(shipped_tool_adapter, monkeypatch, outcome):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    def no_network(self, request, **kwargs):
        pytest.fail("Exporter bypassed the injected public fake Session")
    monkeypatch.setattr(requests.Session, "send", no_network)
    _, exporter_class = shipped_tool_adapter
    spans, fields, removed = _real_sdk_tool_batch(outcome)
    baseline_session, enriched_session = _CapturingHTTPSession(), _CapturingHTTPSession()
    baseline = _http_exporter(baseline_session)
    adapter = exporter_class(_http_exporter(enriched_session),
                             lambda span: _safe_sdk_carrier_fields(span, removed))
    try:
        assert baseline.export(spans) is SpanExportResult.SUCCESS
        assert adapter.export(spans) is SpanExportResult.SUCCESS
        before, after = _serialized_request(baseline_session), _serialized_request(enriched_session)
        assert len(after.resource_spans) == 1
        scope = after.resource_spans[0].scope_spans[0]
        assert len(scope.spans) == 2
        tool, unrelated = scope.spans
        assert tool.trace_id == spans[0].context.trace_id.to_bytes(16, "big")
        assert tool.span_id == spans[0].context.span_id.to_bytes(8, "big")
        assert tool.parent_span_id == spans[0].parent.span_id.to_bytes(8, "big")
        assert tool.dropped_attributes_count == spans[0].dropped_attributes > 0
        assert tool.dropped_events_count == spans[0].dropped_events > 0
        assert tool.dropped_links_count == spans[0].dropped_links > 0
        assert tool.events[0].dropped_attributes_count == spans[0].events[0].dropped_attributes > 0
        assert tool.links[0].dropped_attributes_count == spans[0].links[0].dropped_attributes > 0
        attributes = {item.key: getattr(item.value, item.value.WhichOneof("value"))
                      for item in tool.attributes}
        for key, value in fields.items():
            assert attributes[key] == value
        assert removed.isdisjoint(attributes)
        assert attributes["application.keep"] == "preserved"
        if outcome == "successful_null":
            assert json.loads(attributes["output.value"]) is None
            assert json.loads(attributes["gen_ai.output.messages"])[0]["parts"][0]["response"] is None
        else:
            assert attributes["error.type"] == "LookupError"
            assert tool.status.code == 2
            assert {"gen_ai.tool.call.result", "gen_ai.output.messages", "output.value"}.isdisjoint(attributes)
        assert unrelated == before.resource_spans[0].scope_spans[0].spans[1]
        for message in (before, after):
            for resource_spans in message.resource_spans:
                for scope_spans in resource_spans.scope_spans:
                    for span in scope_spans.spans:
                        span.ClearField("attributes")
        assert after == before
        assert adapter.force_flush(timeout_millis=183) is True
    finally:
        baseline.shutdown()
        adapter.shutdown()
    assert baseline_session.close_count == 1
    assert enriched_session.close_count == 1
