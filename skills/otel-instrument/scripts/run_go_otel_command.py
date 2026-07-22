#!/usr/bin/env python3
"""Resolve and execute allowlisted Go OTel commands without a shell."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any


RUNNER = Path(__file__).resolve()
RESOLVER = RUNNER.with_name("resolve_go_otel_versions.py")
ALLOWED_GO_SUBCOMMANDS = {"build", "list", "run", "test"}
BOOTSTRAP_FOLLOWUP_SUBCOMMANDS = {"build", "list", "run", "test"}
FORBIDDEN_EXTERNAL_TOOL_FLAGS = {"-exec", "-toolexec", "-vettool"}
FORBIDDEN_BOOTSTRAP_FLAGS = {"-mod", "-modfile", "-overlay"}
LEDGER_SCHEMA_VERSION = 1
LEDGER_KIND = "go-otel-bootstrap-accepted-plan"
OWNED_DIRECTORY = Path(".observe") / "tmp" / "go-otel-resolver"
STAGE_DIRECTORY = "bootstrap-stage"
LEDGER_NAME = "accepted-plan.json"
RETIRED_DIRECTORY_PREFIX = f".{OWNED_DIRECTORY.name}.retired."
MAX_PROJECT_FILE_BYTES = 8_000_000
MAX_BLOCKER_DETAIL = 240
PROBE_PROOF_BOUNDARY = (
    "The staged tidy proves only import-reachable dependency resolution for "
    "the fixed bootstrap imports. It does not prove application "
    "instrumentation, compilation, tests, export, or runtime telemetry."
)
FULL_PLAN_PROOF_BOUNDARY = (
    "The resolver proved a compatible file-proxy dependency closure. It does "
    "not prove application instrumentation, compilation, tests, export, or "
    "runtime telemetry."
)
PROBE_IMPORTS = (
    "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp",
    "go.opentelemetry.io/otel",
    "go.opentelemetry.io/otel/sdk/metric",
    "go.opentelemetry.io/otel/sdk/trace",
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp",
    "go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp",
)
GO_ENV_TO_SCRUB = {
    "GO111MODULE",
    "GOARCH",
    "GOBIN",
    "GOCACHE",
    "GOENV",
    "GOEXE",
    "GOEXPERIMENT",
    "GOFLAGS",
    "GOHOSTARCH",
    "GOHOSTOS",
    "GOINSECURE",
    "GOMOD",
    "GOMODCACHE",
    "GONOPROXY",
    "GONOSUMDB",
    "GOOS",
    "GOPATH",
    "GOPRIVATE",
    "GOPROXY",
    "GOROOT",
    "GOSUMDB",
    "GOTELEMETRY",
    "GOTELEMETRYDIR",
    "GOTMPDIR",
    "GOTOOLCHAIN",
    "GOTOOLDIR",
    "GOVCS",
    "GOVERSION",
    "GOWORK",
}


class CommandError(ValueError):
    pass


def path_is_link_or_reparse(path: Path) -> bool:
    try:
        status = os.lstat(path)
    except OSError:
        return False
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & reparse_mask)


def _detect_descriptor_cleanup_support() -> bool:
    required_dir_fd = {os.open, os.mkdir, os.rename, os.stat}
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and required_dir_fd.issubset(os.supports_dir_fd)
        and os.stat in os.supports_follow_symlinks
    )


_DESCRIPTOR_CLEANUP_SUPPORTED = _detect_descriptor_cleanup_support()


def descriptor_cleanup_supported() -> bool:
    return _DESCRIPTOR_CLEANUP_SUPPORTED


def descriptor_mode_supported() -> bool:
    return hasattr(os, "fchmod")


def load_resolver() -> ModuleType:
    if RESOLVER.is_symlink():
        raise CommandError(f"resolver must be a trusted regular sibling: {RESOLVER}")
    spec = importlib.util.spec_from_file_location("otel_go_resolver", RESOLVER)
    if spec is None or spec.loader is None:
        raise CommandError(f"could not load resolver: {RESOLVER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require_dict(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CommandError(f"resolver {name} must be an object")
    return value


def require_argv(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item and "\x00" not in item for item in value
    ):
        raise CommandError(f"resolver {name} must be a non-empty string list")
    return list(value)


def ensure_no_symlink_components(project: Path, target: Path, label: str) -> None:
    try:
        relative = target.relative_to(project)
    except ValueError as error:
        raise CommandError(f"{label} escapes the project") from error
    current = project
    for part in relative.parts:
        current = current / part
        if path_is_link_or_reparse(current):
            raise CommandError(
                f"{label} contains symlink component or reparse point: {current}"
            )


def validate_project(result: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    if type(result.get("schema_version")) is not int or result["schema_version"] != 1:
        raise CommandError("resolver returned an unsupported schema")
    if result.get("candidate_only") is not True:
        raise CommandError("resolver omitted the candidate-only proof boundary")
    project_info = require_dict(result.get("project"), "project")
    project_text = project_info.get("path")
    go_mod_text = project_info.get("go_mod")
    if not isinstance(project_text, str) or not isinstance(go_mod_text, str):
        raise CommandError("resolver project paths are invalid")
    project = Path(project_text)
    go_mod = Path(go_mod_text)
    if not project.is_absolute() or project.resolve() != project:
        raise CommandError("resolver project path is not canonical")
    if go_mod != project / "go.mod" or not go_mod.is_file():
        raise CommandError("resolver project go.mod is invalid")
    if go_mod.is_symlink():
        raise CommandError("project go.mod must not be a symlink")
    cache_info = require_dict(result.get("gomodcache"), "gomodcache")
    cache_text = cache_info.get("path")
    if not isinstance(cache_text, str):
        raise CommandError("resolver module cache path is invalid")
    cache = Path(cache_text)
    if not cache.is_absolute() or cache.resolve() != cache:
        raise CommandError("resolver module cache path is not canonical")
    owned = project / OWNED_DIRECTORY
    proxy = (cache / "cache" / "download").resolve()
    overlapping = (cache, proxy)
    if any(
        source == owned
        or source.is_relative_to(owned)
        or owned.is_relative_to(source)
        for source in overlapping
    ):
        raise CommandError(
            "source module cache or file proxy overlaps the runner-owned directory"
        )
    return project, cache, project_info


def validate_environment(project: Path, env: object) -> dict[str, str]:
    environment = require_dict(env, "go_commands.env")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise CommandError("resolver environment is invalid")
    local = project / OWNED_DIRECTORY
    expected_paths = {
        "GOCACHE": local / "gocache",
        "GOMODCACHE": local / "gomodcache",
        "GOPATH": local / "gopath",
        "HOME": local / "home",
    }
    for key, expected in expected_paths.items():
        if environment.get(key) != str(expected):
            raise CommandError(f"resolver {key} is outside the owned directory")
        ensure_no_symlink_components(project, expected, key)
    if environment.get("GOTOOLCHAIN") != "local":
        raise CommandError("resolver must disable toolchain downloads")
    if environment.get("GOVCS") != "*:off":
        raise CommandError("resolver must disable VCS fallback")
    if environment.get("GOSUMDB") != "off":
        raise CommandError("resolver must disable checksum database access")
    proxy = environment.get("GOPROXY", "")
    if not proxy.startswith("file://") or "," in proxy or "|" in proxy:
        raise CommandError("resolver must use one file-only Go proxy")
    return dict(environment)


def cleanup_contract(
    project: Path, commands: dict[str, Any], env: dict[str, str]
) -> dict[str, object]:
    cleanup_argv = require_argv(commands.get("cleanup_argv"), "cleanup_argv")
    if cleanup_argv != ["go", "clean", "-cache", "-modcache"]:
        raise CommandError("resolver cleanup argv is not bounded")
    owned = commands.get("owned_cache_paths")
    if owned != [env["GOCACHE"], env["GOMODCACHE"]]:
        raise CommandError("resolver owned cache paths are invalid")
    allowed = commands.get("cleanup_allowed_files")
    expected_allowed = [
        str(Path(env["GOCACHE"]) / "README"),
        str(Path(env["GOCACHE"]) / "trim.txt"),
    ]
    if allowed != expected_allowed:
        raise CommandError("resolver cleanup allowlist is invalid")
    return {
        "cleanup": cleanup_argv,
        "owned": list(owned),
        "allowed": list(allowed),
    }


def isolate_runtime_paths(
    plan: dict[str, object], runtime_root: Path
) -> dict[str, object]:
    """Move executable Go state out of the repository for this invocation."""

    environment = dict(require_dict(plan.get("env"), "runtime env"))
    environment.update(
        {
            "GOCACHE": str(runtime_root / "gocache"),
            "GOMODCACHE": str(runtime_root / "gomodcache"),
            "GOPATH": str(runtime_root / "gopath"),
            "HOME": str(runtime_root / "home"),
        }
    )
    isolated = {**plan, "env": environment, "runtime_root": runtime_root}
    if "owned" in isolated:
        isolated["owned"] = [environment["GOCACHE"], environment["GOMODCACHE"]]
        isolated["allowed"] = [
            str(Path(environment["GOCACHE"]) / "README"),
            str(Path(environment["GOCACHE"]) / "trim.txt"),
        ]
    return isolated


def validate_resolved_plan(
    result: object, resolver: ModuleType
) -> dict[str, object]:
    plan = require_dict(result, "plan")
    project, cache, _ = validate_project(plan)
    if plan.get("status") != "complete" or plan.get("complete") is not True:
        reasons = plan.get("reasons")
        raise CommandError(f"resolver did not produce a complete plan: {reasons}")
    go_get = require_dict(plan.get("go_get"), "go_get")
    commands = require_dict(plan.get("go_commands"), "go_commands")
    if go_get.get("ready") is not True or commands.get("ready") is not True:
        raise CommandError("resolver command plan is not ready")
    if go_get.get("cwd") != str(project) or commands.get("cwd") != str(project):
        raise CommandError("resolver command cwd does not match the project")
    env = validate_environment(project, commands.get("env"))
    if go_get.get("env") != env:
        raise CommandError("resolver environments differ")
    go_get_argv = require_argv(go_get.get("argv"), "go_get.argv")
    if go_get_argv[:2] != ["go", "get"]:
        raise CommandError("resolver go_get argv is invalid")
    candidate = candidate_identity(plan.get("selection"))
    modules = go_get_argv[2:]
    if modules != resolver.candidate_modules(candidate):
        raise CommandError("resolver go_get modules do not match the selection")
    contract = cleanup_contract(project, commands, env)
    return {
        "source": "complete",
        "project": project,
        "cache": cache,
        "env": env,
        "go_get": go_get_argv,
        "selection": candidate,
        "candidate": candidate,
        "modules": modules,
        **contract,
    }


def candidate_identity(candidate: object) -> dict[str, str | None]:
    item = require_dict(candidate, "bootstrap_probe.candidate")
    values: dict[str, str | None] = {}
    for key in ("module", "version", "core_version", "go_version"):
        value = item.get(key)
        if value is not None and not isinstance(value, str):
            raise CommandError(f"bootstrap candidate {key} is invalid")
        values[key] = value
    if not all(values[key] for key in ("module", "version", "core_version")):
        raise CommandError("bootstrap candidate is incomplete")
    if values["module"] != (
        "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
    ):
        raise CommandError("bootstrap candidate module is invalid")
    return values


def validate_bootstrap_plan(
    result: object, resolver: ModuleType
) -> dict[str, object]:
    plan = require_dict(result, "plan")
    project, cache, project_info = validate_project(plan)
    if plan.get("complete") is True or plan.get("status") == "complete":
        raise CommandError("bootstrap probe is not allowed when a complete plan exists")
    existing = project_info.get("existing_otel_requirements")
    if not isinstance(existing, list) or existing:
        raise CommandError(
            "bootstrap probe requires a project with no OTel requirements"
        )
    probe = require_dict(plan.get("bootstrap_probe"), "bootstrap_probe")
    if probe.get("eligible") is not True:
        raise CommandError(f"bootstrap probe is not eligible: {probe.get('reasons')}")
    candidate = candidate_identity(probe.get("candidate"))
    modules = require_argv(probe.get("modules"), "bootstrap_probe.modules")
    expected_modules = resolver.candidate_modules(candidate)
    if modules != expected_modules:
        raise CommandError("bootstrap direct bundle does not match the candidate")
    env = validate_environment(project, resolver.execution_env(project, cache))
    return {
        "source": "bootstrap",
        "project": project,
        "cache": cache,
        "env": env,
        "go_get": ["go", "get", *modules],
        "selection": candidate,
        "modules": modules,
        "candidate": candidate,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve and execute an allowlisted OTel Go dependency or validation "
            "command without shell interpolation."
        )
    )
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--gomodcache", type=Path)
    parser.add_argument(
        "--action", choices=("go-get", "cleanup", "probe-bootstrap")
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def select_argv(
    args: argparse.Namespace, plan: dict[str, object]
) -> tuple[str, list[str]]:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if args.action and command:
        raise CommandError("use either --action or a command after --, not both")
    if args.action == "go-get":
        return "go-get", list(plan["go_get"])
    if args.action == "cleanup":
        cleanup = plan.get("cleanup")
        if not isinstance(cleanup, list):
            raise CommandError("cleanup is unavailable for this plan")
        return "cleanup", list(cleanup)
    if args.action == "probe-bootstrap":
        return "probe-bootstrap", ["go", "mod", "tidy"]
    if not command or command[0] != "go" or len(command) < 2:
        raise CommandError("provide one explicit allowed Go command after --")
    if command[1] == "mod":
        if len(command) < 3 or command[2] != "tidy":
            raise CommandError("only `go mod tidy` is allowed for go mod")
    elif command[1] not in ALLOWED_GO_SUBCOMMANDS:
        raise CommandError(f"unsupported Go subcommand: {command[1]}")
    if any(not item or "\x00" in item for item in command):
        raise CommandError("command arguments must be non-empty and NUL-free")
    forbidden = [
        item
        for item in command[2:]
        if item.split("=", 1)[0] in FORBIDDEN_EXTERNAL_TOOL_FLAGS
    ]
    if forbidden:
        raise CommandError(
            "external Go tool execution flags are not allowed: "
            + ", ".join(forbidden)
        )
    return command[1], command


def command_environment(plan_env: dict[str, str]) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in GO_ENV_TO_SCRUB
    }
    environment.update(plan_env)
    return environment


def read_bounded(path: Path, label: str) -> bytes:
    if path.is_symlink():
        raise CommandError(f"{label} must not be a symlink")
    try:
        size = path.stat().st_size
    except OSError as error:
        raise CommandError(f"could not stat {label}: {error}") from error
    if size > MAX_PROJECT_FILE_BYTES:
        raise CommandError(f"{label} exceeds {MAX_PROJECT_FILE_BYTES} bytes")
    try:
        return path.read_bytes()
    except OSError as error:
        raise CommandError(f"could not read {label}: {error}") from error


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def optional_file_state(path: Path, label: str) -> dict[str, object]:
    if not path.exists() and not path.is_symlink():
        return {"present": False, "sha256": None}
    payload = read_bounded(path, label)
    return {"present": True, "sha256": digest(payload)}


def directive_state(resolver: ModuleType, go_mod: bytes) -> dict[str, object]:
    try:
        text = go_mod.decode("utf-8")
    except UnicodeError as error:
        raise CommandError(f"project go.mod is not UTF-8: {error}") from error
    module = resolver.module_directive(text)
    go_version, go_status = resolver.go_directive_details(text)
    if module is None or go_status != "valid" or go_version is None:
        raise CommandError("project module/go directives are no longer valid")
    toolchain: list[str] = []
    for raw_line in text.splitlines():
        code, _ = resolver.split_go_mod_comment(raw_line)
        stripped = code.strip()
        if stripped == "toolchain" or stripped.startswith("toolchain "):
            toolchain.append(stripped)
    return {"module": module, "go": go_version, "toolchain": toolchain}


def project_state(project: Path, resolver: ModuleType) -> dict[str, object]:
    go_mod = read_bounded(project / "go.mod", "project go.mod")
    return {
        "go_mod_sha256": digest(go_mod),
        "go_sum": optional_file_state(project / "go.sum", "project go.sum"),
        "directives": directive_state(resolver, go_mod),
    }


def snapshot_project(project: Path) -> dict[str, tuple[bool, bytes, int | None]]:
    snapshot: dict[str, tuple[bool, bytes, int | None]] = {}
    for name in ("go.mod", "go.sum"):
        path = project / name
        if not path.exists() and not path.is_symlink():
            snapshot[name] = (False, b"", None)
            continue
        payload = read_bounded(path, f"project {name}")
        snapshot[name] = (True, payload, stat.S_IMODE(path.stat().st_mode))
    return snapshot


def atomic_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise CommandError(f"temporary path already exists: {temporary}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, flags, mode)
        if descriptor_mode_supported():
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def restore_project(
    project: Path, snapshot: dict[str, tuple[bool, bytes, int | None]]
) -> None:
    failures: list[str] = []
    for name, (present, payload, mode) in snapshot.items():
        path = project / name
        try:
            if path.is_symlink():
                path.unlink()
            if present:
                atomic_write(path, payload, mode or 0o644)
            elif path.exists():
                path.unlink()
        except (CommandError, OSError) as error:
            failures.append(f"{name}:{error}")
    if failures:
        raise CommandError("project rollback failed: " + "; ".join(failures[:2]))


def exact_pins_present(
    project: Path, resolver: ModuleType, modules: list[str]
) -> bool:
    payload = read_bounded(project / "go.mod", "project go.mod")
    try:
        parsed = resolver.parse_requirements(payload.decode("utf-8"))
    except UnicodeError as error:
        raise CommandError(f"project go.mod is not UTF-8: {error}") from error
    if parsed["issues"] or parsed["has_replace"] or parsed["has_exclude"]:
        return False
    requirements: dict[str, list[str]] = {}
    for item in parsed["requirements"]:
        requirements.setdefault(item["module"], []).append(item["version"])
    for pin in modules:
        module, version = pin.rsplit("@", 1)
        if requirements.get(module) != [version]:
            return False
    return True


def verify_post_edit(
    project: Path,
    resolver: ModuleType,
    ledger: dict[str, Any],
) -> dict[str, object]:
    current = project_state(project, resolver)
    if current["directives"] != ledger["directives"]:
        raise CommandError("go/toolchain/module directives changed")
    if not exact_pins_present(project, resolver, ledger["modules"]):
        raise CommandError("exact intended OTel pins are not present")
    return current


def ledger_path(project: Path) -> Path:
    return project / OWNED_DIRECTORY / LEDGER_NAME


def write_ledger(project: Path, ledger: dict[str, Any]) -> None:
    path = ledger_path(project)
    ensure_no_symlink_components(project, path, "accepted-plan ledger")
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_no_symlink_components(project, path, "accepted-plan ledger")
    payload = (
        json.dumps(ledger, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    atomic_write(path, payload)


def create_ledger(
    plan: dict[str, object],
    resolver: ModuleType,
    state: str,
    *,
    proof_source: str = "bootstrap-probe",
) -> dict[str, Any]:
    project = plan["project"]
    if not isinstance(project, Path):
        raise CommandError("bootstrap project is invalid")
    project_details = project_state(project, resolver)
    cache = plan.get("cache")
    if not isinstance(cache, Path):
        raise CommandError("bootstrap module cache is invalid")
    proof_boundaries = {
        "bootstrap-probe": PROBE_PROOF_BOUNDARY,
        "resolver-full-closure": FULL_PLAN_PROOF_BOUNDARY,
    }
    if proof_source not in proof_boundaries:
        raise CommandError("accepted-plan proof source is invalid")
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": LEDGER_KIND,
        "state": state,
        "project": str(project),
        "gomodcache": str(cache),
        "candidate": plan["candidate"],
        "modules": plan["modules"],
        "directives": project_details["directives"],
        "go_mod_sha256": project_details["go_mod_sha256"],
        "go_sum": project_details["go_sum"],
        "proof_source": proof_source,
        "proof_boundary": proof_boundaries[proof_source],
    }


def read_ledger(project: Path) -> dict[str, Any] | None:
    path = ledger_path(project)
    ensure_no_symlink_components(project, path, "accepted-plan ledger")
    if not path.exists():
        return None
    try:
        value = json.loads(read_bounded(path, "accepted-plan ledger"))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise CommandError(f"accepted-plan ledger is invalid: {error}") from error
    ledger = require_dict(value, "accepted-plan ledger")
    if (
        ledger.get("schema_version") != LEDGER_SCHEMA_VERSION
        or ledger.get("kind") != LEDGER_KIND
    ):
        raise CommandError("accepted-plan ledger schema is invalid")
    if ledger.get("state") not in {"probed", "applied"}:
        raise CommandError("accepted-plan ledger state is invalid")
    proof_boundaries = {
        "bootstrap-probe": PROBE_PROOF_BOUNDARY,
        "resolver-full-closure": FULL_PLAN_PROOF_BOUNDARY,
    }
    proof_source = ledger.get("proof_source")
    if (
        proof_source not in proof_boundaries
        or ledger.get("proof_boundary") != proof_boundaries[proof_source]
    ):
        raise CommandError("accepted-plan proof boundary is invalid")
    return ledger


def validate_ledger(
    ledger: dict[str, Any],
    project: Path,
    cache: Path,
    resolver: ModuleType,
    *,
    state: str,
    bootstrap_plan: dict[str, object] | None = None,
) -> dict[str, object]:
    if ledger.get("state") != state:
        raise CommandError(f"accepted-plan ledger must be in {state} state")
    if ledger.get("project") != str(project) or ledger.get("gomodcache") != str(cache):
        raise CommandError("accepted-plan project or module-cache drift")
    candidate = candidate_identity(ledger.get("candidate"))
    modules = require_argv(ledger.get("modules"), "accepted-plan modules")
    if modules != resolver.candidate_modules(candidate):
        raise CommandError("accepted-plan candidate/module drift")
    if bootstrap_plan is not None:
        if (
            candidate != bootstrap_plan.get("candidate")
            or modules != bootstrap_plan.get("modules")
        ):
            raise CommandError("accepted-plan resolver candidate drift")
    current = project_state(project, resolver)
    if current["go_mod_sha256"] != ledger.get("go_mod_sha256"):
        raise CommandError("accepted-plan go.mod SHA drift")
    if current["go_sum"] != ledger.get("go_sum"):
        raise CommandError("accepted-plan go.sum drift")
    if current["directives"] != ledger.get("directives"):
        raise CommandError("accepted-plan directive drift")
    if state == "applied" and not exact_pins_present(project, resolver, modules):
        raise CommandError("accepted-plan exact OTel pins drift")
    env = validate_environment(project, resolver.execution_env(project, cache))
    return {
        "source": "ledger",
        "project": project,
        "cache": cache,
        "env": env,
        "go_get": ["go", "get", *modules],
        "selection": candidate,
        "candidate": candidate,
        "modules": modules,
        "ledger": ledger,
    }


def compact_detail(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    compact = " ".join(text.split())
    if len(compact) > MAX_BLOCKER_DETAIL:
        return compact[: MAX_BLOCKER_DETAIL - 1] + "…"
    return compact


def terminal_blocker(reason: str, **details: object) -> None:
    payload = {"action": "probe-bootstrap", "status": "blocked", "reason": reason}
    payload.update(details)
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True), file=sys.stderr)


def remove_bookkeeping(project: Path) -> tuple[int, list[str]]:
    """Deactivate the exact accepted-plan ledger by tombstoning its directory.

    Executable caches and probe staging live in a fresh external temporary
    directory. Repository contents are deliberately never traversed here:
    unexpected entries block cleanup and remain untouched. The accepted-plan
    directory is moved intact into a fresh quarantine directory, so even an
    exact-ledger substitution between validation and rename is never unlinked.
    """

    if not descriptor_cleanup_supported():
        return remove_bookkeeping_portable(project)

    root = project / OWNED_DIRECTORY
    errors: list[str] = []
    error_count = 0

    def record(path: Path, error: OSError) -> None:
        nonlocal error_count
        error_count += 1
        if len(errors) < 3:
            errors.append(f"{path.name}:{error.strerror or error}")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )

    descriptor: int | None = None
    parent_descriptor: int | None = None
    root_descriptor: int | None = None
    quarantine_descriptor: int | None = None
    ancestor_identities: list[tuple[str | None, tuple[int, int]]] = []

    def identity(open_descriptor: int) -> tuple[int, int]:
        status = os.fstat(open_descriptor)
        return status.st_dev, status.st_ino

    def canonical_ancestors_match() -> bool:
        if not ancestor_identities:
            return False
        reopened: int | None = None
        try:
            reopened = os.open(project, flags)
            if identity(reopened) != ancestor_identities[0][1]:
                return False
            for component, expected in ancestor_identities[1:]:
                if component is None:
                    return False
                next_descriptor = os.open(component, flags, dir_fd=reopened)
                os.close(reopened)
                reopened = next_descriptor
                if identity(reopened) != expected:
                    return False
            return True
        except OSError:
            return False
        finally:
            if reopened is not None:
                os.close(reopened)

    try:
        descriptor = os.open(project, flags)
        ancestor_identities.append((None, identity(descriptor)))
        current_path = project
        for index, component in enumerate(OWNED_DIRECTORY.parts):
            child_path = current_path / component
            try:
                child_descriptor = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                return 0, []
            except OSError as error:
                record(child_path, error)
                return error_count, errors
            if index == len(OWNED_DIRECTORY.parts) - 1:
                parent_descriptor = descriptor
                descriptor = None
                root_descriptor = child_descriptor
                break
            ancestor_identities.append((component, identity(child_descriptor)))
            os.close(descriptor)
            descriptor = child_descriptor
            current_path = child_path

        if parent_descriptor is None or root_descriptor is None:
            return 0, []
        root_status = os.fstat(root_descriptor)
        root_identity = (root_status.st_dev, root_status.st_ino)
        root_name = OWNED_DIRECTORY.name
        try:
            names = os.listdir(root_descriptor)
        except OSError as error:
            record(root, error)
            return error_count, errors
        unexpected = sorted(name for name in names if name != LEDGER_NAME)
        if unexpected:
            error_count += 1
            errors.append(
                f"{root.name}:unexpected entries block non-recursive cleanup: "
                + ", ".join(unexpected[:3])
            )
            return error_count, errors
        if LEDGER_NAME in names:
            try:
                ledger_status = os.stat(
                    LEDGER_NAME,
                    dir_fd=root_descriptor,
                    follow_symlinks=False,
                )
            except OSError as error:
                record(root / LEDGER_NAME, error)
                return error_count, errors
            if not stat.S_ISREG(ledger_status.st_mode):
                error_count += 1
                errors.append(
                    f"{LEDGER_NAME}:accepted-plan ledger is not a regular file"
                )
                return error_count, errors
        quarantine_name = f"{RETIRED_DIRECTORY_PREFIX}{secrets.token_hex(12)}"
        try:
            os.mkdir(quarantine_name, mode=0o700, dir_fd=parent_descriptor)
            quarantine_descriptor = os.open(
                quarantine_name, flags, dir_fd=parent_descriptor
            )
            os.rename(
                root_name,
                "retired",
                src_dir_fd=parent_descriptor,
                dst_dir_fd=quarantine_descriptor,
            )
        except OSError as error:
            record(root, error)
            return error_count, errors
        try:
            retired = os.stat(
                "retired",
                dir_fd=quarantine_descriptor,
                follow_symlinks=False,
            )
        except OSError as error:
            record(root, error)
            return error_count, errors
        if not stat.S_ISDIR(retired.st_mode) or (
            retired.st_dev,
            retired.st_ino,
        ) != root_identity:
            error_count += 1
            errors.append(f"{root.name}:directory namespace changed during cleanup")
        if not canonical_ancestors_match():
            error_count += 1
            if len(errors) < 3:
                errors.append(
                    f"{root.name}:canonical ancestor namespace changed during cleanup"
                )
    finally:
        if quarantine_descriptor is not None:
            os.close(quarantine_descriptor)
        if root_descriptor is not None:
            os.close(root_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
        if descriptor is not None:
            os.close(descriptor)
    return error_count, errors


def portable_directory_identity(path: Path) -> tuple[int, int]:
    status = os.lstat(path)
    if path_is_link_or_reparse(path) or not stat.S_ISDIR(status.st_mode):
        raise OSError(f"expected a real directory: {path}")
    return status.st_dev, status.st_ino


def remove_bookkeeping_portable(project: Path) -> tuple[int, list[str]]:
    """Tombstone exact bookkeeping without Unix directory descriptors.

    Identity and reparse checks fail closed around the atomic directory move.
    Windows cannot eliminate the narrow path check/use window without native
    directory handles, but the helper never recursively deletes repository
    content or follows a caller-controlled reparse point.
    """

    root = project / OWNED_DIRECTORY
    parent = root.parent
    try:
        ensure_no_symlink_components(project, root, "accepted-plan directory")
        if not os.path.lexists(root):
            return 0, []
        project_identity = portable_directory_identity(project)
        parent_identity = portable_directory_identity(parent)
        root_identity = portable_directory_identity(root)
        names = sorted(entry.name for entry in os.scandir(root))
        unexpected = [name for name in names if name != LEDGER_NAME]
        if unexpected:
            return 1, [
                f"{root.name}:unexpected entries block non-recursive cleanup: "
                + ", ".join(unexpected[:3])
            ]
        if LEDGER_NAME in names:
            ledger = root / LEDGER_NAME
            ledger_status = os.lstat(ledger)
            if path_is_link_or_reparse(ledger) or not stat.S_ISREG(
                ledger_status.st_mode
            ):
                return 1, [
                    f"{LEDGER_NAME}:accepted-plan ledger is not a regular file"
                ]
        quarantine = parent / (
            f"{RETIRED_DIRECTORY_PREFIX}{secrets.token_hex(12)}"
        )
        quarantine.mkdir(mode=0o700)
        quarantine_identity = portable_directory_identity(quarantine)
        if (
            portable_directory_identity(project) != project_identity
            or portable_directory_identity(parent) != parent_identity
            or portable_directory_identity(root) != root_identity
        ):
            return 1, [f"{root.name}:directory namespace changed during cleanup"]
        retired = quarantine / "retired"
        os.replace(root, retired)
        if (
            portable_directory_identity(project) != project_identity
            or portable_directory_identity(parent) != parent_identity
            or portable_directory_identity(quarantine) != quarantine_identity
            or portable_directory_identity(retired) != root_identity
        ):
            return 1, [f"{root.name}:directory namespace changed during cleanup"]
        return 0, []
    except OSError as error:
        return 1, [f"{root.name}:{error.strerror or error}"]


def retired_bookkeeping_exists(project: Path) -> bool:
    """Recognize an intentional prior tombstone without traversing it."""

    parent = project / OWNED_DIRECTORY.parent
    ensure_no_symlink_components(project, parent, "retired bookkeeping parent")
    if not parent.is_dir():
        return False
    return any(
        path.name.startswith(RETIRED_DIRECTORY_PREFIX)
        and not path_is_link_or_reparse(path)
        and path.is_dir()
        for path in parent.iterdir()
    )


def stage_probe(plan: dict[str, object], resolver: ModuleType) -> int:
    project = plan["project"]
    if not isinstance(project, Path):
        raise CommandError("bootstrap project is invalid")
    runtime_root = plan.get("runtime_root")
    if not isinstance(runtime_root, Path):
        raise CommandError("bootstrap runtime root is invalid")
    stage = runtime_root / STAGE_DIRECTORY
    try:
        stage.mkdir(exist_ok=False)
        modules = plan["modules"]
        if not isinstance(modules, list):
            raise CommandError("bootstrap modules are invalid")
        selection = plan["selection"]
        if not isinstance(selection, dict):
            raise CommandError("bootstrap candidate is invalid")
        go_version = project_state(project, resolver)["directives"]["go"]
        go_mod = "\n".join(
            [
                "module otel.bootstrap.probe",
                "",
                f"go {go_version}",
                "",
                "require (",
                *(
                    f"\t{pin.rsplit('@', 1)[0]} {pin.rsplit('@', 1)[1]}"
                    for pin in modules
                ),
                ")",
                "",
            ]
        ).encode("utf-8")
        imports = "\n".join(
            f'\t_ "{module}"' for module in PROBE_IMPORTS
        )
        source = (
            "package main\n\nimport (\n"
            + imports
            + "\n)\n\nfunc main() {}\n"
        ).encode("utf-8")
        atomic_write(stage / "go.mod", go_mod, 0o600)
        atomic_write(stage / "main.go", source, 0o600)
        completed = subprocess.run(
            ["go", "mod", "tidy"],
            cwd=stage,
            env=command_environment(plan["env"]),
            check=False,
            capture_output=True,
        )
    except (CommandError, OSError) as error:
        terminal_blocker(
            "probe-stage-or-tidy-unavailable",
            detail=str(error)[:MAX_BLOCKER_DETAIL],
        )
        return 126
    post_tidy_error: CommandError | None = None
    if completed.returncode == 0:
        try:
            staged = project_state(stage, resolver)
            expected_directives = {
                "module": "otel.bootstrap.probe",
                "go": go_version,
                "toolchain": [],
            }
            if staged["directives"] != expected_directives:
                raise CommandError("staged go/module/toolchain directives changed")
            if read_bounded(stage / "main.go", "bootstrap source") != source:
                raise CommandError("fixed bootstrap source changed")
            if not exact_pins_present(stage, resolver, modules):
                raise CommandError("staged exact intended OTel pins changed")
        except CommandError as error:
            post_tidy_error = error
    if completed.returncode != 0:
        terminal_blocker(
            "go-mod-tidy-failed",
            exit_code=completed.returncode,
            detail=compact_detail(completed.stderr or completed.stdout),
        )
        return completed.returncode if completed.returncode > 0 else 1
    if post_tidy_error is not None:
        terminal_blocker(
            "probe-post-tidy-invariant-failed",
            detail=str(post_tidy_error)[:MAX_BLOCKER_DETAIL],
        )
        return 4
    try:
        ledger = create_ledger(plan, resolver, "probed")
        write_ledger(project, ledger)
    except (CommandError, OSError) as error:
        terminal_blocker(
            "accepted-plan-ledger-write-failed",
            detail=str(error)[:MAX_BLOCKER_DETAIL],
        )
        return 3
    print(
        json.dumps(
            {
                "action": "probe-bootstrap",
                "status": "accepted",
                "state": "probed",
                "candidate": selection,
                "modules": modules,
                "ledger": str(ledger_path(project)),
                "proof_boundary": PROBE_PROOF_BOUNDARY,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def verify_cleanup(plan: dict[str, object]) -> list[str]:
    runtime_root = plan.get("runtime_root")
    if not isinstance(runtime_root, Path):
        raise CommandError("cleanup runtime root is invalid")
    allowed = {Path(path) for path in plan["allowed"]}
    unexpected: list[str] = []
    for cache_text in plan["owned"]:
        cache = Path(cache_text)
        ensure_no_symlink_components(runtime_root, cache, "owned runtime cache")
        if not cache.exists():
            continue
        allowed_directories = {
            parent
            for path in allowed
            if path.is_relative_to(cache)
            for parent in path.parents
            if parent == cache or parent.is_relative_to(cache)
        }
        for path in cache.rglob("*"):
            if path.is_symlink():
                unexpected.append(f"symlink:{path}")
            elif path.is_file() and path not in allowed:
                unexpected.append(str(path))
            elif path.is_dir() and path not in allowed_directories:
                unexpected.append(f"directory:{path}")
            elif not path.is_file() and not path.is_dir():
                unexpected.append(f"special:{path}")
    return sorted(unexpected)


def compact_notice(action: str, argv: list[str], plan: dict[str, object]) -> str:
    selection = plan.get("selection")
    selected = selection if isinstance(selection, dict) else None
    return json.dumps(
        {
            "action": action,
            "argv": argv,
            "cwd": str(plan["project"]),
            "selection": selected,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def execute(
    argv: list[str],
    plan: dict[str, object],
    env: dict[str, str] | None = None,
) -> int:
    try:
        completed = subprocess.run(
            argv,
            cwd=plan["project"],
            env=env or command_environment(plan["env"]),
            check=False,
        )
    except OSError as error:
        print(f"could not execute {argv[0]}: {error}", file=sys.stderr)
        return 126
    if completed.returncode < 0:
        return 128 + (-completed.returncode)
    return completed.returncode


def run_ledger_go_get(
    argv: list[str], plan: dict[str, object], resolver: ModuleType
) -> int:
    project = plan["project"]
    if not isinstance(project, Path):
        raise CommandError("accepted-plan project is invalid")
    snapshot = snapshot_project(project)
    print(compact_notice("go-get", argv, plan), flush=True)
    try:
        return_code = execute(argv, plan)
    except BaseException:
        restore_project(project, snapshot)
        raise
    ledger = plan["ledger"]
    if not isinstance(ledger, dict):
        raise CommandError("accepted-plan ledger is invalid")
    if return_code != 0:
        restore_project(project, snapshot)
        return return_code
    try:
        updated = verify_post_edit(project, resolver, ledger)
    except CommandError:
        restore_project(project, snapshot)
        raise
    ledger = dict(ledger)
    ledger.update(updated)
    ledger["state"] = "applied"
    try:
        write_ledger(project, ledger)
    except (CommandError, OSError):
        restore_project(project, snapshot)
        raise
    return 0


def run_ledger_followup(
    action: str,
    argv: list[str],
    plan: dict[str, object],
    resolver: ModuleType,
) -> int:
    project = plan["project"]
    if not isinstance(project, Path):
        raise CommandError("accepted-plan project is invalid")
    if action != "mod" and action not in BOOTSTRAP_FOLLOWUP_SUBCOMMANDS:
        raise CommandError(f"{action} is not allowed by an accepted bootstrap plan")
    if action == "mod" and argv != ["go", "mod", "tidy"]:
        raise CommandError("accepted bootstrap plan allows only exact `go mod tidy`")
    forbidden = [
        item
        for item in argv[2:]
        if item.split("=", 1)[0] in FORBIDDEN_BOOTSTRAP_FLAGS
    ]
    if forbidden:
        raise CommandError(
            "dependency-mutating Go flags are not allowed: " + ", ".join(forbidden)
        )
    snapshot = snapshot_project(project)
    environment = command_environment(plan["env"])
    if action != "mod":
        environment["GOFLAGS"] = "-mod=readonly"
    print(compact_notice(action, argv, plan), flush=True)
    try:
        return_code = execute(argv, plan, environment)
    except BaseException:
        restore_project(project, snapshot)
        raise
    ledger = plan["ledger"]
    if not isinstance(ledger, dict):
        raise CommandError("accepted-plan ledger is invalid")
    if action == "mod" and return_code == 0:
        try:
            updated = verify_post_edit(project, resolver, ledger)
        except CommandError:
            restore_project(project, snapshot)
            raise
        ledger = dict(ledger)
        ledger.update(updated)
        try:
            write_ledger(project, ledger)
        except (CommandError, OSError):
            restore_project(project, snapshot)
            raise
    else:
        current = project_state(project, resolver)
        if (
            current["go_mod_sha256"] != ledger["go_mod_sha256"]
            or current["go_sum"] != ledger["go_sum"]
        ):
            restore_project(project, snapshot)
            raise CommandError(f"{action} changed go.mod or go.sum")
    return return_code


def run(args: argparse.Namespace, runtime_root: Path) -> int:
    try:
        resolver = load_resolver()
        resolved = resolver.resolve(args.project, args.gomodcache)
        project, cache, _ = validate_project(resolved)
        bookkeeping_root = project / OWNED_DIRECTORY
        if args.action == "cleanup" and (
            bookkeeping_root.exists() or bookkeeping_root.is_symlink()
        ):
            count, errors = remove_bookkeeping(project)
            if count:
                print(
                    json.dumps(
                        {
                            "action": "cleanup",
                            "status": "blocked",
                            "count": count,
                            "errors": errors,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                )
                return 3
            print(
                json.dumps(
                    {"action": "cleanup", "status": "complete"},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
        if args.action == "cleanup" and retired_bookkeeping_exists(project):
            print(
                json.dumps(
                    {"action": "cleanup", "status": "complete"},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0
        ledger = read_ledger(project)
        if args.action == "probe-bootstrap":
            plan = validate_bootstrap_plan(resolved, resolver)
            plan = isolate_runtime_paths(plan, runtime_root)
            return stage_probe(plan, resolver)

        if ledger is not None:
            if ledger.get("state") == "probed":
                if ledger.get("proof_source") == "bootstrap-probe":
                    expected = validate_bootstrap_plan(resolved, resolver)
                else:
                    expected = validate_resolved_plan(resolved, resolver)
                plan = validate_ledger(
                    ledger,
                    project,
                    cache,
                    resolver,
                    state="probed",
                    bootstrap_plan=expected,
                )
                if args.action != "go-get":
                    raise CommandError(
                        "run the exact pinned go-get before follow-up commands"
                    )
            else:
                plan = validate_ledger(
                    ledger, project, cache, resolver, state="applied"
                )
                if args.action == "go-get":
                    raise CommandError(
                        "the exact pinned dependency edit is already applied"
                    )
            action, argv = select_argv(args, plan)
            plan = isolate_runtime_paths(plan, runtime_root)
            if action == "go-get":
                return run_ledger_go_get(argv, plan, resolver)
            return run_ledger_followup(action, argv, plan, resolver)

        plan = validate_resolved_plan(resolved, resolver)
        action, argv = select_argv(args, plan)
        if action == "go-get":
            ledger = create_ledger(
                plan,
                resolver,
                "probed",
                proof_source="resolver-full-closure",
            )
            write_ledger(project, ledger)
            plan = {**plan, "ledger": ledger}
            plan = isolate_runtime_paths(plan, runtime_root)
            return run_ledger_go_get(argv, plan, resolver)
        if action != "cleanup":
            raise CommandError(
                "run the exact pinned go-get before follow-up commands"
            )
        plan = isolate_runtime_paths(plan, runtime_root)
    except (CommandError, OSError) as error:
        if args.action == "probe-bootstrap":
            terminal_blocker(
                "probe-not-eligible", detail=str(error)[:MAX_BLOCKER_DETAIL]
            )
        else:
            print(f"cannot execute Go OTel command: {error}", file=sys.stderr)
        return 2

    print(compact_notice(action, argv, plan), flush=True)
    return_code = execute(argv, plan)
    if return_code != 0:
        return return_code
    if action == "cleanup":
        unexpected = verify_cleanup(plan)
        if unexpected:
            print(
                "resolver cleanup left unexpected cache payloads: "
                + json.dumps(unexpected),
                file=sys.stderr,
            )
            return 3
    return 0


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(
        prefix="obstudio-go-otel-", ignore_cleanup_errors=True
    ) as runtime_text:
        return run(args, Path(runtime_text))


if __name__ == "__main__":
    raise SystemExit(main())
