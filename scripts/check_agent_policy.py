#!/usr/bin/env python3
"""Validate deterministic repository policy contracts for coding agents."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


REQUIRED_HEADINGS = (
    "Coding Agent Definition of Done",
    "Reviewer Routing",
    "Code Review Rules",
    "Confluence Document Updates",
)
REQUIRED_RULE_IDS = (
    "OBS-SCOPE",
    "OBS-TEST",
    "OBS-SKILL",
    "OBS-PRESERVE",
    "OBS-UI",
    "OBS-PLUGIN",
    "OBS-INTEGRATION",
)
ROUTED_AGENT_GUIDES = (
    "observer/AGENTS.md",
    "observer/client/AGENTS.md",
    "extension/AGENTS.md",
    "skills/AGENTS.md",
    "evals/AGENTS.md",
    "pytest-codex-evals/AGENTS.md",
)
RUBRIC_DIRECTORY_NAMES = {"qual", "rubric"}
EVAL_DEFINITION_DIRECTORY_NAMES = RUBRIC_DIRECTORY_NAMES | {"runtime", "sanity"}
SHARED_CONSUMER_MAP = Path("skills/references/consumers.json")

MAKE_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*[?+:!]?=")
MAKE_TARGET_RE = re.compile(r"^([^\s:#=][^:#=]*):(?!=)")
SKILL_TABLE_ROW_RE = re.compile(r"^\|\s*`\$([^`]+)`\s*\|", re.MULTILINE)


def _read(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{path}: cannot read file: {exc}")
        return ""


def _section(markdown: str, title: str) -> str | None:
    match = re.search(rf"^##\s+{re.escape(title)}\s*$", markdown, re.MULTILINE)
    if not match:
        return None
    end = re.search(r"^##\s+", markdown[match.end() :], re.MULTILINE)
    if end:
        return markdown[match.end() : match.end() + end.start()]
    return markdown[match.end() :]


def _canonical_skills(root: Path, errors: list[str]) -> set[str]:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        errors.append("skills/: canonical skill directory is missing")
        return set()

    names: set[str] = set()
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        name = skill_file.parent.name
        names.add(name)
        text = _read(skill_file, errors)
        frontmatter_name = re.search(r"^name:\s*([^\s]+)\s*$", text, re.MULTILINE)
        if not frontmatter_name:
            errors.append(f"{skill_file.relative_to(root)}: missing frontmatter name")
        elif frontmatter_name.group(1) != name:
            errors.append(
                f"{skill_file.relative_to(root)}: frontmatter name "
                f"{frontmatter_name.group(1)!r} must match directory {name!r}"
            )
    if not names:
        errors.append("skills/: no canonical */SKILL.md files found")
    return names


def _check_skill_discovery(root: Path, canonical: set[str], errors: list[str]) -> None:
    discovery_dir = root / ".agents" / "skills"
    if not discovery_dir.is_dir():
        errors.append(".agents/skills/: discovery directory is missing")
        return

    discovered = {entry.name for entry in discovery_dir.iterdir()}
    missing = canonical - discovered
    extra = discovered - canonical
    if missing:
        errors.append(
            ".agents/skills/: missing canonical skill links: " + ", ".join(sorted(missing))
        )
    if extra:
        errors.append(
            ".agents/skills/: entries without canonical skills: " + ", ".join(sorted(extra))
        )

    for name in sorted(canonical & discovered):
        link = discovery_dir / name
        if not link.is_symlink():
            errors.append(f"{link.relative_to(root)}: must be a symbolic link")
            continue
        raw_target = os.readlink(link)
        if Path(raw_target).is_absolute():
            errors.append(f"{link.relative_to(root)}: link target must be relative")
            continue
        expected_target = Path("..") / ".." / "skills" / name
        if Path(raw_target) != expected_target:
            errors.append(
                f"{link.relative_to(root)}: link target must be {expected_target}, "
                f"found {raw_target}"
            )
        try:
            resolved = link.resolve(strict=True)
        except OSError as exc:
            errors.append(f"{link.relative_to(root)}: broken skill link: {exc}")
            continue
        expected = (root / "skills" / name).resolve(strict=True)
        if resolved != expected:
            errors.append(
                f"{link.relative_to(root)}: resolves to {resolved}, expected {expected}"
            )


def _check_instruction_structure(
    root: Path, agents_text: str, canonical: set[str], errors: list[str]
) -> None:
    for heading in REQUIRED_HEADINGS:
        if _section(agents_text, heading) is None:
            errors.append(f"AGENTS.md: missing required '## {heading}' section")

    for reference in ("CONTRIBUTING.md", "skills/", ".agents/skills/"):
        if reference not in agents_text:
            errors.append(f"AGENTS.md: missing required reference to {reference}")

    routing = _section(agents_text, "Reviewer Routing") or ""
    for guide in ROUTED_AGENT_GUIDES:
        if guide not in routing:
            errors.append(f"AGENTS.md Reviewer Routing: missing {guide}")
        if not (root / guide).is_file():
            errors.append(f"{guide}: routed instruction file is missing")

    review_rules = _section(agents_text, "Code Review Rules") or ""
    for rule_id in REQUIRED_RULE_IDS:
        if rule_id not in review_rules:
            errors.append(f"AGENTS.md Code Review Rules: missing {rule_id}")

    available = _section(agents_text, "Available Skills")
    if available is None:
        errors.append("AGENTS.md: missing required '## Available Skills' section")
    else:
        table_names = set(SKILL_TABLE_ROW_RE.findall(available))
        missing = canonical - table_names
        extra = table_names - canonical
        if missing:
            errors.append(
                "AGENTS.md Available Skills: missing canonical skills: "
                + ", ".join(sorted(missing))
            )
        if extra:
            errors.append(
                "AGENTS.md Available Skills: unknown skills: " + ", ".join(sorted(extra))
            )

    adapter_path = root / ".github" / "copilot-instructions.md"
    adapter = _read(adapter_path, errors)
    if adapter:
        if "/AGENTS.md" not in adapter and "`AGENTS.md`" not in adapter:
            errors.append(
                ".github/copilot-instructions.md: must route to the canonical root AGENTS.md"
            )
        for heading in ("Reviewer Routing", "Code Review Rules"):
            if heading not in adapter:
                errors.append(
                    f".github/copilot-instructions.md: missing routing reference to {heading}"
                )


def _check_pr_template(root: Path, errors: list[str]) -> None:
    path = root / ".github" / "PULL_REQUEST_TEMPLATE.md"
    template = _read(path, errors)
    for heading in ("Summary", "Scope", "Validation evidence", "Risk and review"):
        if re.search(rf"^##\s+{re.escape(heading)}\s*$", template, re.MULTILINE) is None:
            errors.append(f".github/PULL_REQUEST_TEMPLATE.md: missing '## {heading}'")
    for evidence in (
        "Exact commands and results",
        "Skill eval file(s)",
        "Local rubric command and result",
        "UI interaction/accessibility",
        "Plugin/integration compatibility",
        "Checks skipped",
        "Residual risks",
    ):
        if evidence.casefold() not in template.casefold():
            errors.append(
                f".github/PULL_REQUEST_TEMPLATE.md: missing evidence field {evidence!r}"
            )


def _check_cross_document_claims(
    agents_text: str, contributing_text: str, errors: list[str]
) -> None:
    coverage_pointer = re.search(
        r"(?:see|follow)\s+`?AGENTS\.md`?[^.\n]*coverage",
        contributing_text,
        re.IGNORECASE,
    )
    if coverage_pointer and "coverage" not in agents_text.lower():
        errors.append(
            "CONTRIBUTING.md: coverage guidance points to AGENTS.md, but AGENTS.md "
            "contains no coverage guidance"
        )


def _default_base_ref(root: Path) -> str | None:
    candidates: list[str] = []
    try:
        symbolic = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if symbolic.returncode == 0 and symbolic.stdout.strip():
        candidates.append(symbolic.stdout.strip())
    candidates.extend(("origin/main", "origin/master", "main", "master"))
    for candidate in candidates:
        resolved = subprocess.run(
            ["git", "rev-parse", "--verify", f"{candidate}^{{commit}}"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if resolved.returncode == 0:
            return candidate
    return None


def _repo_path(raw_path: str, errors: list[str]) -> Path | None:
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        errors.append(f"git diff path escapes repository: {raw_path!r}")
        return None
    return path


def _git_changed_files(
    root: Path, base_ref: str, errors: list[str]
) -> tuple[list[tuple[str, Path]], str | None]:
    if base_ref.startswith("-") or re.fullmatch(r"[A-Za-z0-9._/@{}^~:+-]+", base_ref) is None:
        errors.append(f"invalid agent-policy base ref: {base_ref!r}")
        return [], None

    try:
        merge_base = subprocess.run(
            ["git", "merge-base", base_ref, "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"cannot resolve agent-policy base {base_ref!r}: {exc}")
        return [], None
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        detail = merge_base.stderr.strip() or merge_base.stdout.strip() or "git merge-base failed"
        errors.append(f"cannot resolve agent-policy base {base_ref!r}: {detail}")
        return [], None
    base_tree = merge_base.stdout.strip()

    try:
        completed = subprocess.run(
            ["git", "diff", "--name-status", "-z", "--find-renames", base_tree, "--"],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "-z", "--others", "--exclude-standard", "--"],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"cannot inspect changed files from {base_ref!r}: {exc}")
        return [], base_tree
    if completed.returncode != 0:
        detail = (
            completed.stderr.decode("utf-8", "replace").strip()
            or completed.stdout.decode("utf-8", "replace").strip()
            or "git diff failed"
        )
        errors.append(f"cannot inspect changed files from {base_ref!r}: {detail}")
        return [], base_tree
    if untracked.returncode != 0:
        detail = (
            untracked.stderr.decode("utf-8", "replace").strip()
            or untracked.stdout.decode("utf-8", "replace").strip()
            or "git ls-files failed"
        )
        errors.append(f"cannot inspect untracked files: {detail}")
        return [], base_tree

    changes: list[tuple[str, Path]] = []
    seen: set[tuple[str, Path]] = set()

    def add(status: str, raw_path: str) -> None:
        path = _repo_path(raw_path, errors)
        item = (status, path) if path is not None else None
        if item is not None and item not in seen:
            seen.add(item)
            changes.append(item)

    def nul_fields(output: bytes, source: str) -> list[bytes]:
        if not output:
            return []
        if not output.endswith(b"\0"):
            errors.append(f"cannot parse {source}: missing NUL terminator")
            return []
        return output[:-1].split(b"\0")

    diff_fields = nul_fields(completed.stdout, "git diff output")
    index = 0
    while index < len(diff_fields):
        status = os.fsdecode(diff_fields[index])
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count > len(diff_fields):
            errors.append(f"cannot parse git diff entry for status {status!r}")
            break
        paths = [os.fsdecode(value) for value in diff_fields[index : index + path_count]]
        index += path_count
        if status.startswith("R"):
            add("D", paths[0])
            add("A", paths[1])
        elif status.startswith("C"):
            add("A", paths[1])
        else:
            add(status, paths[0])

    for raw_path in nul_fields(untracked.stdout, "git ls-files output"):
        add("A", os.fsdecode(raw_path))
    return changes, base_tree


def _git_file_text(root: Path, tree: str, path: Path) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{tree}:{path.as_posix()}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout if completed.returncode == 0 else None


def _parse_shared_consumer_map(
    text: str,
    source: str,
    errors: list[str],
    canonical: set[str] | None = None,
) -> dict[str, set[str]]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{source}: invalid JSON: {exc}")
        return {}
    if not isinstance(raw, dict):
        errors.append(f"{source}: expected an object mapping shared files to skills")
        return {}

    mapping: dict[str, set[str]] = {}
    for reference, consumers in raw.items():
        if not isinstance(reference, str) or not reference or Path(reference).is_absolute():
            errors.append(f"{source}: invalid shared reference key {reference!r}")
            continue
        if ".." in Path(reference).parts:
            errors.append(f"{source}: shared reference key escapes its directory: {reference!r}")
            continue
        if not isinstance(consumers, list) or not consumers:
            errors.append(f"{source}: {reference!r} must name at least one consuming skill")
            continue
        if not all(isinstance(item, str) and item for item in consumers):
            errors.append(f"{source}: {reference!r} has an invalid consumer list")
            continue
        consumer_set = set(consumers)
        if len(consumer_set) != len(consumers):
            errors.append(f"{source}: {reference!r} repeats a consuming skill")
        if canonical is not None:
            unknown = consumer_set - canonical
            if unknown:
                errors.append(
                    f"{source}: {reference!r} names unknown skills: "
                    + ", ".join(sorted(unknown))
                )
        mapping[reference] = consumer_set
    return mapping


def _load_shared_consumers(
    root: Path, errors: list[str], canonical: set[str] | None = None
) -> dict[str, set[str]]:
    return _parse_shared_consumer_map(
        _read(root / SHARED_CONSUMER_MAP, errors),
        SHARED_CONSUMER_MAP.as_posix(),
        errors,
        canonical,
    )


def _shared_consumers_at_ref(
    root: Path, tree: str | None, errors: list[str]
) -> dict[str, set[str]]:
    if tree is None:
        return {}
    text = _git_file_text(root, tree, SHARED_CONSUMER_MAP)
    if text is None:
        return {}
    return _parse_shared_consumer_map(
        text,
        f"{SHARED_CONSUMER_MAP.as_posix()} at {tree}",
        errors,
    )


def _check_shared_reference_consumers(
    root: Path, canonical: set[str], errors: list[str]
) -> dict[str, set[str]]:
    mapping = _load_shared_consumers(root, errors, canonical)
    shared_root = root / "skills" / "references"
    shared_paths: dict[str, Path] = {}
    for path in shared_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(shared_root)
        if (
            relative.as_posix() == "consumers.json"
            or "tests" in relative.parts
            or "__pycache__" in relative.parts
        ):
            continue
        shared_paths[relative.as_posix()] = path
    expected = set(shared_paths)
    missing = expected - set(mapping)
    extra = set(mapping) - expected
    if missing:
        errors.append(
            f"{SHARED_CONSUMER_MAP}: missing shared references: "
            + ", ".join(sorted(missing))
        )
    if extra:
        errors.append(
            f"{SHARED_CONSUMER_MAP}: unknown shared references: "
            + ", ".join(sorted(extra))
        )

    references_by_name: dict[str, list[str]] = {}
    for reference in expected:
        references_by_name.setdefault(Path(reference).name, []).append(reference)
    unique_references_by_name: dict[str, str] = {}
    for name, references in sorted(references_by_name.items()):
        if len(references) > 1:
            errors.append(
                f"{SHARED_CONSUMER_MAP}: shared filename {name!r} is ambiguous across: "
                + ", ".join(sorted(references))
            )
        else:
            unique_references_by_name[name] = references[0]

    direct_consumers = {reference: set() for reference in expected}
    for consumer in sorted(canonical):
        consumer_root = root / "skills" / consumer
        for path in consumer_root.rglob("*"):
            relative = path.relative_to(consumer_root)
            if (
                not path.is_file()
                or "tests" in relative.parts
                or "__pycache__" in relative.parts
            ):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for marker, reference in unique_references_by_name.items():
                if marker in content:
                    direct_consumers[reference].add(consumer)

    dependencies = {reference: set() for reference in expected}
    for source, path in shared_paths.items():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for marker, target in unique_references_by_name.items():
            if target != source and marker in content:
                dependencies[source].add(target)

    effective_consumers = {
        reference: set(consumers) for reference, consumers in direct_consumers.items()
    }
    changed = True
    while changed:
        changed = False
        for source, targets in dependencies.items():
            for target in targets:
                added = effective_consumers[source] - effective_consumers[target]
                if added:
                    effective_consumers[target].update(added)
                    changed = True

    for reference, consumers in mapping.items():
        discovered = effective_consumers.get(reference, set())
        omitted = discovered - consumers
        stale = consumers - discovered
        if omitted:
            errors.append(
                f"{SHARED_CONSUMER_MAP}: {reference!r} omits consuming skills: "
                + ", ".join(sorted(omitted))
            )
        if stale:
            errors.append(
                f"{SHARED_CONSUMER_MAP}: {reference!r} names skills that do not reference it: "
                + ", ".join(sorted(stale))
            )
    return mapping


def _eval_definition_case(
    path: Path, directory_names: set[str]
) -> str | None:
    parts = path.parts
    if (
        len(parts) != 6
        or path.suffix != ".json"
        or parts[0] != "evals"
        or parts[3] != "eval"
        or parts[4] not in directory_names
    ):
        return None
    return f"{parts[1]}/{parts[2]}"


def _json_equivalent(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if not isinstance(right, dict):
            return False
        return left.keys() == right.keys() and all(
            _json_equivalent(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        if not isinstance(right, list):
            return False
        return len(left) == len(right) and all(
            _json_equivalent(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return left == right


def _json_sort_key(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _effective_rubric_definition(
    definition: object, path: Path, path_case: str
) -> tuple[object, str]:
    if not isinstance(definition, dict):
        return definition, path_case

    normalized = dict(definition)
    normalized.pop("id", None)
    normalized["language"] = path.parts[1]
    normalized["service"] = path.parts[2]
    normalized.setdefault("judge_prompt", None)
    if not normalized.get("judge_inputs"):
        normalized["judge_inputs"] = []

    prompts = normalized.get("prompts")
    if isinstance(prompts, list):
        normalized_prompts: list[object] = []
        for prompt in prompts:
            if not isinstance(prompt, dict):
                normalized_prompts.append(prompt)
                continue
            normalized_prompt = dict(prompt)
            normalized_prompt.pop("id", None)
            if not normalized_prompt.get("eval_inputs"):
                normalized_prompt["eval_inputs"] = []
            elif isinstance(normalized_prompt["eval_inputs"], list):
                normalized_prompt["eval_inputs"] = sorted(
                    normalized_prompt["eval_inputs"],
                    key=_json_sort_key,
                )
            normalized_prompts.append(normalized_prompt)
        normalized["prompts"] = sorted(
            normalized_prompts,
            key=_json_sort_key,
        )

    return normalized, path_case


def _git_tree_paths(
    root: Path, tree: str, prefix: Path, errors: list[str]
) -> list[Path] | None:
    try:
        completed = subprocess.run(
            [
                "git",
                "ls-tree",
                "-r",
                "-z",
                "--name-only",
                tree,
                "--",
                prefix.as_posix(),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"cannot inspect {prefix} at base tree {tree}: {exc}")
        return None
    if completed.returncode != 0:
        detail = (
            completed.stderr.decode("utf-8", "replace").strip()
            or completed.stdout.decode("utf-8", "replace").strip()
            or "git ls-tree failed"
        )
        errors.append(f"cannot inspect {prefix} at base tree {tree}: {detail}")
        return None
    if completed.stdout and not completed.stdout.endswith(b"\0"):
        errors.append(
            f"cannot inspect {prefix} at base tree {tree}: missing NUL terminator"
        )
        return None

    paths: list[Path] = []
    for raw_path in completed.stdout.rstrip(b"\0").split(b"\0"):
        if not raw_path:
            continue
        path = _repo_path(os.fsdecode(raw_path), errors)
        if path is not None:
            paths.append(path)
    return paths


def _base_rubric_definitions(
    root: Path, base_tree: str, errors: list[str]
) -> dict[str, list[object]] | None:
    paths = _git_tree_paths(root, base_tree, Path("evals"), errors)
    if paths is None:
        return None

    definitions: dict[str, list[object]] = {}
    for path in paths:
        path_case = _eval_definition_case(path, RUBRIC_DIRECTORY_NAMES)
        if path_case is None:
            continue
        text = _git_file_text(root, base_tree, path)
        if text is None:
            errors.append(f"cannot read {path} at base tree {base_tree}")
            return None
        try:
            definition = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"{path} at base tree {base_tree}: invalid JSON: {exc}")
            return None
        definition, case = _effective_rubric_definition(
            definition, path, path_case
        )
        definitions.setdefault(case, []).append(definition)
    return definitions


def _changed_rubric_evals(
    root: Path,
    changes: list[tuple[str, Path]],
    errors: list[str],
    base_tree: str | None = None,
) -> tuple[
    dict[str, list[tuple[Path, str]]],
    dict[str, list[tuple[Path, str]]],
]:
    by_skill: dict[str, list[tuple[Path, str]]] = {}
    candidates: list[tuple[Path, str, str, object]] = []
    for status, path in changes:
        path_case = _eval_definition_case(path, RUBRIC_DIRECTORY_NAMES)
        if path_case is None:
            continue
        if status.startswith("D"):
            continue
        text = _read(root / path, errors)
        try:
            definition = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: changed rubric eval is invalid JSON: {exc}")
            continue
        skill = definition.get("skill") if isinstance(definition, dict) else None
        if not isinstance(skill, str) or not skill.strip():
            errors.append(f"{path}: changed rubric eval must have a non-empty top-level skill")
            continue
        definition, case = _effective_rubric_definition(
            definition, path, path_case
        )
        candidates.append((path, case, skill, definition))

    base_definitions: dict[str, list[object]] = {}
    if candidates and base_tree is not None:
        loaded = _base_rubric_definitions(root, base_tree, errors)
        if loaded is None:
            return {}, {}
        base_definitions = loaded

    unchanged_by_skill: dict[str, list[tuple[Path, str]]] = {}
    for path, case, skill, definition in candidates:
        if base_tree is not None and any(
            _json_equivalent(definition, base_definition)
            for base_definition in base_definitions.get(case, [])
        ):
            unchanged_by_skill.setdefault(skill, []).append((path, case))
            continue
        by_skill.setdefault(skill, []).append((path, case))
    return by_skill, unchanged_by_skill


def _physical_tree_paths(root: Path, relative_root: Path) -> list[Path]:
    tree_root = root / relative_root
    if tree_root.is_file() or tree_root.is_symlink():
        return [tree_root.relative_to(root)]
    if not tree_root.exists():
        return []
    return sorted(
        path.relative_to(root)
        for path in tree_root.rglob("*")
        if path.is_file() or path.is_symlink()
    )


def _remaining_tree_paths(
    root: Path, relative_root: Path, errors: list[str]
) -> list[Path]:
    if not (root / ".git").exists():
        return _physical_tree_paths(root, relative_root)
    try:
        completed = subprocess.run(
            [
                "git",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                relative_root.as_posix(),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"cannot inspect remaining paths under {relative_root}: {exc}")
        return _physical_tree_paths(root, relative_root)
    if completed.returncode != 0:
        detail = (
            completed.stderr.decode("utf-8", "replace").strip()
            or completed.stdout.decode("utf-8", "replace").strip()
            or "git ls-files failed"
        )
        errors.append(f"cannot inspect remaining paths under {relative_root}: {detail}")
        return _physical_tree_paths(root, relative_root)
    if completed.stdout and not completed.stdout.endswith(b"\0"):
        errors.append(
            f"cannot inspect remaining paths under {relative_root}: "
            "missing NUL terminator"
        )
        return _physical_tree_paths(root, relative_root)

    paths: list[Path] = []
    for raw_path in completed.stdout.rstrip(b"\0").split(b"\0"):
        if not raw_path:
            continue
        path = _repo_path(os.fsdecode(raw_path), errors)
        if path is None:
            continue
        absolute_path = root / path
        if absolute_path.exists() or absolute_path.is_symlink():
            paths.append(path)
    return sorted(set(paths))


def _current_eval_definitions_for_skills(
    root: Path, skills: set[str], errors: list[str]
) -> dict[str, list[Path]]:
    by_skill = {skill: [] for skill in skills}
    if not skills:
        return by_skill
    for relative_path in _remaining_tree_paths(root, Path("evals"), errors):
        if (
            _eval_definition_case(relative_path, EVAL_DEFINITION_DIRECTORY_NAMES)
            is None
        ):
            continue
        text = _read(root / relative_path, errors)
        try:
            definition = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(
                f"{relative_path}: cannot validate removed skill eval cleanup: {exc}"
            )
            continue
        skill = definition.get("skill") if isinstance(definition, dict) else None
        if skill in by_skill:
            by_skill[skill].append(relative_path)
    return by_skill


def _missing_rubric_message(
    skill: str,
    unchanged_rubrics: dict[str, list[tuple[Path, str]]],
) -> str:
    unchanged = unchanged_rubrics.get(skill, [])
    if unchanged:
        paths = ", ".join(str(path) for path, _case in unchanged)
        return (
            f"skills/{skill}/: shipped skill content changed, but its matching rubric "
            f"changes are effectively equivalent to the base tree after normalizing "
            f"identity and default metadata ({paths}); semantically update a rubric eval "
            "that exercises the changed behavior and run "
            f"make eval-rubric SKILL=skills/{skill} CASE=<language>/<service>"
        )
    return (
        f"skills/{skill}/: shipped skill content changed without a changed matching "
        "rubric eval under evals/<language>/<service>/eval/qual/ (or "
        f"eval/rubric/) with skill={skill!r}; add or update one and run "
        f"make eval-rubric SKILL=skills/{skill} CASE=<language>/<service>"
    )


def _check_skill_eval_diff(
    root: Path,
    changes: list[tuple[str, Path]],
    errors: list[str],
    shared_consumers: dict[str, set[str]] | None = None,
    base_shared_consumers: dict[str, set[str]] | None = None,
    base_tree: str | None = None,
) -> None:
    changed_skills: set[str] = set()
    deleted_skill_manifests: set[str] = set()
    changed_shared_references: set[str] = set()
    for status, path in changes:
        parts = path.parts
        if len(parts) < 3 or parts[0] != "skills":
            continue
        if "tests" in parts[2:] or "__pycache__" in parts[2:]:
            continue
        if parts[1] == "references":
            reference = Path(*parts[2:]).as_posix()
            if reference != "consumers.json":
                changed_shared_references.add(reference)
            continue
        changed_skills.add(parts[1])
        if (
            status.startswith("D")
            and len(parts) == 3
            and parts[2] == "SKILL.md"
        ):
            deleted_skill_manifests.add(parts[1])

    removed_skills = {
        skill
        for skill in deleted_skill_manifests
        if not (root / "skills" / skill / "SKILL.md").is_file()
    }
    removed_eval_definitions = _current_eval_definitions_for_skills(
        root, removed_skills, errors
    )
    for skill in sorted(removed_skills):
        remaining_paths = _remaining_tree_paths(
            root, Path("skills") / skill, errors
        )
        if remaining_paths:
            errors.append(
                f"skills/{skill}/: complete skill removal leaves repository-visible "
                "canonical files: "
                + ", ".join(str(path) for path in remaining_paths)
            )
        remaining_reports = _remaining_tree_paths(
            root, Path("eval-reports") / skill, errors
        )
        if remaining_reports:
            errors.append(
                f"skills/{skill}/: complete skill removal leaves tracked latest eval "
                "reports: " + ", ".join(str(path) for path in remaining_reports)
            )
        stale_evals = removed_eval_definitions.get(skill, [])
        if stale_evals:
            errors.append(
                f"skills/{skill}/: complete skill removal leaves eval definitions naming "
                f"the removed skill: {', '.join(str(path) for path in stale_evals)}; "
                "delete them or migrate their top-level skill field"
            )

    changed_rubrics, unchanged_rubrics = _changed_rubric_evals(
        root, changes, errors, base_tree
    )
    for skill in sorted(changed_skills):
        if skill in removed_skills or skill in changed_rubrics:
            continue
        errors.append(_missing_rubric_message(skill, unchanged_rubrics))

    if shared_consumers is None:
        shared_consumers = _load_shared_consumers(root, errors)
    if base_shared_consumers is None:
        base_shared_consumers = {}
    for reference in sorted(changed_shared_references):
        consumers = set(shared_consumers.get(reference, set()))
        consumers.update(base_shared_consumers.get(reference, set()))
        if not consumers:
            errors.append(
                f"skills/references/{reference}: no affected skills are declared in "
                f"{SHARED_CONSUMER_MAP} in the current or base tree"
            )
            continue
        for skill in sorted(consumers):
            if skill in removed_skills or skill in changed_rubrics:
                continue
            unchanged = unchanged_rubrics.get(skill, [])
            if unchanged:
                paths = ", ".join(str(path) for path, _case in unchanged)
                errors.append(
                    f"skills/references/{reference}: affected skill {skill!r} has only "
                    f"effectively equivalent matching rubric changes after normalizing "
                    f"identity and default metadata ({paths}); semantically update its "
                    "eval and run "
                    f"make eval-rubric SKILL=skills/{skill} CASE=<language>/<service>"
                )
                continue
            errors.append(
                f"skills/references/{reference}: affected skill {skill!r} has no changed "
                "matching rubric eval; update its eval and run "
                f"make eval-rubric SKILL=skills/{skill} CASE=<language>/<service>"
            )


def _markdown_snippets(text: str) -> list[tuple[int, str]]:
    snippets: list[tuple[int, str]] = []
    fence: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token[0]
            elif token[0] == fence:
                fence = None
            continue
        if fence is not None:
            snippets.append((line_number, line))
            continue
        for inline in re.findall(r"`([^`\n]+)`", line):
            snippets.append((line_number, inline))
    return snippets


def _shell_segments(command: str) -> list[tuple[list[str], str | None]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        return []

    segments: list[tuple[list[str], str | None]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(char in ";&|" for char in token):
            if current:
                segments.append((current, token))
                current = []
        else:
            current.append(token)
    if current:
        segments.append((current, None))
    return segments


def _make_arguments(args: list[str]) -> tuple[Path, list[str]]:
    directory = Path(".")
    targets: list[str] = []
    options_with_values = {
        "-f",
        "--file",
        "--makefile",
        "-I",
        "--include-dir",
        "-j",
        "--jobs",
        "-l",
        "--load-average",
        "-o",
        "--old-file",
        "--assume-old",
        "-W",
        "--what-if",
        "--eval",
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("-C", "--directory"):
            if index + 1 < len(args):
                directory /= args[index + 1]
                index += 2
                continue
            break
        if arg.startswith("--directory="):
            directory /= arg.split("=", 1)[1]
        elif arg.startswith("-C") and len(arg) > 2:
            directory /= arg[2:]
        elif arg in options_with_values:
            index += 2
            continue
        elif arg.startswith("-") or MAKE_ASSIGNMENT_RE.match(arg):
            pass
        elif "$" not in arg:
            targets.append(arg)
        index += 1
    return directory, targets


def _make_references(text: str) -> list[tuple[int, Path, str]]:
    references: list[tuple[int, Path, str]] = []
    for line_number, snippet in _markdown_snippets(text):
        working_dir = Path(".")
        for segment, connector in _shell_segments(snippet):
            if segment and segment[0] == "$":
                segment = segment[1:]
            if len(segment) == 2 and segment[0] == "cd":
                working_dir /= segment[1]
                continue
            try:
                make_index = segment.index("make")
            except ValueError:
                continue
            make_dir, targets = _make_arguments(segment[make_index + 1 :])
            for target in targets:
                references.append((line_number, working_dir / make_dir, target))
            if connector not in ("&&", ";"):
                working_dir = Path(".")
    return references


def _makefile_targets(path: Path, errors: list[str]) -> set[str]:
    text = _read(path, errors)
    targets: set[str] = set()
    for line in text.splitlines():
        match = MAKE_TARGET_RE.match(line)
        if not match:
            continue
        for target in match.group(1).split():
            if not target.startswith(".") and "$" not in target and "%" not in target:
                targets.add(target)
    return targets


def _check_make_references(root: Path, documents: tuple[Path, ...], errors: list[str]) -> None:
    target_cache: dict[Path, set[str]] = {}
    for document in documents:
        text = _read(document, errors)
        for line_number, relative_dir, target in _make_references(text):
            makefile = (root / relative_dir / "Makefile").resolve()
            try:
                makefile.relative_to(root.resolve())
            except ValueError:
                errors.append(
                    f"{document.relative_to(root)}:{line_number}: make directory escapes repository"
                )
                continue
            if not makefile.is_file():
                errors.append(
                    f"{document.relative_to(root)}:{line_number}: make {target} has no "
                    f"Makefile in {relative_dir}"
                )
                continue
            targets = target_cache.setdefault(makefile, _makefile_targets(makefile, errors))
            if target not in targets:
                errors.append(
                    f"{document.relative_to(root)}:{line_number}: unknown make target "
                    f"{target!r} in {makefile.relative_to(root)}"
                )


def check_repository(root: Path, base_ref: str | None = None) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    agents_path = root / "AGENTS.md"
    contributing_path = root / "CONTRIBUTING.md"
    agents_text = _read(agents_path, errors)
    contributing_text = _read(contributing_path, errors)

    canonical = _canonical_skills(root, errors)
    _check_skill_discovery(root, canonical, errors)
    shared_consumers = _check_shared_reference_consumers(root, canonical, errors)
    _check_instruction_structure(root, agents_text, canonical, errors)
    _check_cross_document_claims(agents_text, contributing_text, errors)
    _check_pr_template(root, errors)
    if base_ref:
        changes, base_tree = _git_changed_files(root, base_ref, errors)
        if changes:
            base_shared_consumers = _shared_consumers_at_ref(root, base_tree, errors)
            _check_skill_eval_diff(
                root,
                changes,
                errors,
                shared_consumers=shared_consumers,
                base_shared_consumers=base_shared_consumers,
                base_tree=base_tree,
            )
    policy_documents = (
        agents_path,
        contributing_path,
        *(root / guide for guide in ROUTED_AGENT_GUIDES),
    )
    _check_make_references(root, policy_documents, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to this script's parent repository)",
    )
    parser.add_argument(
        "--base-ref",
        default=os.environ.get("AGENT_POLICY_BASE"),
        help=(
            "git base ref used to enforce changed skill/rubric pairing "
            "(defaults to AGENT_POLICY_BASE, then the repository default branch)"
        ),
    )
    args = parser.parse_args(argv)
    base_ref = args.base_ref
    if base_ref and re.fullmatch(r"0+", base_ref):
        base_ref = None
    if not base_ref:
        base_ref = _default_base_ref(args.root.resolve())
    if not base_ref:
        print(
            "Agent policy check failed:\n"
            "  - cannot determine a git base ref; pass --base-ref or set "
            "AGENT_POLICY_BASE",
            file=sys.stderr,
        )
        return 1
    errors = check_repository(args.root, base_ref)
    if errors:
        print("Agent policy check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Agent policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
