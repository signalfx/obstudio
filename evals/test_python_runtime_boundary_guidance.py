from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_SKILL = REPO_ROOT / "skills" / "otel-audit" / "SKILL.md"
INSTRUMENT_SKILL = REPO_ROOT / "skills" / "otel-instrument" / "SKILL.md"
PYTHON_REFERENCE = (
    REPO_ROOT / "skills" / "otel-instrument" / "references" / "languages" / "python.md"
)
PROFILE_REFERENCE = (
    REPO_ROOT / "skills" / "references" / "organization-observability-profile.md"
)
CONSUMERS = REPO_ROOT / "skills" / "references" / "consumers.json"
CASE_ROOT = REPO_ROOT / "evals" / "python" / "python-runtime-boundaries"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def test_audit_covers_click_process_and_conda_boundaries() -> None:
    text = _read(AUDIT_SKILL)

    for phrase in (
        "organization-observability-profile.md",
        "Click does not choose trace lifetime",
        "fresh root trace per independent task",
        "fork versus spawn model",
        "one verification environment and scenario per",
        "Conda is an interpreter and package-environment boundary",
        "target `opentelemetry-instrument`",
    ):
        assert phrase in text


def test_instrumentation_has_organization_and_python_runtime_contracts() -> None:
    skill = _read(INSTRUMENT_SKILL)
    reference = _read(PYTHON_REFERENCE)
    normalized_reference = " ".join(reference.split())

    assert "organization-observability-profile.md" in skill
    assert "report conflicts" in skill.lower()
    for phrase in (
        "Click is only the command dispatcher",
        "distinct nonzero trace IDs",
        "Normalize dynamic command values through a source-owned allowlist",
        "A Gunicorn preload master must not construct OTel providers",
        "Standalone Uvicorn multi-worker uses a different process model",
        "Decode the OTLP payload or query the collector",
        "telemetry flushed after graceful worker termination",
        "Record Gunicorn and standalone Uvicorn as separate full-runtime scenarios",
        "Conda does not inherently prevent OpenTelemetry instrumentation",
        "conda run -n customer-python opentelemetry-instrument python app.py",
        "Do not silently replace it with `conda run -n customer-python python app.py`",
        "mark executable and telemetry proof `Not proven`",
    ):
        assert phrase in normalized_reference


def test_organization_profile_is_declared_for_both_consumers() -> None:
    profile = _read(PROFILE_REFERENCE)
    normalized_profile = " ".join(profile.split())
    consumers = json.loads(_read(CONSUMERS))

    assert consumers["organization-observability-profile.md"] == [
        "otel-audit",
        "otel-instrument",
    ]
    for phrase in (
        "evidence lead, not as runtime proof",
        "nearest `OBSERVABILITY.md`",
        "No profile may override credential safety",
        "Never place credentials",
    ):
        assert phrase in normalized_profile


def test_runtime_boundary_fixture_has_semantic_rubrics_for_both_skills() -> None:
    for filename, skill in (("audit.json", "otel-audit"), ("instrument.json", "otel-instrument")):
        definition = json.loads(_read(CASE_ROOT / "eval" / "qual" / filename))
        assert definition["skill"] == skill
        assert len(definition["rubric"]) == 5

    profile = _read(CASE_ROOT / "OBSERVABILITY.md")
    assert "customer-python-api" in profile
    assert "customer-python-cli" in profile
    assert "span link" in profile
