"""Deterministic checks for the default local application-log contract."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
LANGUAGES = SKILLS / "otel-instrument" / "references" / "languages"


def _read(path: Path) -> str:
    assert path.is_file(), f"Expected file not found: {path}"
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    return " ".join(_read(path).split())


def test_audit_selects_missing_supported_local_logs_by_default() -> None:
    audit = _normalized(SKILLS / "otel-audit" / "SKILL.md")
    instrument = _normalized(SKILLS / "otel-instrument" / "SKILL.md")

    for term in (
        "local Observer provider/exporter/bridge",
        "`required` with `instrument_mode: default`",
        "explicitly disabled",
        "operator-owned exporter",
    ):
        assert term in audit

    for term in (
        "Default Local Application Log Export",
        "`OTEL_LOGS_EXPORTER=none` disables",
        "exactly one bridge/export path",
        "Obstudio-to-Splunk cloud forwarding is traces and metrics only",
    ):
        assert term in instrument


def test_all_language_guides_define_local_logs_and_cloud_boundary() -> None:
    expected = {
        "python.md": (
            "LoggerProvider",
            "LoggingInstrumentor",
            "BatchLogRecordProcessor",
            "OTLPLogExporter",
        ),
        "node.md": (
            "ConsoleInstrumentation",
            "BatchLogRecordProcessor",
            "OTLPLogExporter",
            "@opentelemetry/exporter-logs-otlp-proto",
            "logRecordProcessors",
        ),
        "java.md": (
            "OTEL_LOGS_EXPORTER",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            "Logback",
            "Log4j",
            "experimental.capture-mdc-attributes",
        ),
        "go.md": (
            "sdk/log",
            "otlploghttp",
            "otelslog",
            "SetLoggerProvider",
        ),
    }

    for filename, language_terms in expected.items():
        guide = _normalized(LANGUAGES / filename)
        for term in (
            "OTEL_LOGS_EXPORTER",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            "/v1/logs",
            "cloud forwarding remains traces and metrics only",
            *language_terms,
        ):
            assert term in guide, f"{filename} is missing {term!r}"


def test_language_guides_reject_generic_cloud_header_inheritance() -> None:
    for filename in ("python.md", "node.md", "go.md"):
        guide = _normalized(LANGUAGES / filename)
        for term in (
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
            "move generic OTLP headers to trace/metric signal variables",
            "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
            "select the official exporter matching",
        ):
            assert term in guide, f"{filename} is missing {term!r}"

    java = _normalized(LANGUAGES / "java.md")
    assert "Move a direct-cloud `OTEL_EXPORTER_OTLP_ENDPOINT`" in java
    assert "trace- and metric-specific endpoint/header settings" in java


def test_shell_wrappers_only_add_local_log_configuration_for_otlp() -> None:
    python = _read(LANGUAGES / "python.md")
    java = _read(LANGUAGES / "java.md")

    assert 'if [ "$OTEL_LOGS_EXPORTER" = otlp ]; then' in python
    assert "every other explicit\noperator-owned exporter bypass" in python
    assert 'if [ "$OTEL_LOGS_EXPORTER" = otlp ]; then' in java
    assert 'if [ "$logs_exporter" = otlp ]; then' in java
    assert '"${otel_log_args[@]}"' in java
    assert "including\n`OTEL_LOGS_EXPORTER=none` -- use the precedence-aware" in java
    assert 'OTEL_LOGS_EXPORTER="${OTEL_LOGS_EXPORTER:-otlp}" \\' not in java


def test_language_rubrics_grade_the_default_local_log_contract() -> None:
    rubric_paths = (
        ROOT / "evals/python/flask-basic/eval/qual/instrument.json",
        ROOT / "evals/node/express-basic/eval/qual/instrument.json",
        ROOT / "evals/java/springboot-basic/eval/qual/instrument.json",
        ROOT / "evals/go/kvstore/eval/qual/instrument.json",
    )

    for path in rubric_paths:
        definition = json.loads(_read(path))
        contract = " ".join(definition["rubric"])
        assert "local Observer" in contract
        assert "OTEL_LOGS_EXPORTER=none" in contract
        assert "cloud" in contract


def test_audit_rubrics_grade_the_default_local_log_gap() -> None:
    rubric_paths = (
        ROOT / "evals/python/flask-basic/eval/qual/audit.json",
        ROOT / "evals/node/express-basic/eval/qual/audit.json",
        ROOT / "evals/java/springboot-basic/eval/qual/audit.json",
        ROOT / "evals/go/kvstore/eval/qual/audit.json",
    )

    for path in rubric_paths:
        definition = json.loads(_read(path))
        contract = " ".join(definition["rubric"])
        assert "required default gap" in contract
        assert "local Observer" in contract
        assert "cloud forwarding limited to traces and metrics" in contract


def test_runtime_evals_query_local_application_logs() -> None:
    runtime_paths = (
        ROOT / "evals/python/flask-basic/eval/runtime/instrument.json",
        ROOT / "evals/node/express-basic/eval/runtime/instrument.json",
        ROOT / "evals/go/kvstore/eval/runtime/instrument.json",
    )

    for path in runtime_paths:
        definition = json.loads(_read(path))
        endpoints = definition["checks"][0]["expect"]["endpoints"]
        assert any(endpoint.get("url") == "/api/query/logs" for endpoint in endpoints)
