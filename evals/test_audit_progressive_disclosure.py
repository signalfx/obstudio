from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "otel-audit" / "SKILL.md"
REPORT_FLOW = ROOT / "skills" / "references" / "report-flow-contract.md"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_audit_renderer_owns_the_canonical_reader_projection() -> None:
    skill = normalized(SKILL)

    for term in (
        ".observe/otel-audit.json",
        ".observe/otel.html",
        ".observe/otel.md",
        "canonical machine-readable audit source",
        "self-contained human review report",
        "backward-compatible reader summary",
        "render-markdown command owns the complete .observe/otel.md",
        "Do not hand-author or independently update .observe/otel.md",
        "turns exact existing repository-relative citations into local file links",
        "Review report: [otel.html](/absolute/repo/.observe/otel.html)",
    ):
        assert term.replace("`", "") in skill.replace("`", "")


def test_audit_human_report_is_one_priority_ordered_decision_view() -> None:
    skill = normalized(SKILL)
    flow = normalized(REPORT_FLOW)

    for text in (skill, flow):
        for term in (
            "exactly one findings list ordered by",
            "Priority controls order only",
            "Do not render priority sections, headings, labels, tags, colors, legends, counts, action queues",
            "Do not render Priority, Effort, or Status filter facets",
            "Findings · N",
            "Do not render tag chips on finding cards",
            "Do not render Required, Recommended, Deferred, Fix now, Consider next, Decide now, or Decide first as human categories",
            "N in selection",
            "Save selection",
            "plain selectable terminal fallback",
            "$otel-instrument --ids OTEL-001,OTEL-002 --decision OTEL-003=option-id",
        ):
            assert term.replace("`", "") in text.replace("`", "")


def test_audit_finding_cards_keep_technical_detail_collapsed() -> None:
    skill = normalized(SKILL)
    flow = normalized(REPORT_FLOW)

    for text in (skill, flow):
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
    flow = normalized(REPORT_FLOW)

    for text in (skill, flow):
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
