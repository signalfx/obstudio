from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .definitions import CaseResult, GradeCheckResult, SideResult, ValidationResult
from .reports import ReportTemplate, template_for_kind


LIVE_MODES = {"with_skill", "with_baseline", "ab"}
SIDE_ATTRS = {
    "with_skill": "with_skill",
    "with_baseline": "baseline",
}
LIVE_SECTION_DEFINITIONS = {
    "sanity": (template_for_kind("sanity"), "sanity_failures"),
    "rubric": (template_for_kind("rubric"), "rubric_failures"),
    "runtime": (template_for_kind("runtime"), "runtime_failures"),
}
KIND_LIVE_SECTIONS = {
    "sanity": ("sanity",),
    "rubric": ("rubric",),
    "runtime": ("runtime",),
    "validation": (),
}


def write_side_reports(
    repo_root: Path,
    run_root: Path,
    skill: str,
    mode: str,
    results: list[CaseResult],
    metadata: dict[str, Any] | None = None,
) -> None:
    write_live_reports(repo_root, run_root, skill, mode, results, metadata)


def write_ab_reports(
    repo_root: Path,
    run_root: Path,
    skill: str,
    results: list[CaseResult],
    metadata: dict[str, Any] | None = None,
) -> None:
    write_live_reports(repo_root, run_root, skill, "ab", results, metadata)


def write_live_reports(
    repo_root: Path,
    run_root: Path,
    skill: str,
    mode: str,
    results: list[CaseResult],
    metadata: dict[str, Any] | None = None,
) -> None:
    if mode not in LIVE_MODES:
        raise ValueError(f"{mode} is not a live report mode")

    normalized_metadata = report_metadata(skill, mode, run_root, metadata)
    result_paths = write_live_result_jsons(repo_root, run_root, mode, results)
    benchmark = build_live_benchmark(skill, mode, results, normalized_metadata, result_paths)
    report = render_live_report(skill, benchmark)

    prefix = mode
    benchmark_path = run_root / f"{prefix}-benchmark.json"
    report_path = run_root / f"{prefix}-report.md"
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")

    shutil.copyfile(report_path, run_root / "report.md")
    shutil.copyfile(benchmark_path, run_root / "benchmark.json")


def write_validation_reports(
    repo_root: Path,
    run_root: Path,
    skill: str,
    results: list[ValidationResult],
    metadata: dict[str, Any] | None = None,
) -> None:
    normalized_metadata = report_metadata(skill, "validation", run_root, metadata)
    benchmark = build_validation_benchmark(repo_root, skill, results, normalized_metadata)
    benchmark_path = run_root / "validation-benchmark.json"
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")

    report = render_validation_report(skill, benchmark)
    report_path = run_root / "validation-report.md"
    report_path.write_text(report, encoding="utf-8")


def write_combined_session_reports(runs: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for run in runs:
        if not run.get("results"):
            continue
        key = (str(run["repo_root"]), str(run["run_root"]), run["skill"])
        grouped.setdefault(key, []).append(run)

    for run_group in grouped.values():
        first = run_group[0]
        repo_root = first["repo_root"]
        run_root = first["run_root"]
        skill = first["skill"]
        validation_results: list[ValidationResult] = []
        validation_metadata: dict[str, Any] = {}
        live_runs: list[dict[str, Any]] = []
        for run in run_group:
            if run["mode"] == "validation":
                validation_results.extend(run["results"])
                validation_metadata = run.get("metadata", validation_metadata)
            elif run["mode"] in LIVE_MODES:
                live_runs.append(run)

        benchmark = build_combined_benchmark(repo_root, run_root, skill, validation_results, validation_metadata, live_runs)
        report = render_combined_report(skill, benchmark)
        benchmark_path = run_root / "benchmark.json"
        report_path = run_root / "report.md"
        benchmark_path.parent.mkdir(parents=True, exist_ok=True)
        benchmark_path.write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
        report_path.write_text(report, encoding="utf-8")

        latest_dir = repo_root / "eval-reports" / skill / report_key(benchmark)
        latest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(report_path, latest_dir / "report.md")
        shutil.copyfile(benchmark_path, latest_dir / "benchmark.json")


def build_combined_benchmark(
    repo_root: Path,
    run_root: Path,
    skill: str,
    validation_results: list[ValidationResult],
    validation_metadata: dict[str, Any],
    live_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    if not validation_metadata:
        validation_metadata = next((run.get("metadata", {}) for run in live_runs if run.get("metadata")), {})
    if not validation_metadata:
        validation_metadata = {"mode": "validation", "skill": skill, "run_id": run_root.name, "repo_root": str(repo_root)}
    validation = build_validation_benchmark(repo_root, skill, validation_results, report_metadata(skill, "validation", run_root, validation_metadata))

    live = []
    for run in sorted(live_runs, key=lambda item: item["mode"]):
        result_paths = collect_existing_result_paths(repo_root, run["run_root"], run["results"])
        live.append(
            build_live_benchmark(
                skill,
                run["mode"],
                run["results"],
                report_metadata(skill, run["mode"], run["run_root"], run.get("metadata")),
                result_paths,
            )
        )

    metadata = combined_metadata(skill, run_root, validation_metadata, live)
    return {
        "skill": skill,
        "metadata": metadata,
        "validation": validation,
        "live": live,
        "sanity_failures": collect_combined_failures(live, "sanity"),
        "rubric_failures": collect_combined_failures(live, "rubric"),
        "runtime_failures": collect_combined_failures(live, "runtime"),
    }


def collect_existing_result_paths(
    repo_root: Path,
    run_root: Path,
    results: list[CaseResult],
) -> dict[str, dict[str, str]]:
    paths: dict[str, dict[str, str]] = {}
    for base_id, group in grouped_case_results(results).items():
        first = group[0]
        eval_dir = run_root / "results" / first.language / first.service / eval_kind(base_id)
        side_paths: dict[str, str] = {}
        for name in ("eval", "with_skill", "with_baseline"):
            path = eval_dir / f"{name}.json"
            if path.is_file():
                side_paths[name] = relative_to_repo(repo_root, path)
        paths[base_id] = side_paths
    return paths


def combined_metadata(
    skill: str,
    run_root: Path,
    validation_metadata: dict[str, Any],
    live: list[dict[str, Any]],
) -> dict[str, Any]:
    live_metadata = [item.get("metadata", {}) for item in live]
    metadata_sources = live_metadata or [validation_metadata]
    modes = [item.get("mode", "validation") for item in live] or ["validation"]
    eval_kinds = sorted({str(meta.get("eval_kind") or "-") for meta in metadata_sources if meta.get("eval_kind")}) or ["validation"]
    agent_models = sorted({str(meta.get("agent_model") or "-") for meta in metadata_sources if meta.get("agent_model")}) or ["-"]
    judge_models = sorted({str(meta.get("judge_model") or "-") for meta in metadata_sources if meta.get("judge_model")}) or ["-"]
    config_paths = sorted({str(meta.get("config_path") or "-") for meta in [validation_metadata, *live_metadata] if meta.get("config_path")}) or ["-"]
    return {
        "mode": ", ".join(modes),
        "eval_kind": ", ".join(eval_kinds),
        "skill": skill,
        "run_id": run_root.name,
        "agent_model": ", ".join(agent_models),
        "judge_model": ", ".join(judge_models),
        "rubric_enabled": any(bool(meta.get("rubric_enabled")) for meta in metadata_sources),
        "runtime_enabled": any(bool(meta.get("runtime_enabled")) for meta in metadata_sources),
        "workers": ", ".join(sorted({str(meta.get("workers") or "-") for meta in metadata_sources if meta.get("workers")})) or "-",
        "config_path": ", ".join(config_paths),
    }


def render_combined_report(skill: str, benchmark: dict[str, Any]) -> str:
    lines = [
        f"# {skill} Codex Eval Report",
    ]
    lines.extend(render_environment_table(benchmark["metadata"], "Modes"))

    lines.extend(render_validation_section(benchmark["validation"]))
    for section_key in live_section_keys(benchmark["metadata"]):
        template, failures_key = LIVE_SECTION_DEFINITIONS[section_key]
        lines.extend(render_live_section(template, benchmark["live"], benchmark[failures_key]))
    lines.extend(["", "## Result JSON", ""])
    lines.append("File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.")
    return "\n".join(lines) + "\n"


def live_section_keys(metadata: dict[str, Any]) -> tuple[str, ...]:
    kinds = eval_kind_values(metadata)
    if len(kinds) == 1 and kinds[0] in KIND_LIVE_SECTIONS:
        return KIND_LIVE_SECTIONS[kinds[0]]
    return tuple(LIVE_SECTION_DEFINITIONS)


def render_validation_section(validation: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "## Validation",
        "",
        "| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    evals = validation.get("evals", [])
    if not evals:
        lines.append("| - | - | 0 | - | 0 | 0 | 0 |")
        return lines
    for item in evals:
        lines.append(
            "| {eval_id} | {service} | {prompts} | {path} | {det} | {qual} | {runtime} |".format(
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                path=markdown_cell(item["definition_path"]),
                det=item["sanity_check_count"],
                qual=item["rubric_check_count"],
                runtime=item.get("runtime_check_count", 0),
            )
        )
    return lines


def render_live_section(template: ReportTemplate, live_runs: list[dict[str, Any]], failures: list[dict[str, str]]) -> list[str]:
    category = template.category
    lines = [
        "",
        f"## {template.summary_title}",
        "",
        "| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = []
    for live in live_runs:
        for item in live.get("evals", []):
            rows.append(
                "| {mode} | {eval_id} | {service} | {prompts} | {ws} | {ws_tokens} | {ws_time} | {base} | {base_tokens} | {base_time} |".format(
                    mode=markdown_cell(live["mode"]),
                    eval_id=markdown_cell(item["id"]),
                    service=markdown_cell(item["case"]),
                    prompts=item["prompt_count"],
                    ws=format_category(item.get("with_skill"), category),
                    ws_tokens=format_tokens(item.get("with_skill")),
                    ws_time=format_duration(item.get("with_skill")),
                    base=format_category(item.get("with_baseline"), category),
                    base_tokens=format_tokens(item.get("with_baseline")),
                    base_time=format_duration(item.get("with_baseline")),
                )
            )
    if rows:
        lines.extend(rows)
    else:
        lines.append("| - | - | - | 0 | - | - | - | - | - | - |")

    lines.extend(["", f"## {template.failure_title}", ""])
    if not failures:
        lines.append(template.empty_failures)
    else:
        lines.extend(["| Mode | Service | Side | Prompt | Result | Evidence |", "|---|---|---|---|---|---|"])
        for failure in failures:
            lines.append(
                "| {mode} | {service} | {side} | {prompt} | {result} | {evidence} |".format(
                    mode=markdown_cell(failure.get("mode")),
                    service=markdown_cell(failure["service"]),
                    side=markdown_cell(failure["side"]),
                    prompt=markdown_cell(failure["prompt"]),
                    result=markdown_cell(failure["result"]),
                    evidence=markdown_cell(truncate(failure["evidence"], 320)),
                )
            )
    if template.evidence_title:
        lines.extend(["", f"## {template.evidence_title}", ""])
        lines.append("Runtime failure evidence includes the relevant Docker Compose log tail in the failure table.")
    return lines


def write_live_result_jsons(
    repo_root: Path,
    run_root: Path,
    mode: str,
    results: list[CaseResult],
) -> dict[str, dict[str, str]]:
    paths: dict[str, dict[str, str]] = {}
    for base_id, group in grouped_case_results(results).items():
        first = group[0]
        eval_dir = run_root / "results" / first.language / first.service / eval_kind(base_id)
        eval_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "mode": mode,
            "id": base_id,
            "skill": first.skill,
            "language": first.language,
            "service": first.service,
            "prompt_count": len(group),
            "prompts": [case_result_payload(result) for result in group],
            "aggregate": aggregate_case_group(group),
        }
        eval_path = eval_dir / "eval.json"
        eval_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        side_paths = {"eval": relative_to_repo(repo_root, eval_path)}
        for side_key in SIDE_ATTRS:
            side_payload = {
                "mode": mode,
                "side": side_key,
                "id": base_id,
                "skill": first.skill,
                "language": first.language,
                "service": first.service,
                "prompt_count": len(group),
                "prompts": [side_result_payload(result, side_key) for result in group],
                "aggregate": aggregate_side(group, side_key),
            }
            side_path = eval_dir / f"{side_key}.json"
            side_path.write_text(json.dumps(side_payload, indent=2), encoding="utf-8")
            side_paths[side_key] = relative_to_repo(repo_root, side_path)
        paths[base_id] = side_paths
    return paths


def case_result_payload(result: CaseResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "base_id": result.base_id,
        "prompt_id": result.prompt_id,
        "case": f"{result.language}/{result.service}",
        "with_skill": side_summary(result.with_skill),
        "with_baseline": side_summary(result.baseline),
    }


def side_result_payload(result: CaseResult, side_key: str) -> dict[str, Any]:
    side = side_for_key(result, side_key)
    return {
        "id": result.id,
        "base_id": result.base_id,
        "prompt_id": result.prompt_id,
        "case": f"{result.language}/{result.service}",
        "result": side_summary(side),
    }


def side_summary(side: SideResult | None) -> dict[str, Any] | None:
    if side is None:
        return None
    return {
        "exit_code": side.exit_code,
        "sanity": check_summary(side, "sanity"),
        "runtime": check_summary(side, "runtime"),
        "rubric": load_rubric_grade(side),
        "command_count": side.command_count,
        "duration_seconds": side.duration_seconds,
        "agent_duration_seconds": side.agent_duration_seconds,
        "rubric_duration_seconds": side.rubric_duration_seconds,
        "tokens": side.tokens,
        "agent_tokens": side.agent_tokens,
        "rubric_tokens": side.rubric_tokens,
        "errors": side.errors,
        "trace_path": side.trace_path,
        "final_message_path": side.final_message_path,
        "rubric_grade_path": side.rubric_grade_path,
        "rubric_trace_path": side.rubric_trace_path,
    }


def check_summary(side: SideResult, category: str) -> dict[str, Any]:
    checks = checks_for_category(side, category)
    total = sum(1 for check in checks if not check.skipped)
    passed = sum(1 for check in checks if check.passed and not check.skipped)
    skipped = sum(1 for check in checks if check.skipped)
    return {
        "pass_rate": 1.0 if total == 0 else passed / total,
        "passed": passed,
        "total": total,
        "skipped": skipped,
        "checks": [check.model_dump(mode="json") for check in checks],
    }


def checks_for_category(side: SideResult, category: str) -> list[GradeCheckResult]:
    return [check for check in side.grade.checks if check.category == category]


def aggregate_check_category(sides: list[SideResult], category: str) -> dict[str, Any]:
    checks = [check for side in sides for check in checks_for_category(side, category)]
    return {
        "passed": sum(1 for check in checks if check.passed and not check.skipped),
        "total": sum(1 for check in checks if not check.skipped),
        "skipped": sum(1 for check in checks if check.skipped),
    }


def build_live_benchmark(
    skill: str,
    mode: str,
    results: list[CaseResult],
    metadata: dict[str, Any],
    result_paths: dict[str, dict[str, str]],
) -> dict[str, Any]:
    evals = []
    for base_id, group in grouped_case_results(results).items():
        aggregate = aggregate_case_group(group)
        aggregate["result_paths"] = result_paths.get(base_id, {})
        evals.append(aggregate)

    failures = collect_failures(results)
    return {
        "mode": mode,
        "skill": skill,
        "metadata": metadata,
        "evals": evals,
        "failures": failures,
        "summary": {
            "eval_count": len(evals),
            "case_count": len(results),
            "prompt_count": len(results),
            "failure_count": len(failures),
            "with_skill": aggregate_side(results, "with_skill"),
            "with_baseline": aggregate_side(results, "with_baseline"),
        },
    }


def aggregate_case_group(group: list[CaseResult]) -> dict[str, Any]:
    first = group[0]
    return {
        "id": first.base_id,
        "case": f"{first.language}/{first.service}",
        "language": first.language,
        "service": first.service,
        "prompt_count": len(group),
        "prompts": [result.prompt_id for result in group],
        "with_skill": aggregate_side(group, "with_skill"),
        "with_baseline": aggregate_side(group, "with_baseline"),
    }


def aggregate_side(results: list[CaseResult], side_key: str) -> dict[str, Any] | None:
    sides = [side for result in results if (side := side_for_key(result, side_key)) is not None]
    if not sides:
        return None

    rubric = [grade for side in sides if (grade := load_rubric_grade(side)) is not None]
    rubric_total = sum(int(grade["total"]) for grade in rubric)
    rubric_passed = sum(int(grade["passed"]) for grade in rubric)
    scores = [int(grade["score"]) for grade in rubric if isinstance(grade.get("score"), int)]
    return {
        "prompt_count": len(sides),
        "sanity": aggregate_check_category(sides, "sanity"),
        "runtime": aggregate_check_category(sides, "runtime"),
        "rubric": None
        if not rubric
        else {
            "passed": rubric_passed,
            "total": rubric_total,
            "average_score": average(scores) if scores else None,
        },
        "command_count": sum(side.command_count for side in sides),
        "duration_seconds": round(sum(side.duration_seconds for side in sides), 3),
        "agent_duration_seconds": round(sum(side.agent_duration_seconds for side in sides), 3),
        "rubric_duration_seconds": round(sum(side.rubric_duration_seconds for side in sides), 3),
        "tokens": sum(side.tokens for side in sides),
        "agent_tokens": sum(side.agent_tokens for side in sides),
        "rubric_tokens": sum(side.rubric_tokens for side in sides),
        "error_count": sum(len(side.errors) for side in sides),
    }


def collect_failures(results: list[CaseResult]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for result in sorted(results, key=lambda item: (item.language, item.service, item.base_id, item.prompt_id)):
        service = f"{result.language}/{result.service}"
        for side_key in SIDE_ATTRS:
            side = side_for_key(result, side_key)
            if side is None:
                continue
            for check in side.grade.checks:
                if check.passed or check.skipped:
                    continue
                category = check.category
                failures.append(
                    {
                        "service": service,
                        "side": side_key,
                        "prompt": result.prompt_id,
                        "category": category,
                        "result": f"{category}:{check.id} FAIL",
                        "evidence": check.evidence,
                    }
                )
            rubric = load_rubric_grade(side)
            if rubric is None:
                continue
            rubric_failures = 0
            for check in rubric.get("checks", []):
                if bool(check.get("pass")):
                    continue
                rubric_failures += 1
                failures.append(
                    {
                        "service": service,
                        "side": side_key,
                        "prompt": result.prompt_id,
                        "category": "rubric",
                        "result": f"rubric:{check.get('id', 'check')} FAIL",
                        "evidence": str(check.get("evidence") or check.get("notes") or ""),
                    }
                )
            if not rubric_failures and rubric.get("overall_pass") is False:
                failures.append(
                    {
                        "service": service,
                        "side": side_key,
                        "prompt": result.prompt_id,
                        "category": "rubric",
                        "result": "rubric:overall FAIL",
                        "evidence": str(rubric.get("notes") or "overall rubric grade failed"),
                    }
                )
    return failures


def collect_combined_failures(live_runs: list[dict[str, Any]], category: str) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for live in live_runs:
        mode = live.get("mode", "")
        for failure in live.get("failures", []):
            if failure.get("category") != category:
                continue
            with_mode = dict(failure)
            with_mode["mode"] = str(mode)
            failures.append(with_mode)
    return failures


def render_live_report(skill: str, benchmark: dict[str, Any]) -> str:
    lines = [
        f"# {skill} Codex Eval Report",
    ]
    lines.extend(render_environment_table(benchmark["metadata"], "Mode"))

    lines.extend(
        [
            "",
            "## Eval Summary",
            "",
            "| Eval | Service | Prompts | With Skill Sanity | With Skill Rubric | With Skill Tokens | With Skill Time | With Baseline Sanity | With Baseline Rubric | Baseline Tokens | Baseline Time |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in benchmark["evals"]:
        lines.append(
            "| {eval_id} | {service} | {prompts} | {ws_det} | {ws_qual} | {ws_tokens} | {ws_time} | {base_det} | {base_qual} | {base_tokens} | {base_time} |".format(
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                ws_det=format_sanity(item.get("with_skill")),
                ws_qual=format_rubric(item.get("with_skill")),
                ws_tokens=format_tokens(item.get("with_skill")),
                ws_time=format_duration(item.get("with_skill")),
                base_det=format_sanity(item.get("with_baseline")),
                base_qual=format_rubric(item.get("with_baseline")),
                base_tokens=format_tokens(item.get("with_baseline")),
                base_time=format_duration(item.get("with_baseline")),
            )
        )

    lines.extend(["", "## Failure Cases", ""])
    failures = benchmark["failures"]
    if not failures:
        lines.append("No sanity or rubric failures.")
    else:
        lines.extend(["| Service | Side | Prompt | Result | Evidence |", "|---|---|---|---|---|"])
        for failure in failures:
            lines.append(
                "| {service} | {side} | {prompt} | {result} | {evidence} |".format(
                    service=markdown_cell(failure["service"]),
                    side=markdown_cell(failure["side"]),
                    prompt=markdown_cell(failure["prompt"]),
                    result=markdown_cell(failure["result"]),
                    evidence=markdown_cell(truncate(failure["evidence"], 320)),
                )
            )

    lines.extend(["", "## Result JSON", ""])
    lines.append("File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.")
    return "\n".join(lines) + "\n"


def build_validation_benchmark(
    repo_root: Path,
    skill: str,
    results: list[ValidationResult],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    evals = []
    for base_id, group in grouped_validation_results(results).items():
        first = group[0]
        evals.append(
            {
                "id": first.base_id,
                "case": f"{first.language}/{first.service}",
                "language": first.language,
                "service": first.service,
                "prompt_count": len(group),
                "prompts": [result.prompt_id for result in group],
                "definition_path": relative_to_repo(repo_root, first.definition_path),
                "eval_dir": relative_to_repo(repo_root, first.fixture_dir),
                "skill_path": relative_to_repo(repo_root, first.skill_path),
                "sanity_check_count": first.sanity_check_count,
                "rubric_check_count": first.rubric_check_count,
                "runtime_check_count": first.runtime_check_count,
            }
        )

    return {
        "mode": "validation",
        "skill": skill,
        "metadata": metadata,
        "evals": evals,
        "summary": {
            "eval_count": len(evals),
            "case_count": len(results),
            "prompt_count": len(results),
            "sanity_check_count": sum(result.sanity_check_count for result in results),
            "rubric_check_count": sum(result.rubric_check_count for result in results),
            "runtime_check_count": sum(result.runtime_check_count for result in results),
        },
    }


def render_validation_report(skill: str, benchmark: dict[str, Any]) -> str:
    lines = [
        f"# {skill} Codex Eval Validation Report",
        "",
        "This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.",
    ]
    lines.extend(render_environment_table(benchmark["metadata"], "Mode"))

    lines.extend(
        [
            "",
            "## Eval Summary",
            "",
            "| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |",
            "|---|---|---:|---|---:|---:|---:|",
        ]
    )
    for item in benchmark["evals"]:
        lines.append(
            "| {eval_id} | {service} | {prompts} | {path} | {det} | {qual} | {runtime} |".format(
                eval_id=markdown_cell(item["id"]),
                service=markdown_cell(item["case"]),
                prompts=item["prompt_count"],
                path=markdown_cell(item["definition_path"]),
                det=item["sanity_check_count"],
                qual=item["rubric_check_count"],
                runtime=item.get("runtime_check_count", 0),
            )
        )
    lines.append("")
    return "\n".join(lines)


def report_metadata(
    skill: str,
    mode: str,
    run_root: Path,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = dict(metadata or {})
    normalized.setdefault("mode", mode)
    normalized.setdefault("eval_kind", "validation" if mode == "validation" else "standard")
    normalized.setdefault("skill", skill)
    normalized.setdefault("run_id", run_root.name)
    normalized.setdefault("agent_model", "-")
    normalized.setdefault("judge_model", "-")
    normalized.setdefault("rubric_enabled", "-")
    normalized.setdefault("runtime_enabled", "-")
    normalized.setdefault("workers", "-")
    normalized.setdefault("config_path", "-")
    return normalized


def render_environment_table(metadata: dict[str, Any], mode_label: str) -> list[str]:
    rows = [
        (mode_label, "mode"),
        ("Eval kind", "eval_kind"),
        ("Skill", "skill"),
        ("Run ID", "run_id"),
    ]
    if not metadata_has_eval_kind(metadata, "validation"):
        rows.append(("Agent model", "agent_model"))
    if metadata_has_eval_kind(metadata, "rubric") or truthy_metadata(metadata.get("rubric_enabled")):
        rows.extend(
            [
                ("Judge model", "judge_model"),
                ("Rubric enabled", "rubric_enabled"),
            ]
        )
    if metadata_has_eval_kind(metadata, "runtime") or truthy_metadata(metadata.get("runtime_enabled")):
        rows.append(("Runtime enabled", "runtime_enabled"))
    rows.extend(
        [
            ("Workers", "workers"),
            ("Config", "config_path"),
        ]
    )

    lines = [
        "",
        "## Environment",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    for label, key in rows:
        lines.append(f"| {label} | {markdown_cell(metadata.get(key))} |")
    return lines


def metadata_has_eval_kind(metadata: dict[str, Any], expected: str) -> bool:
    return expected in eval_kind_values(metadata)


def eval_kind_values(metadata: dict[str, Any]) -> list[str]:
    return [value.lower() for value in str(metadata.get("eval_kind") or "").replace(",", " ").split()]


def truthy_metadata(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def report_key(benchmark: dict[str, Any]) -> str:
    metadata = benchmark.get("metadata", {})
    value = str(metadata.get("eval_kind") or "").strip().lower()
    if value and "," not in value:
        return safe_name(value)
    mode = str(metadata.get("mode") or "validation").strip().lower()
    if mode == "with_skill":
        return "skill"
    if mode == "with_baseline":
        return "baseline"
    return safe_name(mode or "validation")


def grouped_case_results(results: list[CaseResult]) -> dict[str, list[CaseResult]]:
    grouped: dict[str, list[CaseResult]] = {}
    for result in sorted(results, key=lambda item: (item.language, item.service, item.base_id, item.prompt_id)):
        grouped.setdefault(result.base_id, []).append(result)
    return grouped


def grouped_validation_results(results: list[ValidationResult]) -> dict[str, list[ValidationResult]]:
    grouped: dict[str, list[ValidationResult]] = {}
    for result in sorted(results, key=lambda item: (item.language, item.service, item.base_id, item.prompt_id)):
        grouped.setdefault(result.base_id, []).append(result)
    return grouped


def side_for_key(result: CaseResult, side_key: str) -> SideResult | None:
    return getattr(result, SIDE_ATTRS[side_key])


def load_rubric_grade(side: SideResult) -> dict[str, Any] | None:
    if not side.rubric_grade_path:
        return None
    path = Path(side.rubric_grade_path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    checks = data.get("checks") or []
    passed = sum(1 for check in checks if bool(check.get("pass")))
    normalized = {
        "overall_pass": data.get("overall_pass"),
        "score": data.get("score"),
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "path": side.rubric_grade_path,
    }
    return normalized


def format_sanity(side: dict[str, Any] | None) -> str:
    if side is None:
        return "-"
    sanity = side["sanity"]
    return format_count(int(sanity["passed"]), int(sanity["total"]))


def format_category(side: dict[str, Any] | None, category: str) -> str:
    if side is None:
        return "-"
    if category == "rubric":
        return format_rubric(side)
    data = side.get(category)
    if not data:
        return "-"
    total = int(data["total"])
    passed = int(data["passed"])
    skipped = int(data.get("skipped") or 0)
    if total == 0 and skipped == 0:
        return "-"
    if total == 0 and skipped:
        return f"{skipped} skipped"
    value = format_count(passed, total)
    if skipped:
        return f"{value}, {skipped} skipped"
    return value


def format_rubric(side: dict[str, Any] | None) -> str:
    if side is None or side.get("rubric") is None:
        return "-"
    rubric = side["rubric"]
    value = format_count(int(rubric["passed"]), int(rubric["total"]))
    score = rubric.get("average_score")
    if score is None:
        return value
    return f"{value}, avg score {score:.0f}"


def format_tokens(side: dict[str, Any] | None) -> str:
    if side is None:
        return "-"
    tokens = int(side.get("tokens") or 0)
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def format_duration(side: dict[str, Any] | None) -> str:
    if side is None:
        return "-"
    seconds = float(side.get("duration_seconds") or 0.0)
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.1f}s"


def format_count(passed: int, total: int) -> str:
    if total == 0:
        return "100% (0/0)"
    return f"{passed / total:.0%} ({passed}/{total})"


def average(values: list[int]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def eval_kind(base_id: str) -> str:
    parts = [part for part in base_id.split("/") if part]
    if len(parts) >= 4:
        return safe_name("-".join(parts[2:]))
    return safe_name(parts[-1] if parts else "eval")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)


def truncate(value: str, limit: int) -> str:
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def markdown_cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def relative_to_repo(repo_root: Path, path: str | Path) -> str:
    absolute = Path(path)
    try:
        return str(absolute.relative_to(repo_root))
    except ValueError:
        return str(absolute)
