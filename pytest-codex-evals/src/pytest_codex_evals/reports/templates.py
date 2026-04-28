from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportTemplate:
    category: str
    summary_title: str
    failure_title: str
    empty_failures: str
    evidence_title: str | None = None


TEMPLATES = {
    "sanity": ReportTemplate(
        category="sanity",
        summary_title="Sanity Summary",
        failure_title="Sanity Failures",
        empty_failures="No sanity failures.",
    ),
    "rubric": ReportTemplate(
        category="rubric",
        summary_title="Rubric Summary",
        failure_title="Rubric Failures",
        empty_failures="No rubric failures.",
    ),
    "runtime": ReportTemplate(
        category="runtime",
        summary_title="Runtime Summary",
        failure_title="Runtime Failures",
        empty_failures="No runtime failures.",
        evidence_title="Compose Evidence",
    ),
}


def template_for_kind(kind: str) -> ReportTemplate:
    if kind not in TEMPLATES:
        raise ValueError(f"unknown report template: {kind}")
    return TEMPLATES[kind]
