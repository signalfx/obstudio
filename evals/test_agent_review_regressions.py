"""Keep the supplied agent audit evidence reproducible from its fixture."""

import json
from pathlib import Path
import re

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
