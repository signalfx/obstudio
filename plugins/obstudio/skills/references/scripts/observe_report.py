#!/usr/bin/env python3
"""Validate, scope, and render the structured OTel report workflow."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import http.server
import importlib.util
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def _load_sibling(filename: str) -> Any:
    path = Path(__file__).resolve().with_name(filename)
    name = f"_{path.stem}_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return module


# Names from the core and html modules are re-exported so callers keep using one module.
# Patching MODULE.X for a name that lives in core or html does not affect that module's own code.
for _module in (
    _load_sibling("observe_report_core.py"),
    _load_sibling("observe_report_html.py"),
):
    globals().update({k: v for k, v in vars(_module).items() if not k.startswith("_")})
del _module


REPORT_SERVER_SCHEMA_VERSION = 5
REPORT_SERVER_IDLE_TIMEOUT_SECONDS = 8 * 60 * 60
REPORT_SERVER_FILES = {
    "otel.html": "text/html; charset=utf-8",
    "otel-instrumentation.html": "text/html; charset=utf-8",
    "otel-audit.json": "application/json; charset=utf-8",
}


def directory_identity(descriptor: int) -> tuple[int, int]:
    status = os.fstat(descriptor)
    return status.st_dev, status.st_ino


def output_directory_matches(
    boundary: Path,
    relative_parts: tuple[str, ...],
    boundary_identity: tuple[int, int],
    parent_identity: tuple[int, int],
) -> bool:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(boundary, flags)
    except OSError:
        return False
    try:
        if directory_identity(descriptor) != boundary_identity:
            return False
        for component in relative_parts:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return directory_identity(descriptor) == parent_identity
    except OSError:
        return False
    finally:
        os.close(descriptor)


def open_output_parent(
    path: Path,
) -> tuple[int, Path, tuple[str, ...], tuple[int, int], tuple[int, int]]:
    path = Path(os.path.abspath(path))
    parent = path.parent
    boundary = parent
    while not os.path.lexists(boundary):
        next_boundary = boundary.parent
        if next_boundary == boundary:
            fail(f"could not find an existing output boundary for {path}")
        boundary = next_boundary
    relative_parts = parent.relative_to(boundary).parts
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(boundary, flags)
    boundary_identity = directory_identity(descriptor)
    try:
        for component in relative_parts:
            try:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return (
            descriptor,
            boundary,
            relative_parts,
            boundary_identity,
            directory_identity(descriptor),
        )
    except BaseException:
        os.close(descriptor)
        raise


def descriptor_atomic_writes_supported() -> bool:
    # CPython does not advertise os.replace in supports_dir_fd on every POSIX
    # platform where its signature happens to accept dir_fd. Use the
    # equivalently atomic POSIX rename operation and gate that exact primitive.
    required_dir_fd = {os.open, os.stat, os.mkdir, os.unlink, os.rename}
    required_follow_symlinks = {os.stat}
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and required_dir_fd.issubset(os.supports_dir_fd)
        and required_follow_symlinks.issubset(os.supports_follow_symlinks)
    )


def path_is_link_or_reparse(status: os.stat_result) -> bool:
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & reparse_mask)


def portable_parent_chain(parent: Path) -> list[tuple[Path, tuple[int, int]]]:
    lineage: list[Path] = []
    current = parent
    while True:
        lineage.append(current)
        if current.parent == current:
            break
        current = current.parent
    identities: list[tuple[Path, tuple[int, int]]] = []
    for directory in reversed(lineage):
        if identities and not portable_parent_chain_matches(identities):
            fail(
                "output ancestor changed during portable parent creation; this "
                "platform lacks descriptor-relative filesystem operations"
            )
        if not os.path.lexists(directory):
            try:
                directory.mkdir()
            except FileExistsError:
                pass
            if identities and not portable_parent_chain_matches(identities):
                fail(
                    "output ancestor changed while creating a portable parent; "
                    "this platform lacks descriptor-relative filesystem operations"
                )
        status = os.lstat(directory)
        if path_is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
            fail(
                "portable output parent must contain only real directories, "
                f"not symlinks or reparse points: {directory}"
            )
        identities.append((directory, (status.st_dev, status.st_ino)))
    return identities


def portable_parent_chain_matches(
    identities: list[tuple[Path, tuple[int, int]]],
) -> bool:
    for directory, expected in identities:
        try:
            status = os.lstat(directory)
        except OSError:
            return False
        if (
            path_is_link_or_reparse(status)
            or not stat.S_ISDIR(status.st_mode)
            or (status.st_dev, status.st_ino) != expected
        ):
            return False
    return True


def require_portable_regular_target(path: Path) -> None:
    if not os.path.lexists(path):
        return
    status = os.lstat(path)
    if path_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        fail(
            "portable output target must be a regular file, not a symlink, "
            f"reparse point, or directory: {path}"
        )


def write_text_portable(path: Path, value: str) -> None:
    """Atomic fallback for platforms without descriptor-relative APIs.

    Python on Windows cannot bind path operations to a retained directory
    handle. Reparse checks plus before/after directory identity checks detect
    namespace replacement, but cannot eliminate the narrow check/use window
    between validation and a path-based open or replace.
    """

    identities = portable_parent_chain(path.parent)
    require_portable_regular_target(path)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        payload = value.encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        if not portable_parent_chain_matches(identities):
            fail(
                "output parent changed before portable atomic replace; this "
                "platform lacks descriptor-relative filesystem operations"
            )
        require_portable_regular_target(path)
        os.replace(temporary, path)
        if not portable_parent_chain_matches(identities):
            fail(
                "output parent changed during portable atomic replace; this "
                "platform lacks descriptor-relative filesystem operations"
            )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        # A failed path-based write may have observed a replaced namespace.
        # Leave the mode-0600 random temporary entry rather than risk unlinking
        # an entry substituted by another process.


def write_text_descriptor(path: Path, value: str) -> None:
    path = Path(os.path.abspath(path))
    (
        parent_descriptor,
        boundary,
        relative_parts,
        boundary_identity,
        parent_identity,
    ) = open_output_parent(path)
    temporary_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    try:
        try:
            target_status = os.stat(
                path.name, dir_fd=parent_descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            target_status = None
        if target_status is not None and not stat.S_ISREG(target_status.st_mode):
            fail(f"output target must be a regular file, not a symlink or directory: {path}")
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        payload = value.encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.rename(
            temporary_name,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
        if not output_directory_matches(
            boundary,
            relative_parts,
            boundary_identity,
            parent_identity,
        ):
            fail(f"output directory namespace changed during write: {path.parent}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        # Do not unlink a failed temporary name: even under the retained parent
        # fd, another process could have exchanged that directory entry.
        os.close(parent_descriptor)


def write_text(path: Path, value: str) -> None:
    path = Path(os.path.abspath(path))
    if not path.name:
        fail(f"output path must name a file: {path}")
    if descriptor_atomic_writes_supported():
        write_text_descriptor(path, value)
    else:
        write_text_portable(path, value)


def write_json(path: Path, data: dict[str, Any]) -> None:
    write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def load_flow(
    report: dict[str, Any],
    selection_path: Path | None,
    instrumentation_path: Path | None,
    verify_path: Path | None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    selection = load_selection(selection_path, report)
    instrumentation = (
        normalize_instrumentation(load_json(instrumentation_path), report, selection)
        if instrumentation_path
        else None
    )
    if verify_path and instrumentation is None:
        fail("--verify-json requires --instrumentation-json")
    verify = (
        normalize_verify(load_json(verify_path), report, selection, instrumentation)
        if verify_path and instrumentation is not None
        else None
    )
    return selection, instrumentation, verify


def cmd_validate(args: argparse.Namespace) -> int:
    report = normalize_audit_report(load_json(args.audit_json))
    print(
        f"PASS: {args.audit_json} ({len(report['findings'])} findings, "
        f"{len(report['verification']['scenarios'])} scenarios)"
    )
    return 0


def load_canonical_audit_for_selection(audit_json: Path) -> dict[str, Any]:
    try:
        return normalize_audit_report(load_json(audit_json))
    except ReportError as exc:
        fail(
            "canonical audit is invalid; the selection cannot be used until "
            f"$otel-audit is rerun or the audit JSON is repaired: {exc}"
        )


def cmd_select(args: argparse.Namespace) -> int:
    report = load_canonical_audit_for_selection(args.audit_json)
    raw_answers: list[dict[str, str]] = []
    for value in args.decision:
        finding_id, separator, option_id = value.partition("=")
        if not separator or not finding_id.strip() or not option_id.strip():
            fail("--decision must use FINDING_ID=OPTION_ID")
        raw_answers.append(
            {"finding_id": finding_id.strip(), "option_id": option_id.strip()}
        )
    if args.all and args.ids.strip():
        fail("select --all cannot be combined with --ids")
    if args.all:
        raw_ids = select_all_requested_ids(report, raw_answers)
        if not raw_ids:
            fail(
                "select --all found no selectable executable findings. "
                "Answer-only selections authorize no instrumentation code edits."
            )
    else:
        raw_ids = [item.strip() for item in args.ids.split(",") if item.strip()]
    if not raw_ids and not raw_answers:
        fail("select requires --ids, --all, and/or at least one --decision answer")
    ao_selectors = {
        key: value
        for key, value in (
            ("project_name", args.ao_project),
            ("project_id", args.ao_project_id),
            ("agent_stream_name", args.ao_agent_stream),
            ("agent_stream_id", args.ao_agent_stream_id),
        )
        if value is not None
    }
    ao_target = (
        {**ao_selectors, "create_if_missing": not args.ao_reuse_only}
        if ao_selectors or args.ao_reuse_only else None
    )
    selection = normalize_selection(
        {
            "schema_version": (
                CURRENT_SELECTION_SCHEMA_VERSION
                if ao_target is not None
                else DECISION_SELECTION_SCHEMA_VERSION
                if raw_answers
                else OVERLAY_SCHEMA_VERSION
            ),
            "kind": "otel-selection",
            "audit_id": report["meta"]["audit_id"],
            "audit_sha256": audit_digest(report),
            "requested_ids": raw_ids,
            "decision_answers": raw_answers,
            "approved_by": args.approved_by,
            "approved_at": args.approved_at,
            **({"ao_target": ao_target} if ao_target is not None else {}),
        },
        report,
    )
    approved_ids = selection["approved_ids"]
    write_json(args.output, selection)
    added = [finding_id for finding_id in approved_ids if finding_id not in raw_ids]
    print(
        f"wrote {args.output} ({len(approved_ids)} findings in scope"
        + (", selected all eligible executable findings" if args.all else "")
        + (f", auto-included dependencies: {','.join(added)}" if added else "")
        + ")"
    )
    return 0


def cmd_adopt_selection(args: argparse.Namespace) -> int:
    report = load_canonical_audit_for_selection(args.audit_json)
    if not args.output.parent.is_dir():
        fail(f"selection output parent is not a directory: {args.output.parent}")

    matches: list[tuple[int, int, str, Path, dict[str, Any]]] = []
    rejected: list[str] = []
    for trust_tier, candidate in selection_candidate_paths(
        args.audit_json,
        args.output,
        args.candidate,
        args.search_dir,
    ):
        if not candidate.is_file():
            continue
        selection, reason = try_load_bound_selection(candidate, report)
        if selection is None:
            if reason and candidate.name.startswith(("otel-selection", "otel-audit")):
                rejected.append(f"{candidate}: {reason}")
            continue
        try:
            modified = candidate.stat().st_mtime_ns
        except OSError:
            modified = 0
        matches.append(
            (trust_tier, modified, os.path.abspath(candidate), candidate, selection)
        )

    if not matches:
        details = ("\nRejected candidates:\n- " + "\n- ".join(rejected[:10])) if rejected else ""
        fail(
            "no saved audit selection matching the canonical audit was found. "
            "Run select with explicit IDs or use the $otel-instrument command "
            "generated by .observe/otel.html."
            + details
        )

    matches.sort(key=lambda item: (item[0], -item[1], item[2]))
    _trust_tier, _modified, _path_key, source, selection = matches[0]
    selected_all_from_empty = False
    if args.all_if_empty and not selection["approved_ids"]:
        selection = select_all_selection(
            report,
            selection.get("decision_answers", []),
            selection.get("approved_by"),
            selection.get("approved_at"),
            selection.get("ao_target"),
        )
        selected_all_from_empty = True
    write_json(args.output, selection)
    auto_added = [
        finding_id
        for finding_id in selection["approved_ids"]
        if finding_id not in selection["requested_ids"]
    ]
    print(
        f"wrote {args.output} from {source} "
        f"({len(selection['approved_ids'])} findings in scope"
        + (
            ", selected all eligible executable findings"
            if selected_all_from_empty
            else ""
        )
        + (
            f", auto-included dependencies: {','.join(auto_added)}"
            if auto_added
            else ""
        )
        + ")"
    )
    return 0


def infer_source_root(audit_json: Path) -> Path:
    audit_parent = audit_json.resolve().parent
    return audit_parent.parent if audit_parent.name == ".observe" else audit_parent


def cmd_render_html(args: argparse.Namespace) -> int:
    audit_data = load_json(args.audit_json)
    report = normalize_audit_report(audit_data)
    if args.instrumentation_json or args.verify_json:
        fail(
            "audit HTML does not render instrumentation or verification overlays; "
            "use render-instrumentation-html"
        )
    selection = load_selection(args.selection_json, report, audit_data)
    source_root = (args.repo_root or infer_source_root(args.audit_json)).resolve()
    if not source_root.is_dir():
        fail(f"source repository root is not a directory: {source_root}")
    html_text = render_html(
        report,
        selection,
        source_root,
        args.output.resolve().parent,
        include_service_root=not args.omit_service_root,
    )
    write_text(args.output, html_text)
    print(f"wrote {args.output} ({len(report['findings'])} findings)")
    return 0


def audit_finalization_preflight_errors(data: Any) -> list[str]:
    """Return common independent authoring errors in one bounded response."""

    if not isinstance(data, dict):
        return []
    errors: list[str] = []

    row_contracts: tuple[tuple[str, Any, tuple[str, ...]], ...] = (
        (
            "genai_readiness",
            data.get("genai_readiness"),
            (
                "surface",
                "status",
                "evidence",
                "required_signals",
                "owner",
                "acceptance_criteria",
                "impact",
            ),
        ),
        (
            "current_instrumentation.incident_readiness",
            (
                data.get("current_instrumentation", {}).get("incident_readiness")
                if isinstance(data.get("current_instrumentation"), dict)
                else None
            ),
            ("area", "status", "evidence", "required_signals", "impact"),
        ),
    )
    for path, rows, fields in row_contracts:
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            for field in fields:
                value = row.get(field)
                try:
                    compact_row_text(value, f"{path}[{index}].{field}")
                except ReportError:
                    errors.append(f"{path}[{index}].{field} must be a string")

    return errors[:50]


def markdown_local_file_link(label: str, path: PurePath) -> str:
    """Return a CommonMark-safe link to one absolute local path."""

    escaped_label = (
        label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    )
    destination = quote(
        path.as_posix(),
        safe="/: ._~!$&'()*+,;=@-",
    )
    return f"[{escaped_label}](<{destination}>)"


def markdown_web_link(label: str, url: str) -> str:
    """Return a CommonMark link to one loopback HTTP report URL."""

    escaped_label = (
        label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    )
    return f"[{escaped_label}]({url})"


def report_server_state_path(report_directory: Path) -> Path:
    identity = hashlib.sha256(
        str(report_directory.resolve()).encode("utf-8")
    ).hexdigest()[:20]
    user_suffix = (
        f"-{os.getuid()}"
        if os.name != "nt" and hasattr(os, "getuid")
        else ""
    )
    state_directory = (
        Path(tempfile.gettempdir()) / f"obstudio-report-servers{user_suffix}"
    )
    state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        directory_descriptor = os.open(
            state_directory,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            directory_status = os.fstat(directory_descriptor)
            if (
                not stat.S_ISDIR(directory_status.st_mode)
                or (
                    hasattr(os, "getuid")
                    and directory_status.st_uid != os.getuid()
                )
            ):
                fail(
                    f"report server state directory is not private: "
                    f"{state_directory}"
                )
            os.fchmod(directory_descriptor, 0o700)
            current_status = os.lstat(state_directory)
            if (
                path_is_link_or_reparse(current_status)
                or (current_status.st_dev, current_status.st_ino)
                != (directory_status.st_dev, directory_status.st_ino)
            ):
                fail(
                    f"report server state directory changed during validation: "
                    f"{state_directory}"
                )
        finally:
            os.close(directory_descriptor)
    else:
        directory_status = os.lstat(state_directory)
        if (
            path_is_link_or_reparse(directory_status)
            or not stat.S_ISDIR(directory_status.st_mode)
        ):
            fail(
                f"report server state directory is not a private directory: "
                f"{state_directory}"
            )
    return state_directory / f"{identity}.json"


def read_report_server_state_file(state_path: Path) -> dict[str, Any] | None:
    """Read private server state without treating an in-progress launch as live."""

    descriptor: int | None = None
    try:
        descriptor = os.open(
            state_path,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or (os.name != "nt" and status.st_mode & 0o077)
        ):
            return None
        with os.fdopen(descriptor, encoding="utf-8") as state_file:
            descriptor = None
            state = json.load(state_file)
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return state if isinstance(state, dict) else None


def load_report_server_state(
    state_path: Path,
    report_directory: Path,
    expected_token: str | None = None,
) -> dict[str, Any] | None:
    state = read_report_server_state_file(state_path)
    if state is None:
        return None
    try:
        directory_status = report_directory.stat()
    except OSError:
        return None
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != REPORT_SERVER_SCHEMA_VERSION
        or state.get("directory") != str(report_directory.resolve())
        or state.get("directory_device") != directory_status.st_dev
        or state.get("directory_inode") != directory_status.st_ino
        or not isinstance(state.get("pid"), int)
        or state["pid"] <= 0
        or not isinstance(state.get("port"), int)
        or not 1 <= state["port"] <= 65535
        or not isinstance(state.get("token"), str)
        or not state["token"]
        or (expected_token is not None and state["token"] != expected_token)
    ):
        return None
    connection = http.client.HTTPConnection(
        "127.0.0.1",
        state["port"],
        timeout=0.5,
    )
    try:
        connection.request(
            "GET",
            f"/{state['token']}/__obstudio_report_server__",
        )
        response = connection.getresponse()
        healthy = (
            response.status == 200
            and response.read().decode("utf-8") == "ok"
        )
    except (OSError, UnicodeError, http.client.HTTPException):
        return None
    finally:
        connection.close()
    return state if healthy else None


def read_report_file(
    directory_descriptor: int | None,
    report_directory: Path,
    filename: str,
) -> bytes:
    """Read one allowlisted regular file without following a final symlink."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    source_identity: tuple[int, int] | None = None
    try:
        if directory_descriptor is not None:
            descriptor = os.open(filename, flags, dir_fd=directory_descriptor)
        else:
            source = report_directory / filename
            source_status = os.lstat(source)
            if (
                path_is_link_or_reparse(source_status)
                or not stat.S_ISREG(source_status.st_mode)
            ):
                raise OSError("report is not a regular non-link file")
            source_identity = (source_status.st_dev, source_status.st_ino)
            descriptor = os.open(source, flags)
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise OSError("report is not a regular file")
        if source_identity is not None and (
            status.st_dev,
            status.st_ino,
        ) != source_identity:
            raise OSError("report changed while it was opened")
        with os.fdopen(descriptor, "rb") as report_file:
            descriptor = None
            return report_file.read()
    finally:
        if descriptor is not None:
            os.close(descriptor)


def report_server_handler(
    report_directory: Path,
    token: str,
    directory_descriptor: int | None,
) -> type[http.server.BaseHTTPRequestHandler]:
    class ReportHandler(http.server.BaseHTTPRequestHandler):
        def version_string(self) -> str:
            return "ObstudioReport"

        def do_GET(self) -> None:
            request_path = urlsplit(self.path).path
            parts = request_path.removeprefix("/").split("/")
            if len(parts) != 2 or not secrets.compare_digest(parts[0], token):
                self.send_error(404)
                return
            self.server.last_report_access = time.monotonic()  # type: ignore[attr-defined]
            filename = parts[1]
            if filename == "__obstudio_report_server__":
                self.send_payload(b"ok", "text/plain; charset=utf-8")
                return
            if filename not in REPORT_SERVER_FILES:
                self.send_error(404)
                return
            try:
                payload = read_report_file(
                    directory_descriptor,
                    report_directory,
                    filename,
                )
            except FileNotFoundError:
                self.send_error(404)
                return
            except OSError:
                self.send_error(404)
                return
            self.send_payload(payload, REPORT_SERVER_FILES[filename])

        def send_payload(self, payload: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; img-src data:; "
                "base-uri 'none'; form-action 'none'",
            )
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return ReportHandler


def serve_report_until_idle(
    server: http.server.ThreadingHTTPServer,
    idle_timeout_seconds: float = REPORT_SERVER_IDLE_TIMEOUT_SECONDS,
) -> None:
    """Handle requests until the server has received no valid request for the limit."""

    while (
        time.monotonic() - server.last_report_access  # type: ignore[attr-defined]
        < idle_timeout_seconds
    ):
        server.handle_request()


def cmd_serve_report(args: argparse.Namespace) -> int:
    """Serve only generated human HTML and canonical audit JSON on loopback."""

    if args.directory.is_symlink():
        fail(f"report directory must not be a symlink: {args.directory}")
    report_directory = args.directory.resolve()
    if not report_directory.is_dir():
        fail(f"report directory is not a directory: {report_directory}")
    bootstrap_directory_status = report_directory.stat()
    bootstrap = read_report_server_state_file(args.state_file)
    if (
        bootstrap is None
        or bootstrap.get("schema_version") != REPORT_SERVER_SCHEMA_VERSION
        or bootstrap.get("directory") != str(report_directory)
        or bootstrap.get("directory_device") != bootstrap_directory_status.st_dev
        or bootstrap.get("directory_inode") != bootstrap_directory_status.st_ino
        or not isinstance(bootstrap.get("token"), str)
        or not bootstrap["token"]
    ):
        fail("report server launch state is missing or invalid")
    token = bootstrap["token"]
    directory_descriptor: int | None = None
    if os.name != "nt":
        directory_descriptor = os.open(
            report_directory,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    directory_status = (
        os.fstat(directory_descriptor)
        if directory_descriptor is not None
        else report_directory.stat()
    )
    if (
        bootstrap["directory_device"] != directory_status.st_dev
        or bootstrap["directory_inode"] != directory_status.st_ino
    ):
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        fail("report directory changed during server launch")
    handler = report_server_handler(report_directory, token, directory_descriptor)
    try:
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            server.daemon_threads = True
            server.timeout = 1
            server.last_report_access = time.monotonic()  # type: ignore[attr-defined]
            live_state = {
                "schema_version": REPORT_SERVER_SCHEMA_VERSION,
                "directory": str(report_directory),
                "directory_device": directory_status.st_dev,
                "directory_inode": directory_status.st_ino,
                "pid": os.getpid(),
                "port": server.server_port,
                "token": token,
            }
            write_json(args.state_file, live_state)
            try:
                args.state_file.chmod(0o600)
            except OSError:
                pass
            try:
                serve_report_until_idle(server)
            except KeyboardInterrupt:
                pass
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        cleanup_report_server_state(args.state_file, token)
    return 0


def report_server_url(state: dict[str, Any], filename: str) -> str:
    """Return one allowlisted report URL from validated server state."""

    if filename not in REPORT_SERVER_FILES:
        fail(f"report server does not expose {filename}")
    token = state.get("token")
    if isinstance(token, str) and token:
        return f"http://127.0.0.1:{state['port']}/{token}/{filename}"
    current_url = state.get("url")
    if isinstance(current_url, str) and "/" in current_url:
        return f"{current_url.rsplit('/', 1)[0]}/{filename}"
    fail("report server state does not contain a usable URL")


def try_acquire_report_server_lock(descriptor: int) -> bool:
    """Try to hold the per-directory launch lock until startup completes."""

    try:
        if os.name == "nt":
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def release_report_server_lock(descriptor: int) -> None:
    """Release a launch lock; kernel ownership makes crash recovery automatic."""

    try:
        if os.name == "nt":
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def cleanup_report_server_state(state_path: Path, token: str) -> None:
    """Remove owned state only while holding the shared launch lock."""

    lock_descriptor = os.open(
        state_path.with_suffix(".lock"),
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    if not try_acquire_report_server_lock(lock_descriptor):
        os.close(lock_descriptor)
        return
    try:
        current_state = read_report_server_state_file(state_path)
        if current_state is not None and current_state.get("token") == token:
            try:
                state_path.unlink()
            except FileNotFoundError:
                pass
    finally:
        release_report_server_lock(lock_descriptor)


def start_or_reuse_report_server(
    report_directory: Path,
    report_filename: str = "otel.html",
) -> dict[str, Any]:
    """Return a live loopback URL backed by a detached local report server."""

    if report_directory.is_symlink():
        fail(f"report directory must not be a symlink: {report_directory}")
    report_directory = report_directory.resolve()
    if report_filename not in REPORT_SERVER_FILES:
        fail(f"report server does not expose {report_filename}")
    state_path = report_server_state_path(report_directory)
    state = load_report_server_state(state_path, report_directory)
    if state is not None:
        return {
            "pid": state["pid"],
            "port": state["port"],
            "reused": True,
            "url": report_server_url(state, report_filename),
        }

    lock_path = state_path.with_suffix(".lock")
    lock_descriptor = os.open(
        lock_path,
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if try_acquire_report_server_lock(lock_descriptor):
            break
        state = load_report_server_state(state_path, report_directory)
        if state is not None:
            os.close(lock_descriptor)
            return {
                "pid": state["pid"],
                "port": state["port"],
                "reused": True,
                "url": report_server_url(state, report_filename),
            }
        time.sleep(0.05)
    else:
        os.close(lock_descriptor)
        fail("timed out waiting for the loopback report server launch lock")

    try:
        state = load_report_server_state(state_path, report_directory)
        if state is not None:
            return {
                "pid": state["pid"],
                "port": state["port"],
                "reused": True,
                "url": report_server_url(state, report_filename),
            }

        token = secrets.token_urlsafe(24)
        directory_status = report_directory.stat()
        write_json(
            state_path,
            {
                "schema_version": REPORT_SERVER_SCHEMA_VERSION,
                "directory": str(report_directory),
                "directory_device": directory_status.st_dev,
                "directory_inode": directory_status.st_ino,
                "pid": 0,
                "port": 0,
                "token": token,
            },
        )
        try:
            state_path.chmod(0o600)
        except OSError:
            pass
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "serve-report",
            "--directory",
            str(report_directory),
            "--state-file",
            str(state_path),
        ]
        process_options: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            process_options["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            process_options["start_new_session"] = True
        process = subprocess.Popen(command, **process_options)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = load_report_server_state(
                state_path,
                report_directory,
                expected_token=token,
            )
            if state is not None:
                return {
                    "pid": state["pid"],
                    "port": state["port"],
                    "reused": False,
                    "url": report_server_url(state, report_filename),
                }
            if process.poll() is not None:
                break
            time.sleep(0.05)
        if process.poll() is None:
            process.terminate()
        fail("could not start the loopback audit report server")
    finally:
        release_report_server_lock(lock_descriptor)


def cmd_finalize_audit(args: argparse.Namespace) -> int:
    """Validate, render, and serve the interactive audit HTML."""

    if args.html.name != "otel.html":
        fail("--html must use the canonical report name otel.html")
    expected_audit = args.html.resolve().parent / "otel-audit.json"
    if args.audit_json.resolve() != expected_audit:
        fail(
            "audit input must be the canonical otel-audit.json beside otel.html"
        )
    raw_report = load_json(args.audit_json)
    preflight_errors = audit_finalization_preflight_errors(raw_report)
    if preflight_errors:
        fail(
            f"audit finalization found {len(preflight_errors)} independent authoring "
            "errors:\n- "
            + "\n- ".join(preflight_errors)
        )
    report = normalize_audit_report(raw_report)
    source_root = (args.repo_root or infer_source_root(args.audit_json)).resolve()
    if not source_root.is_dir():
        fail(f"source repository root is not a directory: {source_root}")
    write_text(
        args.html,
        render_html(
            report,
            load_selection(None, report),
            source_root,
            args.html.resolve().parent,
        ),
    )
    html_path = args.html.resolve()
    report_server = start_or_reuse_report_server(html_path.parent)
    print(
        json.dumps(
            {
                "result": "PASS",
                "audit_sha256": audit_digest(report),
                "findings": len(report["findings"]),
                "scenarios": len(report["verification"]["scenarios"]),
                "audit": str(args.audit_json.resolve()),
                "html": str(html_path),
                "server": {"requested": True, **report_server},
                "links": {
                    "review_report": markdown_web_link(
                        "otel.html", report_server["url"]
                    ),
                    "machine_report": markdown_local_file_link(
                        "otel-audit.json", args.audit_json.resolve()
                    ),
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def cmd_render_instrumentation_html(args: argparse.Namespace) -> int:
    if args.output.name != "otel-instrumentation.html":
        fail("--output must use the canonical report name otel-instrumentation.html")
    expected_audit = args.output.resolve().parent / "otel-audit.json"
    if args.audit_json.resolve() != expected_audit:
        fail(
            "audit input must be the canonical otel-audit.json beside "
            "otel-instrumentation.html"
        )
    report = normalize_audit_report(load_json(args.audit_json))
    selection, instrumentation, verify = load_flow(
        report, args.selection_json, args.instrumentation_json, args.verify_json
    )
    if instrumentation is None:
        fail("render-instrumentation-html requires --instrumentation-json")
    source_root = (args.repo_root or infer_source_root(args.audit_json)).resolve()
    if not source_root.is_dir():
        fail(f"source repository root is not a directory: {source_root}")
    html_text = render_instrumentation_html(
        report,
        selection,
        instrumentation,
        verify,
        source_root,
        args.output.resolve().parent,
    )
    write_text(args.output, html_text)
    html_path = args.output.resolve()
    audit_html_path = html_path.parent / "otel.html"
    if not audit_html_path.exists():
        write_text(
            audit_html_path,
            render_html(report, selection, source_root, html_path.parent),
        )
    report_server = start_or_reuse_report_server(
        html_path.parent,
        "otel-instrumentation.html",
    )
    audit_url = report_server_url(report_server, "otel.html")
    print(
        json.dumps(
            {
                "result": "PASS",
                "findings": len(instrumentation["findings"]),
                "verification": verify["meta"]["result"] if verify else "Not run",
                "html": str(html_path),
                "server": {"requested": True, **report_server},
                "links": {
                    "instrumentation_report": markdown_web_link(
                        "otel-instrumentation.html",
                        report_server["url"],
                    ),
                    "audit_report": markdown_web_link("otel.html", audit_url),
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def cmd_validate_flow(args: argparse.Namespace) -> int:
    report = load_canonical_audit_for_selection(args.audit_json)
    selection, instrumentation, verify = load_flow(
        report, args.selection_json, args.instrumentation_json, args.verify_json
    )
    stages = ["audit", "selection"]
    if instrumentation:
        stages.append("instrumentation")
    if verify:
        stages.append("verify")
    print(
        f"PASS: {' -> '.join(stages)} ({len(selection['approved_ids'])} findings in scope, "
        f"audit {report['meta']['audit_id']})"
    )
    return 0


def cmd_instrumentation_digest(args: argparse.Namespace) -> int:
    """Print the canonical digest for one bound instrumentation overlay."""
    report = normalize_audit_report(load_json(args.audit_json))
    _selection, instrumentation, _verify = load_flow(
        report,
        args.selection_json,
        args.instrumentation_json,
        None,
    )
    if instrumentation is None:
        fail("instrumentation-digest requires instrumentation JSON")
    print(instrumentation_digest(instrumentation))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate canonical OTel audit JSON")
    validate.add_argument("audit_json", type=Path)
    validate.set_defaults(func=cmd_validate)

    select = subparsers.add_parser("select", help="validate IDs and write a bound selection")
    select.add_argument("audit_json", type=Path)
    select.add_argument(
        "--ids",
        default="",
        help="comma-separated executable finding IDs",
    )
    select.add_argument(
        "--all",
        action="store_true",
        help=(
            "select every currently eligible executable finding; stops with "
            "manual-decision options when a choice is required"
        ),
    )
    select.add_argument("-o", "--output", type=Path, required=True)
    select.add_argument("--approved-by")
    select.add_argument("--approved-at")
    select.add_argument(
        "--decision",
        action="append",
        default=[],
        metavar="FINDING_ID=OPTION_ID",
        help="record a manual decision answer; repeat for multiple decisions",
    )
    select.add_argument("--ao-project", help="Agent Observability project name; reuse or create if missing")
    select.add_argument("--ao-project-id", help="existing Agent Observability project ID; lookup only")
    select.add_argument("--ao-agent-stream", help="Agent Stream name within the selected project; reuse or create if missing")
    select.add_argument("--ao-agent-stream-id", help="existing Agent Stream ID; lookup only")
    select.add_argument("--ao-reuse-only", action="store_true", help="require existing named AO resources instead of creating missing resources")
    select.set_defaults(func=cmd_select)

    adopt = subparsers.add_parser(
        "adopt-selection",
        help=(
            "copy the highest-trust saved otel-selection*.json or "
            "otel-audit*.json review_selection bound to the audit into "
            ".observe/otel-selection.json"
        ),
    )
    adopt.add_argument("audit_json", type=Path)
    adopt.add_argument("-o", "--output", type=Path, required=True)
    adopt.add_argument(
        "--candidate",
        action="append",
        default=[],
        type=Path,
        help="explicit selection JSON candidate; repeat for multiple files",
    )
    adopt.add_argument(
        "--search-dir",
        action="append",
        default=[],
        type=Path,
        help=(
            "directory to search for otel-selection*.json or saved "
            "otel-audit*.json; repeat as needed"
        ),
    )
    adopt.add_argument(
        "--all-if-empty",
        action="store_true",
        help=(
            "when the adopted selection has only decision answers, select every "
            "eligible executable finding using those answers"
        ),
    )
    adopt.set_defaults(func=cmd_adopt_selection)

    render = subparsers.add_parser("render-html", help="render self-contained audit and scope-planning HTML")
    render.add_argument("audit_json", type=Path)
    render.add_argument("-o", "--output", type=Path, required=True)
    render.add_argument("--selection-json", type=Path)
    render.add_argument("--instrumentation-json", type=Path)
    render.add_argument("--verify-json", type=Path)
    render.add_argument(
        "--repo-root",
        type=Path,
        help="source repository root for portable local-file links (inferred from .observe by default)",
    )
    render.add_argument(
        "--omit-service-root",
        action="store_true",
        help="omit the runnable service root from a published static example",
    )
    render.set_defaults(func=cmd_render_html)

    finalize_audit = subparsers.add_parser(
        "finalize-audit",
        help="validate canonical audit, render interactive HTML, and serve it on loopback",
    )
    finalize_audit.add_argument("audit_json", type=Path)
    finalize_audit.add_argument("--html", type=Path, required=True)
    finalize_audit.add_argument(
        "--repo-root",
        type=Path,
        help="source repository root for portable local-file links (inferred from .observe by default)",
    )
    finalize_audit.set_defaults(func=cmd_finalize_audit)

    serve_report = subparsers.add_parser(
        "serve-report",
        help=argparse.SUPPRESS,
    )
    serve_report.add_argument("--directory", type=Path, required=True)
    serve_report.add_argument("--state-file", type=Path, required=True)
    serve_report.set_defaults(func=cmd_serve_report)

    instrumentation_html = subparsers.add_parser(
        "render-instrumentation-html",
        help="render self-contained instrumentation, product-impact, and proof HTML",
    )
    instrumentation_html.add_argument("audit_json", type=Path)
    instrumentation_html.add_argument("-o", "--output", type=Path, required=True)
    instrumentation_html.add_argument("--selection-json", type=Path, required=True)
    instrumentation_html.add_argument("--instrumentation-json", type=Path, required=True)
    instrumentation_html.add_argument("--verify-json", type=Path)
    instrumentation_html.add_argument(
        "--repo-root",
        type=Path,
        help="source repository root for portable local-file links (inferred from .observe by default)",
    )
    instrumentation_html.set_defaults(func=cmd_render_instrumentation_html)

    flow = subparsers.add_parser("validate-flow", help="validate bound workflow overlays")
    flow.add_argument("audit_json", type=Path)
    flow.add_argument("--selection-json", type=Path, required=True)
    flow.add_argument("--instrumentation-json", type=Path)
    flow.add_argument("--verify-json", type=Path)
    flow.set_defaults(func=cmd_validate_flow)

    instrumentation_digest_command = subparsers.add_parser(
        "instrumentation-digest",
        help="print the canonical digest of a bound instrumentation overlay",
    )
    instrumentation_digest_command.add_argument("audit_json", type=Path)
    instrumentation_digest_command.add_argument(
        "--selection-json", type=Path, required=True
    )
    instrumentation_digest_command.add_argument(
        "--instrumentation-json", type=Path, required=True
    )
    instrumentation_digest_command.set_defaults(func=cmd_instrumentation_digest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ReportError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
