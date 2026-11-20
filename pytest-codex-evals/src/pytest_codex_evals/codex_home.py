from __future__ import annotations

import argparse
import json
import os
import tempfile
import tomllib
from pathlib import Path


def _temporary_directories() -> set[Path]:
    paths = [tempfile.gettempdir(), "/tmp"]
    paths.extend(os.environ[name] for name in ("TMPDIR", "TMP", "TEMP") if os.environ.get(name, "").strip())
    return {Path(path).expanduser().resolve() for path in paths}


def _is_within(path: Path, directory: Path) -> bool:
    if path.is_relative_to(directory):
        return True
    if not directory.exists():
        return False
    # resolve() preserves spelling on case-insensitive filesystems.
    for ancestor in (path, *path.parents):
        try:
            if ancestor.samefile(directory):
                return True
        except (FileNotFoundError, NotADirectoryError):
            continue
    return False


def resolve_eval_home(workspace: Path | None = None, *, protected: bool = False) -> Path | None:
    """Normalize the configured home; protect it when used as loading evidence."""
    value = os.environ.get("CODEX_EVAL_HOME", "").strip()
    if not value:
        return None
    home = Path(value).expanduser().resolve()
    if not home.is_dir():
        raise ValueError("CODEX_EVAL_HOME must be an existing directory; run make eval-codex-home first")
    if protected and any(_is_within(home, directory) for directory in _temporary_directories()):
        raise ValueError("CODEX_EVAL_HOME must be outside actor-writable temporary directories")
    if protected and workspace is not None:
        workspace = workspace.resolve()
        if _is_within(home, workspace) or _is_within(workspace, home):
            raise ValueError("CODEX_EVAL_HOME must be separate from the actor workspace")
    return home


def validate_native_sandbox(workspace: Path, extra_args: list[str]) -> None:
    home = resolve_eval_home(workspace, protected=True)
    if home is None:
        raise ValueError("Native skill-loading evidence requires CODEX_EVAL_HOME")
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False, exit_on_error=False)
    parser.add_argument("--add-dir", action="append", default=[])
    parser.add_argument("-c", "--config", action="append", default=[])
    parser.add_argument("-s", "--sandbox")
    parser.add_argument("-p", "--profile")
    parser.add_argument("-C", "--cd")
    parser.add_argument("--worktree", action="store_true")
    parser.add_argument("--approve-for-me", action="store_true")
    parser.add_argument("--dangerously-bypass-approvals-and-sandbox", action="store_true")
    try:
        options, unknown = parser.parse_known_args(extra_args)
    except argparse.ArgumentError as exc:
        raise ValueError(f"Invalid native Codex arguments: {exc}") from exc
    if unknown:
        raise ValueError("Native skill-loading evidence cannot verify unsupported extra Codex arguments")
    if (options.profile or options.cd or options.worktree or options.approve_for_me or options.dangerously_bypass_approvals_and_sandbox
            or options.sandbox not in {None, "workspace-write", "read-only"}):
        raise ValueError("Native skill-loading evidence requires the eval workspace and a restricted sandbox without profile overrides")
    configurations = []
    config = home / "config.toml"
    if config.exists():
        configurations.append(tomllib.loads(config.read_text(encoding="utf-8")))
    for override in options.config:
        key, separator, value = override.partition("=")
        if not separator:
            raise ValueError("Codex config overrides must use key=value")
        try:
            configurations.append(tomllib.loads(override))
        except tomllib.TOMLDecodeError:
            configurations.append(tomllib.loads(f"{key}={json.dumps(value)}"))
    roots = list(options.add_dir)
    for configuration in configurations:
        if configuration.get("approval_policy", "never") != "never":
            raise ValueError("Native skill-loading evidence requires permission escalation to stay disabled")
        if any(configuration.get(key) for key in ("profile", "permissions", "permissions_profile", "sandbox_permissions", "sandbox_policy")):
            raise ValueError("Native skill-loading evidence does not support custom permission profiles")
        mode = configuration.get("sandbox_mode", "workspace-write")
        if not isinstance(mode, str) or mode not in {"workspace-write", "read-only"}:
            raise ValueError("Native skill-loading evidence requires a restricted sandbox")
        sandbox = configuration.get("sandbox_workspace_write", {})
        if not isinstance(sandbox, dict) or not isinstance(sandbox.get("writable_roots", []), list):
            raise ValueError("Codex writable_roots must be a list of paths")
        roots.extend(sandbox.get("writable_roots", []))
    for value in roots:
        if not isinstance(value, str):
            raise ValueError("Codex writable_roots must contain paths")
        root = Path(value).expanduser()
        if not root.is_absolute():
            raise ValueError("Native skill-loading evidence requires absolute additional writable roots")
        root = root.resolve()
        if _is_within(home, root) or _is_within(root, home):
            raise ValueError("Native skill-loading evidence cannot use a Codex home exposed by additional writable roots")
