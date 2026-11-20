"""Explicit pilot ownership; Promptfoo does not infer skill dependencies."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

PARTICIPANTS = {"otel-audit"}
CONSUMERS = "skills/references/consumers.json"
FIXTURE = "evals/python/flask-basic/"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args]).decode()


def at(root: Path, revision: str, path: str) -> dict | None:
    # Missing paths are normal for additions/deletions. Other Git errors are fatal.
    if path not in git(root, "ls-tree", "--name-only", revision, "--", path).splitlines():
        return None
    return json.loads(git(root, "show", f"{revision}:{path}"))


def changed_paths(raw: str) -> list[str]:
    fields = iter(raw.rstrip("\0").split("\0")) if raw else iter(())
    paths = []
    for status in fields:
        if status[0] not in "ACDMRTUXB":
            raise ValueError(f"unknown diff status: {status!r}")
        paths.append(next(fields))
        if status[0] in "RC":
            paths.append(next(fields))
    return paths


def owners(path: str, maps: list[dict], definitions: list[dict | None]) -> set[str]:
    if path.startswith("skills/references/"):
        key = path.removeprefix("skills/references/")
        declared = set().union(*(set(mapping.get(key, [])) for mapping in maps))
        return declared or PARTICIPANTS  # New/unmapped shared dependency: fail closed.
    for prefix in ("skills/", ".agents/skills/"):
        if path.startswith(prefix):
            return {path.removeprefix(prefix).split("/")[0]}
    if path.startswith("evals/") and "/eval/" in path and path.endswith(".json"):
        return {item["skill"] for item in definitions if item and "skill" in item} or PARTICIPANTS
    if path.startswith(FIXTURE):
        return PARTICIPANTS
    if path.startswith(("evals/promptfoo/", "pytest-codex-evals/")) or path in {
        "AGENTS.md", "CONTRIBUTING.md", "skills/AGENTS.md", "evals/AGENTS.md",
        "evals/Makefile", "evals/pyproject.toml", "evals/uv.lock",
        "evals/evaluator-semantics.toml", "evals/codex-eval-home.config.toml",
        ".github/workflows/ci.yml",
    } or (path.startswith("evals/codex-evals") and path.endswith(".toml")):
        return PARTICIPANTS
    return set()


def select(root: Path, base: str, head: str) -> dict:
    merge_base = git(root, "merge-base", base, head).strip()
    maps = [at(root, ref, CONSUMERS) or {} for ref in (merge_base, head)]
    raw = git(root, "diff", "--name-status", "-z", "--find-renames", merge_base, head, "--")
    reasons = {}
    for path in changed_paths(raw):
        definitions = [at(root, ref, path) for ref in (merge_base, head)] if (
            path.startswith("evals/") and "/eval/" in path and path.endswith(".json")
        ) else []
        affected = owners(path, maps, definitions)
        if path == CONSUMERS:
            affected = PARTICIPANTS
        if affected:
            reasons[path] = sorted(affected)
    affected = set().union(*(set(value) for value in reasons.values()))
    return {
        "merge_base": merge_base, "head": git(root, "rev-parse", head).strip(),
        "selected": sorted(affected & PARTICIPANTS),
        "outside_pilot": sorted(affected - PARTICIPANTS), "reasons": reasons,
        "state": "selected" if affected & PARTICIPANTS else "skipped: not affected",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    print(json.dumps(select(Path(__file__).resolve().parents[2], args.base, args.head), indent=2))
