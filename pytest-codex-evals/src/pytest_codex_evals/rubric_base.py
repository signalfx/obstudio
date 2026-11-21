"""Shared rubric composition, also usable by the stdlib-only policy checker."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path


COMMON_FIELDS = {"rubric", "judge_inputs", "strict_rubric_output", "rubric_dimensions"}


def rubric_source_reference(path: Path, data: object, field: str) -> Path | None:
    if not isinstance(data, dict) or field not in data:
        return None
    path = path.absolute()
    if path.parent.name not in {"qual", "rubric"} or path.parent.parent.name != "eval":
        raise ValueError(f"{field} requires a nested rubric eval definition")
    reference = data[field]
    if (not isinstance(reference, str) or not reference.strip()
            or "\\" in reference or Path(reference).is_absolute()):
        raise ValueError(f"{field} must be a relative JSON file within the eval root")
    source = Path(os.path.normpath(path.parent / reference))
    fixture = path.parents[2]
    if not source.is_relative_to(fixture.parent.parent):
        raise ValueError(f"{field} must stay within the eval root")
    if source.is_relative_to(fixture):
        raise ValueError(f"{field} must not be staged in the actor fixture workspace")
    if source.suffix != ".json":
        raise ValueError(f"{field} must reference a JSON file")
    return source


def rubric_base_reference(path: Path, data: object) -> Path | None:
    return rubric_source_reference(path, data, "rubric_base")


def validate_rubric_source(source: Path, eval_root: Path) -> None:
    parents = (parent for parent in (source, *source.parents) if parent.is_relative_to(eval_root))
    if any(parent.is_symlink() for parent in parents):
        raise ValueError("rubric source must not be a symlink")
    if not source.is_file():
        raise ValueError(f"rubric source must be a regular file: {source}")


def read_rubric_source(source: Path, eval_root: Path) -> str:
    validate_rubric_source(source, eval_root)
    return source.read_text(encoding="utf-8")


def validate_rubric_dimensions(rubric: list[str], dimensions: list[dict], strict: bool) -> None:
    if not dimensions:
        return
    if not strict:
        raise ValueError("rubric_dimensions requires strict_rubric_output")
    names = []
    assigned = []
    for dimension in dimensions:
        if (not isinstance(dimension, dict) or set(dimension) != {"id", "criteria"}
                or not isinstance(dimension["id"], str)
                or re.fullmatch(r"[a-z0-9][a-z0-9-]*", dimension["id"]) is None
                or not isinstance(dimension["criteria"], list) or not dimension["criteria"]
                or any(not isinstance(item, str) or re.fullmatch(r"rubric-[1-9][0-9]*", item) is None
                       for item in dimension["criteria"])):
            raise ValueError("invalid rubric_dimensions entry")
        names.append(dimension["id"])
        assigned.extend(dimension["criteria"])
    if len(names) != len(set(names)):
        raise ValueError("rubric_dimensions must have unique dimension ids")
    expected = {f"rubric-{index}" for index in range(1, len(rubric) + 1)}
    if len(assigned) != len(expected) or set(assigned) != expected:
        raise ValueError("rubric_dimensions must assign each rubric criterion exactly once")


def resolve_rubric_base(
    path: Path, data: dict, *,
    read_source: Callable[[Path, Path], str] = read_rubric_source,
) -> dict:
    path = path.absolute()
    source = rubric_base_reference(path, data)
    if source is None:
        if isinstance(data, dict) and "rubric_additions_source" in data:
            raise ValueError("rubric_additions_source requires rubric_base")
        return data
    if any(key in data for key in COMMON_FIELDS | {"judge_prompt"}):
        raise ValueError("rubric_base cannot be combined with overridden common fields")
    base = json.loads(read_source(source, path.parents[2].parent.parent))
    required = {"rubric", "judge_inputs", "strict_rubric_output"}
    if (not isinstance(base, dict) or not required.issubset(base)
            or set(base) - COMMON_FIELDS
            or not isinstance(base["rubric"], list) or not base["rubric"]
            or any(not isinstance(item, str) or not item for item in base["rubric"])
            or not isinstance(base["judge_inputs"], list)
            or any(not isinstance(item, str) or not item for item in base["judge_inputs"])
            or not isinstance(base["strict_rubric_output"], bool)):
        raise ValueError(f"invalid rubric base {source}")
    if "rubric_dimensions" in base:
        if not isinstance(base["rubric_dimensions"], list) or not base["rubric_dimensions"]:
            raise ValueError("rubric_dimensions must be a nonempty list")
        validate_rubric_dimensions(base["rubric"], base["rubric_dimensions"], base["strict_rubric_output"])
    additions = data.get("rubric_additions", {})
    if not isinstance(additions, dict):
        raise ValueError("rubric_additions must be an object")
    additions_source = rubric_source_reference(path, data, "rubric_additions_source")
    if additions_source is not None:
        shared = json.loads(read_source(additions_source, path.parents[2].parent.parent))
        if (not isinstance(shared, dict) or set(shared) != {"rubric_additions"}
                or not isinstance(shared["rubric_additions"], dict)):
            raise ValueError("invalid shared rubric_additions source")
        shared_additions = shared["rubric_additions"]
        if shared_additions.keys() & additions.keys():
            raise ValueError("shared and inline rubric_additions must use different criterion IDs")
        additions = {**shared_additions, **additions}
    rubric = list(base["rubric"])
    for label, addition in additions.items():
        if (not isinstance(label, str) or re.fullmatch(r"rubric-[1-9][0-9]*", label) is None
                or not isinstance(addition, str) or not addition):
            raise ValueError("invalid rubric_additions entry")
        index = int(label.removeprefix("rubric-")) - 1
        if index >= len(rubric):
            raise ValueError(f"rubric_additions references unknown criterion: {label}")
        rubric[index] += "\n\n" + addition
    resolved = {**base, **data, "rubric": rubric}
    resolved.pop("rubric_base")
    resolved.pop("rubric_additions", None)
    resolved.pop("rubric_additions_source", None)
    return resolved
