#!/usr/bin/env python3
"""Publish generated artifacts without following caller-controlled links."""

from __future__ import annotations

import os
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


class SecureOutputError(ValueError):
    """Raised when an output boundary cannot be authenticated safely."""


@dataclass
class AuthenticatedDirectory:
    path: Path
    identity: tuple[int, int]
    descriptor: int | None = None

    def close(self) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass


def _absolute_lexical(path: Path) -> Path:
    absolute = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
    if sys.platform != "darwin":
        return absolute
    # macOS exposes these root-owned compatibility aliases on every standard
    # installation. Normalize only an alias whose link text still names its
    # expected root target; never resolve a caller-controlled descendant.
    for alias, expected in (
        (Path("/var"), Path("/private/var")),
        (Path("/tmp"), Path("/private/tmp")),
        (Path("/etc"), Path("/private/etc")),
    ):
        try:
            relative = absolute.relative_to(alias)
            status = os.lstat(alias)
            linked = Path(os.path.abspath(alias.parent / os.readlink(alias)))
        except (ValueError, OSError):
            continue
        if stat.S_ISLNK(status.st_mode) and linked == expected:
            return expected / relative
    return absolute


def _identity(status: os.stat_result) -> tuple[int, int]:
    return status.st_dev, status.st_ino


def path_is_link_or_reparse(status: os.stat_result) -> bool:
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(attributes & reparse_mask)


def descriptor_operations_supported() -> bool:
    required_dir_fd = {os.open, os.stat, os.mkdir, os.rename}
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and required_dir_fd.issubset(os.supports_dir_fd)
        and os.stat in os.supports_follow_symlinks
    )


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_directory_chain(path: Path, *, create: bool) -> int:
    absolute = _absolute_lexical(path)
    anchor = Path(absolute.anchor)
    if not absolute.anchor:
        raise SecureOutputError(f"directory path must be absolute: {path}")
    descriptor = os.open(anchor, _directory_flags())
    try:
        for component in absolute.relative_to(anchor).parts:
            try:
                next_descriptor = os.open(
                    component, _directory_flags(), dir_fd=descriptor
                )
            except FileNotFoundError:
                if not create:
                    raise SecureOutputError(
                        f"directory does not exist or is not a directory: {absolute}"
                    ) from None
                try:
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                try:
                    next_descriptor = os.open(
                        component, _directory_flags(), dir_fd=descriptor
                    )
                except OSError as error:
                    raise SecureOutputError(
                        "output parent must contain only real directories, not "
                        f"symlinks or reparse points: {absolute} ({error})"
                    ) from error
            except OSError as error:
                raise SecureOutputError(
                    "directory boundary must contain only real directories, not "
                    f"symlinks or reparse points: {absolute} ({error})"
                ) from error
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_project_output_parent(
    project: AuthenticatedDirectory, output: Path
) -> int:
    if project.descriptor is None:
        raise SecureOutputError(
            "authenticated project descriptor is unavailable for relative output"
        )
    descriptor = os.dup(project.descriptor)
    try:
        if _identity(os.fstat(descriptor)) != project.identity:
            raise SecureOutputError(
                f"project boundary changed before artifact publication: {project.path}"
            )
        relative_parent = output.parent.relative_to(project.path)
        for component in relative_parent.parts:
            try:
                next_descriptor = os.open(
                    component, _directory_flags(), dir_fd=descriptor
                )
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                try:
                    next_descriptor = os.open(
                        component, _directory_flags(), dir_fd=descriptor
                    )
                except OSError as error:
                    raise SecureOutputError(
                        "output parent must contain only real directories, not "
                        f"symlinks or reparse points: {output.parent} ({error})"
                    ) from error
            except OSError as error:
                raise SecureOutputError(
                    "output parent must contain only real directories, not "
                    f"symlinks or reparse points: {output.parent} ({error})"
                ) from error
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _portable_directory_chain(
    path: Path, *, create: bool
) -> list[tuple[Path, tuple[int, int]]]:
    absolute = _absolute_lexical(path)
    anchor = Path(absolute.anchor)
    if not absolute.anchor:
        raise SecureOutputError(f"directory path must be absolute: {path}")
    directories = [anchor]
    current = anchor
    for component in absolute.relative_to(anchor).parts:
        current = current / component
        directories.append(current)

    identities: list[tuple[Path, tuple[int, int]]] = []
    for directory in directories:
        if identities and not _portable_chain_matches(identities):
            raise SecureOutputError(
                "directory boundary changed during portable validation; this "
                "platform lacks descriptor-relative filesystem operations"
            )
        if not os.path.lexists(directory):
            if not create:
                raise SecureOutputError(
                    f"directory does not exist or is not a directory: {absolute}"
                )
            try:
                directory.mkdir()
            except FileExistsError:
                pass
        try:
            status = os.lstat(directory)
        except OSError as error:
            raise SecureOutputError(
                f"could not authenticate directory boundary {directory}: {error}"
            ) from error
        if path_is_link_or_reparse(status) or not stat.S_ISDIR(status.st_mode):
            raise SecureOutputError(
                "directory boundary must contain only real directories, not "
                f"symlinks or reparse points: {directory}"
            )
        identities.append((directory, _identity(status)))
    return identities


def _portable_chain_matches(
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
            or _identity(status) != expected
        ):
            return False
    return True


def _directory_identity(path: Path) -> tuple[int, int]:
    if descriptor_operations_supported():
        descriptor = _open_directory_chain(path, create=False)
        try:
            return _identity(os.fstat(descriptor))
        finally:
            os.close(descriptor)
    return _portable_directory_chain(path, create=False)[-1][1]


def authenticate_directory(path: Path) -> AuthenticatedDirectory:
    absolute = _absolute_lexical(path)
    if descriptor_operations_supported():
        try:
            descriptor = _open_directory_chain(absolute, create=False)
        except SecureOutputError:
            raise
        except OSError as error:
            raise SecureOutputError(
                f"could not authenticate directory boundary {absolute}: {error}"
            ) from error
        return AuthenticatedDirectory(
            absolute, _identity(os.fstat(descriptor)), descriptor
        )
    try:
        identity = _directory_identity(absolute)
    except SecureOutputError:
        raise
    except OSError as error:
        raise SecureOutputError(
            f"could not authenticate directory boundary {absolute}: {error}"
        ) from error
    return AuthenticatedDirectory(absolute, identity)


def require_same_directory(directory: AuthenticatedDirectory) -> None:
    if directory.descriptor is not None:
        try:
            retained_identity = _identity(os.fstat(directory.descriptor))
        except OSError as error:
            raise SecureOutputError(
                f"retained directory boundary is unavailable: {error}"
            ) from error
        if retained_identity != directory.identity:
            raise SecureOutputError(
                f"retained directory boundary changed: {directory.path}"
            )
    try:
        current_identity = _directory_identity(directory.path)
    except SecureOutputError:
        raise
    except OSError as error:
        raise SecureOutputError(
            f"could not re-authenticate directory boundary {directory.path}: {error}"
        ) from error
    if current_identity != directory.identity:
        raise SecureOutputError(
            f"directory boundary changed during artifact publication: {directory.path}"
        )


def resolve_output_path(
    project: AuthenticatedDirectory, requested: Path
) -> Path:
    expanded = Path(os.path.expanduser(os.fspath(requested)))
    if expanded.is_absolute():
        return _absolute_lexical(expanded)
    output = _absolute_lexical(project.path / expanded)
    try:
        output.relative_to(project.path)
    except ValueError:
        raise SecureOutputError(
            f"relative output escapes the authenticated project boundary: {requested}"
        ) from None
    return output


def _require_regular_target_descriptor(parent_descriptor: int, name: str) -> None:
    try:
        status = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    if path_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise SecureOutputError(
            "output target must be a regular file, not a symlink, reparse "
            f"point, or directory: {name}"
        )


def _write_descriptor(
    path: Path,
    value: str,
    project: AuthenticatedDirectory | None = None,
) -> None:
    parent_descriptor = (
        _open_project_output_parent(project, path)
        if project is not None
        else _open_directory_chain(path.parent, create=True)
    )
    parent_identity = _identity(os.fstat(parent_descriptor))
    temporary_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    stream: int | None = None
    try:
        _require_regular_target_descriptor(parent_descriptor, path.name)
        stream = os.open(
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
            offset += os.write(stream, payload[offset:])
        os.fsync(stream)
        os.close(stream)
        stream = None
        _require_regular_target_descriptor(parent_descriptor, path.name)
        os.rename(
            temporary_name,
            path.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        os.fsync(parent_descriptor)
        current = _open_directory_chain(path.parent, create=False)
        try:
            if _identity(os.fstat(current)) != parent_identity:
                raise SecureOutputError(
                    f"output parent namespace changed during publication: {path.parent}"
                )
        finally:
            os.close(current)
    finally:
        if stream is not None:
            os.close(stream)
        # A failed write deliberately leaves its unpredictable mode-0600
        # temporary entry: unlinking a name after a namespace race could remove
        # an entry supplied by another process.
        os.close(parent_descriptor)


def _require_regular_target_portable(path: Path) -> None:
    if not os.path.lexists(path):
        return
    status = os.lstat(path)
    if path_is_link_or_reparse(status) or not stat.S_ISREG(status.st_mode):
        raise SecureOutputError(
            "output target must be a regular file, not a symlink, reparse "
            f"point, or directory: {path}"
        )


def _write_portable(path: Path, value: str) -> None:
    """Best available atomic publication without descriptor-relative APIs.

    Reparse checks and directory identity checks detect namespace replacement,
    but Python cannot eliminate the narrow path check/use window on Windows.
    """

    identities = _portable_directory_chain(path.parent, create=True)
    _require_regular_target_portable(path)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(12)}.tmp")
    stream: int | None = None
    try:
        stream = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        payload = value.encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(stream, payload[offset:])
        os.fsync(stream)
        os.close(stream)
        stream = None
        if not _portable_chain_matches(identities):
            raise SecureOutputError(
                "output parent changed before portable atomic publication"
            )
        _require_regular_target_portable(path)
        os.replace(temporary, path)
        if not _portable_chain_matches(identities):
            raise SecureOutputError(
                "output parent changed during portable atomic publication"
            )
    finally:
        if stream is not None:
            os.close(stream)


def write_text(
    project: AuthenticatedDirectory,
    requested: Path,
    value: str,
) -> Path:
    if not requested.name:
        raise SecureOutputError(f"output path must name a file: {requested}")
    require_same_directory(project)
    output = resolve_output_path(project, requested)
    try:
        if descriptor_operations_supported():
            try:
                output.relative_to(project.path)
            except ValueError:
                output_project = None
            else:
                output_project = project
            _write_descriptor(output, value, output_project)
        else:
            _write_portable(output, value)
    except SecureOutputError:
        raise
    except OSError as error:
        raise SecureOutputError(
            f"could not publish artifact at {output}: {error}"
        ) from error
    require_same_directory(project)
    return output
