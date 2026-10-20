"""Keep the supplied agent audit evidence reproducible from its fixture."""

import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


FIXTURE = Path(__file__).parent / "python/model-directed-agent"
REFERENCE = re.compile(r"(?<![\w/])((?:[\w.-]+/)*[\w.-]+\.(?:py|md|txt))(?::(\d+)(?:-(\d+))?)?")


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
            for filename, first, last in REFERENCE.findall(value):
                source = FIXTURE / filename
                assert source.is_file(), (name, field, filename)
                if first:
                    assert 1 <= int(first) <= int(last or first) <= len(source.read_text().splitlines()), (name, field, value)

    inspect(audit)
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
