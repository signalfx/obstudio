from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "otel-audit" / "SKILL.md"
REFERENCES = ROOT / "skills" / "otel-audit" / "references"


def normalized(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path == SKILL:
        text += "\n" + "\n".join(
            reference.read_text(encoding="utf-8")
            for reference in sorted(REFERENCES.rglob("*.md"))
        )
    return " ".join(text.split())


def test_audit_loads_only_relevant_contracts() -> None:
    entrypoint = SKILL.read_text(encoding="utf-8")

    assert len(entrypoint.encode("utf-8")) <= 10_000
    for route in (
        "references/languages/{go,python,node,java}.md",
        "references/telemetry-assessment.md",
        "../references/incident-readiness.md",
        "../references/genai-readiness.md",
        "references/genai-audit.md",
        "references/report-contract.md",
    ):
        assert route in entrypoint

    assert "do not load or restate unrelated language guidance" in " ".join(
        entrypoint.split()
    )
    assert "do not load either reference for non-GenAI services" in " ".join(
        entrypoint.split()
    )
    assert "one bounded `rg --files` inventory" in entrypoint
    assert "Do not repeat a complete file listing" in entrypoint
    assert "Do not load the shared" in entrypoint
    assert "LLM Inference Lifecycle Contract" not in entrypoint
    assert "@opentelemetry/instrumentation-express" not in entrypoint

    for reference in (
        REFERENCES / "telemetry-assessment.md",
        REFERENCES / "genai-audit.md",
        REFERENCES / "report-contract.md",
        *(REFERENCES / "languages").glob("*.md"),
    ):
        assert reference.is_file()


def test_local_report_contract_is_the_single_audit_authority() -> None:
    entrypoint = " ".join(SKILL.read_text(encoding="utf-8").split())
    report = " ".join(
        (REFERENCES / "report-contract.md").read_text(encoding="utf-8").split()
    )

    assert "sole authority for audit artifacts and handoff" in entrypoint
    assert "sole normative audit artifact, reader, and handoff contract" in report
    assert "consult only its `## Audit Contract`" not in report
    assert "if an ambiguity remains" not in entrypoint


def test_nested_audit_reference_routes_resolve_from_their_owner() -> None:
    skills = (ROOT / "skills").resolve()
    for owner in sorted(REFERENCES.rglob("*.md")):
        for relative in re.findall(r"`([^`]+\.md)`", owner.read_text()):
            if relative.startswith(".observe/") or "{" in relative:
                continue
            target = (owner.parent / relative).resolve()
            assert target.is_file(), f"{owner} routes to missing {relative}"
            assert target.is_relative_to(skills)

    assessment = REFERENCES / "telemetry-assessment.md"
    scanner_route = "../scripts/scan_python_otel_topology.py"
    assert scanner_route in assessment.read_text(encoding="utf-8")
    assert (assessment.parent / scanner_route).resolve().is_file()


def test_audit_renderer_owns_the_canonical_reader_projection() -> None:
    skill = normalized(SKILL)

    for term in (
        ".observe/otel-audit.json",
        ".observe/otel.html",
        "canonical machine-readable audit source",
        "self-contained human review report",
        "Write two audit artifacts",
        "finalize-audit",
        "--html .observe/otel.html",
        "turns exact existing repository-relative citations into local file links",
        "Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)",
    ):
        assert term.replace("`", "") in skill.replace("`", "")

    for term in (
        "the only failure is starting the loopback report server",
        "Do not inspect the helper implementation",
        "repeat the same server start without a concrete environment remedy",
        "include that proven error class",
        "bind: operation not permitted",
        "do not shorten it to \"the server could not start.\"",
        "say that it exposed no deeper cause",
        "never invent a review URL",
        "exact one-line handoff applies only when links.review_report exists",
    ):
        assert term.replace("`", "") in skill.replace("`", "")


def test_audit_human_report_is_one_priority_ordered_decision_view() -> None:
    skill = normalized(SKILL)

    for text in (skill,):
        for term in (
            "exactly one findings list ordered by",
            "Priority defines ordering only",
            "Findings · N",
            "Each card has one title, one expected monitoring outcome",
            "only the plain selectable terminal command section",
            "Do not render a selection-count summary",
            "do not expose browser save or download controls",
            "$otel-instrument --ids OTEL-001,OTEL-002 --decision OTEL-003=option-id",
            "normally finalized report must never show the literal <service-root> placeholder",
        ):
            assert term.replace("`", "") in text.replace("`", "")


def test_audit_finding_cards_keep_technical_detail_collapsed() -> None:
    skill = normalized(SKILL)

    for text in (skill,):
        for term in (
            "expanded narrative decision-sized",
            "Gap, Why it matters, a mode-aware required action, and Next step",
            "Instrumentation change for executable work",
            "Decision needed for a manual prerequisite",
            "External requirement for an external prerequisite",
            "one collapsed Technical details disclosure",
            "Do not render raw verification-scenario IDs",
            "Those fields remain in canonical JSON",
        ):
            assert term.replace("`", "") in text.replace("`", "")


def test_audit_selection_handoff_preserves_explicit_user_intent() -> None:
    skill = normalized(SKILL)

    for text in (skill,):
        for term in (
            "neutral Select checkbox",
            "requested_ids",
            "approved_ids",
            "decision_answers",
            "Use explicit requested IDs",
            "dependency-closed executable selection",
            "review_selection",
            ".observe/otel-selection.json",
        ):
            assert term.replace("`", "") in text.replace("`", "")


def test_audit_does_not_promote_context_or_mutually_exclusive_branches_to_findings() -> None:
    skill = normalized(SKILL)

    for text in (skill,):
        for term in (
            "Do not create manual or external findings just to record product/runtime choices",
            "billing, cost, safety policy, content-governance, or external business context",
            "create one option-locked executable finding per real branch",
            "Do not use one shared executable finding for multiple exclusive options",
            "two branch implementations appear as simultaneous independent audit gaps",
        ):
            assert term.replace("`", "") in text.replace("`", "")

    for term in (
        "Readiness rows are audit context first",
        "Promote a missing or partial readiness surface",
        "only when the repository owns a concrete OTel closure gap",
        "Do not promote service behavior choices, health endpoint semantics, readiness/liveness contracts",
        "put each branch ID in only that option's unlocks",
    ):
        assert term.replace("`", "") in skill.replace("`", "")
