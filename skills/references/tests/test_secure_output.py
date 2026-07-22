from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT_DIRECTORY = Path(__file__).parents[1] / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import secure_output


class SecureOutputTest(unittest.TestCase):
    def test_reparse_attribute_is_treated_as_link(self) -> None:
        status = SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o755,
            st_file_attributes=getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
            ),
        )

        self.assertTrue(secure_output.path_is_link_or_reparse(status))

    def test_portable_writer_replaces_existing_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory).resolve()
            project = secure_output.authenticate_directory(project_path)
            target = project_path / "nested" / "result.json"
            target.parent.mkdir()
            target.write_text("old\n", encoding="utf-8")

            with mock.patch.object(
                secure_output, "descriptor_operations_supported", return_value=False
            ):
                written = secure_output.write_text(
                    project, Path("nested/result.json"), "new\n"
                )

            self.assertEqual(written, target)
            self.assertEqual(target.read_text(encoding="utf-8"), "new\n")

    def test_portable_writer_rejects_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory).resolve()
            project = secure_output.authenticate_directory(project_path)
            outside = project_path / "outside"
            outside.mkdir()
            (project_path / "linked").symlink_to(outside, target_is_directory=True)

            with mock.patch.object(
                secure_output, "descriptor_operations_supported", return_value=False
            ):
                with self.assertRaisesRegex(
                    secure_output.SecureOutputError, "symlinks or reparse points"
                ):
                    secure_output.write_text(
                        project, Path("linked/result.json"), "unsafe\n"
                    )

            self.assertFalse((outside / "result.json").exists())

    def test_portable_writer_rejects_windows_reparse_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory).resolve()
            project = secure_output.authenticate_directory(project_path)
            reparse = project_path / "reparse"
            reparse.mkdir()
            original_lstat = secure_output.os.lstat

            def lstat_with_reparse(path: object) -> object:
                status = original_lstat(path)
                if Path(path) != reparse:
                    return status
                return SimpleNamespace(
                    st_mode=status.st_mode,
                    st_dev=status.st_dev,
                    st_ino=status.st_ino,
                    st_file_attributes=getattr(
                        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
                    ),
                )

            with (
                mock.patch.object(
                    secure_output,
                    "descriptor_operations_supported",
                    return_value=False,
                ),
                mock.patch.object(
                    secure_output.os, "lstat", side_effect=lstat_with_reparse
                ),
            ):
                with self.assertRaisesRegex(
                    secure_output.SecureOutputError, "symlinks or reparse points"
                ):
                    secure_output.write_text(
                        project, Path("reparse/result.json"), "unsafe\n"
                    )

    def test_relative_output_cannot_escape_project_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory).resolve() / "project"
            project_path.mkdir()
            project = secure_output.authenticate_directory(project_path)
            outside = project_path.parent / "outside.json"

            with self.assertRaisesRegex(
                secure_output.SecureOutputError, "escapes.*project boundary"
            ):
                secure_output.write_text(
                    project, Path("../outside.json"), "unsafe\n"
                )

            self.assertFalse(outside.exists())

    @unittest.skipUnless(sys.platform == "darwin", "macOS system alias contract")
    def test_verified_macos_var_alias_is_normalized_without_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw_project = Path(directory) / "project"
            raw_project.mkdir()
            if not str(raw_project).startswith("/var/"):
                self.skipTest("temporary directory is not exposed through /var")

            project = secure_output.authenticate_directory(raw_project)
            written = secure_output.write_text(
                project, raw_project / "result.json", "safe\n"
            )

            self.assertEqual(project.path, raw_project.resolve())
            self.assertEqual(written, raw_project.resolve() / "result.json")
            self.assertEqual(written.read_text(encoding="utf-8"), "safe\n")

    def test_posix_relative_output_cannot_be_redirected_by_project_aba(self) -> None:
        if not secure_output.descriptor_operations_supported():
            self.skipTest("requires descriptor-relative POSIX operations")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "project"
            root.mkdir()
            moved = base / "saved-project"
            replacement = base / "replacement-project"
            replacement.mkdir()
            project = secure_output.authenticate_directory(root)
            original = secure_output._write_descriptor

            def swap_then_write(
                path: Path,
                value: str,
                boundary: secure_output.AuthenticatedDirectory | None = None,
            ) -> None:
                root.rename(moved)
                replacement.rename(root)
                try:
                    original(path, value, boundary)
                finally:
                    root.rename(replacement)
                    moved.rename(root)

            with mock.patch.object(
                secure_output, "_write_descriptor", side_effect=swap_then_write
            ):
                with self.assertRaises(secure_output.SecureOutputError):
                    secure_output.write_text(
                        project, Path(".observe/result.json"), "payload\n"
                    )

            self.assertEqual(
                (root / ".observe/result.json").read_text(encoding="utf-8"),
                "payload\n",
            )
            self.assertFalse((replacement / ".observe/result.json").exists())


if __name__ == "__main__":
    unittest.main()
