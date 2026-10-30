#!/usr/bin/env python3
"""Reject eval result models or reasoning effort that differ from repo defaults."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path


DEFAULT_CONFIG = "evals/codex-evals.toml"


def reasoning_effort(arguments: list[str]) -> str | None:
    effort = None
    arguments = iter(arguments)
    for argument in arguments:
        if argument in {"--config", "-c"}:
            assignment = next(arguments, "")
        elif argument.startswith("--config="):
            assignment = argument.split("=", 1)[1]
        elif argument.startswith("-c") and len(argument) > 2:
            assignment = argument[2:]
        else:
            continue
        override = tomllib.loads(assignment)
        effort = override.get("model_reasoning_effort", effort)
    return effort


def changed_report_directories(root: Path, base_ref: str) -> set[str]:
    base = subprocess.check_output(
        ["git", "merge-base", "HEAD", base_ref], cwd=root, text=True, stderr=subprocess.PIPE,
    ).strip()
    paths = subprocess.check_output(
        ["git", "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", base, "--", "eval-reports"], cwd=root,
    ).decode().split("\0")
    paths += subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "eval-reports"], cwd=root,
    ).decode().split("\0")
    return {"/".join(path.split("/")[:3]) for path in paths if len(path.split("/")) >= 4}


def check_report(root: Path, path: Path, models: dict, effort: str) -> None:
    path.resolve().relative_to(root.resolve())
    report = json.loads(path.read_text())
    metadata = report["metadata"]
    for role in ("agent", "judge"):
        actual = metadata.get(f"{role}_model")
        if role == "judge" and actual == "-" and metadata.get("rubric_enabled") is False:
            continue
        if actual != models[role]:
            raise ValueError(f"{role}_model: expected {models[role]!r}, found {actual!r}")
    config_path = metadata["config_path"]
    config = root / config_path
    config.resolve().relative_to(root.resolve())
    recorded = report["source"]["files"].get(config_path)
    if recorded != hashlib.sha256(config.read_bytes()).hexdigest():
        raise ValueError("config source hash differs; rerun the eval before checking effort")
    selected = tomllib.loads(config.read_text())
    actual_effort = reasoning_effort(selected.get("agent", {}).get("extra_args", []))
    if actual_effort != effort:
        raise ValueError(f"model_reasoning_effort: expected {effort!r}, found {actual_effort!r}")


def check_repository(root: Path, base_ref: str | None = None) -> list[str]:
    errors = []
    try:
        defaults = tomllib.loads((root / DEFAULT_CONFIG).read_text())
        models = defaults["models"]
        effort = reasoning_effort(defaults.get("agent", {}).get("extra_args", []))
        if not isinstance(effort, str) or not effort or any(
            not isinstance(models.get(role), str) or not models[role] for role in ("agent", "judge")
        ):
            raise ValueError("default config must declare agent/judge models and reasoning effort")
        changed = changed_report_directories(root, base_ref) if base_ref else None
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.CalledProcessError) as exc:
        return [str(exc)]
    for directory in sorted((root / "eval-reports").glob("*/*")):
        if not directory.is_dir() or directory.name == "validation":
            continue
        if changed is not None and directory.relative_to(root).as_posix() not in changed:
            continue
        benchmark = directory / "benchmark.json"
        if not benchmark.exists() and not (directory / "report.md").exists():
            continue
        try:
            check_report(root, benchmark, models, effort)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            errors.append(f"{benchmark.relative_to(root)}: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base-ref", help="Check only new or changed report directories")
    args = parser.parse_args()
    errors = check_repository(args.repo_root.resolve(), args.base_ref)
    if errors:
        print("Eval model/effort mismatch:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    print("Eval models and effort match repository defaults.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
