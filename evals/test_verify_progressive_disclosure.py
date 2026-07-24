from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY_DIR = ROOT / "skills" / "otel-verify"
VERIFY_SKILL = VERIFY_DIR / "SKILL.md"
INSTRUMENT_SKILL = ROOT / "skills" / "otel-instrument" / "SKILL.md"
INSTRUMENT_HANDOFF = (
    ROOT
    / "skills"
    / "otel-instrument"
    / "references"
    / "json-approval-handoff.md"
)
REPORT_FLOW = ROOT / "skills" / "references" / "report-flow-contract.md"
DIRECT_REF = VERIFY_DIR / "references" / "direct-verification.md"
EXPLORER_REF = VERIFY_DIR / "references" / "explorer-witness.md"
PATH_REF = VERIFY_DIR / "references" / "path-scenario-coverage.md"
TEST_AUTHORING_REF = VERIFY_DIR / "references" / "app-code-test-authoring.md"
REPORT_REF = VERIFY_DIR / "references" / "verification-report.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_verify_routes_explorer_and_topology_details_to_references() -> None:
    skill = _read(VERIFY_SKILL)
    explorer = _read(EXPLORER_REF)
    paths = _read(PATH_REF)

    assert "references/explorer-witness.md" in skill
    assert "references/path-scenario-coverage.md" in skill
    assert (
        VERIFY_DIR / "references/explorer-witness.md"
    ).resolve() == EXPLORER_REF.resolve()
    assert (
        VERIFY_DIR / "references/path-scenario-coverage.md"
    ).resolve() == PATH_REF.resolve()

    for term in (
        "## Unit+OTLP Contract Harness",
        "verification.scenario",
        "http.server.request.duration",
        "`library-owned compatibility`",
        "Mark `Verified: unit+OTLP` only when",
    ):
        assert term in explorer

    for term in (
        "## Nested Topology Harnesses",
        "generated temporary nested SDK contract",
        "workflow -> agent -> llm.call",
        "querying parent span ids, links, span depth",
        "contract-only evidence",
    ):
        assert term in paths

    assert "`library-owned compatibility`" not in skill
    assert "generated temporary nested SDK contract" not in skill


def test_verify_routes_test_authoring_details_only_on_explicit_request() -> None:
    skill = _read(VERIFY_SKILL)
    authoring = _read(TEST_AUTHORING_REF)

    assert "only when the user explicitly asks" in skill
    assert "references/app-code-test-authoring.md" in skill
    assert (
        VERIFY_DIR / "references/app-code-test-authoring.md"
    ).resolve() == TEST_AUTHORING_REF.resolve()

    for term in (
        "existing test framework, fixtures, naming, and fake",
        "before importing app modules that",
        "A real call into the instrumented app code",
        "Run the focused tests and record their paths and results",
        "smallest required seam",
    ):
        assert term in authoring

    assert "Use the repo's existing test framework" not in skill
    assert "Add focused tests near the instrumented code's existing test area" not in skill


def test_verify_conditional_sections_remain_concise() -> None:
    skill = _read(VERIFY_SKILL)
    explorer_section = _section(
        skill,
        "### 6. Prefer Unit+OTLP Contract Harnesses",
        "### 7. Author App-Code Tests When Requested",
    )
    authoring_section = _section(
        skill,
        "### 7. Author App-Code Tests When Requested",
        "### 8. Produce Verification Artifacts",
    )

    assert len(explorer_section.split()) < 180
    assert len(authoring_section.split()) < 100
    assert "Verified: unit+OTLP" in explorer_section
    assert "explicitly asks" in authoring_section


def test_verify_frontloads_stable_title_table_and_validator_rules() -> None:
    lines = _read(VERIFY_SKILL).splitlines()
    front = " ".join("\n".join(lines[:130]).split())
    report = " ".join(_read(REPORT_REF).split())
    assert "final segment of the owning module/package identifier" in front
    assert "semantic-import suffix such as `/v2`" in front
    assert "use the preceding module segment" in front
    assert "never put a full module path" in front
    assert "Escape every literal vertical bar as `\\|`" in front
    assert "Backticks do not make raw `|` safe" in front
    assert "scripts/validate_reader_report.py" in front
    assert "references/verification-report.md" in front
    assert "python3 -I" in report
    assert "rerun until the validator passes" in report
    assert "Do not finalize an unvalidated report" in report


def test_direct_verify_closes_source_visible_runtime_and_cardinality_gaps() -> None:
    raw_skill = _read(VERIFY_SKILL)
    assert "references/direct-verification.md" in raw_skill
    skill = " ".join((raw_skill + "\n" + _read(DIRECT_REF)).split())

    for requirement in (
        "no canonical `.observe/otel-audit.json` exists",
        "endpoint configurability",
        "stable `service.name`",
        "bounded span names and dimensions",
        "force-flush and shutdown paths",
        "source-proven absent capability",
        "reader row with `Not configured`",
        "cardinality defect",
        "emission remains `Not proven`",
        "exact `OTel item` label",
        ".observe/tmp/otel-verify-expected-items.txt",
    ):
        assert requirement in skill


def test_incomplete_scenario_evidence_is_not_presented_as_a_pass() -> None:
    for path in (VERIFY_SKILL, REPORT_FLOW):
        text = " ".join(_read(path).split())
        assert "focused evidence obtained" in text.lower()
        assert "`not_proven` scenario" in text
        assert "passed" in text
        assert "incomplete" in text

    instrument = _read(INSTRUMENT_SKILL)
    assert "references/json-approval-handoff.md" in instrument
    instrument_contract = " ".join(
        (instrument + "\n" + _read(INSTRUMENT_HANDOFF)).split()
    )
    assert "focused evidence obtained" in instrument_contract.lower()
    assert "`not_proven` scenario" in instrument_contract
    assert "passed" in instrument_contract
    assert "incomplete" in instrument_contract
