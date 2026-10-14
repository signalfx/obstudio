"""Check source/probe and counterexample integrity for decorator-gate rubrics."""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import textwrap
from pathlib import Path

import jsonschema
import pytest

from pytest_codex_evals.definitions.rubric import RubricEvalDefinition


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evals/python/ai-assistant-demo"
INPUTS = FIXTURE / "eval/inputs"
EVIDENCE = INPUTS / "per-function-decorator-gate-evidence.json"
FULL_CONFORMANCE_EVIDENCE = INPUTS / "per-function-full-conformance-evidence.json"


def _evidence():
    return json.loads(EVIDENCE.read_text())


def _pointer(value, pointer):
    for part in pointer.lstrip("/").split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def _spans(probe):
    return [
        span
        for payload in probe["wire_otlp"]
        for resource in payload["resourceSpans"]
        for scope in resource["scopeSpans"]
        for span in scope["spans"]
    ]


def _attributes(span):
    return {item["key"]: item["value"].get("stringValue")
            for item in span["attributes"]}


def test_original_demo_inventory_has_actual_coroutines_and_async_generator():
    evidence = _evidence()
    expected = {
        "agent.call_model": ("llm", "coroutine"),
        "agent.run_agent": ("agent", "async_generator"),
        "tools.execute_tool": ("tool", "coroutine"),
        "tools.retrieve_documents": ("retriever", "coroutine"),
    }
    files = {file["path"]: file for file in evidence["demo_files"]}
    assert len(evidence["functions"]) == len(expected)
    for function in evidence["functions"]:
        file = files[function["path"]]
        assert hashlib.sha256(file["source"].encode()).hexdigest() == file["sha256"]
        node = next(node for node in ast.parse(file["source"]).body
                    if getattr(node, "name", None) == function["qualified_name"].split(".")[1])
        assert isinstance(node, ast.AsyncFunctionDef)
        shape = ("async_generator" if any(isinstance(child, ast.Yield)
                                         for child in ast.walk(node)) else "coroutine")
        assert (function["span_type"], shape) == expected[function["qualified_name"]]
        assert function["shape"] == shape
        assert (function["line_start"], function["line_end"]) == (node.lineno, node.end_lineno)
        assert function["source_excerpt"] == ast.get_source_segment(file["source"], node)
        assert function["source_sha256"] == file["sha256"]
        assert function["existing_genai_producer"] is None
        assert not node.decorator_list
    docs = evidence["document_source_snapshot"]
    assert hashlib.sha256(docs["raw_json"].encode()).hexdigest() == docs["sha256"]
    assert all({"id", "title", "text"} <= doc.keys() for doc in json.loads(docs["raw_json"]))


def test_sdk_and_preservation_excerpts_are_lossless_not_answer_replacements():
    evidence = _evidence()
    for key in ("dated_sdk_fact_extract", "preservation_cases"):
        extract = evidence[key]
        original = FIXTURE / extract["origin_file"]
        assert hashlib.sha256(original.read_bytes()).hexdigest() == extract["origin_sha256"]
        source = json.loads(original.read_text())
        for pointer, value in extract["sections"].items():
            assert value == _pointer(source, pointer)
    for key in ("installed_source_receipt", "native_public_probe"):
        receipt = evidence[key]
        assert hashlib.sha256(receipt["raw_json"].encode()).hexdigest() == receipt["origin_sha256"]
        assert isinstance(json.loads(receipt["raw_json"]), dict)


def test_native_probe_preserves_real_negative_and_positive_capture_facts():
    probe = json.loads(_evidence()["native_public_probe"]["raw_json"])
    spans = _spans(probe)
    assert len(spans) == 13  # This immutable capture predates the later oversized-input probe.
    unsafe = next(span for span in spans if span["name"] == "execute_tool unsafe-mapped-tool")
    assert "RAW_PRIVATE_INPUT_OUTPUT_SENTINEL" in _attributes(unsafe)["gen_ai.tool.call.arguments"]
    for name in ("execute_tool null-tool", "execute_tool error-tool"):
        span = next(span for span in spans if span["name"] == name)
        assert json.loads(_attributes(span)["gen_ai.tool.call.result"]) == {"value": ""}
    retriever = next(span for span in spans if span["name"] == "retrieval demo-shaped-retriever")
    documents = json.loads(_attributes(retriever)["gen_ai.retrieval.documents"])
    assert documents[0]["metadata"] == {}
    original_documents = next(item["demo_shaped_retriever_original_return"]
                              for item in probe["behavior"]
                              if "demo_shaped_retriever_original_return" in item)
    assert json.loads(documents[0]["content"]) == original_documents[0]
    safe_retriever = next(span for span in spans if span["name"] == "retrieval safe-retriever")
    safe_result = next(item["safe_agent_result"] for item in probe["behavior"]
                       if "safe_agent_result" in item)
    assert json.loads(_attributes(safe_retriever)["gen_ai.retrieval.documents"]) == safe_result["documents"]
    for captured in (retriever, safe_retriever):
        native_query = _attributes(captured)["gen_ai.retrieval.query.text"]
        bound_arguments = json.loads(native_query)
        assert bound_arguments == {"query": "safe query"}
        assert native_query != bound_arguments["query"]
    generators = [span for span in spans if span["name"] == "invoke_agent bounded-safe-generator"]
    assert len(generators) == 2  # Ordinary exhaustion and early close both emitted.
    leaf = next(span for span in spans if span["name"] == "execute_tool safe-tool")
    current = next(item for item in probe["contexts_during_business_call"]
                   if item["operation"] == "safe-tool")
    assert current["span_id"] == base64.b64decode(leaf["parentSpanId"]).hex()
    assert current["span_id"] != base64.b64decode(leaf["spanId"]).hex()
    model = next(span for span in spans if span["name"] == "chat synthetic-model")
    assert not {"gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
                "gen_ai.response.finish_reasons"} & _attributes(model).keys()
    for operation in ("safe-model", "safe-retriever"):
        context = next(item for item in probe["contexts_during_business_call"]
                       if item["operation"] == operation)
        assert context["span_id"] == current["span_id"]
        native = model if operation == "safe-model" else next(
            span for span in spans if span["name"] == "retrieval safe-retriever")
        assert context["span_id"] == base64.b64decode(native["parentSpanId"]).hex()
        assert context["span_id"] != base64.b64decode(native["spanId"]).hex()
        assert context["trace_id"] == base64.b64decode(native["traceId"]).hex()


def test_field_good_candidates_differ_in_function_producer_evidence():
    evidence = _evidence()
    candidates = evidence["verification_candidates"]
    assert [item["id"] for item in candidates] == ["candidate-A", "candidate-B", "candidate-C"]
    for candidate in candidates:
        compile(candidate["source_snapshot"], candidate["id"], "exec")  # Syntax only, no imports/execution.
        function = next(node for node in ast.parse(candidate["source_snapshot"]).body
                        if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute_tool")
        body_has_helper = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                              and node.func.id == "start_splunk_ao_span" for node in ast.walk(function))
        if candidate["id"] in ("candidate-A", "candidate-B"):
            assert not function.decorator_list and body_has_helper
        else:
            assert len(function.decorator_list) == 1 and not body_has_helper
    assert candidates[0]["decision_artifact"] is None
    assert candidates[1]["decision_artifact"] == candidates[2]["decision_artifact"]
    attrs = evidence["synthetic_field_example"]["attributes"]
    for key in ("gen_ai.input.messages", "gen_ai.output.messages"):
        message = json.loads(attrs[key])[0]
        assert message["parts"][0]["type"] == "text"
    for existing in evidence["preservation_cases"]["sections"].values():
        assert any(isinstance(node, ast.With) for node in ast.walk(ast.parse(existing["source_snapshot"])))
    assert not {"expected", "verdict", "pass"} & evidence.keys()


def test_full_conformance_packet_preserves_public_source_and_business_identity():
    evidence = json.loads(FULL_CONFORMANCE_EVIDENCE.read_text())
    historical = _evidence()["dated_sdk_fact_extract"]["sections"]["/helper_public_api"]
    helper = evidence["sdk_source"]["helper"]
    assert helper["file_sha256"] == historical["package_source_sha256"]
    assert helper["source_excerpt"].strip() == historical["package_function_source_snapshot"].strip()
    receipts = [
        *evidence["later_source_snapshot"].values(),
        *evidence["sdk_source"].values(),
        *evidence["public_otel_source"].values(),
    ]
    for receipt in receipts:
        if isinstance(receipt, dict) and "source_excerpt" in receipt:
            assert hashlib.sha256(receipt["source_excerpt"].encode()).hexdigest() == receipt["excerpt_sha256"]
            assert len(receipt["source_excerpt"].splitlines()) == receipt["line_end"] - receipt["line_start"] + 1
    helper_function = ast.parse(helper["source_excerpt"]).body[0]
    assert [argument.arg for argument in helper_function.args.args] == ["splunk_ao_span"]
    creator = next(node for node in ast.walk(helper_function)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "start_as_current_span")
    assert len(creator.args) == 1 and not creator.keywords
    fields = ast.parse(evidence["sdk_source"]["llm_output_field"]["source_excerpt"]).body[0]
    output = next(node for node in fields.body if isinstance(node, ast.AnnAssign)
                  and isinstance(node.target, ast.Name) and node.target.id == "output")
    assert isinstance(output.annotation, ast.Name) and output.annotation.id == "Message"
    assert any(keyword.arg == "default_factory" and isinstance(keyword.value, ast.Lambda)
               for keyword in output.value.keywords)
    conversion = evidence["sdk_source"]["llm_output_conversion"]["source_excerpt"]
    assert isinstance(ast.parse(textwrap.dedent(conversion)).body[0].body[-1], ast.Raise)
    for key in ("tracer_start_span_signature", "tracer_start_as_current_span_signature"):
        signature = evidence["public_otel_source"][key]["source_excerpt"].split('"""', 1)[0]
        function = ast.parse(textwrap.dedent(signature) + "    pass\n").body[0]
        assert {"kind", "attributes"} <= {argument.arg for argument in function.args.args}
    values = evidence["synthetic_business_values"]
    call = values["tool_request_response"]["message"]["tool_calls"][0]
    assert call["id"] == values["tool_history_message"]["tool_call_id"]
    assert call["function"]["arguments"]["service"] == "inventory"
    assert all(case["stage"] == "before_valid_response" for case in values["failure_scenarios"])
    for schema in evidence["message_schema_excerpts"].values():
        definitions = schema["definitions"]
        assert definitions["ToolCallRequestPart"]["properties"]["type"]["const"] == "tool_call"
        assert definitions["ToolCallResponsePart"]["properties"]["type"]["const"] == "tool_call_response"
        response_schema = definitions["ToolCallResponsePart"]
        response = json.loads(values["tool_history_message"]["content"])
        part = {"type": "tool_call_response", "id": call["id"], "response": response}
        validator = jsonschema.Draft202012Validator(response_schema)
        assert not list(validator.iter_errors(part))
        content_only = {**part, "content": part["response"]}
        del content_only["response"]
        errors = list(validator.iter_errors(content_only))
        assert any(error.validator == "required" and "response" in error.validator_value
                   for error in errors)
    assert not {"expected", "verdict", "pass", "chosen_pattern"} & evidence.keys()


@pytest.mark.parametrize("skill,suffix", [
    ("otel-audit", "audit"), ("otel-instrument", "instrument"), ("otel-verify", "verify"),
])
def test_matching_focused_cases_compile_current_harness_schema(skill, suffix):
    path = FIXTURE / f"eval/qual/per-function-decorator-{suffix}.json"
    data = json.loads(path.read_text())
    definition = RubricEvalDefinition.model_validate({
        **data, "id": f"python/ai-assistant-demo/qual/per-function-decorator-{suffix}",
        "language": "python", "service": "ai-assistant-demo", "definition_path": path,
        "fixture_dir": FIXTURE,
    })
    assert definition.skill == skill
    assert len(definition.rubric) == 6
    assert len(definition.prompts) == 1
    prompt = definition.prompts[0]
    assert prompt.id == f"per-function-decorator-{suffix}"
    assert prompt.eval_inputs == [
        "eval/inputs/per-function-decorator-gate-evidence.json",
        "eval/inputs/per-function-full-conformance-evidence.json",
    ]
    assert (FIXTURE / prompt.eval_inputs[0]).resolve() == EVIDENCE.resolve()
    assert (FIXTURE / prompt.eval_inputs[1]).resolve() == FULL_CONFORMANCE_EVIDENCE.resolve()
