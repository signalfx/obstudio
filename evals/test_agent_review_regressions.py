"""Keep the supplied agent audit evidence reproducible from its fixture."""

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


FIXTURE = Path(__file__).parent / "python/model-directed-agent"
SANITIZER_SAMPLES = Path(__file__).parent / "fixtures/agent_sanitizers.json"
REFERENCE = re.compile(r"(?<![\w/])((?:[\w.-]+/)*[\w.-]+\.(?:py|md|txt))(?::(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*))?")


@pytest.mark.parametrize("name", ["agent-audit", "prior-audit"])
def test_supplied_audit_source_references_exist_and_fit_line_bounds(name):
    audit = json.loads((FIXTURE / "eval/inputs" / f"{name}.json").read_text())

    def inspect(value, field=""):
        if isinstance(value, dict):
            for key, item in value.items():
                inspect(item, key)
        elif isinstance(value, list):
            for item in value:
                inspect(item, field)
        elif isinstance(value, str) and field in {"source", "evidence", "config_evidence", "runner"}:
            for filename, locations in REFERENCE.findall(value):
                source = FIXTURE / filename
                assert source.is_file(), (name, field, filename)
                for location in locations.split(",") if locations else []:
                    first, _, last = location.partition("-")
                    assert 1 <= int(first) <= int(last or first) <= len(source.read_text().splitlines()), (name, field, value)

    inspect(audit)
    serving = next(node for node in ast.walk(ast.parse((FIXTURE / "app.py").read_text()))
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and isinstance(node.func.value, ast.Name) and node.func.value.id == "app"
                   and node.func.attr == "run")
    entry = next(item for item in audit["evidence"] if item["check"] == "Entry point")
    cited = set()
    for filename, locations in REFERENCE.findall(entry["source"]):
        if filename == "app.py":
            for location in locations.split(",") if locations else []:
                first, _, last = location.partition("-")
                cited.update(range(int(first), int(last or first) + 1))
    assert serving.lineno in cited, (name, "Entry point citation misses app.run", serving.lineno)
    for environment in audit["verification"]["environments"]:
        assert "historical_check.py" in environment["runner"]


@pytest.mark.parametrize("layout", ["canonical", "isolated", "missing"])
def test_gateway_contract_resolver_discovery_and_preflight(tmp_path, layout):
    root = Path(__file__).resolve().parents[1]
    fixture = root / "evals/python/agent-connection-demo"
    resolver = root / "skills/otel-instrument/scripts/resolve_ao_resources.py"
    if layout == "canonical":
        service = fixture
    else:
        service = tmp_path / "service"
        service.mkdir()
        for name in ["gateway_contract_check.py", "probe.py"]:
            shutil.copy2(fixture / name, service / name)
        if layout == "isolated":
            staged = tmp_path / ".agents/skills/otel-instrument/scripts"
            staged.mkdir(parents=True)
            shutil.copy2(resolver, staged / resolver.name)
    check = service / "gateway_contract_check.py"
    tree = ast.parse(check.read_text())
    discovery = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "default_resolver")
    namespace = {"__file__": str(check), "Path": Path}
    exec(compile(ast.Module(body=[discovery], type_ignores=[]), str(check), "exec"), namespace)
    found = namespace["default_resolver"]()
    if layout == "missing":
        assert found is None
        result = subprocess.run([sys.executable, str(check)], capture_output=True, text=True, timeout=5)
        assert result.returncode == 2
        assert "provide --resolver" in result.stderr
        assert "Traceback" not in result.stderr
        assert "subTest" not in result.stderr
    else:
        assert found.is_file()
        assert found.read_bytes() == resolver.read_bytes()


def test_model_directed_application_regressions_use_real_sdk_and_stdlib_logs():
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("OTEL_") and key.lower() not in {
                       "http_proxy", "https_proxy", "all_proxy", "no_proxy",
                   }}
    environment["NETRC"] = os.devnull
    result = subprocess.run(
        [sys.executable, str(FIXTURE / "checks/review_regressions.py")],
        env=environment, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    environment["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:9"
    result = subprocess.run(
        [sys.executable, "-c", (
            "import logging,sys\n"
            f"sys.path.insert(0,{str(FIXTURE)!r})\n"
            "import otel_setup\n"
            "handlers=tuple(logging.getLogger().handlers)\n"
            "factory=logging.getLogRecordFactory()\n"
            "install,shutdown=otel_setup.configure_opentelemetry()\n"
            "shutdown();install()\n"
            "assert tuple(logging.getLogger().handlers)==handlers\n"
            "assert logging.getLogRecordFactory() is factory\n"
        )], env=environment, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("case", [
    "test_public_wrapper_and_request_hook_use_actual_wire_binding",
    "test_cached_restart_forwards_without_resource_lookup",
    "test_wire_oracle_still_rejects_missing_headers_and_resource_mismatch",
    "test_public_views_cannot_rewrite_identity_topology_or_operations",
    "test_split_wire_batches_are_collected_for_the_native_turn",
    "test_missing_overlapping_and_duplicate_spans_are_rejected",
    "test_same_pid_selects_the_native_turn_from_a_multi_turn_batch",
    "test_complete_unbound_turn_allows_another_recovery_attempt",
])
def test_connection_probe_public_wire_contract(case):
    check = Path(__file__).parent / "python/agent-connection-demo/checks/probe_regressions.py"
    result = subprocess.run(
        [sys.executable, str(check), f"ProbeTests.{case}"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_content_counterexamples_retain_observed_representation_failures():
    fixture = Path(__file__).parent / "python/existing-otel-agent-demo"
    corpus = json.loads((fixture / "eval/inputs/content-counterexamples.json").read_text())
    cases = {case["id"]: case for case in corpus["cases"]}
    assert json.loads(cases["quoted-email"]["value"]) == "reader@example.invalid"
    assert "reasoning=hidden-value" in json.loads(cases["quoted-labels"]["value"])
    assert "hidden_reasoning=thought-sentinel" in cases["labelled-protected-values"]["value"]
    for name in ("typed-reasoning", "json-typed-reasoning"):
        value = cases[name]["value"]
        if isinstance(value, str):
            value = json.loads(value)
        assert value["parts"] == [{"type": "reasoning", "content": "hidden-reasoning-sentinel"}]
    recipe = cases["aggregate-unicode"]["value_recipe"]
    value = {**recipe["prefix"], **{f"{recipe['field_prefix']}{index}": recipe["unit"] * recipe["repeat"]
                                 for index in range(recipe["field_count"])}}
    encoded = json.dumps(value, ensure_ascii=False).encode()
    assert len(encoded) > cases["aggregate-unicode"]["max_serialized_attribute_bytes"]
    assert corpus["malformed_known_parts"] == [
        {"type": "text"}, {"type": "text", "content": 123},
        {"type": "tool_call", "name": 123}, {"type": "tool_call_response"},
    ]


@pytest.mark.parametrize("snapshot_index", range(4))
def test_archived_sanitizer_failures_replay_from_tracked_data(snapshot_index):
    source = json.loads(SANITIZER_SAMPLES.read_text())["failing_sanitizers"][snapshot_index]
    assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
    tree = ast.parse(source["text"])
    allowed = {
        "MAX_MESSAGES", "MAX_PARTS", "MAX_BYTES", "MAX_TEXT_BYTES", "MAX_ATTRIBUTE_BYTES",
        "MAX_DEPTH", "MAX_ITEMS", "SENSITIVE", "LABELLED", "_PRIVATE", "_LABEL", "_EMAIL",
        "EMAIL", "CREDENTIAL",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {item.id for target in node.targets for item in ast.walk(target) if isinstance(item, ast.Name)}
            if names and names <= allowed:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {"sanitize", "bounded"}:
            nodes.append(node)
    namespace = {"json": json, "re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), source["original_path"], "exec"), namespace)
    sanitize = namespace["sanitize"]
    if snapshot_index == 0:
        assert "HIDDEN_SENTINEL" in sanitize("hidden_reasoning=HIDDEN_SENTINEL; question=shipment")
        oversized = json.dumps({f"field_{index}": "a" * 2000 for index in range(16)})
        assert len(sanitize(oversized).encode()) > 8192
    elif snapshot_index == 1:
        for scalar in ('"reader@example.invalid"', '"token=fixture-secret;reasoning=hidden"'):
            assert sanitize(scalar) == scalar
    elif snapshot_index == 2:
        assert "thought-sentinel" in sanitize("hidden_reasoning=thought-sentinel")
        assert "hidden-sentinel" in sanitize("private_prompt=hidden-sentinel")
    else:
        reasoning = {"type": "reasoning", "content": "hidden-reasoning-sentinel"}
        assert "hidden-reasoning-sentinel" in json.dumps(sanitize(reasoning))
        assert "hidden-reasoning-sentinel" in sanitize(json.dumps(reasoning))


@pytest.mark.parametrize("source_index", range(2))
def test_fresh_genai_and_logs_samples_fix_exact_original_quoted_scalars(source_index):
    source = json.loads(SANITIZER_SAMPLES.read_text())["corrected_sanitizers"][source_index]
    assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
    tree = ast.parse(source["text"])
    constants = {"MAX_MESSAGES", "MAX_PARTS", "MAX_BYTES", "PROTECTED", "LABEL", "EMAIL",
                 "PRIVATE", "LABELLED", "PRIVATE_TOKEN", "OMIT"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {item.id for target in node.targets for item in ast.walk(target) if isinstance(item, ast.Name)}
            if names and names <= constants:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {"sanitize", "text", "utf8", "encode", "dumps"}:
            nodes.append(node)
    namespace = {"json": json, "re": re, "Any": object}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), source["filename"], "exec"), namespace)
    for scalar in ('"private-prompt-sentinel"', '"reader@example.invalid"', '"token=fixture-secret;reasoning=hidden"'):
        result = namespace["sanitize"](scalar)
        assert all(value not in str(result) for value in ("private-prompt-sentinel", "reader@example.invalid", "fixture-secret", "hidden"))
