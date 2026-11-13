"""Deterministic checks for the default local application-log contract."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
LANGUAGES = SKILLS / "references" / "languages"


def _read(path: Path) -> str:
    assert path.is_file(), f"Expected file not found: {path}"
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    return " ".join(_read(path).split())


@pytest.mark.parametrize("skill", ["otel-audit", "otel-instrument", "otel-verify"])
def test_logging_language_references_reachable_in_isolated_skill_workspace(
    tmp_path: Path, skill: str,
) -> None:
    from pytest_codex_evals.definitions import SanityEvalCase
    from pytest_codex_evals.runner import prepare_side_workspace

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.txt").write_text("logging fixture\n", encoding="utf-8")
    case = SanityEvalCase(
        id=f"sample/service/{skill}/logging",
        base_id=f"sample/service/{skill}",
        prompt_id="logging",
        skill=skill,
        language="sample",
        service="service",
        task="Assess the existing logging path.",
        fixture_dir=fixture,
        checks=[],
    )
    side = tmp_path / "with_skill"
    prepare_side_workspace(ROOT, case, "with_skill", side)
    staged = side / ".agents" / "skills" / "references"
    entrypoint = _read(side / ".agents" / "skills" / skill / "SKILL.md")
    assert "../references/logging-readiness.md#report-readback" in entrypoint
    common = _read(staged / "logging-readiness.md")
    consumers = json.loads(_read(staged / "consumers.json"))
    help_result = subprocess.run(
        [sys.executable, "-I", str(staged / "scripts/observe_report.py"), "required-controls", "--help"],
        capture_output=True, text=True,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--ids" in help_result.stdout
    assert "--view" in help_result.stdout and "contracts" in help_result.stdout
    spec = importlib.util.spec_from_file_location(
        "isolated_contract_report_fixtures", SKILLS / "references/tests/observe_report_fixtures.py",
    )
    assert spec is not None and spec.loader is not None
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    audit = tmp_path / "otel-audit.json"
    audit.write_text(json.dumps(fixtures.sample_report()), encoding="utf-8")
    original = audit.read_bytes()
    contract_result = subprocess.run(
        [sys.executable, "-I", str(staged / "scripts/observe_report.py"), "required-controls", str(audit),
         "--ids", "OTEL-002", "--view", "contracts"],
        capture_output=True, text=True,
    )
    assert contract_result.returncode == 0, contract_result.stderr
    contracts = json.loads(contract_result.stdout)
    assert contracts["finding_ids"] == ["OTEL-002"]
    assert contracts["prerequisite_context_ids"] == ["OTEL-001"]
    assert contracts["shared_evidence_context"]["finding_ownership_inferred"] is False
    assert contracts["acceptance_controls_included"] is True
    assert contracts["coverage_evaluated"] is contracts["runtime_evaluated"] is False
    assert audit.read_bytes() == original
    source_help = subprocess.run(
        [sys.executable, "-I", str(staged / "scripts/observe_report.py"), "source-settings", "--help"],
        capture_output=True, text=True,
    )
    assert source_help.returncode == 0, source_help.stderr
    assert "--source" in source_help.stdout and "--report" in source_help.stdout
    targets = re.findall(r"\]\((languages/[^)]+)#logging-readiness-checks\)", common)
    expected = {f"languages/{lang}.md" for lang in ("java", "python", "go", "node")}
    assert set(targets) == expected
    for target in targets:
        canonical = SKILLS / "references" / target
        guide = staged / target
        assert guide.read_bytes() == canonical.read_bytes()
        text = _read(guide)
        assert "## Logging Readiness Checks" in text
        readiness = text.split("## Logging Readiness Checks", 1)[1].split("\n## ", 1)[0]
        normalized = " ".join(readiness.lower().split())
        assert "detected" in normalized and "installed" in normalized
        assert "common logging rules" in normalized
        runtime_terms = {
            "languages/java.md": ("executor", "thread-local", "asynchronous"),
            "languages/python.md": ("contextvars", "launcher", "process"),
            "languages/go.md": ("context.context", "goroutine", "cancellation"),
            "languages/node.md": ("callback", "precision", "constructor"),
        }
        assert all(term in normalized for term in runtime_terms[target])
        # The new rules resolve capabilities; concrete recipes stay in setup examples/evals.
        assert not re.search(
            r"\b(?:Flask|Spring|Express|Tomcat|BatchLogRecordProcessor|LogLimitsBuilder)\b",
            readiness,
        )
        assert not re.search(r"\b\d+(?:ms|milliseconds|seconds)\b", readiness)
        assert "fixture-disabled" not in readiness
        for relative in re.findall(r"`((?:\.\.?/)[^`\s]+\.md)`", text):
            assert (guide.parent / relative).is_file(), (skill, target, relative)
        assert skill in consumers[target]
    rules = set(re.findall(r"^## (LOG-[A-Z-]+) --", common, re.MULTILINE))
    assert rules == {
        "LOG-SPEC-CLOSURE", "LOG-RECORD", "LOG-CONTEXT", "LOG-ASYNC-HANDOFF",
        "LOG-EXCEPTION", "LOG-LIMITS", "LOG-DELIVERY", "LOG-DIAGNOSTICS",
        "LOG-VERIFY-FRESH",
    }
    for term in (
        "requirement", "owner", "source/config/default", "TraceId", "SpanId",
        "TraceFlags", "ObservedTimestamp", "SeverityText", "SDK-owned",
        "proof_level", "proof_mode", "unit+otlp", "full_runtime", "app_test",
        "trigger AND acceptance", "individually addressable", "operator",
        "partial_success", "N-R", "after decompression", "when possible and practical",
        "not_explorer_visible", "not_proven", "at most", "original sink",
        "CLI/environment precedence", "case-insensitive host", "original input",
        "### Report readback", "named assertion and its own raw",
    ):
        assert term in common
    assert "Flask" not in common and "BatchLogRecordProcessor" not in common
    assert "800ms" not in common and "1000ms" not in common
    common_words = " ".join(common.split())
    for term in (
        "Configuration value types", "accepted representation", "declared type",
        "non-negative integer milliseconds", "normative references imported",
        "promised operation/outcome", "scalar level applies", "prose caveat",
        "same process during active final logging/drain", "observable order", "not a particular tool-call order",
        "resolve and report their effective values or unlimited behavior",
        "future boundary test does not substitute for accessible configuration facts",
        "source binding preserves a requirement, not proof",
        "Capability and conditional acceptance branches",
        "positive, zero, negative, fractional, malformed",
        "start independently from every selected procedural",
        "Reconcile all IDs to the final allocation",
        "Record creation/update path and the final normalization helper",
        "Count the top-level value at depth 1",
        "byte arrays MUST be truncated counting each byte as one",
        "required-controls .observe/otel-audit.json",
        "evaluates no coverage or runtime",
        "Distinguish documented contract, implementation enforcement",
        "For deadlines, locate creation, propagation and consumption relative to retries",
        "Use three related worklists",
        "inventories audit promises only",
        "eligibility threshold rather than a cancellation deadline",
        "Classify each message's cause",
        "due to a limit",
        "Derive a named configuration inventory independently",
        "Key entries by owner/reader",
        "Separate reading from effective consumption",
        "Populate the value-case table for required settings now",
        "Mere transitive consumption does not require enumerating every unused SDK",
        "No unverified external capability closes a critical application",
        "explicit setting-name → case/default/outcome map",
        "unmatched_attribute_literals",
        "neither establishes an assertion",
        "Configuration validation warnings",
        "MUST synchronize calls",
        "disabled-SDK/retained-propagation conjunction",
        "--view contracts",
        "Promise to assertion",
        "Assertion to available path",
        "source pointers do not prove repair/producer sufficiency",
        "Without an audit, perform the same inspection",
        "actual relevant emitted form",
        "outside-context control, not omitted transfer",
    ):
        assert term in common_words
    assert "https://opentelemetry.io/docs/specs/otel/configuration/common/" in common
    if skill == "otel-audit":
        instructions = _read(side / ".agents" / "skills" / skill / "SKILL.md")
        assert "Judge the completed allocation, not draft chronology" in instructions
        assert "promised operations/outcomes" in instructions
        assert "IDs, environments and scalar proof level" in instructions
    if skill == "otel-instrument":
        instructions = _read(side / ".agents" / "skills" / skill / "SKILL.md")
        assert "Captured framework/container records" in instructions
        assert "supported" in instructions and "logging-only sanitizer" in instructions
        assert "another audit merely" in instructions
        assert "Before serializing logging verdicts" in instructions
        assert "logging-readiness.md#report-readback" in instructions
        assert "complete independent reconciliation remains valid afterward" in instructions

    if skill == "otel-verify":
        instructions = _read(side / ".agents" / "skills" / skill / "SKILL.md")
        assert "assess completeness rather than chronology alone" in instructions
        assert "named assertion and raw outcome/receipt" in instructions
        assert "stale audit/instrumentation success" in instructions
        assert "logging-readiness.md#report-readback" in instructions


@pytest.mark.parametrize("language", ["java", "python", "go", "node"])
def test_previous_language_reference_path_forwards_to_canonical_guide(language: str) -> None:
    previous = SKILLS / "otel-instrument" / "references" / "languages" / f"{language}.md"
    target = re.search(r"\]\(([^)]+)\)", _read(previous))
    assert target is not None
    canonical = LANGUAGES / f"{language}.md"
    assert (previous.parent / target.group(1)).resolve() == canonical.resolve()


def _fenced_code_after(path: Path, marker: str, language: str) -> str:
    section = _read(path).split(marker, 1)[1]
    return section.split(f"```{language}\n", 1)[1].split("\n```", 1)[0]


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def test_dependency_install_examples_apply_checked_candidates() -> None:
    for filename, command, separator in (
        ("node.md", "npm install", "@"),
        ("python.md", "pip install", "=="),
    ):
        guide = _read(LANGUAGES / filename)
        commands = re.findall(
            rf"^{command} [^\n]+", guide.replace("\\\n", " "), re.MULTILINE
        )
        assert commands, filename
        for install in commands:
            specs = shlex.split(install)[2:]
            assert specs, install
            for spec in specs:
                assert separator + "<resolved-" in spec, spec
                assert spec.endswith("-release>"), spec
                assert "latest" not in spec, spec


def _java_launcher(
    tmp_path: Path, *,
    approved_endpoint="http://127.0.0.1:4318/v1/logs",
    approved_protocol="http/protobuf",
) -> tuple[Path, dict[str, str]]:
    launcher = tmp_path / "otel-entrypoint.sh"
    source = _fenced_code_after(
        LANGUAGES / "java.md", "Save this as `otel-entrypoint.sh`:", "bash",
    ).replace(
        "approved_logs_endpoint=http://127.0.0.1:4318/v1/logs",
        f"approved_logs_endpoint={shlex.quote(approved_endpoint)}",
    ).replace(
        "approved_logs_protocol=http/protobuf",
        f"approved_logs_protocol={shlex.quote(approved_protocol)}",
    )
    _write_executable(launcher, source)
    subprocess.run(["/bin/sh", "-n", launcher], check=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "java", f"#!{sys.executable}\n" + """
import json, os, sys
print('JAVA_CALLED=1')
for key in ['OTEL_LOGS_EXPORTER', 'OTEL_EXPORTER_OTLP_LOGS_ENDPOINT']:
    print(key+'='+os.environ.get(key, '<unset>'))
for arg in sys.argv[1:]:
    print('ARG='+arg)
print('CONFIG='+json.dumps({key:value for key,value in os.environ.items()
    if key.startswith('OTEL_') or key in ['JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS']}))
""")
    return launcher, {
        "PATH": str(fake_bin), "JAVA_TOOL_OPTIONS": "",
        "JDK_JAVA_OPTIONS": "", "_JAVA_OPTIONS": "",
    }


def _java_configuration(result: subprocess.CompletedProcess) -> dict[str, str]:
    return json.loads(next(line.removeprefix("CONFIG=")
                           for line in result.stdout.splitlines() if line.startswith("CONFIG=")))


def test_python_logging_readback_routes_are_bounded_and_complete() -> None:
    canonical = _read(LANGUAGES / "python.md")
    mirrored = _read(ROOT / "plugins/obstudio/skills/references/languages/python.md")
    assert mirrored == canonical
    headings = list(re.finditer(r"^(#{2,3}) (.+)$", canonical, re.MULTILINE))
    sections = {}
    for index, heading in enumerate(headings):
        level = len(heading[1])
        end = next((other.start() for other in headings[index + 1:]
                    if len(other[1]) <= level), len(canonical))
        slug = re.sub(r"[^a-z0-9 -]", "", heading[2].lower()).replace(" ", "-")
        assert slug not in sections
        sections[slug] = canonical[heading.start():end]
    readiness = sections["logging-readiness-checks"]
    routed = set(re.findall(r"\]\(#([^)]*)\)", readiness))
    expected = {
        "loading-the-sdk",
        "local-log-preflight-approval",
        "local-splunk-observability-studio-application-logs-and-cloud-boundary",
    }
    assert expected <= routed
    for target in expected:
        section = sections[target]
        # Links expose complete small sections instead of the entire guide.
        assert len(section.splitlines()) <= 100
        assert len(section.encode("utf-8")) <= 9000
        assert section.count("```") % 2 == 0
    bootstrap = sections["loading-the-sdk"]
    assert re.findall(r"^([1-4])\. ", bootstrap, re.MULTILINE) == ["1", "2", "3", "4"]
    assert "**Option 1**" in bootstrap and "**Option 2**" in bootstrap
    approval = sections["local-log-preflight-approval"]
    assert "PREFLIGHT_APPROVED_LOCAL_OTLP_LOGS_ENDPOINT" in approval
    assert "logging configuration has established its original sinks" in approval
    boundary = sections["local-splunk-observability-studio-application-logs-and-cloud-boundary"]
    assert "operator-approved configuration during preflight" in boundary
    assert "This runtime check also detects duplicate handlers" in boundary


def test_python_log_boundary_conflict_never_aborts_application_startup() -> None:
    guide = LANGUAGES / "python.md"
    setup = _fenced_code_after(guide, "**File**: `otel_setup.py`", "python")
    log_helper = setup.split("def _local_log_exporter():", 1)[1].split(
        "def configure_opentelemetry():", 1
    )[0]
    assert "_skip_local_logs" in log_helper
    assert "raise RuntimeError" not in log_helper
    assert "_local_http_endpoint(endpoint)" in log_helper
    assert "PREFLIGHT_APPROVED_LOCAL_OTLP_LOGS_ENDPOINT" in log_helper
    assert "log_exporter = _local_log_exporter() if use_local_log_export else None" in setup
    assert "tracer_provider = TracerProvider" in setup
    assert "meter_provider = MeterProvider" in setup
    assert "must not abort application startup" in _normalized(guide)


def _python_local_log_helpers(
    exporter, *, approved_endpoint="http://127.0.0.1:4318/v1/logs",
):
    setup = _fenced_code_after(
        LANGUAGES / "python.md", "**File**: `otel_setup.py`", "python"
    )
    helpers = {
        "_local_http_endpoint", "_skip_local_logs",
        "_http_logs_endpoint_from_base", "_use_default_local_log_export",
        "_local_log_exporter",
    }
    constants = {"PREFLIGHT_APPROVED_LOCAL_OTLP_LOGS_ENDPOINT"}
    nodes = [
        node for node in ast.parse(setup).body
        if (isinstance(node, ast.FunctionDef) and node.name in helpers)
        or (isinstance(node, ast.Assign) and all(
            isinstance(target, ast.Name) and target.id in constants
            for target in node.targets
        ))
    ]
    namespace = {
        "os": os, "warnings": warnings, "urlsplit": urlsplit,
        "urlunsplit": urlunsplit, "OTLPLogExporter": exporter,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(LANGUAGES / "python.md"), "exec"), namespace)
    namespace["PREFLIGHT_APPROVED_LOCAL_OTLP_LOGS_ENDPOINT"] = approved_endpoint
    return namespace


@pytest.mark.parametrize("header_names", [
    ("OTEL_EXPORTER_OTLP_HEADERS",),
    ("OTEL_EXPORTER_OTLP_HEADERS", "OTEL_EXPORTER_OTLP_LOGS_HEADERS"),
])
def test_python_local_logs_reject_generic_headers_before_exporter_construction(
    monkeypatch, header_names,
) -> None:
    calls = []
    helpers = _python_local_log_helpers(lambda **kwargs: calls.append(kwargs))
    for name in tuple(os.environ):
        if name.startswith("OTEL_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "http://127.0.0.1:55444/v1/logs")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://trace.invalid/v1/traces")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "https://metric.invalid/v1/metrics")
    for name in header_names:
        monkeypatch.setenv(name, "Authorization=synthetic-test-value")
    before = dict(os.environ)

    with pytest.warns(RuntimeWarning, match="local OTLP logs disabled.*headers"):
        assert helpers["_local_log_exporter"]() is None

    assert calls == []
    assert dict(os.environ) == before


@pytest.mark.parametrize("generic_headers", [None, "  "])
def test_python_signal_headers_reach_official_exporter_without_override(
    monkeypatch, generic_headers,
) -> None:
    from opentelemetry.exporter.otlp.proto.http import _log_exporter

    for name in tuple(os.environ):
        if name.startswith("OTEL_"):
            monkeypatch.delenv(name)
    signal_headers = "X-Local=synthetic%20local,X-Route=a%2Fb"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_LOGS_HEADERS", signal_headers)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "http://127.0.0.1:55444/v1/logs")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "X-Trace=synthetic-trace")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_HEADERS", "X-Metric=synthetic-metric")
    if generic_headers is not None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", generic_headers)
    before = dict(os.environ)
    resolutions, calls = [], []
    original_resolve = _log_exporter._resolve_headers

    def resolve_headers(headers, signal_name):
        assert headers is None
        assert os.environ[signal_name] == signal_headers
        result = original_resolve(headers, signal_name)
        resolutions.append(result)
        return result

    def create_exporter(**kwargs):
        calls.append(kwargs)
        return _log_exporter.OTLPLogExporter(**kwargs)

    monkeypatch.setattr(_log_exporter, "_resolve_headers", resolve_headers)
    helpers = _python_local_log_helpers(
        create_exporter, approved_endpoint="http://127.0.0.1:55444/v1/logs",
    )
    exporter = helpers["_local_log_exporter"]()
    try:
        assert exporter is not None
        assert calls == [{"endpoint": "http://127.0.0.1:55444/v1/logs"}]
        assert len(resolutions) == 1
        assert resolutions[0]["x-local"] == "synthetic local"
        assert resolutions[0]["x-route"] == "a/b"
        assert "x-trace" not in resolutions[0] and "x-metric" not in resolutions[0]
        assert dict(os.environ) == before
    finally:
        if exporter is not None:
            exporter.shutdown()


@pytest.mark.parametrize("headers", [None, "  "])
@pytest.mark.parametrize("configuration,accepted", [
    ({}, True),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:55444/collector"}, True),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:55444/collector/v1/traces"}, False),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:55318/other",
      "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:55444/collector/v1/logs"}, True),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://[::1",
      "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:55444/collector/v1/logs"}, True),
    ({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:55445/collector/v1/logs"}, False),
    ({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:55444/other/v1/logs"}, False),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:55445/collector"}, False),
])
def test_python_local_logs_preserve_normal_nondefault_receiver(
    monkeypatch, headers, configuration, accepted,
) -> None:
    calls = []
    exporter = object()

    def create_exporter(**kwargs):
        calls.append(kwargs)
        return exporter

    helpers = _python_local_log_helpers(
        create_exporter, approved_endpoint="http://localhost:55444/collector/v1/logs",
    )
    for name in tuple(os.environ):
        if name.startswith("OTEL_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", "otlp")
    for name, value in configuration.items():
        monkeypatch.setenv(name, value)
    if headers is not None:
        for name in ("OTEL_EXPORTER_OTLP_HEADERS", "OTEL_EXPORTER_OTLP_LOGS_HEADERS"):
            monkeypatch.setenv(name, headers)
    before = dict(os.environ)

    assert helpers["_use_default_local_log_export"]() is True
    if accepted:
        assert helpers["_local_log_exporter"]() is exporter
        assert calls == [{"endpoint": "http://localhost:55444/collector/v1/logs"}]
    else:
        with pytest.warns(RuntimeWarning, match="preflight-approved receiver"):
            assert helpers["_local_log_exporter"]() is None
        assert calls == []
    assert dict(os.environ) == before


@pytest.mark.parametrize("path", [
    "", "/collector", "/collector/", "/collector//",
    "/collector/v1/traces", "/collector/v1/metrics", "/collector/v1/logs",
])
def test_python_generic_endpoint_preserves_otlp_http_base_path(monkeypatch, path) -> None:
    for name in tuple(os.environ):
        if name.startswith("OTEL_"):
            monkeypatch.delenv(name)
    base = "http://localhost:55444" + path
    expected = base + ("" if base.endswith("/") else "/") + "v1/logs"
    calls = []
    exporter = object()

    def create_exporter(**kwargs):
        calls.append(kwargs)
        return exporter

    helpers = _python_local_log_helpers(
        create_exporter,
        approved_endpoint=expected,
    )
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", base)
    assert helpers["_local_log_exporter"]() is exporter
    assert calls == [{"endpoint": expected}]


def test_audit_selects_missing_supported_local_logs_by_default() -> None:
    audit = _normalized(SKILLS / "otel-audit" / "SKILL.md")
    instrument = _normalized(SKILLS / "otel-instrument" / "SKILL.md")

    for term in (
        "local Splunk Observability Studio provider/exporter/bridge",
        "`required` with `instrument_mode: default`",
        "explicitly disabled",
        "operator-owned exporter",
    ):
        assert term in audit

    for term in (
        "Default Local Application Log Export",
        "A request that excludes custom business spans limits span work only",
        "`OTEL_LOGS_EXPORTER=none` disables",
        "exactly one bridge/export path",
        "Splunk Observability Studio cloud forwarding to Splunk is traces and metrics only",
    ):
        assert term in instrument


def test_skills_separate_local_receipt_from_configured_cloud_delivery() -> None:
    receiver = _normalized(SKILLS / "references" / "local-otlp-receiver.md")
    ao = _normalized(SKILLS / "references" / "splunk-agent-observability.md")
    consumers = json.loads(_read(SKILLS / "references" / "consumers.json"))

    for term in (
        "Receiver Receipt Is Not Product Delivery",
        "cloud-compatible gateway may delegate AO",
        "Receipt alone does not create or select",
        "endpoints.otlpHttp",
        "OTLP_HTTP_PORT",
        "configured non-default port",
        "generated application startup must not query Studio-specific discovery",
        "normal AO SDK calls",
    ):
        assert term.lower() in receiver.lower()

    for term in (
        "Configured Runtime Destination",
        "special route-registration call",
        "alternative routing modes, not two mandatory exporters",
        "Studio derives upstream API and ingest endpoints from its active cloud connection and realm",
        "not proof of cloud Agent Observability visibility",
    ):
        assert term in ao

    assert consumers["local-otlp-receiver.md"] == [
        "otel-audit",
        "otel-instrument",
        "otel-verify",
    ]
    assert consumers["splunk-agent-observability.md"] == [
        "otel-audit",
        "otel-instrument",
        "otel-verify",
    ]

    for skill_name in ("otel-audit", "otel-instrument", "otel-verify"):
        skill = _read(SKILLS / skill_name / "SKILL.md")
        assert "../references/local-otlp-receiver.md" in skill

    for filename in ("python.md", "node.md", "java.md", "go.md"):
        guide = _read(LANGUAGES / filename)
        assert "fixed-port equality" in guide or "equality gates" in guide
        assert "OBSTUDIO_OBSERVER_RUNTIME" not in guide
        assert "OBSTUDIO_OBSERVER_TARGET" not in guide
        assert "OBSTUDIO_" not in guide


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
            "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
            "select the official exporter matching",
        ):
            assert term in guide, f"{filename} is missing {term!r}"
        remediation = "move generic OTLP headers to trace/metric signal variables"
        assert remediation in guide, f"{filename} is missing {remediation!r}"
        if filename == "python.md":
            assert (
                "local OTLP log export skipped; check receiver, protocol and header configuration"
                in guide
            )

    java = _normalized(LANGUAGES / "java.md")
    assert "explicit reviewed preflight/configuration change" in java
    assert "never rewrite credentials during startup" in java
    assert "trace- and metric-specific endpoint/header settings" in java


def test_complete_go_setup_has_no_unreferenced_imports() -> None:
    setup = _fenced_code_after(LANGUAGES / "go.md", "**File**: `otel.go`", "go")
    imports = setup.split("import (", 1)[1].split(")", 1)[0]
    body = setup.split("import (", 1)[1].split(")", 1)[1]
    for alias, package in re.findall(r'(?:([A-Za-z_]\w*)\s+)?"([^"\n]+)"', imports):
        name = alias or package.rsplit("/", 1)[-1]
        assert re.search(rf"\b{re.escape(name)}\.", body), f"Unreferenced import: {package}"


def test_go_logs_match_preflight_receiver_without_stopping_traces_or_metrics() -> None:
    go = _read(LANGUAGES / "go.md")
    setup = _fenced_code_after(LANGUAGES / "go.md", "**File**: `otel.go`", "go")
    log_setup = setup.split("useLocalLogExport :=", 1)[1].split(
        "otel.SetTracerProvider(tp)", 1
    )[0]
    exporter = setup.split("func newApplicationLogExporter", 1)[1].split(
        "// fanoutHandler", 1
    )[0]

    assert "preflightApprovedLocalOTLPLogsEndpoint" in setup
    assert "if endpoint != preflightApprovedLocalOTLPLogsEndpoint" in exporter
    assert "the same host with a different port or path is a boundary conflict" in " ".join(go.split())
    assert "checked-in launch or Compose configuration for the selected runtime" in " ".join(go.split())
    assert "only when none of those sources supplies a receiver" in " ".join(go.split())
    rubric = " ".join(json.loads(_read(ROOT / "evals/go/kvstore/eval/qual/instrument.json"))["rubric"])
    assert "fallback only when no such receiver evidence exists" in rubric
    assert "url.Parse(genericEndpoint)" not in exporter
    assert 'os.Getenv("OTEL_EXPORTER_OTLP_HEADERS")' in exporter
    assert 'os.Getenv("OTEL_EXPORTER_OTLP_LOGS_HEADERS")' not in exporter
    assert "otlploghttp.WithHeaders(" not in exporter
    assert "return nil, err" not in log_setup
    assert "tp.Shutdown" not in log_setup
    assert "mp.Shutdown" not in log_setup
    assert log_setup.count(
        'log.Print("local OTLP log export skipped; check receiver and exporter configuration")'
    ) == 2
    assert "slog.SetDefault(slog.New(fanoutHandler{" in setup
    assert "the original\nlogger sink remains active" in go


@pytest.mark.parametrize("generic_headers", [None, "", "  ", "X-Generic=synthetic"])
def test_go_signal_headers_reach_constructor_without_empty_override(
    tmp_path, generic_headers,
) -> None:
    setup = _fenced_code_after(LANGUAGES / "go.md", "**File**: `otel.go`", "go")
    helper = "func newApplicationLogExporter" + setup.split(
        "func newApplicationLogExporter", 1
    )[1].split("// fanoutHandler", 1)[0]
    helper = (helper.replace("*otlploghttp.Exporter", "*boundaryExporter")
              .replace("otlploghttp.New", "newBoundaryExporter")
              .replace("otlploghttp.WithEndpointURL", "withBoundaryEndpoint")
              .replace("otlploghttp.WithHeaders", "withBoundaryHeaders"))
    source = r'''package main
import ("context"; "encoding/json"; "errors"; "fmt"; "os"; "strings")
const preflightApprovedLocalOTLPLogsEndpoint = "http://127.0.0.1:55444/v1/logs"
type boundaryExporter struct { Endpoint string; HeaderValue string; HeaderOverride bool }
type boundaryOption func(*boundaryExporter)
func withBoundaryEndpoint(value string) boundaryOption {
    return func(exporter *boundaryExporter) { exporter.Endpoint = value }
}
func withBoundaryHeaders(value map[string]string) boundaryOption {
    return func(exporter *boundaryExporter) { exporter.HeaderOverride = true }
}
func newBoundaryExporter(_ context.Context, options ...boundaryOption) (*boundaryExporter, error) {
    exporter := &boundaryExporter{HeaderValue: os.Getenv("OTEL_EXPORTER_OTLP_LOGS_HEADERS")}
    for _, option := range options { option(exporter) }
    return exporter, nil
}
''' + helper + r'''
func main() {
    before := strings.Join(os.Environ(), "\n")
    exporter, err := newApplicationLogExporter(context.Background())
    result := map[string]any{"created": exporter != nil, "rejected": err != nil,
        "environmentPreserved": before == strings.Join(os.Environ(), "\n")}
    if exporter != nil {
        result["headersPreserved"] = exporter.HeaderValue == "X-Local=synthetic%20local,X-Route=a%2Fb"
        result["explicitHeaders"] = exporter.HeaderOverride
        result["endpoint"] = exporter.Endpoint
    }
    json.NewEncoder(os.Stdout).Encode(result)
}
'''
    path = tmp_path / "main.go"
    path.write_text(source)
    env = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    env.update(GO111MODULE="off", OTEL_EXPORTER_OTLP_LOGS_HEADERS="X-Local=synthetic%20local,X-Route=a%2Fb",
               OTEL_EXPORTER_OTLP_TRACES_HEADERS="X-Trace=synthetic-trace",
               OTEL_EXPORTER_OTLP_METRICS_HEADERS="X-Metric=synthetic-metric")
    if generic_headers is not None:
        env["OTEL_EXPORTER_OTLP_HEADERS"] = generic_headers
    result = subprocess.run(["go", "run", str(path)], env=env, text=True,
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    expected = {"created": not bool(generic_headers and generic_headers.strip()),
                "rejected": bool(generic_headers and generic_headers.strip()),
                "environmentPreserved": True}
    if expected["created"]:
        expected.update(headersPreserved=True, explicitHeaders=False,
                        endpoint="http://127.0.0.1:55444/v1/logs")
    assert json.loads(result.stdout) == expected


def _node_sdk_owner_result(configuration):
    setup = _fenced_code_after(
        LANGUAGES / "node.md", "**File**: `instrumentation.ts`", "typescript"
    )
    source = "const PREFLIGHT_APPROVED_LOCAL_LOGS_ENDPOINT" + setup.split(
        "const PREFLIGHT_APPROVED_LOCAL_LOGS_ENDPOINT", 1
    )[1].split("let shutdownPromise", 1)[0]
    source = source.replace("let sdk: NodeSDK;", "let sdk;").replace(
        "function positiveSdkNumberFromEnv(name: string): number | undefined",
        "function positiveSdkNumberFromEnv(name)",
    )
    # Calibrated to core 2.12.1 and sdk-node/sdk-logs 0.223.2 public owners.
    stubs = r"""
const warnings = [];
const diag = { warn: (...args) => warnings.push(args) };
function getStringFromEnv(name) {
  const raw = process.env[name];
  return raw == null || raw.trim() === '' ? undefined : raw;
}
function getNumberFromEnv(name) {
  const raw = process.env[name];
  if (raw == null || raw.trim() === '') return undefined;
  const value = Number(raw);
  if (isNaN(value)) { diag.warn(name); return undefined; }
  return value;
}
function nativePositive(name) {
  const value = getNumberFromEnv(name);
  return value !== undefined && value <= 0 ? undefined : value;
}
function selected(name) {
  return process.env[name]?.split(',').map(value => value.trim()).filter(Boolean) ?? ['otlp'];
}
function protocol(signal) {
  return process.env['OTEL_EXPORTER_OTLP_' + signal + '_PROTOCOL'] ||
    process.env.OTEL_EXPORTER_OTLP_PROTOCOL || 'http/protobuf';
}
function resourceFromAttributes(attributes) { return attributes; }
class HttpInstrumentation {}
class ExpressInstrumentation {}
class ConsoleInstrumentation {}
class OTLPLogExporter { constructor(options) { this.options = options; } }
class BatchLogRecordProcessor {
  constructor(options) {
    this.values = {
      batch: options.maxExportBatchSize ?? 512,
      queue: options.maxQueueSize ?? 2048,
      delay: options.scheduledDelayMillis ?? 1000,
      timeout: options.exportTimeoutMillis ?? 30000,
    };
    this.values.batch = Math.min(this.values.batch, this.values.queue);
  }
}
class OTLPTraceExporter { constructor() { this.protocol = 'http/json'; } }
class OTLPMetricExporter { constructor() { this.protocol = 'http/json'; } }
class PeriodicExportingMetricReader {
  constructor(options) {
    let interval = options.exportIntervalMillis ?? 60000;
    let timeout = options.exportTimeoutMillis ?? 30000;
    if (interval <= 0 || timeout <= 0) throw Error('nonpositive metric timing');
    if (interval < timeout) {
      if (options.exportIntervalMillis !== undefined && options.exportTimeoutMillis !== undefined)
        throw Error('explicit timeout exceeds interval');
      timeout = interval;
    }
    this.values = { interval, timeout, protocol: options.exporter.protocol };
  }
}
const original = JSON.stringify(Object.fromEntries(Object.entries(process.env).filter(([key]) => key.startsWith('OTEL_'))));
class NodeSDK {
  constructor(options) {
    this.options = options;
    this.constructorLogs = process.env.OTEL_LOGS_EXPORTER ?? null;
    const interval = nativePositive('OTEL_METRIC_EXPORT_INTERVAL') ?? 60000;
    const timeout = Math.min(nativePositive('OTEL_METRIC_EXPORT_TIMEOUT') ?? 30000, interval);
    this.metrics = options.metricReader ? [options.metricReader.values] :
      selected('OTEL_METRICS_EXPORTER').filter(value => value !== 'none').map(value =>
        ({ interval, timeout, protocol: value === 'otlp' ? protocol('METRICS') : value }));
  }
  start() {
    globalThis.result = {
      metrics: this.metrics,
      traces: this.options.traceExporter ? [this.options.traceExporter.protocol] :
        selected('OTEL_TRACES_EXPORTER').filter(value => value !== 'none').map(value =>
          value === 'otlp' ? protocol('TRACES') : value),
      batch: this.options.logRecordProcessors?.[0].values ?? null,
      localLogs: !!this.options.logRecordProcessors,
      constructorLogs: this.constructorLogs,
      startLogs: process.env.OTEL_LOGS_EXPORTER ?? null,
      nativeLogs: this.options.logRecordProcessors ? [] :
        selected('OTEL_LOGS_EXPORTER').filter(value => ['otlp', 'console'].includes(value)),
    };
  }
}
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    result = subprocess.run(
        ["node", "-e", stubs + source + "console.log(JSON.stringify({...globalThis.result, environmentPreserved: original === JSON.stringify(Object.fromEntries(Object.entries(process.env).filter(([key]) => key.startsWith('OTEL_'))))}));"],
        env={**env, **configuration}, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("configuration,expected", [
    ({}, [60000, 30000]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "", "OTEL_METRIC_EXPORT_TIMEOUT": " "}, [60000, 30000]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "invalid", "OTEL_METRIC_EXPORT_TIMEOUT": "invalid"}, [60000, 30000]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "0", "OTEL_METRIC_EXPORT_TIMEOUT": "-1"}, [60000, 30000]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "1000.5", "OTEL_METRIC_EXPORT_TIMEOUT": "500.25"}, [1000.5, 500.25]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "1000"}, [1000, 1000]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "1000", "OTEL_METRIC_EXPORT_TIMEOUT": "2000"}, [1000, 1000]),
])
def test_node_native_metric_environment_owner(configuration, expected):
    result = _node_sdk_owner_result(configuration)
    assert result["metrics"] == [{"interval": expected[0], "timeout": expected[1], "protocol": "http/protobuf"}]
    assert result["environmentPreserved"]


@pytest.mark.parametrize("configuration,traces,metrics", [
    ({"OTEL_TRACES_EXPORTER": "none"}, [], ["http/protobuf"]),
    ({"OTEL_METRICS_EXPORTER": "none"}, ["http/protobuf"], []),
    ({"OTEL_TRACES_EXPORTER": "console", "OTEL_METRICS_EXPORTER": "console"}, ["console"], ["console"]),
    ({"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"}, ["grpc"], ["grpc"]),
    ({"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc", "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/json", "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL": "http/protobuf"}, ["http/json"], ["http/protobuf"]),
])
def test_node_native_signal_configuration_owner(configuration, traces, metrics):
    result = _node_sdk_owner_result(configuration)
    assert result["traces"] == traces
    assert [value["protocol"] for value in result["metrics"]] == metrics


@pytest.mark.parametrize("configuration,expected", [
    ({}, {"batch": 512, "queue": 2048, "delay": 1000, "timeout": 30000}),
    ({"OTEL_BLRP_MAX_QUEUE_SIZE": "4096", "OTEL_BLRP_MAX_EXPORT_BATCH_SIZE": "1024", "OTEL_BLRP_SCHEDULE_DELAY": "600000", "OTEL_BLRP_EXPORT_TIMEOUT": "1000"}, {"batch": 1024, "queue": 4096, "delay": 600000, "timeout": 1000}),
    ({"OTEL_BLRP_MAX_QUEUE_SIZE": "8", "OTEL_BLRP_MAX_EXPORT_BATCH_SIZE": "16", "OTEL_BLRP_SCHEDULE_DELAY": "1000.5", "OTEL_BLRP_EXPORT_TIMEOUT": "500.25"}, {"batch": 8, "queue": 8, "delay": 1000.5, "timeout": 500.25}),
    ({"OTEL_BLRP_MAX_QUEUE_SIZE": "invalid", "OTEL_BLRP_MAX_EXPORT_BATCH_SIZE": "0", "OTEL_BLRP_SCHEDULE_DELAY": "-1", "OTEL_BLRP_EXPORT_TIMEOUT": " "}, {"batch": 512, "queue": 2048, "delay": 1000, "timeout": 30000}),
])
def test_node_local_batch_configuration_owner(configuration, expected):
    result = _node_sdk_owner_result(configuration)
    assert result["batch"] == expected
    assert result["environmentPreserved"]


def test_node_native_logger_stage_and_unsupported_selector():
    result = _node_sdk_owner_result({"OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_HEADERS": "secret=value"})
    assert result["constructorLogs"] == "otlp"
    assert result["startLogs"] == "none"
    assert result["nativeLogs"] == []
    assert result["environmentPreserved"]
    result = _node_sdk_owner_result({"OTEL_LOGS_EXPORTER": "OTLP"})
    assert not result["localLogs"]
    assert result["nativeLogs"] == []
    assert result["startLogs"] == "OTLP"
    assert result["environmentPreserved"]


@pytest.mark.parametrize("configuration,local_logs", [
    ({"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "HTTP/PROTOBUF"}, False),
    ({"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": " http/protobuf "}, True),
    ({"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "", "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf"}, True),
    ({"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "  ", "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf"}, True),
    ({"OTEL_EXPORTER_OTLP_PROTOCOL": "  "}, True),
    ({"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "", "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"}, False),
])
def test_node_local_protocol_uses_sdk_string_owner(configuration, local_logs):
    result = _node_sdk_owner_result(configuration)
    assert result["localLogs"] is local_logs
    assert result["environmentPreserved"]
    if not local_logs:
        assert result["startLogs"] == "none"


@pytest.mark.parametrize("configuration,expected", [
    ({}, ["1000", "500"]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "", "OTEL_METRIC_EXPORT_TIMEOUT": ""}, ["", ""]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "1000.5", "OTEL_METRIC_EXPORT_TIMEOUT": "500.25"}, ["1000.5", "500.25"]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "invalid", "OTEL_METRIC_EXPORT_TIMEOUT": " "}, ["invalid", " "]),
])
def test_node_local_metric_profile_defaults_only_when_absent(configuration, expected):
    section = _read(LANGUAGES / "node.md").split("For local development with Splunk Observability Studio,", 1)[1]
    lines = []
    for line in section.splitlines():
        if line.startswith("    "):
            lines.append(line[4:])
        elif lines:
            break
    assert lines
    command = "\n".join(lines) + '\nprintf "%s\\n%s\\n" "$OTEL_METRIC_EXPORT_INTERVAL" "$OTEL_METRIC_EXPORT_TIMEOUT"'
    result = subprocess.run(["/bin/sh", "-c", command], env=configuration,
                            text=True, capture_output=True, check=True)
    assert result.stdout.splitlines() == expected


def test_shell_wrappers_only_add_local_log_configuration_for_otlp() -> None:
    python = _read(LANGUAGES / "python.md")
    java = _read(LANGUAGES / "java.md")

    assert 'if [ "$logs_class" = otlp ]; then' in python
    assert "Every selected SDK-supported OTLP member" in python
    assert 'if [ "$logs_class" = none ] || [ "$effective_logs_exporter" = none ]; then' in python
    python_none_branch = python.split(
        'if [ "$logs_class" = none ] || [ "$effective_logs_exporter" = none ]; then',
        1,
    )[1].split("fi", 1)[0]
    assert "export OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION=false" in python_none_branch
    assert 'if [ "$otel_exporter_class" != otlp ]; then' in java
    assert 'scan_otel_options "${JAVA_TOOL_OPTIONS:-}"' in java
    assert 'for otel_jvm_arg in "$@"; do' in java
    assert '-Dotel.exporter.otlp.endpoint)' in java
    assert java.index('if [ "$otel_exporter_class" != otlp ]; then') < java.index(
        'if [ -n "$generic_endpoint" ]'
    )
    assert '[ "$add_logs_endpoint" -eq 0 ] || export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=' in java
    assert "OBSTUDIO_JAVA_LOG_DEFAULTS" not in java
    assert 'ENTRYPOINT ["/usr/local/bin/otel-entrypoint"]' in java
    assert 'CMD ["java", "-jar", "/opt/app.jar"]' not in java
    assert '"${otel_log_args[@]}"' not in java
    assert "including\n`OTEL_LOGS_EXPORTER=none` -- use the precedence-aware" in java
    assert 'OTEL_LOGS_EXPORTER="${OTEL_LOGS_EXPORTER:-otlp}" \\' not in java


def test_python_cli_preserves_non_otlp_bridge_ownership(tmp_path: Path) -> None:
    launcher = tmp_path / "otel-entrypoint.sh"
    _write_executable(
        launcher,
        _fenced_code_after(
            LANGUAGES / "python.md",
            "## Auto-Instrumentation (CLI Wrapper)",
            "bash",
        ),
    )
    subprocess.run(["/bin/sh", "-n", launcher], check=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "python").symlink_to(sys.executable)
    _write_executable(
        fake_bin / "opentelemetry-instrument",
        """#!/bin/sh
printf 'AUTO=%s\\n' "${OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION-<unset>}"
""",
    )
    base_env = {"PATH": str(fake_bin)}

    operator_owned = subprocess.run(
        [launcher, "python", "app.py"],
        env={
            **base_env,
            "OTEL_LOGS_EXPORTER": "console",
            "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "true",
        },
        text=True,
        capture_output=True,
        check=True,
    )
    assert operator_owned.stdout == "AUTO=true\n"

    opted_out = subprocess.run(
        [launcher, "python", "app.py"],
        env={
            **base_env,
            "OTEL_LOGS_EXPORTER": "none",
            "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "true",
        },
        text=True,
        capture_output=True,
        check=True,
    )
    assert opted_out.stdout == "AUTO=false\n"


def _python_cli_launcher(
    tmp_path: Path, *, approved_endpoint="http://127.0.0.1:4318/v1/logs",
    approved_protocol="http/protobuf",
) -> tuple[Path, Path, dict[str, str]]:
    launcher = tmp_path / "otel-entrypoint.sh"
    source = _fenced_code_after(
        LANGUAGES / "python.md", "## Auto-Instrumentation (CLI Wrapper)", "bash"
    )
    source = source.replace(
        'approved_logs_endpoint = "http://127.0.0.1:4318/v1/logs"',
        f"approved_logs_endpoint = {json.dumps(approved_endpoint)}",
    ).replace(
        'approved_logs_protocol = "http/protobuf"',
        f"approved_logs_protocol = {json.dumps(approved_protocol)}",
    )
    _write_executable(launcher, source)
    subprocess.run(["/bin/sh", "-n", launcher], check=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "python").symlink_to(sys.executable)
    _write_executable(fake_bin / "opentelemetry-instrument", f"#!{sys.executable}\n" + """
import json
import os
import sys

args = sys.argv[1:]
options = {}
index = 0
while index < len(args) and args[index] in {
    "--logs_exporter", "--service_name", "--exporter_otlp_endpoint",
    "--exporter_otlp_protocol", "--resource_attributes",
}:
    options[args[index]] = args[index + 1]
    index += 2
if index < len(args) and args[index] == "--":
    index += 1
app = args[index:]
print(json.dumps({
    "options": options, "app": app,
    "env": {key: value for key, value in os.environ.items() if key.startswith("OTEL_")},
}), flush=True)
os.execvpe(app[0], app, os.environ)
""")
    app = tmp_path / "app.py"
    app.write_text("""
import json
import os
import sys

print(json.dumps({"app_argv": sys.argv[1:], "original_sink": "application stdout"}), flush=True)
sys.exit(int(os.environ.get("TEST_APP_EXIT", "0")))
""", encoding="utf-8")
    return launcher, app, {"PATH": str(fake_bin)}


_RESOURCE_IDENTITY_CASES = [
    ({"OTEL_RESOURCE_ATTRIBUTES": "service.name=resource%20operator,service.version=operator-version"},
     "resource operator", "operator-version"),
    ({"OTEL_RESOURCE_ATTRIBUTES": "service.name=resource-operator,service.version=operator-version",
      "OTEL_SERVICE_NAME": "explicit-operator"}, "explicit-operator", "operator-version"),
    ({}, "my-service", None),
]


@pytest.mark.parametrize("configuration,expected_name,expected_version", _RESOURCE_IDENTITY_CASES)
def test_python_programmatic_resource_defaults_preserve_sdk_operator_values(
    monkeypatch, configuration, expected_name, expected_version,
) -> None:
    from opentelemetry.sdk.resources import OTELResourceDetector, Resource

    for key in ("OTEL_SERVICE_NAME", "OTEL_RESOURCE_ATTRIBUTES"):
        monkeypatch.delenv(key, raising=False)
    for key, value in configuration.items():
        monkeypatch.setenv(key, value)
    setup = _fenced_code_after(LANGUAGES / "python.md", "**File**: `otel_setup.py`", "python")
    helper = next(node for node in ast.parse(setup).body
                  if isinstance(node, ast.FunctionDef) and node.name == "_application_resource")
    namespace = {"Resource": Resource, "OTELResourceDetector": OTELResourceDetector}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), "guide-resource", "exec"), namespace)
    attributes = namespace["_application_resource"]().attributes
    assert attributes["service.name"] == expected_name
    assert attributes.get("service.version") == expected_version


@pytest.mark.parametrize("configuration,expected_name,expected_version", _RESOURCE_IDENTITY_CASES)
def test_python_real_cli_wrapper_preserves_operator_resource_identity(
    tmp_path, configuration, expected_name, expected_version,
) -> None:
    launcher = tmp_path / "otel-entrypoint.sh"
    _write_executable(launcher, _fenced_code_after(
        LANGUAGES / "python.md", "## Auto-Instrumentation (CLI Wrapper)", "bash"
    ))
    app = tmp_path / "resource_app.py"
    app.write_text(
        "import json\nfrom opentelemetry.sdk.resources import Resource\n"
        "print(json.dumps(dict(Resource.create().attributes)))\n", encoding="utf-8",
    )
    environment = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    environment.update(configuration, OTEL_SDK_DISABLED="true", OTEL_LOGS_EXPORTER="none",
                       OTEL_TRACES_EXPORTER="none", OTEL_METRICS_EXPORTER="none",
                       PATH=str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", os.defpath))
    result = subprocess.run([str(launcher), sys.executable, str(app)], env=environment,
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    attributes = json.loads(result.stdout)
    if configuration:
        assert attributes["service.name"] == expected_name
    else:
        assert attributes["service.name"].startswith("unknown_service")
    assert attributes.get("service.version") == expected_version


_PYTHON_CLI_TRACE_METRIC_SETTINGS = {
    "OTEL_SERVICE_NAME": "python-cli-test",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:55318/collector/v1/traces",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "https://trace.invalid/v1/traces",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "https://metric.invalid/v1/metrics",
    "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "Authorization=synthetic-trace-secret",
    "OTEL_EXPORTER_OTLP_METRICS_HEADERS": "X-Token=synthetic-metric-secret",
}


def _run_python_cli(
    tmp_path, config, *, exit_code=0,
    approved_endpoint="http://127.0.0.1:4318/v1/logs", approved_protocol="http/protobuf",
):
    launcher, app, base_env = _python_cli_launcher(
        tmp_path, approved_endpoint=approved_endpoint, approved_protocol=approved_protocol,
    )
    app_args = ["two words", "quoted 'value'", "$NOT_EXPANDED", "*"]
    result = subprocess.run(
        [launcher, "python", str(app), *app_args],
        env={**base_env, **config, "TEST_APP_EXIT": str(exit_code)},
        text=True, capture_output=True,
    )
    assert result.returncode == exit_code, result.stderr
    instrument, application = [json.loads(line) for line in result.stdout.splitlines()]
    assert instrument["app"] == ["python", str(app), *app_args]
    assert application == {"app_argv": app_args, "original_sink": "application stdout"}
    return result, instrument


@pytest.mark.parametrize("conflict", [
    {"OTEL_EXPORTER_OTLP_HEADERS": "Authorization=synthetic-header-secret"},
    {"OTEL_EXPORTER_OTLP_HEADERS": "generic-secret", "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "logs-secret"},
    {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://cloud.invalid:4318"},
    {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://cloud.invalid:4318"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "https://localhost:4318/v1/logs"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://cloud.invalid:4318/v1/logs"},
    {"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "unsupported"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://user:synthetic-url-secret@localhost:4318/v1/logs"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:4318/v1/logs?token=synthetic-url-secret"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:4318/v1/logs#synthetic-url-secret"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:4318/v1/logs?"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:4318/v1/logs#"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:invalid/v1/logs"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:0/v1/logs"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://[::1/v1/logs"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:4318/not-logs"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:55319/collector/v1/logs"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:55318/other/v1/logs"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:4318/a b/v1/logs"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:4318/v1/logs\n"},
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "\n"},
    {"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "grpc", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:4317/v1/logs"},
])
def test_python_cli_log_conflicts_preserve_app_trace_metric_and_profile(
    tmp_path, conflict,
) -> None:
    config = {
        **_PYTHON_CLI_TRACE_METRIC_SETTINGS,
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "true",
        **conflict,
    }
    result, instrument = _run_python_cli(
        tmp_path, config, exit_code=37,
        approved_endpoint="http://127.0.0.1:55318/collector/v1/logs",
    )
    assert instrument["options"]["--logs_exporter"] == "none"
    assert instrument["options"]["--exporter_otlp_endpoint"] == config["OTEL_EXPORTER_OTLP_ENDPOINT"]
    assert instrument["options"]["--exporter_otlp_protocol"] == config["OTEL_EXPORTER_OTLP_PROTOCOL"]
    assert "--service_name" not in instrument["options"]
    assert "--resource_attributes" not in instrument["options"]
    assert instrument["env"] == {**config, "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "false"}
    assert result.stderr == "local OTLP log export skipped; check receiver, protocol and header configuration\n"
    assert "secret" not in result.stderr and "http" not in result.stderr


@pytest.mark.parametrize("config,endpoint,protocol", [
    ({}, "http://localhost:55444/v1/logs", "http/protobuf"),
    ({}, "http://localhost:55317", "grpc"),
    ({}, "http://127.0.0.1:4318/v1/logs", "http/protobuf"),
    ({"OTEL_EXPORTER_OTLP_LOGS_HEADERS": "X-Local=synthetic%20local,X-Route=a%2Fb"}, "http://127.0.0.1:4318/v1/logs", "http/protobuf"),
    ({"OTEL_EXPORTER_OTLP_HEADERS": "  ", "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "\t \r\n"}, "http://127.0.0.1:4318/v1/logs", "http/protobuf"),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:55318/collector/v1/traces"}, "http://localhost:55318/collector/v1/traces/v1/logs", "http/protobuf"),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:55318/collector//"}, "http://localhost:55318/collector//v1/logs", "http/protobuf"),
    (_PYTHON_CLI_TRACE_METRIC_SETTINGS, "http://127.0.0.1:55318/collector/v1/traces/v1/logs", "http/protobuf"),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:55318/collector"}, "http://otel-collector:55318/collector/v1/logs", "http/protobuf"),
    ({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://[::1]:55444/v1/logs"}, "http://[::1]:55444/v1/logs", "http/protobuf"),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "https://trace.invalid", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:55444/v1/logs"}, "http://localhost:55444/v1/logs", "http/protobuf"),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://[::1", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:55444/v1/logs"}, "http://localhost:55444/v1/logs", "http/protobuf"),
    ({"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:55317"}, "http://localhost:55317", "grpc"),
    ({"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:55317", "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "http/protobuf", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://localhost:55444/v1/logs"}, "http://localhost:55444/v1/logs", "http/protobuf"),
    ({"OTEL_LOGS_EXPORTER": "  otlp  "}, "http://127.0.0.1:4318/v1/logs", "http/protobuf"),
    ({"OTEL_LOGS_EXPORTER": "\u00a0otlp\u00a0,console,otlp_proto_http,otlp"}, "http://127.0.0.1:4318/v1/logs", "http/protobuf"),
    ({"OTEL_LOGS_EXPORTER": "otlp_proto_http,console", "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "grpc"}, "http://127.0.0.1:4318/v1/logs", "http/protobuf"),
    ({"OTEL_LOGS_EXPORTER": "console,otlp_proto_grpc", "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "http/protobuf"}, "http://localhost:55317", "grpc"),
    ({"OTEL_LOGS_EXPORTER": "otlp_proto_http,console", "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "SDK-invalid-selector"}, "http://127.0.0.1:4318/v1/logs", "http/protobuf"),
    ({"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": ""}, "http://127.0.0.1:4318/v1/logs", "http/protobuf"),
])
def test_python_cli_normal_local_logs_keep_checked_transport_and_app(
    tmp_path, monkeypatch, config, endpoint, protocol,
) -> None:
    from opentelemetry.sdk._configuration import _get_exporter_names, _import_exporters

    result, instrument = _run_python_cli(
        tmp_path, config, exit_code=19,
        approved_endpoint=endpoint, approved_protocol=protocol,
    )
    assert instrument["options"]["--logs_exporter"] == config.get("OTEL_LOGS_EXPORTER", "otlp")
    assert instrument["env"]["OTEL_LOGS_EXPORTER"] == config.get("OTEL_LOGS_EXPORTER", "otlp")
    assert instrument["env"]["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"] == endpoint
    assert instrument["env"]["OTEL_EXPORTER_OTLP_LOGS_PROTOCOL"] == config.get("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", protocol)
    for name, value in config.items():
        assert instrument["env"][name] == value
    assert "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION" not in instrument["env"]
    assert result.stderr == ""
    for name in ("OTEL_LOGS_EXPORTER", "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", "OTEL_EXPORTER_OTLP_PROTOCOL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", instrument["options"]["--logs_exporter"])
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", instrument["options"]["--exporter_otlp_protocol"])
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", instrument["env"]["OTEL_EXPORTER_OTLP_LOGS_PROTOCOL"])
    names = _get_exporter_names("logs")
    otlp_names = {name for name in names if name.startswith("otlp_proto_")}
    assert otlp_names == {"otlp_proto_grpc" if protocol == "grpc" else "otlp_proto_http"}
    # This test environment installs the HTTP exporter; gRPC name resolution
    # still uses the actual SDK reader without requiring another installation.
    if protocol == "http/protobuf":
        exporters = _import_exporters([], [], names)[2]
        assert sum(name.startswith("otlp_proto_") for name in exporters) == 1


@pytest.mark.parametrize("exporter", ["none", " NoNe ", "console", "custom", "OTLP", "  ", "console,", "none,console"])
def test_python_cli_operator_exporters_bypass_added_local_log_validation(
    tmp_path, exporter,
) -> None:
    config = {
        **_PYTHON_CLI_TRACE_METRIC_SETTINGS,
        "OTEL_LOGS_EXPORTER": exporter,
        "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "true",
        "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=synthetic-operator-secret",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "https://operator.invalid/logs",
        "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "operator-protocol",
    }
    result, instrument = _run_python_cli(tmp_path, config, exit_code=23)
    assert instrument["options"]["--logs_exporter"] == exporter
    expected = dict(config)
    if exporter.lower().strip() == "none":
        expected["OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION"] = "false"
    assert instrument["env"] == expected
    assert result.stderr == ""


@pytest.mark.parametrize("exporter,effective", [
    ("otlp,console", "console"),
    ("console, otlp_proto_http ,console", "console,console"),
    ("console,otlp_proto_grpc", "console"),
    ("otlp_proto_http,console,otlp_proto_grpc", "console"),
    ("none,otlp", "none,none"),
    ("NoNe,otlp", "NoNe,NoNe"),
    ("otlp,", ","),
    ("otlp, \n", " \n"),
    ("otlp_proto_grpc,OTLP", "OTLP"),
    ("otlp_proto_http", "none"),
    ("otlp,otlp", "none"),
])
def test_python_cli_conflicts_remove_only_otlp_members(
    tmp_path, monkeypatch, exporter, effective,
) -> None:
    from opentelemetry.sdk._configuration import _get_exporter_names, _import_exporters

    config = {
        **_PYTHON_CLI_TRACE_METRIC_SETTINGS,
        "OTEL_LOGS_EXPORTER": exporter,
        "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "true",
        "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=synthetic-secret",
    }
    result, instrument = _run_python_cli(tmp_path, config, exit_code=31)
    assert instrument["options"]["--logs_exporter"] == effective
    expected = {**config, "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION":
                "false" if effective == "none" else "true"}
    assert instrument["env"] == expected
    assert result.stderr == "local OTLP log export skipped; check receiver, protocol and header configuration\n"
    # Resolve actual installed SDK classes without constructing providers/exporters.
    monkeypatch.setenv("OTEL_LOGS_EXPORTER", effective)
    names = _get_exporter_names("logs")
    if effective == "none" or effective.startswith("console"):
        exporters = _import_exporters([], [], names)[2]
        assert list(exporters) == ([] if effective == "none" else ["console"])
    else:
        with pytest.raises(RuntimeError, match="not found"):
            _import_exporters([], [], names)


@pytest.mark.parametrize("exporter,protocol", [
    ("otlp_proto_grpc,console", "http/protobuf"),
    ("otlp_proto_http,otlp_proto_grpc,console", "http/protobuf"),
    ("otlp,console", "HTTP/PROTOBUF"),
])
def test_python_cli_transport_selection_cannot_bypass_approval(
    tmp_path, exporter, protocol,
) -> None:
    config = {"OTEL_LOGS_EXPORTER": exporter,
              "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": protocol,
              "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "true"}
    result, instrument = _run_python_cli(tmp_path, config)
    assert instrument["options"]["--logs_exporter"] == "console"
    assert instrument["env"] == config
    assert result.stderr.startswith("local OTLP log export skipped;")


def test_python_cli_command_boundary_uses_actual_cli_parser(tmp_path, monkeypatch) -> None:
    import opentelemetry.instrumentation.auto_instrumentation as cli

    launcher, _, environment = _python_cli_launcher(tmp_path)
    capture = tmp_path / "arguments.json"
    _write_executable(Path(environment["PATH"]) / "opentelemetry-instrument",
                      f"#!{sys.executable}\nimport json,sys\n"
                      f"open({str(capture)!r}, 'w').write(json.dumps(sys.argv[1:]))\n")
    late_options = ["--logs_exporter", "otlp", "--exporter_otlp_logs_endpoint",
                    "https://unapproved.invalid/v1/logs", "python", "app.py"]
    subprocess.run([launcher, *late_options], env={**environment, "OTEL_LOGS_EXPORTER": "none"},
                   text=True, capture_output=True, check=True)
    arguments = json.loads(capture.read_text())
    assert arguments[-len(late_options) - 1:] == ["--", *late_options]
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "http://127.0.0.1:4318/v1/logs")
    monkeypatch.setattr(sys, "argv", ["opentelemetry-instrument", *arguments])
    executed = []
    monkeypatch.setattr(cli, "which", lambda command: command)
    monkeypatch.setattr(cli, "execl", lambda *args: executed.append(args))
    cli.run()
    assert executed == [(late_options[0], late_options[0], *late_options[1:])]
    assert os.environ["OTEL_LOGS_EXPORTER"] == "none"
    assert os.environ["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"] == "http://127.0.0.1:4318/v1/logs"


def test_python_cli_preserves_resolved_nondefault_receiver_ports(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "otel-entrypoint.sh"
    source = _fenced_code_after(
        LANGUAGES / "python.md", "## Auto-Instrumentation (CLI Wrapper)", "bash",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "python").symlink_to(sys.executable)
    _write_executable(
        fake_bin / "opentelemetry-instrument",
        """#!/bin/sh
printf 'COMMON=%s\n' "${OTEL_EXPORTER_OTLP_ENDPOINT-<unset>}"
printf 'LOGS=%s\n' "${OTEL_EXPORTER_OTLP_LOGS_ENDPOINT-<unset>}"
""",
    )
    cases = [
        ({"OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{port}"},
         f"http://127.0.0.1:{port}/v1/logs") for port in (55318, 55319)
    ] + [
        ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:55318",
          "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:55444/v1/logs"},
         "http://127.0.0.1:55444/v1/logs"),
        ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:55318/collector/v1/traces"},
         "http://127.0.0.1:55318/collector/v1/traces/v1/logs"),
    ]
    for config, approved in cases:
        # Model the preflight adaptation of the checked-in literal, not a
        # runtime permission for every port on the same loopback host.
        _write_executable(launcher, source.replace(
            'approved_logs_endpoint = "http://127.0.0.1:4318/v1/logs"',
            f"approved_logs_endpoint = {json.dumps(approved)}",
        ))
        subprocess.run(["/bin/sh", "-n", launcher], check=True)
        result = subprocess.run(
            [launcher, "python", "app.py"],
            env={"PATH": str(fake_bin), **config},
            text=True, capture_output=True, check=True,
        )
        assert result.stdout == (
            f"COMMON={config['OTEL_EXPORTER_OTLP_ENDPOINT']}\n"
            f"LOGS={approved}\n"
        )


def test_python_logging_trace_injection_requires_installed_capability() -> None:
    python = _read(LANGUAGES / "python.md")
    normalized = " ".join(python.split())

    assert python.count("inject_trace_context=True") >= 2
    assert "Requires-Python" in python
    assert "Requires-Dist" in python
    assert "installed" in normalized and "signature" in normalized
    assert "source" in normalized and "probe" in normalized
    assert "omit the unsupported `inject_trace_context` argument" in normalized
    assert "it is not a supported `LoggingInstrumentor` option" not in python


def _fixed_library_release_lines(source: str) -> list[tuple[int, str]]:
    library_context = re.compile(
        r"\b(?:SDK|library|package|dependency|instrumentation|OpenTelemetry|"
        r"OTel|Galileo(?:-core)?|Splunk[-_ ]AO|pydantic|LoggingHandler|"
        r"LoggingInstrumentor|Python|Node(?:\.js)?|Java(?: agent)?|Go toolchain)\b",
        re.IGNORECASE,
    )
    release = re.compile(
        r"(?<![\w.])(?:v?\d+(?:\.\d+)+(?:\.[xX*])?|"
        r"v?\d+\.[xX*]|v\d+|\d+\+)"
        r"(?:[-.]?(?:a|b|rc|alpha|beta|dev|post)\.?\d+)?"
        r"(?:[+-][A-Za-z0-9.-]+)?(?![\w.])"
    )
    full_release = re.compile(r"(?<![\w.])v?\d+\.\d+\.\d+(?![\w.])")
    dependency_recipe = re.compile(
        r"\b(?:pip(?:3)?|uv pip|npm|pnpm|yarn) (?:install|add)\b|"
        r"\bgo get\b|[\w./-]+(?:==|>=|<=|~=|@v?)[0-9]"
    )
    offenders = []
    in_frontmatter = source.startswith("---\n")
    previous = ""
    for number, line in enumerate(source.splitlines(), 1):
        if in_frontmatter:
            if number > 1 and line.strip() == "---":
                in_frontmatter = False
            continue  # Only leading skill metadata is exempt.
        candidate = re.sub(
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
            lambda match: "<ip>" if all(int(part) <= 255 for part in match[0].split(".")) else match[0],
            line,
        )
        candidate = re.sub(
            r"service\.version[\"'`]*\s*[:=]\s*[\"'`]?[^\s,}\"'`]+",
            "service.version=<app>",
            candidate,
        )
        if not dependency_recipe.search(line):
            candidate = re.sub(r"https?://[^\s)]+", "<source-url>", candidate)
        candidate = re.sub(
            r"\b(?:gpt|qwen|llama|claude|gemini)[\w:.+-]*|"
            r"\baws-sdk-go-v\d+\b|"
            r"\bschema(?:[-_ ](?:version|v))?[=: ]*v?\d+(?:/v?\d+)?|"
            r"\bschemaVersion[\"'`:= ]+\d+|"
            r"/v\d+/(?:[\w<>{}-]+/?)+|/semconv/v\d+\.[xX*]\b",
            "<id>",
            candidate,
            flags=re.IGNORECASE,
        )
        context = " ".join((previous, candidate))
        contextual_release = bool(
            (library_context.search(context) or dependency_recipe.search(candidate))
            and (
                release.search(candidate)
                or re.search(r"\b(?:version|release|major)\s*[=: ]*\d+\b", candidate, re.IGNORECASE)
                or re.search(library_context.pattern + r"\s+\d+\b", candidate, re.IGNORECASE)
            )
        )
        if full_release.search(candidate) or contextual_release:
            offenders.append((number, line))
        previous = candidate
    return offenders


@pytest.mark.parametrize(
    "source",
    [
        "SDK LoggingHandler only as a pre-1.40 compatibility path",
        "SDK LoggingHandler only for a pinned pre-1.40 compatibility path",
        "SDK v1.40 supports this API",
        "SDK v0.64b0 supports this API",
        "SDK v2.x supports this API",
        "opentelemetry-sdk==1.40",
        "opentelemetry-sdk>=1.40.0rc1",
        "npm install new-library@1.40.0-rc.1",
        "go get example.invalid/library@v1.40.0-beta.2",
        "Java agent 2.x defaults to http/protobuf",
        "pydantic model_copy(update=...) or v1\ncopy(update=...)",
        "pydantic\nv1 copy(update=...)",
        "SDK release 2 uses this API",
        "Pydantic 1 supports this API",
        "Node.js 22+ is required by this dependency recipe",
        "Python >=3.11 is required by this package",
        "---\nversion: 0.1.2\n---\nSDK\nversion: 1.40",
        "Unowned hardcoded SDK example:\n1.40.0",
        "pip install https://example.invalid/library-1.40.0",
    ],
)
def test_fixed_library_release_detector_rejects_short_and_prerelease_recipes(
    source: str,
) -> None:
    assert _fixed_library_release_lines(source), source


@pytest.mark.parametrize(
    "source",
    [
        "---\nname: otel-audit\nmetadata:\n  version: 0.1.2\n---\nCapability guidance",
        "OTel SDK exports to http://127.0.0.1:4318/v1/logs",
        'OTel resource {"service.version": "1.2.3"}',
        "OTel resource service.version=1.2.3",
        "P99 static threshold 1.0 seconds",
        "3.0 stddev and clear_num_stddev=2.5",
        "gen_ai.request.temperature=0.2",
        "schema-v1/v2 remains compatible",
        "A selection is schema\nv2, or schema v3 with an AO resource target",
        "OTel schema version 2 uses these fields",
        'OTel {"schemaVersion": 1}',
        "GET /v2/detector",
        "@opentelemetry/instrumentation-redis-4",
        "go.opentelemetry.io/contrib/instrumentation/github.com/aws/aws-sdk-go-v2/otelaws",
        "OpenTelemetryTransportV3",
        "Never import go.opentelemetry.io/otel/semconv/v1.x",
        "OTel emits chat gpt-5.5",
        "Use 1000 ms export interval and 500 ms timeout",
        "HTTP 5xx and OTEL-001 finding IDs",
        'version = "~> 9.0" in a separate Terraform provider template',
        "OpenTelemetry [mapper](https://github.com/open-telemetry/opentelemetry-java-instrumentation/blob/main/instrumentation/logback/logback-appender-1.0/library/src/main/java/LoggingEventMapper.java)",
    ],
)
def test_fixed_library_release_detector_preserves_non_library_numbers(
    source: str,
) -> None:
    assert not _fixed_library_release_lines(source), source


def test_shipped_guidance_has_no_fixed_library_release_recipes() -> None:
    offenders = []
    for path in SKILLS.rglob("*.md"):
        if "tests" in path.relative_to(SKILLS).parts:
            continue
        offenders.extend(
            f"{path.relative_to(SKILLS)}:{number}: {line}"
            for number, line in _fixed_library_release_lines(_read(path))
        )
    assert not offenders, "Fixed library release recipes: " + "\n".join(offenders)


def test_normal_skill_profiles_enable_native_studio_logs() -> None:
    for name in ("otel-audit", "otel-instrument", "otel-verify"):
        source = _normalized(SKILLS / name / "SKILL.md")
        assert "`OTEL_LOGS_EXPORTER=otlp`" in source
        assert "LogRecords" in source and "Studio" in source
        assert "opt-out" in source
    producer = _normalized(SKILLS / "references" / "splunk-agent-observability.md")
    assert "SDK operation records remain distinct from ordinary OTLP application logs" in producer


def test_java_launcher_ignores_properties_after_the_launch_target(
    tmp_path: Path,
) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    cloud_env = {
        **base_env,
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://cloud.invalid",
        "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=fake-secret",
    }

    application_property = subprocess.run(
        [launcher, "com.example.Main", "-Dotel.logs.exporter=none"],
        env=cloud_env,
        text=True,
        capture_output=True,
    )
    assert application_property.returncode == 0
    assert "Local OTLP logs inactive" in application_property.stderr
    assert "JAVA_CALLED=1" in application_property.stdout
    assert _java_configuration(application_property)["_JAVA_OPTIONS"].endswith("-Dotel.logs.exporter=none")

    option_value = subprocess.run(
        [
            launcher,
            "--class-path",
            "-Dotel.logs.exporter=none",
            "com.example.Main",
        ],
        env=cloud_env,
        text=True,
        capture_output=True,
    )
    assert option_value.returncode == 0
    assert "Local OTLP logs inactive" in option_value.stderr
    assert "JAVA_CALLED=1" in option_value.stdout
    assert _java_configuration(option_value)["_JAVA_OPTIONS"].endswith("-Dotel.logs.exporter=none")

    effective_property = subprocess.run(
        [
            launcher,
            "--class-path",
            "app.jar",
            "-Dotel.logs.exporter=none",
            "com.example.Main",
        ],
        env=cloud_env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "JAVA_CALLED=1" in effective_property.stdout


def test_java_launcher_accepts_local_generic_endpoint_and_empty_exporter(
    tmp_path: Path,
) -> None:
    grpc = tmp_path / "grpc"
    grpc.mkdir()
    launcher, base_env = _java_launcher(grpc, approved_protocol="grpc",
                                       approved_endpoint="http://localhost:4317")
    mixed_protocol = subprocess.run(
        [
            launcher,
            "-Dotel.logs.exporter=otlp",
            "-Dotel.exporter.otlp.logs.protocol=grpc",
            "-Dotel.exporter.otlp.logs.endpoint=http://localhost:4317",
            "-version",
        ],
        env={
            **base_env,
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
        },
        text=True,
        capture_output=True,
        check=True,
    )
    assert "JAVA_CALLED=1" in mixed_protocol.stdout
    assert (
        "ARG=-Dotel.exporter.otlp.logs.endpoint=http://localhost:4317\n"
        in mixed_protocol.stdout
    )

    http = tmp_path / "http"
    http.mkdir()
    launcher, base_env = _java_launcher(http, approved_endpoint="http://telemetry-collector:55318/collector/v1/traces/v1/logs")
    nondefault_http = subprocess.run(
        [
            launcher,
            "-Dotel.logs.exporter=otlp",
            "-Dotel.exporter.otlp.logs.protocol=http/protobuf",
            "-version",
        ],
        env={
            **base_env,
            "OTEL_EXPORTER_OTLP_ENDPOINT": (
                "http://telemetry-collector:55318/collector/v1/traces"
            ),
        },
        text=True,
        capture_output=True,
        check=True,
    )
    assert "JAVA_CALLED=1" in nondefault_http.stdout
    assert (
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="
        "http://telemetry-collector:55318/collector/v1/traces/v1/logs\n"
        in nondefault_http.stdout
    )

    signal = tmp_path / "signal"
    signal.mkdir()
    launcher, base_env = _java_launcher(signal, approved_endpoint="http://arbitrary-observer:55444/v1/logs")
    signal_specific = subprocess.run(
        [launcher, "-version"],
        env={
            **base_env,
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://cloud.invalid",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": (
                "http://arbitrary-observer:55444/v1/logs"
            ),
        },
        text=True,
        capture_output=True,
        check=True,
    )
    assert (
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="
        "http://arbitrary-observer:55444/v1/logs\n"
        in signal_specific.stdout
    )

    empty = tmp_path / "empty"
    empty.mkdir()
    launcher, base_env = _java_launcher(empty)
    empty_exporter = subprocess.run(
        [launcher, "-Dotel.logs.exporter=", "-jar", "app.jar"],
        env=base_env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert empty_exporter.stdout.count("ARG=-Dotel.logs.exporter=\n") == 1
    assert "ARG=-Dotel.logs.exporter=otlp\n" not in empty_exporter.stdout
    assert (
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://127.0.0.1:4318/v1/logs\n"
        in empty_exporter.stdout
    )
    assert "ARG=-Dotel.exporter.otlp.logs.endpoint=" not in empty_exporter.stdout


@pytest.mark.parametrize("conflict,arguments", [
    ({"OTEL_EXPORTER_OTLP_ENDPOINT":"https://cloud.invalid"}, []),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT":"http://unapproved.invalid:4318"}, []),
    ({"OTEL_EXPORTER_OTLP_ENDPOINT":"http://127.0.0.1:55319"}, []),
    ({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT":"http://127.0.0.1:55319/v1/logs"}, []),
    ({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT":"http://127.0.0.1:4318/not-logs"}, []),
    ({"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL":"unsupported"}, []),
    ({"OTEL_EXPORTER_OTLP_HEADERS":"Authorization=synthetic-shared"}, []),
    ({"OTEL_EXPORTER_OTLP_HEADERS":"Authorization=synthetic-shared",
      "OTEL_EXPORTER_OTLP_LOGS_HEADERS":"X-Local=synthetic-local"}, []),
    ({"JAVA_TOOL_OPTIONS":"-Dotel.exporter.otlp.logs.endpoint=http://127.0.0.1:55319/v1/logs"}, []),
    ({"JDK_JAVA_OPTIONS":"-Dotel.exporter.otlp.headers=X-Generic=synthetic-jvm"}, []),
    ({"_JAVA_OPTIONS":"-Duser.kept=true -Dotel.logs.exporter=otlp -Dotel.exporter.otlp.logs.protocol=unsupported"}, []),
    ({}, ["-Dotel.exporter.otlp.logs.endpoint=http://127.0.0.1:55319/v1/logs"]),
    ({}, ["-Dotel.exporter.otlp.logs.endpoint="]),
    ({}, ["-Dotel.exporter.otlp.logs.protocol="]),
])
def test_java_launcher_log_conflicts_preserve_app_and_operator_configuration(
    tmp_path: Path, conflict: dict[str, str], arguments: list[str],
) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    supplied = {"OTEL_LOGS_EXPORTER":"otlp",
                "OTEL_EXPORTER_OTLP_ENDPOINT":"http://127.0.0.1:4318",
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT":"https://trace.invalid/v1/traces",
                "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT":"https://metric.invalid/v1/metrics",
                "OTEL_EXPORTER_OTLP_TRACES_HEADERS":"X-Trace=synthetic-trace",
                "OTEL_EXPORTER_OTLP_METRICS_HEADERS":"X-Metric=synthetic-metric",
                "OTEL_SERVICE_NAME":"operator-java",
                "OTEL_RESOURCE_ATTRIBUTES":" service.name = resource-name , safe.extra = kept ",
                **conflict}
    result = subprocess.run([launcher, *arguments, "com.example.Main", "two words"],
                            env={**base_env, **supplied}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "JAVA_CALLED=1" in result.stdout
    assert "ARG=two words\n" in result.stdout
    assert "Local OTLP logs inactive" in result.stderr
    assert "synthetic" not in result.stderr
    actual = _java_configuration(result)
    for key, value in supplied.items():
        if key != "_JAVA_OPTIONS":
            assert actual[key] == value
    existing = supplied.get("_JAVA_OPTIONS", "")
    assert actual["_JAVA_OPTIONS"] == (existing+" " if existing else "")+"-Dotel.logs.exporter=none"
    for key in ["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL"]:
        if key not in supplied:
            assert key not in actual


@pytest.mark.parametrize("exporters,remaining", [
    (" otlp ", "none"),
    (", ,\totlp\r\n,,", "none"),
    (" ,, \t", "none"),
    (" console , otlp ", "console"),
])
@pytest.mark.parametrize("conflict", [
    {"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "https://unapproved.invalid/v1/logs"},
    {"OTEL_EXPORTER_OTLP_HEADERS": "X-Generic=synthetic-value"},
])
def test_java_launcher_guards_normalized_otlp_membership(
    tmp_path: Path, exporters: str, remaining: str, conflict: dict[str, str],
) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    supplied = {"OTEL_LOGS_EXPORTER": exporters,
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:4318/v1/logs",
                "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "X-Trace=synthetic-trace",
                "OTEL_EXPORTER_OTLP_METRICS_HEADERS": "X-Metric=synthetic-metric", **conflict}
    result = subprocess.run([launcher, "com.example.Main"], env={**base_env, **supplied},
                            capture_output=True, text=True, check=True)
    actual = _java_configuration(result)
    assert "Local OTLP logs inactive" in result.stderr
    assert "synthetic" not in result.stderr
    assert actual["_JAVA_OPTIONS"] == "-Dotel.logs.exporter=" + remaining
    assert all(actual[key] == value for key, value in supplied.items())


@pytest.mark.parametrize("exporters", ["otlp,otlp", "none, otlp", "OTLP", "\u00a0otlp\u00a0"])
def test_java_launcher_retains_sdk_invalid_or_non_otlp_selection(
    tmp_path: Path, exporters: str,
) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    supplied = {"OTEL_LOGS_EXPORTER": exporters,
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "https://unapproved.invalid/v1/logs",
                "OTEL_EXPORTER_OTLP_HEADERS": "X-Generic=synthetic-value"}
    result = subprocess.run([launcher, "com.example.Main"], env={**base_env, **supplied},
                            capture_output=True, text=True, check=True)
    actual = _java_configuration(result)
    # Leave syntax/provider errors with the selected SDK; do not repair into success.
    assert not result.stderr
    assert actual["_JAVA_OPTIONS"] == ""
    assert all(actual[key] == value for key, value in supplied.items())


@pytest.mark.parametrize("exporters", [" otlp ", " console , otlp "])
def test_java_launcher_normalized_otlp_preserves_approved_signal_and_unused_generic(
    tmp_path: Path, exporters: str,
) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    supplied = {"OTEL_LOGS_EXPORTER": exporters,
                "OTEL_EXPORTER_OTLP_ENDPOINT": "https://unused-generic.invalid",
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://127.0.0.1:4318/v1/logs"}
    result = subprocess.run([launcher, "com.example.Main"], env={**base_env, **supplied},
                            capture_output=True, text=True, check=True)
    actual = _java_configuration(result)
    assert not result.stderr and actual["_JAVA_OPTIONS"] == ""
    assert all(actual[key] == value for key, value in supplied.items())


def test_java_launcher_guards_effective_jvm_mixed_selector(tmp_path: Path) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    supplied = {"OTEL_LOGS_EXPORTER": "console", "JAVA_TOOL_OPTIONS": "-Dotel.logs.exporter=otlp,console",
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "https://unapproved.invalid/v1/logs"}
    result = subprocess.run([launcher, "com.example.Main"], env={**base_env, **supplied},
                            capture_output=True, text=True, check=True)
    actual = _java_configuration(result)
    assert "Local OTLP logs inactive" in result.stderr
    assert actual["_JAVA_OPTIONS"] == "-Dotel.logs.exporter=console"
    assert all(actual[key] == value for key, value in supplied.items())


def test_java_launcher_filtered_spi_value_roundtrips_as_one_jvm_property(tmp_path: Path) -> None:
    home = Path(os.environ["JAVA_HOME"]) / "bin" if os.environ.get("JAVA_HOME") else None
    java = str(home / "java") if home else shutil.which("java")
    javac = str(home / "javac") if home else shutil.which("javac")
    if not java or not javac:
        pytest.skip("A configured JDK is required for the real JVM option roundtrip")
    source = tmp_path / "ExporterProperty.java"
    source.write_text("""import java.util.Base64;
public class ExporterProperty {
 public static void main(String[] args) {
  System.out.println(Base64.getEncoder().encodeToString(System.getProperty("otel.logs.exporter").getBytes(java.nio.charset.StandardCharsets.UTF_8)));
  System.out.println(System.getProperty("other", "absent"));
 }
}
""")
    compiled = subprocess.run([javac, "-d", str(tmp_path), str(source)], capture_output=True, text=True)
    if compiled.returncode and "Unable to locate a Java Runtime" in compiled.stderr:
        pytest.skip("No installed JDK behind the platform launcher")
    assert compiled.returncode == 0, compiled.stderr
    launcher, base_env = _java_launcher(tmp_path)
    custom = 'custom"quoted\'name\\path -Dother=injected'
    result = subprocess.run([launcher, "com.example.Main"],
        env={**base_env, "OTEL_LOGS_EXPORTER": "otlp," + custom,
             "OTEL_EXPORTER_OTLP_HEADERS": "X-Generic=synthetic-value"},
        capture_output=True, text=True, check=True)
    actual = _java_configuration(result)
    env = {key:value for key,value in os.environ.items()
           if key not in {"JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"}}
    env["_JAVA_OPTIONS"] = actual["_JAVA_OPTIONS"]
    roundtrip = subprocess.run([java, "-cp", str(tmp_path), "ExporterProperty"], env=env,
                               capture_output=True, text=True, check=True)
    import base64
    encoded, other = roundtrip.stdout.splitlines()
    assert base64.b64decode(encoded).decode() == custom
    assert other == "absent"


@pytest.mark.parametrize("operator_exporter", ["none", "console"])
def test_java_launcher_operator_exporters_bypass_local_approval(
    tmp_path: Path, operator_exporter: str,
) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    supplied = {"OTEL_LOGS_EXPORTER":operator_exporter,
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT":"not a local URL",
                "OTEL_EXPORTER_OTLP_HEADERS":"X-Generic=synthetic-value",
                "OTEL_JAVAAGENT_CONFIGURATION_FILE":"operator.properties"}
    result = subprocess.run([launcher,"-version"],env={**base_env,**supplied},
                            capture_output=True,text=True,check=True)
    assert not result.stderr
    actual = _java_configuration(result)
    assert actual["_JAVA_OPTIONS"] == ""
    assert all(actual[key] == value for key,value in supplied.items())


def test_java_launcher_approved_signal_uses_effective_jvm_precedence(tmp_path: Path) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    result = subprocess.run([launcher,"-Dotel.exporter.otlp.logs.endpoint=http://127.0.0.1:4318/v1/logs","-version"],
        env={**base_env,"OTEL_EXPORTER_OTLP_ENDPOINT":"https://unused-generic.invalid?unused=1#fragment",
             "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT":"http://127.0.0.1:55319/v1/logs",
             "OTEL_EXPORTER_OTLP_LOGS_HEADERS":"X-Local=synthetic%20local"},
        capture_output=True,text=True,check=True)
    assert not result.stderr
    actual=_java_configuration(result)
    assert actual["_JAVA_OPTIONS"] == ""
    assert actual["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"] == "http://127.0.0.1:55319/v1/logs"
    assert actual["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://unused-generic.invalid?unused=1#fragment"
    assert actual["OTEL_EXPORTER_OTLP_LOGS_HEADERS"] == "X-Local=synthetic%20local"


@pytest.mark.parametrize("selection", ["environment", "jvm-property"])
def test_java_launcher_unresolved_agent_file_is_preflight_blocker(
    tmp_path: Path, selection: str,
) -> None:
    launcher, base_env = _java_launcher(tmp_path)
    config = tmp_path / "operator.properties"
    config.write_text("otel.logs.exporter=none\n")
    environment = dict(base_env)
    arguments = []
    if selection == "environment":
        environment["OTEL_JAVAAGENT_CONFIGURATION_FILE"] = str(config)
    else:
        arguments.append("-Dotel.javaagent.configuration-file="+str(config))
    result = subprocess.run([launcher,*arguments,"-version"], env=environment,
                            capture_output=True,text=True)
    assert result.returncode == 1
    assert "configuration-file ownership during preflight" in result.stderr
    assert "JAVA_CALLED=1" not in result.stdout
    assert config.read_text() == "otel.logs.exporter=none\n"


@pytest.mark.parametrize("generic,approved_signal", [
    ("http://127.0.0.1:4318/collector?selector=example",
     "http://127.0.0.1:4318/collector?selector=example/v1/logs"),
    ("http://127.0.0.1:4318/collector#example",
     "http://127.0.0.1:4318/collector#example/v1/logs"),
])
def test_java_launcher_does_not_append_path_inside_generic_query_or_fragment(
    tmp_path: Path, generic: str, approved_signal: str,
) -> None:
    # Both are valid distinct input strings; concatenation would falsely equate
    # the generic URL to approval by putting v1/logs inside query/fragment text.
    launcher, base_env = _java_launcher(tmp_path, approved_endpoint=approved_signal)
    result = subprocess.run([launcher,"-version"],
        env={**base_env,"OTEL_EXPORTER_OTLP_ENDPOINT":generic},
        capture_output=True,text=True,check=True)
    assert "Local OTLP logs inactive" in result.stderr
    actual=_java_configuration(result)
    assert actual["OTEL_EXPORTER_OTLP_ENDPOINT"] == generic
    assert actual["_JAVA_OPTIONS"].endswith("-Dotel.logs.exporter=none")
    assert "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT" not in actual


def test_java_launcher_rejects_argfiles_and_ambiguous_option_environments(
    tmp_path: Path,
) -> None:
    launcher, base_env = _java_launcher(tmp_path)

    for env_name in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"):
        argfile = subprocess.run(
            [launcher, "-version"],
            env={**base_env, env_name: "-Dreviewed=true @hidden.options"},
            text=True,
            capture_output=True,
        )
        assert argfile.returncode == 1
        assert "expand Java argument files" in argfile.stderr
        assert "JAVA_CALLED=1" not in argfile.stdout

        for ambiguous in (
            '"-Dreviewed=value with spaces" -Dotel.logs.exporter=none',
            r"-Dreviewed=value\ with\ spaces -Dotel.logs.exporter=none",
        ):
            option_env = subprocess.run(
                [launcher, "-version"],
                env={**base_env, env_name: ambiguous},
                text=True,
                capture_output=True,
            )
            assert option_env.returncode == 1
            assert env_name in option_env.stderr
            assert "move reviewed options to explicit launcher arguments" in (
                option_env.stderr
            )
            assert "JAVA_CALLED=1" not in option_env.stdout

        for control_whitespace in ("\r", "\n", "\f", "\v"):
            option_env = subprocess.run(
                [launcher, "-version"],
                env={
                    **base_env,
                    env_name: (
                        "-Dreviewed=true"
                        f"{control_whitespace}-Dotel.logs.exporter=none"
                    ),
                },
                text=True,
                capture_output=True,
            )
            assert option_env.returncode == 1
            assert env_name in option_env.stderr
            assert "unsupported non-space/tab control whitespace" in (
                option_env.stderr
            )
            assert "JAVA_CALLED=1" not in option_env.stdout

        tab_separated = subprocess.run(
            [launcher, "-version"],
            env={
                **base_env,
                env_name: "-Dreviewed=true\t-Dotel.logs.exporter=none",
            },
            text=True,
            capture_output=True,
            check=True,
        )
        assert "JAVA_CALLED=1" in tab_separated.stdout

    for launcher_args in (
        ["@hidden.options"],
        ["--class-path", "@hidden.options", "com.example.Main"],
    ):
        argfile = subprocess.run(
            [launcher, *launcher_args],
            env=base_env,
            text=True,
            capture_output=True,
        )
        assert argfile.returncode == 1
        assert "expand Java argument files" in argfile.stderr
        assert "JAVA_CALLED=1" not in argfile.stdout


def test_node_shutdown_drains_before_flushing_telemetry(tmp_path: Path) -> None:
    node = _read(LANGUAGES / "node.md")
    handler = node.split("export function installGracefulSignalHandlers", 1)[1].split(
        "```",
        1,
    )[0]

    assert handler.index("await stopAndDrain();") < handler.index(
        "await shutdownOnce();"
    )
    assert "Application drain failed" in handler
    assert "OpenTelemetry shutdown failed" in handler
    assert "signal handlers are already installed" in handler
    assert "forcedExit.unref()" not in handler
    assert "process.exit(failed ? 1 : 0)" in handler
    assert "server.close" in node
    assert "drain every detected queue/worker" in node
    assert "`process.exitCode` alone cannot stop a hung drain or exporter" in _normalized(
        LANGUAGES / "node.md"
    )

    lifecycle = "let shutdownPromise" + node.split("let shutdownPromise", 1)[1].split(
        "\n```",
        1,
    )[0]
    replacements = {
        "let shutdownPromise: Promise<void> | undefined;": "let shutdownPromise;",
        "export function shutdownOnce(): Promise<void> {": "function shutdownOnce() {",
        "type StopAndDrain = () => void | Promise<void>;\n": "",
        "export function installGracefulSignalHandlers(\n"
        "  stopAndDrain: StopAndDrain,\n"
        "): void {": "function installGracefulSignalHandlers(stopAndDrain) {",
        "const handleSignal = (forcedExitCode: number): void => {": (
            "const handleSignal = (forcedExitCode) => {"
        ),
        "catch (error: unknown)": "catch (error)",
    }
    for typed, javascript in replacements.items():
        assert typed in lifecycle
        lifecycle = lifecycle.replace(typed, javascript)

    def run_signal_case(
        name: str, stop_and_drain: str, *, fast_timeout: bool = False,
        repeat_signal: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        script = tmp_path / f"{name}.js"
        case_lifecycle = lifecycle.replace("10_000", "50") if fast_timeout else lifecycle
        script.write_text(
            "const fs = require('node:fs');\n"
            "const sdk = { shutdown: async () => fs.writeSync(1, 'FLUSHED\\n') };\n"
            f"{case_lifecycle}\n"
            f"installGracefulSignalHandlers({stop_and_drain});\n"
            "setInterval(() => {}, 1_000);\n"
            "setImmediate(() => process.kill(process.pid, 'SIGTERM'));\n"
            + (f"setTimeout(() => process.kill(process.pid, '{repeat_signal}'), 30);\n"
               if repeat_signal else ""),
            encoding="utf-8",
        )
        return subprocess.run(
            ["node", script],
            text=True,
            capture_output=True,
            timeout=5,
        )

    success = run_signal_case(
        "success",
        "async () => fs.writeSync(1, 'DRAINED\\n')",
    )
    assert success.returncode == 0
    assert success.stdout == "DRAINED\nFLUSHED\n"

    failure = run_signal_case(
        "failure",
        "async () => { throw new Error('boom'); }",
    )
    assert failure.returncode == 1
    assert failure.stdout == "FLUSHED\n"
    assert "Application drain failed" in failure.stderr

    stalled = run_signal_case(
        "stalled", "() => new Promise(() => {})", fast_timeout=True
    )
    assert stalled.returncode == 143
    assert stalled.stdout == ""

    for signal in ("SIGTERM", "SIGINT"):
        repeated = run_signal_case(
            "repeated-" + signal,
            "async () => { fs.writeSync(1, 'DRAINING\\n'); "
            "await new Promise(resolve => setTimeout(resolve, 100)); "
            "fs.writeSync(1, 'DRAINED\\n'); }",
            repeat_signal=signal,
        )
        assert repeated.returncode == 0, repeated.stderr
        assert repeated.stdout == "DRAINING\nDRAINED\nFLUSHED\n"


def test_node_non_otlp_exporters_never_add_obstudio_console_bridge() -> None:
    node = _read(LANGUAGES / "node.md")
    operator_owned_branch = node.split(
        "if (configured && configured !== 'otlp') {",
        1,
    )[1].split("const protocol", 1)[0]

    assert "logRecordProcessors: undefined" in operator_owned_branch
    assert "logInstrumentations: []" in operator_owned_branch
    assert "suppressAutoLogs: false" in operator_owned_branch
    assert "configured !== 'none'" not in operator_owned_branch
    assert "...logInstrumentations" in node
    assert "logInstrumentations: [new ConsoleInstrumentation()]" in node


def test_node_local_logs_require_preflight_match_and_fail_closed() -> None:
    node = _read(LANGUAGES / "node.md")
    normalized = _normalized(LANGUAGES / "node.md")
    assert "A logs-only endpoint, header, or protocol" in normalized
    assert "including in JavaScript translations" in normalized
    assert "Never turn a log-only protocol conflict into a process-wide exception" in normalized
    assert "Do not change `OTEL_LOGS_EXPORTER`, the logs endpoint, or the logs protocol" in normalized
    helper = node.split("function defaultLocalLogConfiguration() {", 1)[1].split(
        "const originalLogsExporter = process.env.OTEL_LOGS_EXPORTER;", 1
    )[0]

    assert "explicitLogsEndpoint !== PREFLIGHT_APPROVED_LOCAL_LOGS_ENDPOINT" in helper
    assert "url: PREFLIGHT_APPROVED_LOCAL_LOGS_ENDPOINT" in helper
    assert "OTEL_EXPORTER_OTLP_ENDPOINT?.trim()" not in helper
    assert "process.env.OTEL_EXPORTER_OTLP_HEADERS?.trim()" in helper
    assert "process.env.OTEL_EXPORTER_OTLP_LOGS_HEADERS?.trim()" not in helper
    assert "new BatchLogRecordProcessor({" in helper
    assert "scheduledDelayMillis: positiveSdkNumberFromEnv('OTEL_BLRP_SCHEDULE_DELAY')" in helper
    assert "logInstrumentations: [new ConsoleInstrumentation()]" in helper
    assert "} catch {" in helper
    assert "logRecordProcessors: undefined" in helper.split("} catch {", 1)[1]
    assert "logInstrumentations: []" in helper.split("} catch {", 1)[1]
    assert "suppressAutoLogs: true" in helper.split("} catch {", 1)[1]
    assert "reportLocalLogSkip();" in helper.split("} catch {", 1)[1]
    assert "process.stderr.write(" in node.split("function reportLocalLogSkip()", 1)[1]
    assert "error.message" not in helper
    assert "process.env.OTEL_LOGS_EXPORTER =" not in helper
    assert "process.env.OTEL_LOGS_EXPORTER ||=" not in helper
    assert "process.env.OTEL_EXPORTER_OTLP_LOGS_ENDPOINT =" not in helper
    assert "process.env.OTEL_EXPORTER_OTLP_LOGS_ENDPOINT ||=" not in helper
    assert "process.env.OTEL_EXPORTER_OTLP_LOGS_PROTOCOL =" not in helper
    assert "process.env.OTEL_EXPORTER_OTLP_LOGS_PROTOCOL ||=" not in helper
    assert "const originalLogsExporter = process.env.OTEL_LOGS_EXPORTER;" in node

    sdk_integration = node.split("let sdk: NodeSDK;", 1)[1].split("sdk.start();", 1)[0]
    assert "if (logRecordProcessors?.length) {\n  try {" in sdk_integration
    assert "sdk = new NodeSDK({" in sdk_integration
    assert "...base.instrumentations, ...logInstrumentations" in sdk_integration
    assert "} catch {" in sdk_integration
    assert "reportLocalLogSkip();" in sdk_integration.split("} catch {", 1)[1]
    assert "const base = baseSdkOptions();" in node
    assert sdk_integration.count("sdk = new NodeSDK(base);") == 2
    assert "suppressAutoLogs = true;" in sdk_integration
    assert "if (suppressAutoLogs) process.env.OTEL_LOGS_EXPORTER = 'none';" in node
    assert "delete process.env.OTEL_LOGS_EXPORTER" in node


def test_node_log_only_failures_keep_trace_metric_startup() -> None:
    setup = _fenced_code_after(
        LANGUAGES / "node.md", "**File**: `instrumentation.ts`", "typescript"
    )
    source = "const PREFLIGHT_APPROVED_LOCAL_LOGS_ENDPOINT" + setup.split(
        "const PREFLIGHT_APPROVED_LOCAL_LOGS_ENDPOINT", 1
    )[1].split("let shutdownPromise", 1)[0]
    source = source.replace("let sdk: NodeSDK;", "let sdk;").replace(
        "function positiveSdkNumberFromEnv(name: string): number | undefined",
        "function positiveSdkNumberFromEnv(name)",
    )
    stubs = """
const counts = { trace: 0, metric: 0 };
const diag = { warn: () => {} };
function getStringFromEnv(name) {
  const raw = process.env[name];
  return raw == null || raw.trim() === '' ? undefined : raw;
}
function getNumberFromEnv(name) {
  const raw = process.env[name];
  if (raw == null || raw.trim() === '') return undefined;
  const value = Number(raw);
  return isNaN(value) ? undefined : value;
}
function resourceFromAttributes(attributes) { return attributes; }
class HttpInstrumentation {}
class ExpressInstrumentation {}
let logBoundary = null;
const originalOtelEnvironment = Object.fromEntries(
  Object.entries(process.env).filter(([name]) => name.startsWith('OTEL_')),
);
class OTLPLogExporter {
  constructor(options) {
    if (process.env.FAIL_LOG_CONSTRUCTOR === 'exporter') throw Error('secret');
    logBoundary = {
      headers: process.env.OTEL_EXPORTER_OTLP_LOGS_HEADERS ?? null,
      explicitHeaders: Object.hasOwn(options, 'headers'),
      url: options.url,
    };
  }
}
class BatchLogRecordProcessor {
  constructor() { if (process.env.FAIL_LOG_CONSTRUCTOR === 'processor') throw Error('secret'); }
}
class ConsoleInstrumentation {
  constructor() { if (process.env.FAIL_LOG_CONSTRUCTOR === 'bridge') throw Error('secret'); }
}
class NodeSDK {
  constructor(options) {
    if (options.logRecordProcessors && process.env.FAIL_LOG_CONSTRUCTOR === 'sdk') {
      throw Error('secret');
    }
    this.options = options;
    counts.trace++;
    counts.metric++;
  }
  start() {
    globalThis.startResult = {
      localLogs: !!this.options.logRecordProcessors,
      logOption: Object.hasOwn(this.options, 'logRecordProcessors'),
      autoExporter: this.options.logRecordProcessors
        ? null : (process.env.OTEL_LOGS_EXPORTER || 'otlp'),
      trace: counts.trace,
      metric: counts.metric,
    };
  }
}
"""
    env = os.environ.copy()
    for name in tuple(env):
        if name.startswith("OTEL_") or name == "FAIL_LOG_CONSTRUCTOR":
            env.pop(name, None)

    cases = [
        ({"OTEL_EXPORTER_OTLP_HEADERS": "", "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "  "}, True, None, False),
        ({"OTEL_LOGS_EXPORTER": "none"}, False, "none", False),
        ({"OTEL_LOGS_EXPORTER": "console"}, False, "console", False),
        ({"OTEL_EXPORTER_OTLP_HEADERS": "token=secret"}, False, "none", True),
        ({"OTEL_EXPORTER_OTLP_LOGS_HEADERS": "X-Local=synthetic%20local"}, True, None, False),
        ({"OTEL_EXPORTER_OTLP_HEADERS": "generic-secret", "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "local-secret"}, False, "none", True),
        ({"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"}, False, "none", True),
        ({"OTEL_LOGS_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_HEADERS": "token=secret"}, False, "none", True),
    ]
    cases.extend(
        ({"FAIL_LOG_CONSTRUCTOR": name}, False, "none", True)
        for name in ("exporter", "processor", "bridge", "sdk")
    )
    cases.append(
        ({"FAIL_LOG_CONSTRUCTOR": "exporter", "OTEL_LOGS_EXPORTER": "otlp"}, False, "none", True)
    )
    for overrides, logs_enabled, auto_exporter, diagnostic in cases:
        result = subprocess.run(
            ["node", "-e", stubs + source + "console.log(JSON.stringify({ ...globalThis.startResult, restored: process.env.OTEL_LOGS_EXPORTER ?? null, boundary: logBoundary, environmentPreserved: JSON.stringify(originalOtelEnvironment) === JSON.stringify(Object.fromEntries(Object.entries(process.env).filter(([name]) => name.startsWith('OTEL_')))) }));"],
            env={**env, **overrides},
            text=True,
            capture_output=True,
            check=True,
        )
        assert json.loads(result.stdout) == {
            "localLogs": logs_enabled,
            "logOption": logs_enabled,
            "autoExporter": auto_exporter,
            "trace": 1,
            "metric": 1,
            "restored": overrides.get("OTEL_LOGS_EXPORTER"),
            "boundary": ({
                "headers": overrides.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS"),
                "explicitHeaders": False,
                "url": "http://127.0.0.1:4318/v1/logs",
            } if logs_enabled else (
                None if overrides.get("FAIL_LOG_CONSTRUCTOR") not in {"processor", "bridge", "sdk"}
                else {"headers": None, "explicitHeaders": False,
                      "url": "http://127.0.0.1:4318/v1/logs"}
            )),
            "environmentPreserved": True,
        }
        assert result.stderr == (
            "OTel local log pipeline skipped; trace and metric startup continues.\n"
            if diagnostic else ""
        )


def test_audit_nonlocal_log_conflict_is_a_locked_external_dependency() -> None:
    audit = _normalized(SKILLS / "otel-audit" / "SKILL.md")

    for term in (
        "create an `external follow-up` whose exact `required_fix` and `external_requirement` name the operator-owned configuration change",
        "create the local-log `required`/`default` finding with that external ID in `dependencies`",
        "keeps the executable finding locked",
        "never put this configuration conflict in `scan_blockers`",
    ):
        assert term in audit


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
        assert "local Splunk Observability Studio" in contract
        assert "OTEL_LOGS_EXPORTER=none" in contract
        assert "cloud" in contract


def test_direct_no_custom_span_prompts_still_grade_default_local_logs() -> None:
    rubric_paths = (
        ROOT / "evals/python/flask-basic/eval/qual/instrument.json",
        ROOT / "evals/node/express-basic/eval/qual/instrument.json",
        ROOT / "evals/java/springboot-basic/eval/qual/instrument.json",
        ROOT / "evals/go/kvstore/eval/qual/instrument.json",
    )

    for path in rubric_paths:
        definition = json.loads(_read(path))
        direct_prompt = next(
            prompt["task"]
            for prompt in definition["prompts"]
            if prompt["id"] == "direct"
        ).lower()
        contract = " ".join(definition["rubric"]).lower()

        assert "no custom business spans" in direct_prompt
        assert "local splunk observability studio" in contract
        assert "default" in contract
        assert "log" in contract

    skill = _read(ROOT / "skills/otel-instrument/SKILL.md")
    assert (
        "a direct request for the standard\n"
        "auto-instrumentation and default-local-log baseline may proceed"
    ) in skill
    assert "not applicable (direct baseline)" in skill
    assert (
        "On the permitted direct baseline\n"
        "  path, link only the absolute `.observe/otel-instrumentation.md` report"
    ) in skill
    assert (
        "When no canonical audit exists, stop before application-code edits"
        not in skill
    )


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
        assert "local Splunk Observability Studio" in contract
        assert "cloud forwarding limited to traces and metrics" in contract


def test_runtime_evals_prove_structured_logs_preserved_sink_and_opt_out() -> None:
    runtime_cases = {
        ROOT / "evals/python/flask-basic/eval/runtime/instrument.json": (
            "python-flask-basic",
            1,
        ),
        ROOT / "evals/node/express-basic/eval/runtime/instrument.json": (
            "node-express-basic",
            1,
        ),
        ROOT / "evals/go/kvstore/eval/runtime/instrument.json": (
            "go-kvstore",
            3,
        ),
    }

    for path, (service_name, record_count) in runtime_cases.items():
        definition = json.loads(_read(path))
        compose = _read(path.with_name("docker-compose.yml"))
        http_port = re.search(r"OTLP_HTTP_PORT=(\d+)", compose)
        assert http_port is not None
        expected_logs_endpoint = (
            f"http://observer:{http_port.group(1)}/v1/logs"
        )
        assert "runs the app in Docker Compose" in definition["prompts"][0]["task"]
        assert expected_logs_endpoint in definition["prompts"][0]["task"]
        default_check, opt_out_check = definition["checks"]

        assert default_check["environment"]["CODEX_EVAL_OTEL_LOGS_EXPORTER"] == ""
        assert default_check["stop_services_before_validation"] == ["app"]
        default_logs = next(
            endpoint
            for endpoint in default_check["expect"]["endpoints"]
            if endpoint.get("url") == "/api/query/logs"
        )
        record_check = next(
            check
            for check in default_logs["record_checks"]
            if check["id"] == "request-context-log"
            or check["id"] == "request-context-logs"
        )
        assert record_check["match"] == {"body": "runtime request completed"}
        assert record_check["field_contains"] == {"severityText": "WARN"}
        assert record_check["field_equals"] == {
            "resource.serviceName": service_name
        }
        assert record_check["non_empty"] == ["traceId", "spanId"]
        assert record_check["exact_count"] == record_count
        assert record_check["unique_by"] == ["traceId", "spanId"]
        assert record_check["correlates_with_trace"] is True

        shutdown_check = next(
            check
            for check in default_logs["record_checks"]
            if check["id"] == "shutdown-log"
        )
        assert shutdown_check == {
            "id": "shutdown-log",
            "match": {"body": "runtime shutdown completed"},
            "field_contains": {"severityText": "WARN"},
            "field_equals": {"resource.serviceName": service_name},
            "exact_count": 1,
        }

        default_sink = default_check["expect"]["service_logs"][0]
        assert default_sink["occurrences"]["runtime request completed"] == record_count
        assert default_sink["occurrences"]["runtime shutdown completed"] == 1

        assert opt_out_check["environment"]["CODEX_EVAL_OTEL_LOGS_EXPORTER"] == "none"
        assert opt_out_check["stop_services_before_validation"] == ["app"]
        opt_out_endpoints = opt_out_check["expect"]["endpoints"]
        assert {endpoint["id"] for endpoint in opt_out_endpoints} == {
            "traces",
            "metrics",
            "logs",
        }
        opt_out_logs = next(
            endpoint for endpoint in opt_out_endpoints if endpoint["id"] == "logs"
        )
        assert opt_out_logs["record_checks"] == [
            {
                "id": "no-exported-application-logs",
                "match": {"resource.serviceName": service_name},
                "exact_count": 0,
            }
        ]
        opt_out_sink = opt_out_check["expect"]["service_logs"][0]
        assert opt_out_sink["occurrences"]["runtime request completed"] == record_count
        assert opt_out_sink["occurrences"]["runtime shutdown completed"] == 1


def test_runtime_fixtures_emit_one_shutdown_marker_from_signal_lifecycle() -> None:
    fixture_sources = (
        ROOT / "evals/python/flask-basic/app.py",
        ROOT / "evals/node/express-basic/app.js",
        ROOT / "evals/go/kvstore/cmd/kvstore-server/main.go",
    )

    for path in fixture_sources:
        source = _read(path)
        assert source.count('"runtime shutdown completed"') == 1
        assert "SIGTERM" in source


def test_language_rubrics_grade_each_log_acceptance_path_independently() -> None:
    rubric_paths = (
        ROOT / "evals/python/flask-basic/eval/qual/instrument.json",
        ROOT / "evals/node/express-basic/eval/qual/instrument.json",
        ROOT / "evals/java/springboot-basic/eval/qual/instrument.json",
        ROOT / "evals/go/kvstore/eval/qual/instrument.json",
    )

    for path in rubric_paths:
        rubric = [item.lower() for item in json.loads(_read(path))["rubric"]]
        assert any(
            "request-context warning" in item
            and "severity" in item
            and "trace" in item
            and "span" in item
            and "resource identity" in item
            for item in rubric
        ), f"{path} lacks a focused record-integrity rubric"
        assert any(
            "otel_logs_exporter=none" in item and "sink" in item
            for item in rubric
        ), f"{path} lacks a focused opt-out and sink-preservation rubric"
        assert any(
            "cloud" in item and "trace/metric-only" in item
            for item in rubric
        ), f"{path} lacks a focused cloud-boundary rubric"
        assert any(
            "shutdown" in item and "flush" in item
            for item in rubric
        ), f"{path} lacks a focused shutdown rubric"


def test_java_fixture_has_deterministic_request_log_and_runtime_rationale() -> None:
    controller = _read(
        ROOT
        / "evals/java/springboot-basic/src/main/java/com/example/tasks/TaskController.java"
    )
    rationale = _normalized(ROOT / "evals/README.md")

    assert 'LOGGER.warn("runtime request completed")' in controller
    for term in (
        "no live Java runtime eval",
        "checked-in OpenTelemetry Java agent",
        "could pass independently",
        "record fields",
        "opt-out",
    ):
        assert term in rationale


def test_runtime_observer_keeps_grpc_loopback_when_http_is_container_visible() -> None:
    compose_paths = (
        ROOT / "evals/go/chi-basic/eval/runtime/docker-compose.yml",
        ROOT / "evals/go/chi-partial/eval/runtime/docker-compose.yml",
        ROOT / "evals/go/kvstore/eval/runtime/docker-compose.yml",
        ROOT / "evals/node/express-basic/eval/runtime/docker-compose.yml",
        ROOT / "evals/python/fastapi-celery/eval/runtime/docker-compose.yml",
        ROOT / "evals/python/flask-basic/eval/runtime/docker-compose.yml",
    )

    nondefault_http_ports = []
    for path in compose_paths:
        compose = _read(path)
        http_port_match = re.search(r"OTLP_HTTP_PORT=(\d+)", compose)
        grpc_port_match = re.search(r"OTLP_GRPC_PORT=(\d+)", compose)
        assert http_port_match is not None
        assert grpc_port_match is not None
        http_port = http_port_match.group(1)
        grpc_port = grpc_port_match.group(1)
        assert "HOST=0.0.0.0" in compose
        assert "OTLP_GRPC_HOST=127.0.0.1" in compose
        assert f"OTEL_EXPORTER_OTLP_ENDPOINT=http://observer:{http_port}" in compose
        if http_port != "4318" or grpc_port != "4317":
            nondefault_http_ports.append(http_port)

    assert nondefault_http_ports, "at least one runtime must exercise changed OTLP ports"

    for path in (
        ROOT / "evals/go/kvstore/eval/runtime/docker-compose.yml",
        ROOT / "evals/node/express-basic/eval/runtime/docker-compose.yml",
    ):
        compose = _read(path)
        http_port_match = re.search(r"OTLP_HTTP_PORT=(\d+)", compose)
        assert http_port_match is not None
        assert (
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="
            f"http://observer:{http_port_match.group(1)}/v1/logs"
        ) in compose

    flask_compose = _read(
        ROOT / "evals/python/flask-basic/eval/runtime/docker-compose.yml"
    )
    assert "OTEL_EXPORTER_OTLP_ENDPOINT=http://observer:55318" in flask_compose
    assert "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=" not in flask_compose
    assert "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=" not in flask_compose
    flask_runtime = json.loads(
        _read(ROOT / "evals/python/flask-basic/eval/runtime/instrument.json")
    )
    flask_task = flask_runtime["prompts"][0]["task"]
    assert "configures only the generic standard OTel HTTP endpoint" in flask_task
    assert "deriving exactly one http://observer:55318/v1/logs endpoint" in flask_task

    node_compose = _read(ROOT / "evals/node/express-basic/eval/runtime/docker-compose.yml")
    assert "instrumentation.cjs" not in node_compose

    fastapi_definition = json.loads(
        _read(ROOT / "evals/python/fastapi-celery/eval/runtime/instrument.json")
    )
    fastapi_task = fastapi_definition["prompts"][0]["task"]
    assert "lifespan" in fastapi_task
    assert "do not call FastAPI.add_event_handler" in fastapi_task

    observer_main = _read(ROOT / "observer/cmd/obstudio/main.go")
    assert 'valueOrEnv(config.otlpGRPCHost, "OTLP_GRPC_HOST", host)' in observer_main
    for dockerfile in (
        ROOT / "observer/Dockerfile",
        ROOT / "evals/runtime/observer.Dockerfile",
    ):
        observer_dockerfile = _read(dockerfile)
        assert "OBSTUDIO_MODE=docker-runtime-eval" in observer_dockerfile
        assert (
            "OBSTUDIO_DOCKER_RUNTIME_EVAL_ALLOW_NON_LOOPBACK=true"
            in observer_dockerfile
        )
        assert "OTLP_GRPC_HOST=127.0.0.1" in observer_dockerfile

    runtime_compose_files = sorted(
        ROOT.glob("evals/**/eval/runtime/docker-compose.yml")
    )
    assert runtime_compose_files
    for compose_file in runtime_compose_files:
        compose = _read(compose_file)
        if "dockerfile: evals/runtime/observer.Dockerfile" not in compose:
            continue
        observer_service = compose.split("\n  app:", 1)[0]
        assert "target: 17900" in observer_service
        assert "host_ip: 127.0.0.1" in observer_service

        definition = json.loads(_read(compose_file.with_name("instrument.json")))
        for check in definition["checks"]:
            assert check["expect"]["clear_path"] is None


@pytest.mark.parametrize("configuration,expected", [
    ({}, (60000, 30000)),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "1000.5", "OTEL_METRIC_EXPORT_TIMEOUT": "500.25"}, (1000.5, 500.25)),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "", "OTEL_METRIC_EXPORT_TIMEOUT": ""}, (60000, 30000)),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "invalid", "OTEL_METRIC_EXPORT_TIMEOUT": "invalid"}, (60000, 30000)),
])
def test_python_reader_constructor_retains_sdk_timing_reader(monkeypatch, caplog, configuration, expected):
    import io
    from opentelemetry.sdk.metrics import export as metric_export
    from opentelemetry.sdk.metrics._internal import export as sdk_export

    class OwnedUnstartedThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def start(self):
            pass
        def join(self, timeout=None):
            pass

    # Keep the actual SDK constructor/parser; prevent only its test-local ticker.
    monkeypatch.setattr(sdk_export, "Thread", OwnedUnstartedThread)
    for key in ("OTEL_METRIC_EXPORT_INTERVAL", "OTEL_METRIC_EXPORT_TIMEOUT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in configuration.items():
        monkeypatch.setenv(key, value)
    setup = _fenced_code_after(LANGUAGES / "python.md", "**File**: `otel_setup.py`", "python")
    owner = next(node for node in ast.parse(setup).body
                 if isinstance(node, ast.FunctionDef) and node.name == "configure_opentelemetry")
    call = next(node for node in ast.walk(owner) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "PeriodicExportingMetricReader")
    output = io.StringIO()
    exporter = metric_export.ConsoleMetricExporter(out=output)
    namespace = {"PeriodicExportingMetricReader": metric_export.PeriodicExportingMetricReader,
                 "OTLPMetricExporter": lambda: exporter, "os": os, "int": int}
    reader = eval(compile(ast.Expression(body=call), "guide-reader", "eval"), namespace)
    try:
        assert (reader._export_interval_millis, reader._export_timeout_millis) == expected
        assert output.getvalue() == ""
        assert all(os.environ[key] == value for key, value in configuration.items())
        if any(value in ("", "invalid") for value in configuration.values()):
            assert len([record for record in caplog.records
                        if record.name == sdk_export.__name__ and record.levelno == 30]) == 2
    finally:
        reader.shutdown()


@pytest.mark.parametrize("configuration", [
    {"OTEL_EXPORTER_OTLP_PROTOCOL": ""},
    {"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": ""},
    {"OTEL_EXPORTER_OTLP_PROTOCOL": "", "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": ""},
])
def test_python_manual_empty_protocol_uses_http_default(monkeypatch, configuration):
    for key in tuple(os.environ):
        if key.startswith("OTEL_"):
            monkeypatch.delenv(key)
    for key, value in configuration.items():
        monkeypatch.setenv(key, value)
    calls = []
    exporter = object()
    def create_exporter(**kwargs):
        calls.append(kwargs)
        return exporter
    helpers = _python_local_log_helpers(create_exporter)
    before = dict(os.environ)
    assert helpers["_local_log_exporter"]() is exporter
    assert calls == [{"endpoint": "http://127.0.0.1:4318/v1/logs"}]
    assert dict(os.environ) == before


def test_python_decorated_span_records_escaping_error_once():
    from types import SimpleNamespace
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    provider = TracerProvider(shutdown_on_exit=False)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("guide-test")
    order = SimpleNamespace(total=12)
    failure = RuntimeError("controlled failure")
    def charge_payment(_order):
        raise failure
    namespace = {"tracer": tracer, "trace": trace, "Order": object,
                 "db": SimpleNamespace(get_order=lambda _id: order), "charge_payment": charge_payment}
    example = _fenced_code_after(LANGUAGES / "python.md", "## Custom Spans", "python")
    function = next(node for node in ast.parse(example).body if isinstance(node, ast.FunctionDef))
    exec(compile(ast.Module(body=[function], type_ignores=[]), "guide-custom-span", "exec"), namespace)
    try:
        with pytest.raises(RuntimeError) as raised:
            namespace["process_order"]("controlled-order")
        assert raised.value is failure
        span, = exporter.get_finished_spans()
        assert span.status.status_code == trace.StatusCode.ERROR
        assert [event.name for event in span.events] == ["exception"]
        assert not trace.get_current_span().get_span_context().is_valid
    finally:
        provider.shutdown()






@pytest.mark.parametrize("configuration,expected", [
    ({}, ["1000", "500"]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "1000.5", "OTEL_METRIC_EXPORT_TIMEOUT": "500.25"}, ["1000.5", "500.25"]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "", "OTEL_METRIC_EXPORT_TIMEOUT": ""}, ["", ""]),
    ({"OTEL_METRIC_EXPORT_INTERVAL": "invalid", "OTEL_METRIC_EXPORT_TIMEOUT": "invalid"}, ["invalid", "invalid"]),
])
def test_python_local_metric_profile_defaults_only_when_absent(tmp_path, configuration, expected):
    guide = _read(LANGUAGES / "python.md")
    section = guide.split("For local development with Splunk Observability Studio,", 1)[1]
    command_lines = []
    for line in section.splitlines():
        if line.startswith("    "):
            command_lines.append(line[4:])
        elif command_lines:
            break
    assert command_lines
    command = "\n".join(command_lines)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "python", f"#!{sys.executable}\nimport os,json\n"
                      "print(json.dumps([os.environ.get('OTEL_METRIC_EXPORT_INTERVAL'), "
                      "os.environ.get('OTEL_METRIC_EXPORT_TIMEOUT')]))\n")
    result = subprocess.run(["/bin/sh", "-c", command],
                            env={"PATH": str(fake_bin), **configuration},
                            text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == expected
