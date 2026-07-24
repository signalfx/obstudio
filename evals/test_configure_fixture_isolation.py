from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pytest_codex_evals.runner import (
    capture_source_tree,
    materialize_fixture_workspace,
)


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "evals" / "dashboards"
CANONICAL = FIXTURES / "checkout-configure"
AUDIT_ONLY = FIXTURES / "checkout-configure-audit-only"
PARTIAL_OVERLAY = FIXTURES / "checkout-configure-partial-overlay"


def _visible_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _canonical_digest(path: Path) -> str:
    payload = json.loads(path.read_bytes())
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def test_configure_eval_fixture_roots_expose_only_intended_inputs() -> None:
    assert _visible_files(CANONICAL) == {
        "eval/qual/configure.json",
        "otel-audit.json",
    }
    assert _visible_files(AUDIT_ONLY) == {
        "eval/qual/configure.json",
        "otel-audit-source-only.json",
    }
    assert _visible_files(PARTIAL_OVERLAY) == {
        "eval/qual/configure.json",
        "otel-audit-source-only.json",
        "otel-selection-partial.json",
    }


@pytest.mark.parametrize(
    ("fixture", "expected"),
    (
        (CANONICAL, {"otel-audit.json"}),
        (AUDIT_ONLY, {"otel-audit-source-only.json"}),
        (
            PARTIAL_OVERLAY,
            {"otel-audit-source-only.json", "otel-selection-partial.json"},
        ),
    ),
)
def test_configure_eval_agent_sees_only_intended_inputs(
    tmp_path: Path,
    fixture: Path,
    expected: set[str],
) -> None:
    destination = tmp_path / fixture.name
    materialize_fixture_workspace(capture_source_tree(fixture), destination)

    assert _visible_files(destination) == expected


def test_configure_eval_definitions_match_their_fixture_roots() -> None:
    expected = (
        (CANONICAL, "checkout-configure", "generate"),
        (AUDIT_ONLY, "checkout-configure-audit-only", "accepted-source-metric"),
        (
            PARTIAL_OVERLAY,
            "checkout-configure-partial-overlay",
            "partial-overlay-fails-closed",
        ),
    )
    for fixture, service, prompt_id in expected:
        definition = json.loads(
            (fixture / "eval" / "qual" / "configure.json").read_bytes()
        )
        assert definition["service"] == service
        assert [prompt["id"] for prompt in definition["prompts"]] == [prompt_id]


def test_configure_canonical_audit_copies_are_exact_and_selection_is_bound() -> None:
    audit_only = AUDIT_ONLY / "otel-audit-source-only.json"
    partial_audit = PARTIAL_OVERLAY / "otel-audit-source-only.json"
    selection = json.loads(
        (PARTIAL_OVERLAY / "otel-selection-partial.json").read_bytes()
    )

    assert audit_only.read_bytes() == partial_audit.read_bytes()
    audit = json.loads(partial_audit.read_bytes())
    assert selection["audit_id"] == audit["meta"]["audit_id"]
    assert selection["audit_sha256"] == _canonical_digest(partial_audit)


def test_configure_primary_fixture_uses_canonical_audit_json() -> None:
    audit = json.loads((CANONICAL / "otel-audit.json").read_bytes())
    definition = json.loads(
        (CANONICAL / "eval" / "qual" / "configure.json").read_bytes()
    )
    prompt = definition["prompts"][0]["task"]
    rubric = " ".join(definition["rubric"])

    assert audit["schema_version"] == 2
    assert audit["kind"] == "otel-audit"
    assert audit["current_instrumentation"]["metrics"]
    assert "otel-audit.json" in prompt
    assert "otel-audit.json" in rubric
    assert "otel-report.md" not in prompt
    assert ".observe/otel.md" not in rubric
