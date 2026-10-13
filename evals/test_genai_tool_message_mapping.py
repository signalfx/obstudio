from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest


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
