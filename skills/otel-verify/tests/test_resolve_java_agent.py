from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


RESOLVER = Path(__file__).parents[1] / "scripts" / "resolve_java_agent.py"
SHARED_RESOLVER = (
    Path(__file__).parents[2] / "references" / "scripts" / "resolve_java_agent.py"
)
UPSTREAM_PREMAIN = "io.opentelemetry.javaagent.OpenTelemetryAgent"
SPLUNK_PREMAIN = "com.splunk.opentelemetry.javaagent.SplunkAgent"


def write_agent(
    path: Path,
    *,
    version: str,
    premain: str = UPSTREAM_PREMAIN,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Manifest-Version: 1.0",
        f"Implementation-Version: {version}",
    ]
    if premain:
        lines.append(f"Premain-Class: {premain}")
    payload = "\r\n".join(lines) + "\r\n\r\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", payload)


def mutate_zip_headers(
    path: Path,
    *,
    encrypted: bool = False,
    compression: int | None = None,
) -> None:
    payload = bytearray(path.read_bytes())
    local = payload.index(b"PK\x03\x04")
    central = payload.index(b"PK\x01\x02")
    if encrypted:
        for position in (local + 6, central + 8):
            flags = struct.unpack_from("<H", payload, position)[0]
            struct.pack_into("<H", payload, position, flags | 1)
    if compression is not None:
        struct.pack_into("<H", payload, local + 8, compression)
        struct.pack_into("<H", payload, central + 10, compression)
    path.write_bytes(payload)


def write_eocd_only_candidate(path: Path, *, entries: int, central_size: int = 0) -> None:
    """Write a tiny candidate whose EOCD advertises a hostile directory budget."""

    path.write_bytes(
        struct.pack(
            "<4s4H2LH",
            b"PK\x05\x06",
            0,
            0,
            entries,
            entries,
            central_size,
            0,
            0,
        )
    )


def write_central_directory_candidate(
    path: Path,
    *,
    actual_entries: int,
    advertised_entries: int,
) -> None:
    record = struct.pack(
        "<4s6H3L5H2L",
        b"PK\x01\x02",
        *([0] * 16),
    )
    central_directory = record * actual_entries
    path.write_bytes(
        central_directory
        + struct.pack(
            "<4s4H2LH",
            b"PK\x05\x06",
            0,
            0,
            advertised_entries,
            advertised_entries,
            len(central_directory),
            0,
            0,
        )
    )


def bounded_omission(result: dict[str, object], reason: str) -> dict[str, object]:
    discovery = result["bounded_discovery"]
    assert isinstance(discovery, dict)
    omissions = discovery["omissions"]
    assert isinstance(omissions, list)
    return next(row for row in omissions if row["reason"] == reason)


def load_shared_resolver():
    spec = importlib.util.spec_from_file_location(
        "resolve_java_agent_tested", SHARED_RESOLVER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RESOLVER_MODULE = load_shared_resolver()


class ResolveJavaAgentTest(unittest.TestCase):
    def test_upstream_agent_name_overrides_unrelated_splunk_ancestor(self) -> None:
        path = Path(
            "/workspace/splunk/service/opentelemetry-javaagent-2.1.0.jar"
        )

        self.assertEqual(
            RESOLVER_MODULE.family_from_path(path),
            "opentelemetry",
        )

    def test_splunk_coordinate_overrides_renamed_upstream_filename(self) -> None:
        path = Path(
            "/m2/com/splunk/splunk-otel-javaagent/2.1.0/"
            "opentelemetry-javaagent-2.1.0.jar"
        )

        self.assertEqual(
            RESOLVER_MODULE.family_from_path(path),
            "splunk",
        )

    def test_generic_agent_name_does_not_inherit_workspace_family(self) -> None:
        path = Path(
            "/workspace/splunk/service/opentelemetry-javaagent.jar"
        )

        self.assertIsNone(RESOLVER_MODULE.family_from_path(path))

    def test_generic_upstream_agent_resolves_inside_splunk_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "splunk" / "service"
            project.mkdir(parents=True)
            candidate = project / "opentelemetry-javaagent.jar"
            write_agent(candidate, version="2.1.0")

            result = self.run_resolver(
                project,
                maven_repo=root / "missing-m2",
                extra=("--candidate", str(candidate)),
                unset_env=tuple(
                    RESOLVER_MODULE.ENV_AGENT_PATHS
                    + RESOLVER_MODULE.ENV_AGENT_OPTIONS
                ),
            )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["selected"]["family"], "opentelemetry")

    def test_explicit_generic_upstream_agent_outranks_splunk_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "splunk" / "service"
            project.mkdir(parents=True)
            candidate = project / "opentelemetry-javaagent.jar"
            write_agent(candidate, version="2.1.0")
            cached = (
                root
                / "m2/com/splunk/splunk-otel-javaagent/2.2.0"
                / "splunk-otel-javaagent-2.2.0.jar"
            )
            write_agent(
                cached,
                version="splunk-2.2.0-otel-2.2.0",
                premain=SPLUNK_PREMAIN,
            )

            result = self.run_resolver(
                project,
                maven_repo=root / "m2",
                extra=("--candidate", str(candidate)),
                unset_env=tuple(
                    RESOLVER_MODULE.ENV_AGENT_PATHS
                    + RESOLVER_MODULE.ENV_AGENT_OPTIONS
                ),
            )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["selected"]["path"], str(candidate.resolve()))
        self.assertEqual(result["selected"]["family"], "opentelemetry")

    def run_resolver(
        self,
        project: Path,
        *,
        maven_repo: Path,
        extra: tuple[str, ...] = (),
        unset_env: tuple[str, ...] = (),
    ) -> dict[str, object]:
        environment = os.environ.copy()
        for variable in unset_env:
            environment.pop(variable, None)
        completed = subprocess.run(
            [
                sys.executable,
                str(RESOLVER),
                "--project",
                str(project),
                "--maven-repo",
                str(maven_repo),
                "--gradle-cache",
                str(project / "missing-gradle-cache"),
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        return json.loads(completed.stdout)

    def resolve_in_process(
        self,
        project: Path,
        *,
        candidates: tuple[Path, ...] = (),
        maven_repo: Path | None = None,
        portable: bool = False,
    ) -> dict[str, object]:
        args = argparse.Namespace(
            project=project,
            candidate=[str(path) for path in candidates],
            maven_repo=[maven_repo or project / "missing-m2"],
            gradle_cache=[project / "missing-gradle-cache"],
            expected_family=None,
            expected_version=None,
            expected_sha256=None,
            output=None,
        )
        cleared_environment = {
            variable: ""
            for variable in (
                *RESOLVER_MODULE.ENV_AGENT_PATHS,
                *RESOLVER_MODULE.ENV_AGENT_OPTIONS,
            )
        }
        with (
            mock.patch.dict(os.environ, cleared_environment),
            mock.patch.object(
                RESOLVER_MODULE,
                "descriptor_operations_supported",
                return_value=not portable,
            ),
        ):
            return RESOLVER_MODULE.resolve(args)

    def test_selects_newest_valid_cached_agent_and_emits_verification_pin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            repository = root / "m2"
            older = (
                repository
                / "com/splunk/splunk-otel-javaagent/2.26.0"
                / "splunk-otel-javaagent-2.26.0.jar"
            )
            newer = (
                repository
                / "com/splunk/splunk-otel-javaagent/2.27.0"
                / "splunk-otel-javaagent-2.27.0.jar"
            )
            write_agent(
                older,
                version="splunk-2.26.0-otel-2.26.0",
                premain=SPLUNK_PREMAIN,
            )
            write_agent(
                newer,
                version="splunk-2.27.0-otel-2.27.0",
                premain=SPLUNK_PREMAIN,
            )

            result = self.run_resolver(project, maven_repo=repository)

            self.assertEqual(result["status"], "resolved")
            selected = result["selected"]
            self.assertEqual(selected["path"], str(newer.resolve()))
            self.assertEqual(selected["artifact_version"], "2.27.0")
            self.assertEqual(selected["source"], "maven_cache")
            self.assertEqual(selected["family"], "splunk")
            self.assertEqual(
                selected["sha256"], hashlib.sha256(newer.read_bytes()).hexdigest()
            )
            self.assertEqual(
                selected["javaagent_argv"], [f"-javaagent:{newer.resolve()}"]
            )
            self.assertEqual(
                selected["verification_pin"]["sha256"], selected["sha256"]
            )
            self.assertEqual(
                selected["verification_pin"]["artifact_identity"],
                selected["artifact_identity"],
            )
            self.assertIn("--expected-sha256", selected["pre_attach_recheck_argv"])
            self.assertEqual(
                result["production_parity"]["status"], "not_proven"
            )
            self.assertIn("no user-supplied agent is required", result["message"])

    def test_candidate_bound_does_not_hide_257th_valid_agent_as_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            valid = root / "opentelemetry-javaagent-1.2.3.jar"
            write_agent(valid, version="1.2.3")
            candidates = [
                root / f"missing-opentelemetry-javaagent-{index}.jar"
                for index in range(RESOLVER_MODULE.MAX_CANDIDATES)
            ] + [valid]
            extra = tuple(
                argument
                for candidate in candidates
                for argument in ("--candidate", str(candidate))
            )

            result = self.run_resolver(
                project,
                maven_repo=root / "missing-m2",
                extra=extra,
                unset_env=tuple(
                    RESOLVER_MODULE.ENV_AGENT_PATHS
                    + RESOLVER_MODULE.ENV_AGENT_OPTIONS
                ),
            )

            self.assertEqual(result["status"], "incomplete")
            self.assertFalse(result["complete"])
            self.assertIsNone(result["selected"])
            self.assertEqual(result["searched"]["raw_candidates"], 257)
            self.assertEqual(result["searched"]["candidates_validated"], 256)
            omission = bounded_omission(result, "candidate_validation_limit")
            self.assertEqual(omission["omitted_count"], 1)
            self.assertFalse(omission["count_is_lower_bound"])
            self.assertIn("bounded discovery", result["message"])

    def test_high_occurrence_config_is_retained_with_bounded_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "runtime.conf").write_text(
                "\n".join(
                    f'JAVA_TOOL_OPTIONS="-javaagent:agent-{index}.jar"'
                    for index in range(100)
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(RESOLVER_MODULE, "MAX_CANDIDATES", 4):
                result = self.resolve_in_process(project)

            self.assertEqual(result["status"], "incomplete")
            self.assertFalse(result["complete"])
            self.assertIsNone(result["selected"])
            self.assertLessEqual(result["searched"]["raw_candidates"], 4)
            omission = bounded_omission(result, "configured_candidate_limit")
            self.assertEqual(omission["omitted_count"], 1)
            self.assertTrue(omission["count_is_lower_bound"])
            self.assertEqual(omission["limit"], 4)

    def test_duplicate_config_occurrences_have_a_bounded_visit_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            project.mkdir()
            (project / "runtime.conf").write_text(
                "\n".join(
                    'JAVA_TOOL_OPTIONS="-javaagent:agent.jar"'
                    for _ in range(100)
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                RESOLVER_MODULE,
                "MAX_CANDIDATE_VISITS",
                5,
            ):
                result = self.resolve_in_process(project)

            self.assertEqual(result["status"], "incomplete")
            self.assertFalse(result["complete"])
            self.assertLessEqual(result["searched"]["raw_candidates"], 1)
            omission = bounded_omission(
                result,
                "configured_candidate_visit_limit",
            )
            self.assertEqual(omission["omitted_count"], 1)
            self.assertTrue(omission["count_is_lower_bound"])
            self.assertEqual(omission["limit"], 5)

    def test_cache_traversal_stops_after_first_unique_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cache"
            for index in range(4):
                candidate = root / "agents" / f"{index:03d}" / f"agent-{index}.jar"
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_bytes(b"jar")

            omissions = []
            with (
                mock.patch.object(RESOLVER_MODULE, "MAX_CANDIDATES", 3),
                mock.patch.object(RESOLVER_MODULE, "MAX_CANDIDATE_VISITS", 100),
            ):
                candidates = RESOLVER_MODULE.cache_candidates(
                    [root],
                    ["agents/*/*.jar"],
                    "maven_cache",
                    omissions,
                )

            self.assertEqual(len(candidates), 3)
            self.assertEqual(
                [str(row[0]) for row in candidates],
                sorted(str(row[0]) for row in candidates),
            )
            self.assertEqual(len(omissions), 1)
            self.assertEqual(omissions[0].reason, "maven_cache_candidate_limit")
            self.assertTrue(omissions[0].count_is_lower_bound)

    def test_large_cache_tree_has_a_bounded_entry_visit_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cache"
            coordinate = root / "agents"
            for index in range(20):
                (coordinate / f"irrelevant-{index:03d}").mkdir(parents=True)

            omissions = []
            with mock.patch.object(
                RESOLVER_MODULE,
                "MAX_CANDIDATE_VISITS",
                5,
            ):
                candidates = RESOLVER_MODULE.cache_candidates(
                    [root],
                    ["agents/*/*.jar"],
                    "maven_cache",
                    omissions,
                )

            self.assertEqual(candidates, [])
            self.assertEqual(len(omissions), 1)
            self.assertEqual(
                omissions[0].reason,
                "maven_cache_entry_visit_limit",
            )
            self.assertTrue(omissions[0].count_is_lower_bound)

    def test_cache_directory_swap_cannot_escape_authenticated_root(self) -> None:
        for portable in (False, True):
            with (
                self.subTest(portable=portable),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                project = root / "project"
                project.mkdir()
                repository = root / "m2"
                original = repository / "io"
                original.mkdir(parents=True)
                outside = root / "outside"
                hostile = (
                    outside
                    / "opentelemetry/javaagent/opentelemetry-javaagent/9.9.9"
                    / "opentelemetry-javaagent-9.9.9.jar"
                )
                write_agent(hostile, version="9.9.9")
                saved = repository / "authenticated-io"
                real_open_cursor = RESOLVER_MODULE.open_scan_cursor
                swapped = False

                def swap_queued_directory(scan_root, cursor):
                    nonlocal swapped
                    if cursor.parts == ("io",) and not swapped:
                        original.rename(saved)
                        original.symlink_to(outside, target_is_directory=True)
                        swapped = True
                    return real_open_cursor(scan_root, cursor)

                with mock.patch.object(
                    RESOLVER_MODULE,
                    "open_scan_cursor",
                    side_effect=swap_queued_directory,
                ):
                    result = self.resolve_in_process(
                        project,
                        maven_repo=repository,
                        portable=portable,
                    )

                self.assertTrue(swapped)
                self.assertEqual(result["status"], "incomplete")
                self.assertFalse(result["complete"])
                self.assertIsNone(result["selected"])
                self.assertEqual(result["searched"]["valid_candidates"], 0)
                omission = bounded_omission(
                    result,
                    "maven_cache_traversal_error",
                )
                self.assertTrue(omission["count_is_lower_bound"])
                self.assertNotIn(str(hostile.resolve()), json.dumps(result))

    def test_rooted_candidate_leaf_is_bound_to_discovered_identity(self) -> None:
        for portable in (False, True):
            with (
                self.subTest(portable=portable),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                repository = root / "cache"
                candidate = (
                    repository
                    / "agents/1.2.3"
                    / "opentelemetry-javaagent-1.2.3.jar"
                )
                write_agent(candidate, version="1.2.3")
                with mock.patch.object(
                    RESOLVER_MODULE,
                    "descriptor_operations_supported",
                    return_value=not portable,
                ):
                    references = RESOLVER_MODULE.cache_candidates(
                        [repository],
                        ["agents/*/*.jar"],
                        "maven_cache",
                        [],
                    )
                    self.assertEqual(len(references), 1)
                    saved = candidate.with_name("authenticated-original.jar")
                    candidate.rename(saved)
                    write_agent(candidate, version="9.9.9")
                    selected, error = RESOLVER_MODULE.validate_candidate(
                        references[0].path,
                        references[0].authority,
                    )

                self.assertIsNone(selected)
                self.assertIn("changed", error or "")

    def test_symlinked_explicit_cache_root_is_bound_to_resolved_target(self) -> None:
        for portable in (False, True):
            with (
                self.subTest(portable=portable),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                project = root / "project"
                project.mkdir()
                repository = root / "real-m2"
                candidate = (
                    repository
                    / "io/opentelemetry/javaagent/opentelemetry-javaagent/1.2.3"
                    / "opentelemetry-javaagent-1.2.3.jar"
                )
                write_agent(candidate, version="1.2.3")
                linked = root / "linked-m2"
                linked.symlink_to(repository, target_is_directory=True)

                result = self.resolve_in_process(
                    project,
                    maven_repo=linked,
                    portable=portable,
                )

                self.assertEqual(result["status"], "resolved")
                self.assertTrue(result["complete"])
                self.assertEqual(result["selected"]["path"], str(candidate.resolve()))
                self.assertEqual(result["bounded_discovery"]["omissions"], [])

    def test_broken_or_non_directory_cache_roots_are_incomplete(self) -> None:
        for root_kind in ("broken-link", "regular-file"):
            with (
                self.subTest(root_kind=root_kind),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                project = root / "project"
                project.mkdir()
                repository = root / "requested-m2"
                if root_kind == "broken-link":
                    repository.symlink_to(root / "missing", target_is_directory=True)
                else:
                    repository.write_text("not a cache\n", encoding="utf-8")

                result = self.resolve_in_process(
                    project,
                    maven_repo=repository,
                )

                self.assertEqual(result["status"], "incomplete")
                self.assertFalse(result["complete"])
                self.assertIsNone(result["selected"])
                omission = bounded_omission(
                    result,
                    "maven_cache_root_authentication_error",
                )
                self.assertFalse(omission["count_is_lower_bound"])

    def test_candidate_cap_prefix_and_omission_are_scandir_order_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "cache"
            for version in ("3.0.0", "1.0.0", "4.0.0", "2.0.0"):
                candidate = (
                    repository
                    / "agents"
                    / version
                    / f"opentelemetry-javaagent-{version}.jar"
                )
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_bytes(b"candidate")

            real_scandir = RESOLVER_MODULE.os.scandir

            class ReversedScandir:
                def __init__(self, target):
                    self.context = real_scandir(target)

                def __enter__(self):
                    entries = list(self.context.__enter__())
                    return iter(sorted(entries, key=lambda entry: entry.name, reverse=True))

                def __exit__(self, *args):
                    return self.context.__exit__(*args)

            def discover(*, reverse: bool):
                omissions = []
                patches = [
                    mock.patch.object(RESOLVER_MODULE, "MAX_CANDIDATES", 2),
                    mock.patch.object(RESOLVER_MODULE, "MAX_CANDIDATE_VISITS", 100),
                ]
                if reverse:
                    patches.append(
                        mock.patch.object(
                            RESOLVER_MODULE.os,
                            "scandir",
                            side_effect=ReversedScandir,
                        )
                    )
                with patches[0], patches[1]:
                    if reverse:
                        with patches[2]:
                            rows = RESOLVER_MODULE.cache_candidates(
                                [repository],
                                ["agents/*/*.jar"],
                                "maven_cache",
                                omissions,
                            )
                    else:
                        rows = RESOLVER_MODULE.cache_candidates(
                            [repository],
                            ["agents/*/*.jar"],
                            "maven_cache",
                            omissions,
                        )
                return (
                    [str(row.path.relative_to(repository)) for row in rows],
                    [row.as_dict() for row in omissions],
                )

            normal = discover(reverse=False)
            reversed_order = discover(reverse=True)
            self.assertEqual(normal, reversed_order)
            self.assertEqual(
                normal[0],
                [
                    "agents/1.0.0/opentelemetry-javaagent-1.0.0.jar",
                    "agents/2.0.0/opentelemetry-javaagent-2.0.0.jar",
                ],
            )
            self.assertEqual(
                normal[1][0]["reason"],
                "maven_cache_candidate_limit",
            )

    def test_config_file_count_bound_is_incomplete_in_both_walkers(self) -> None:
        for portable in (False, True):
            with (
                self.subTest(portable=portable),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                project = root / "project"
                project.mkdir()
                valid = root / "opentelemetry-javaagent-1.2.3.jar"
                write_agent(valid, version="1.2.3")
                (project / "00.conf").write_text("# first\n", encoding="utf-8")
                (project / "01.conf").write_text(
                    f'JAVA_TOOL_OPTIONS="-javaagent:{valid}"\n',
                    encoding="utf-8",
                )

                with mock.patch.object(
                    RESOLVER_MODULE,
                    "MAX_CONFIG_FILES",
                    1,
                ):
                    result = self.resolve_in_process(
                        project,
                        portable=portable,
                    )

                self.assertEqual(result["status"], "incomplete")
                self.assertFalse(result["complete"])
                self.assertIsNone(result["selected"])
                self.assertEqual(result["searched"]["config_files_read"], 1)
                omission = bounded_omission(result, "config_file_count_limit")
                self.assertEqual(omission["omitted_count"], 1)
                self.assertTrue(omission["count_is_lower_bound"])
                self.assertEqual(omission["limit"], 1)

    def test_config_entry_visit_bound_is_incomplete_in_both_walkers(self) -> None:
        for portable in (False, True):
            with (
                self.subTest(portable=portable),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                project = root / "project"
                project.mkdir()
                valid = root / "opentelemetry-javaagent-1.2.3.jar"
                write_agent(valid, version="1.2.3")
                for index in range(3):
                    (project / f"irrelevant-{index}").write_text(
                        "not configuration\n",
                        encoding="utf-8",
                    )

                with mock.patch.object(
                    RESOLVER_MODULE,
                    "MAX_CONFIG_ENTRY_VISITS",
                    2,
                ):
                    result = self.resolve_in_process(
                        project,
                        candidates=(valid,),
                        portable=portable,
                    )

                self.assertEqual(result["status"], "incomplete")
                self.assertFalse(result["complete"])
                self.assertIsNone(result["selected"])
                omission = bounded_omission(
                    result,
                    "config_entry_visit_limit",
                )
                self.assertEqual(omission["limit"], 2)
                self.assertTrue(omission["count_is_lower_bound"])

    def test_descriptor_config_depth_bound_is_incomplete(self) -> None:
        if os.scandir not in os.supports_fd:
            self.skipTest("requires descriptor-backed directory scanning")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            valid = root / "opentelemetry-javaagent-1.2.3.jar"
            write_agent(valid, version="1.2.3")
            current = project
            for index in range(3):
                current = current / f"level-{index}"
                current.mkdir()

            with mock.patch.object(
                RESOLVER_MODULE,
                "MAX_CONFIG_DIRECTORY_DEPTH",
                2,
            ):
                result = self.resolve_in_process(
                    project,
                    candidates=(valid,),
                )

            self.assertEqual(result["status"], "incomplete")
            self.assertIsNone(result["selected"])
            omission = bounded_omission(
                result,
                "config_directory_depth_limit",
            )
            self.assertEqual(omission["limit"], 2)

    def test_portable_config_depth_bound_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            valid = root / "opentelemetry-javaagent-1.2.3.jar"
            write_agent(valid, version="1.2.3")
            current = project
            for index in range(3):
                current = current / f"level-{index}"
                current.mkdir()

            with mock.patch.object(
                RESOLVER_MODULE,
                "MAX_CONFIG_DIRECTORY_DEPTH",
                2,
            ):
                result = self.resolve_in_process(
                    project,
                    candidates=(valid,),
                    portable=True,
                )

            self.assertEqual(result["status"], "incomplete")
            self.assertIsNone(result["selected"])
            omission = bounded_omission(
                result,
                "config_directory_depth_limit",
            )
            self.assertEqual(omission["limit"], 2)

    def test_oversized_config_is_incomplete_in_both_walkers(self) -> None:
        for portable in (False, True):
            with (
                self.subTest(portable=portable),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                project = root / "project"
                project.mkdir()
                valid = root / "opentelemetry-javaagent-1.2.3.jar"
                write_agent(valid, version="1.2.3")
                (project / "runtime.conf").write_text(
                    "#" * 80 + f'\nJAVA_TOOL_OPTIONS="-javaagent:{valid}"\n',
                    encoding="utf-8",
                )

                with mock.patch.object(
                    RESOLVER_MODULE,
                    "MAX_CONFIG_BYTES",
                    64,
                ):
                    result = self.resolve_in_process(
                        project,
                        portable=portable,
                    )

                self.assertEqual(result["status"], "incomplete")
                self.assertFalse(result["complete"])
                self.assertIsNone(result["selected"])
                omission = bounded_omission(result, "config_file_size_limit")
                self.assertEqual(omission["omitted_count"], 1)
                self.assertFalse(omission["count_is_lower_bound"])
                self.assertEqual(omission["limit"], 64)
                self.assertEqual(omission["limit_unit"], "bytes")

    def test_unreadable_source_selected_agent_config_never_falls_back_to_cache(
        self,
    ) -> None:
        for portable in (False, True):
            with (
                self.subTest(portable=portable),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                project = root / "project"
                project.mkdir()
                selected_by_source = root / "opentelemetry-javaagent-1.2.3.jar"
                write_agent(selected_by_source, version="1.2.3")
                config = project / "Dockerfile"
                config.write_text(
                    f'ENV JAVA_TOOL_OPTIONS="-javaagent:{selected_by_source}"\n',
                    encoding="utf-8",
                )
                repository = root / "m2"
                cache_fallback = (
                    repository
                    / "io/opentelemetry/javaagent/opentelemetry-javaagent/9.9.9"
                    / "opentelemetry-javaagent-9.9.9.jar"
                )
                write_agent(cache_fallback, version="9.9.9")
                config.chmod(0)
                try:
                    result = self.resolve_in_process(
                        project,
                        maven_repo=repository,
                        portable=portable,
                    )
                finally:
                    config.chmod(0o600)

                self.assertEqual(result["status"], "incomplete")
                self.assertFalse(result["complete"])
                self.assertIsNone(result["selected"])
                self.assertEqual(result["searched"]["valid_candidates"], 1)
                omission = bounded_omission(
                    result,
                    "config_file_open_error",
                )
                self.assertTrue(omission["count_is_lower_bound"])

    def test_config_read_error_is_incomplete_in_both_walkers(self) -> None:
        for portable in (False, True):
            with (
                self.subTest(portable=portable),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                project = root / "project"
                project.mkdir()
                (project / "Dockerfile").write_text(
                    'ENV JAVA_TOOL_OPTIONS="-javaagent:hidden.jar"\n',
                    encoding="utf-8",
                )
                real_read = RESOLVER_MODULE.read_bounded_descriptor
                failed = False

                def fail_first_read(descriptor, maximum):
                    nonlocal failed
                    if not failed:
                        failed = True
                        raise OSError("read failed")
                    return real_read(descriptor, maximum)

                with mock.patch.object(
                    RESOLVER_MODULE,
                    "read_bounded_descriptor",
                    side_effect=fail_first_read,
                ):
                    result = self.resolve_in_process(
                        project,
                        portable=portable,
                    )

                self.assertTrue(failed)
                self.assertEqual(result["status"], "incomplete")
                self.assertIsNone(result["selected"])
                bounded_omission(result, "config_file_read_error")

    def test_descriptor_config_discovery_errors_are_bounded_omissions(self) -> None:
        cases = (
            ("list", "config_directory_list_error"),
            ("stat", "config_entry_stat_error"),
            ("child", "config_child_directory_error"),
        )
        for failure, reason in cases:
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                project = root / "project"
                nested = project / "runtime"
                nested.mkdir(parents=True)
                (nested / "Dockerfile").write_text(
                    'ENV JAVA_TOOL_OPTIONS="-javaagent:hidden.jar"\n',
                    encoding="utf-8",
                )
                if failure == "list":
                    patcher = mock.patch.object(
                        RESOLVER_MODULE,
                        "bounded_sorted_names",
                        side_effect=PermissionError("directory unreadable"),
                    )
                elif failure == "stat":
                    real_stat = RESOLVER_MODULE.os.stat

                    def fail_stat(path, *args, **kwargs):
                        if path == "runtime" and kwargs.get("dir_fd") is not None:
                            raise PermissionError("entry stat failed")
                        return real_stat(path, *args, **kwargs)

                    patcher = mock.patch.object(
                        RESOLVER_MODULE.os,
                        "stat",
                        side_effect=fail_stat,
                    )
                else:
                    real_open = RESOLVER_MODULE.os.open

                    def fail_child(path, flags, mode=0o777, *, dir_fd=None):
                        if path == "runtime" and dir_fd is not None:
                            raise PermissionError("child open failed")
                        if dir_fd is None:
                            return real_open(path, flags, mode)
                        return real_open(path, flags, mode, dir_fd=dir_fd)

                    patcher = mock.patch.object(
                        RESOLVER_MODULE.os,
                        "open",
                        side_effect=fail_child,
                    )

                project_descriptor = os.open(
                    project,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                omissions = []
                try:
                    with patcher:
                        snapshots = RESOLVER_MODULE.descriptor_config_snapshots(
                            project,
                            project_descriptor,
                            RESOLVER_MODULE.file_identity(os.fstat(project_descriptor)),
                            omissions,
                        )
                finally:
                    os.close(project_descriptor)

                self.assertEqual(snapshots, [])
                self.assertIn(reason, {row.reason for row in omissions})

    def test_portable_walk_and_identity_errors_are_bounded_omissions(self) -> None:
        for failure, reason in (
            ("walk", "config_walk_error"),
            ("identity", "config_identity_chain_error"),
        ):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as directory,
            ):
                project = Path(directory) / "project"
                project.mkdir()
                (project / "Dockerfile").write_text(
                    'ENV JAVA_TOOL_OPTIONS="-javaagent:hidden.jar"\n',
                    encoding="utf-8",
                )
                if failure == "walk":
                    patcher = mock.patch.object(
                        RESOLVER_MODULE,
                        "bounded_sorted_names",
                        side_effect=PermissionError("walk failed"),
                    )
                else:
                    patcher = mock.patch.object(
                        RESOLVER_MODULE,
                        "portable_config_chain",
                        side_effect=OSError("identity changed"),
                    )

                with (
                    patcher,
                    mock.patch.object(
                        RESOLVER_MODULE,
                        "descriptor_operations_supported",
                        return_value=False,
                    ),
                ):
                    snapshots = RESOLVER_MODULE.portable_config_snapshots(
                        project,
                        RESOLVER_MODULE.file_identity(os.lstat(project)),
                        omissions := [],
                    )

                self.assertEqual(snapshots, [])
                self.assertIn(reason, {row.reason for row in omissions})

    def test_candidate_controlled_zip_failures_are_rejected_and_scan_continues(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            encrypted = root / "encrypted-agent.jar"
            unsupported = root / "unsupported-compression-agent.jar"
            malformed = root / "malformed-agent.jar"
            valid = root / "opentelemetry-javaagent-1.2.3.jar"
            write_agent(encrypted, version="1.2.3")
            mutate_zip_headers(encrypted, encrypted=True)
            write_agent(unsupported, version="1.2.3")
            mutate_zip_headers(unsupported, compression=99)
            malformed.write_bytes(b"not-a-zip")
            write_agent(valid, version="1.2.3")
            candidates = (encrypted, unsupported, malformed, valid)
            extra = tuple(
                argument
                for candidate in candidates
                for argument in ("--candidate", str(candidate))
            )

            result = self.run_resolver(
                project,
                maven_repo=root / "missing-m2",
                extra=extra,
                unset_env=tuple(
                    RESOLVER_MODULE.ENV_AGENT_PATHS
                    + RESOLVER_MODULE.ENV_AGENT_OPTIONS
                ),
            )

            self.assertEqual(result["status"], "resolved")
            self.assertTrue(result["complete"])
            self.assertEqual(result["selected"]["path"], str(valid.resolve()))
            rejected = {row["path"]: row["reason"] for row in result["rejected"]}
            self.assertIn("encrypted", rejected[str(encrypted)])
            self.assertIn("not supported", rejected[str(unsupported)])
            self.assertTrue(rejected[str(malformed)].startswith("invalid-jar:"))

    def test_fifty_thousand_entry_zip_is_rejected_before_metadata_materialization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = (
                Path(directory) / "opentelemetry-javaagent-1.2.3.jar"
            )
            write_eocd_only_candidate(candidate, entries=50_001)

            selected, error = RESOLVER_MODULE.validate_candidate(candidate)

            self.assertIsNone(selected)
            self.assertIn("invalid-jar", error or "")
            self.assertIn("entry count 50001", error or "")
            self.assertIn(
                str(RESOLVER_MODULE.MAX_ZIP_ENTRIES),
                error or "",
            )

    def test_zip_central_directory_byte_budget_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = (
                Path(directory) / "opentelemetry-javaagent-1.2.3.jar"
            )
            write_eocd_only_candidate(
                candidate,
                entries=1,
                central_size=RESOLVER_MODULE.MAX_ZIP_CENTRAL_DIRECTORY_BYTES
                + 1,
            )

            selected, error = RESOLVER_MODULE.validate_candidate(candidate)

            self.assertIsNone(selected)
            self.assertIn("invalid-jar", error or "")
            self.assertIn("central directory exceeds", error or "")

    def test_actual_zip_entry_count_is_bounded_before_metadata_materialization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = (
                Path(directory) / "opentelemetry-javaagent-1.2.3.jar"
            )
            write_central_directory_candidate(
                candidate,
                actual_entries=4,
                advertised_entries=1,
            )

            with (
                mock.patch.object(RESOLVER_MODULE, "MAX_ZIP_ENTRIES", 3),
                mock.patch.object(
                    RESOLVER_MODULE.zipfile,
                    "ZipFile",
                    side_effect=AssertionError("metadata must not be materialized"),
                ),
            ):
                selected, error = RESOLVER_MODULE.validate_candidate(candidate)

            self.assertIsNone(selected)
            self.assertIn("invalid-jar", error or "")
            self.assertIn("entry count exceeds 3", error or "")

    def test_actual_zip_entry_count_must_match_eocd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = (
                Path(directory) / "opentelemetry-javaagent-1.2.3.jar"
            )
            write_central_directory_candidate(
                candidate,
                actual_entries=2,
                advertised_entries=1,
            )

            with mock.patch.object(
                RESOLVER_MODULE.zipfile,
                "ZipFile",
                side_effect=AssertionError("metadata must not be materialized"),
            ):
                selected, error = RESOLVER_MODULE.validate_candidate(candidate)

            self.assertIsNone(selected)
            self.assertIn("invalid-jar", error or "")
            self.assertIn("entry count does not match", error or "")

    def test_zip_rejection_does_not_swallow_process_control_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "opentelemetry-javaagent-1.2.3.jar"
            write_agent(candidate, version="1.2.3")

            with (
                mock.patch.object(
                    RESOLVER_MODULE.zipfile.ZipFile,
                    "read",
                    side_effect=KeyboardInterrupt,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                RESOLVER_MODULE.validate_candidate(candidate)

    def test_equal_size_equal_mtime_path_swap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "opentelemetry-javaagent-1.2.3.jar"
            replacement = root / "replacement.jar"
            write_agent(candidate, version="1.2.3")
            write_agent(
                replacement,
                version="1.2.3",
                premain="x" * len(UPSTREAM_PREMAIN),
            )
            before = candidate.stat()
            self.assertEqual(candidate.stat().st_size, replacement.stat().st_size)
            os.utime(
                replacement,
                ns=(before.st_atime_ns, before.st_mtime_ns),
            )
            saved = root / "validated-original.jar"
            original_match = RESOLVER_MODULE.candidate_namespace_matches
            swapped = False

            def swap_then_match(path, expected_file, parents):
                nonlocal swapped
                if not swapped:
                    candidate.rename(saved)
                    replacement.replace(candidate)
                    os.utime(
                        candidate,
                        ns=(before.st_atime_ns, before.st_mtime_ns),
                    )
                    swapped = True
                return original_match(path, expected_file, parents)

            with mock.patch.object(
                RESOLVER_MODULE,
                "candidate_namespace_matches",
                side_effect=swap_then_match,
            ):
                selected, error = RESOLVER_MODULE.validate_candidate(candidate)

            self.assertTrue(swapped)
            self.assertIsNone(selected)
            self.assertEqual(error, "jar-path-changed-during-validation")

    def test_generated_pre_attach_recheck_rejects_changed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            repository = root / "m2"
            candidate = (
                repository
                / "io/opentelemetry/javaagent/opentelemetry-javaagent/1.2.3"
                / "opentelemetry-javaagent-1.2.3.jar"
            )
            write_agent(candidate, version="1.2.3")
            first = self.run_resolver(project, maven_repo=repository)
            recheck = first["selected"]["pre_attach_recheck_argv"]

            with zipfile.ZipFile(candidate, "a") as archive:
                archive.writestr("changed-marker", "different bytes")
            completed = subprocess.run(
                recheck,
                check=False,
                capture_output=True,
                text=True,
            )
            second = json.loads(completed.stdout)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(second["status"], "unresolved")
            self.assertEqual(
                second["claims"]["verification_pin_match"], "mismatch"
            )

    def test_generated_pre_attach_recheck_ignores_unrelated_cache_limits(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            repository = root / "m2"
            candidate = (
                repository
                / "io/opentelemetry/javaagent/opentelemetry-javaagent/1.2.3"
                / "opentelemetry-javaagent-1.2.3.jar"
            )
            write_agent(candidate, version="1.2.3")
            first = self.run_resolver(project, maven_repo=repository)
            recheck = first["selected"]["pre_attach_recheck_argv"]

            hostile_home = root / "hostile-home"
            hostile_cache = hostile_home / ".m2" / "repository"
            for index in range(RESOLVER_MODULE.MAX_CANDIDATE_VISITS + 1):
                (hostile_cache / f"irrelevant-{index:04d}").mkdir(
                    parents=True,
                    exist_ok=True,
                )
            environment = os.environ.copy()
            environment["HOME"] = str(hostile_home)
            completed = subprocess.run(
                recheck,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            second = json.loads(completed.stdout)

        self.assertIn("--exact-candidate-only", recheck)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(second["status"], "resolved")
        self.assertTrue(second["complete"])
        self.assertEqual(second["bounded_discovery"]["omissions"], [])
        self.assertEqual(second["searched"]["maven_roots"], [])
        self.assertEqual(second["searched"]["gradle_roots"], [])
        self.assertEqual(
            second["selected"]["verification_pin"],
            first["selected"]["verification_pin"],
        )

    def test_symlinked_dockerfile_cannot_disclose_outside_agent_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            private_path = "/PRIVATE_HOST_VALUE_8472.jar"
            outside = root / "outside-Dockerfile"
            outside.write_text(
                f'ENV JAVA_TOOL_OPTIONS="-javaagent:{private_path}"\n',
                encoding="utf-8",
            )
            (project / "Dockerfile").symlink_to(outside)

            result = self.run_resolver(
                project,
                maven_repo=root / "missing-m2",
                unset_env=tuple(
                    RESOLVER_MODULE.ENV_AGENT_PATHS
                    + RESOLVER_MODULE.ENV_AGENT_OPTIONS
                ),
            )

            serialized = json.dumps(result)
            self.assertNotIn(private_path, serialized)
            self.assertNotIn("Dockerfile", result["expected"]["evidence"])

    def test_equal_size_equal_mtime_config_swap_is_not_retained(self) -> None:
        if not RESOLVER_MODULE.descriptor_operations_supported():
            self.skipTest("requires descriptor-relative no-follow operations")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            config = project / "Dockerfile"
            private_path = "/PRIVATE_HOST_RACE_VALUE_9265.jar"
            private_text = (
                f'ENV JAVA_TOOL_OPTIONS="-javaagent:{private_path}"\n'
            )
            safe_text = "#" * (len(private_text) - 1) + "\n"
            config.write_text(safe_text, encoding="utf-8")
            replacement = root / "replacement-Dockerfile"
            replacement.write_text(private_text, encoding="utf-8")
            before = config.stat()
            os.utime(
                replacement,
                ns=(before.st_atime_ns, before.st_mtime_ns),
            )
            self.assertEqual(config.stat().st_size, replacement.stat().st_size)
            self.assertEqual(
                config.stat().st_mtime_ns,
                replacement.stat().st_mtime_ns,
            )
            saved = project / "original-Dockerfile"
            real_open = os.open
            swapped = False

            def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if path == "Dockerfile" and dir_fd is not None and not swapped:
                    config.rename(saved)
                    replacement.replace(config)
                    os.utime(
                        config,
                        ns=(before.st_atime_ns, before.st_mtime_ns),
                    )
                    swapped = True
                return real_open(path, flags, mode, dir_fd=dir_fd)

            boundary = RESOLVER_MODULE.authenticate_directory(project)
            try:
                with (
                    mock.patch.object(
                        RESOLVER_MODULE,
                        "descriptor_operations_supported",
                        return_value=True,
                    ),
                    mock.patch.object(
                        RESOLVER_MODULE.os,
                        "open",
                        side_effect=swap_before_open,
                    ),
                ):
                    snapshots = RESOLVER_MODULE.collect_config_snapshots(
                        boundary.path,
                        root_descriptor=boundary.descriptor,
                        root_identity=boundary.identity,
                    )
            finally:
                boundary.close()

            self.assertTrue(swapped)
            self.assertNotIn(
                private_path,
                "\n".join(snapshot.text for snapshot in snapshots),
            )

    def test_project_configured_candidate_wins_and_can_match_declared_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            configured = project / "tools" / "otel-agent-1.9.0.jar"
            write_agent(configured, version="1.9.0")
            (project / "Dockerfile").write_text(
                f'ENV JAVA_TOOL_OPTIONS="-javaagent:{configured}"\n',
                encoding="utf-8",
            )
            repository = root / "m2"
            cached = (
                repository
                / "io/opentelemetry/javaagent/opentelemetry-javaagent/2.0.0"
                / "opentelemetry-javaagent-2.0.0.jar"
            )
            write_agent(cached, version="2.0.0")

            result = self.run_resolver(
                project,
                maven_repo=repository,
                extra=("--expected-version", "1.9.0"),
            )

            self.assertEqual(result["selected"]["path"], str(configured.resolve()))
            self.assertEqual(result["selected"]["source"], "project_config")
            self.assertEqual(
                result["claims"]["repository_configuration_match"],
                "exact",
            )
            self.assertEqual(result["claims"]["verification_execution"], "not_run")
            self.assertEqual(result["claims"]["production_parity"], "not_proven")
            self.assertEqual(result["production_parity"]["status"], "not_proven")

    def test_expected_version_selects_exact_older_cache_pin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            repository = root / "m2"
            expected = (
                repository
                / "com/splunk/splunk-otel-javaagent/2.26.0"
                / "splunk-otel-javaagent-2.26.0.jar"
            )
            newer = (
                repository
                / "com/splunk/splunk-otel-javaagent/2.27.0"
                / "splunk-otel-javaagent-2.27.0.jar"
            )
            write_agent(
                expected,
                version="splunk-2.26.0-otel-2.26.0",
                premain=SPLUNK_PREMAIN,
            )
            write_agent(
                newer,
                version="splunk-2.27.0-otel-2.27.0",
                premain=SPLUNK_PREMAIN,
            )

            result = self.run_resolver(
                project,
                maven_repo=repository,
                extra=(
                    "--expected-family",
                    "splunk",
                    "--expected-version",
                    "2.26.0",
                ),
            )

            self.assertEqual(result["selected"]["path"], str(expected.resolve()))
            self.assertEqual(result["selected"]["selection_reason"], "exact_config_pin")
            self.assertEqual(
                result["claims"]["repository_configuration_match"], "exact"
            )
            self.assertEqual(result["claims"]["production_parity"], "not_proven")

    def test_expected_version_precedes_cross_family_source_rank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            upstream = project / "opentelemetry-javaagent-1.0.0.jar"
            write_agent(upstream, version="1.0.0")
            expected = (
                root
                / "m2/com/splunk/splunk-otel-javaagent/2.0.0"
                / "splunk-otel-javaagent-2.0.0.jar"
            )
            write_agent(
                expected,
                version="splunk-2.0.0-otel-2.0.0",
                premain=SPLUNK_PREMAIN,
            )

            result = self.run_resolver(
                project,
                maven_repo=root / "m2",
                extra=(
                    "--candidate",
                    str(upstream),
                    "--expected-version",
                    "2.0.0",
                ),
                unset_env=tuple(
                    RESOLVER_MODULE.ENV_AGENT_PATHS
                    + RESOLVER_MODULE.ENV_AGENT_OPTIONS
                ),
            )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["selected"]["path"], str(expected.resolve()))
        self.assertEqual(result["selected"]["family"], "splunk")
        self.assertEqual(result["selected"]["artifact_version"], "2.0.0")
        self.assertEqual(result["searched"]["valid_candidates"], 2)
        self.assertEqual(
            result["claims"]["repository_configuration_match"], "exact"
        )

    def test_expected_digest_precedes_cross_family_source_rank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            upstream = project / "opentelemetry-javaagent-1.0.0.jar"
            write_agent(upstream, version="1.0.0")
            expected = (
                root
                / "m2/com/splunk/splunk-otel-javaagent/2.0.0"
                / "splunk-otel-javaagent-2.0.0.jar"
            )
            write_agent(
                expected,
                version="splunk-2.0.0-otel-2.0.0",
                premain=SPLUNK_PREMAIN,
            )
            expected_sha256 = hashlib.sha256(expected.read_bytes()).hexdigest()

            result = self.run_resolver(
                project,
                maven_repo=root / "m2",
                extra=(
                    "--candidate",
                    str(upstream),
                    "--expected-sha256",
                    expected_sha256,
                ),
                unset_env=tuple(
                    RESOLVER_MODULE.ENV_AGENT_PATHS
                    + RESOLVER_MODULE.ENV_AGENT_OPTIONS
                ),
            )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["selected"]["path"], str(expected.resolve()))
        self.assertEqual(result["selected"]["family"], "splunk")
        self.assertEqual(result["searched"]["valid_candidates"], 2)
        self.assertEqual(
            result["claims"]["verification_pin_match"], "exact"
        )

    def test_signalfx_base_image_selects_splunk_family_for_generic_container_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "Dockerfile").write_text(
                "FROM registry.example/observability/signalfx-base:1.2.3\n"
                "ENV OTEL_JAVAAGENT_PATH=/opt/opentelemetry-javaagent.jar\n",
                encoding="utf-8",
            )
            repository = root / "m2"
            splunk = (
                repository
                / "com/splunk/splunk-otel-javaagent/2.27.0"
                / "splunk-otel-javaagent-2.27.0.jar"
            )
            upstream = (
                repository
                / "io/opentelemetry/javaagent/opentelemetry-javaagent/2.28.0"
                / "opentelemetry-javaagent-2.28.0.jar"
            )
            write_agent(
                splunk,
                version="splunk-2.27.0-otel-2.27.0",
                premain=SPLUNK_PREMAIN,
            )
            write_agent(upstream, version="2.28.0")

            result = self.run_resolver(project, maven_repo=repository)

            self.assertEqual(result["status"], "resolved")
            self.assertEqual(result["expected"]["family"], "splunk")
            self.assertEqual(result["expected"]["source"], "repository_config")
            self.assertEqual(result["selected"]["path"], str(splunk.resolve()))
            self.assertEqual(
                result["claims"]["repository_configuration_match"], "family_only"
            )

    def test_rejects_jar_without_premain_class(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            repository = root / "m2"
            invalid = (
                repository
                / "io/opentelemetry/javaagent/opentelemetry-javaagent/2.0.0"
                / "opentelemetry-javaagent-2.0.0.jar"
            )
            write_agent(invalid, version="2.0.0", premain="")

            result = self.run_resolver(project, maven_repo=repository)

            self.assertEqual(result["status"], "unresolved")
            self.assertIsNone(result["selected"])
            self.assertTrue(
                any(
                    row["reason"] == "missing-Premain-Class"
                    for row in result["rejected"]
                )
            )
            self.assertNotIn("provide a pinned", result["message"].lower())

    def test_rejects_trusted_filename_with_unrecognized_premain_class(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            repository = root / "m2"
            malicious = (
                repository
                / "io/opentelemetry/javaagent/opentelemetry-javaagent/2.3.0"
                / "opentelemetry-javaagent-2.3.0.jar"
            )
            write_agent(
                malicious,
                version="2.3.0",
                premain="example.malicious.Agent",
            )

            result = self.run_resolver(project, maven_repo=repository)

            self.assertEqual(result["status"], "unresolved")
            self.assertIsNone(result["selected"])
            self.assertTrue(
                any(
                    row["path"] == str(malicious)
                    and row["reason"] == "unrecognized-Premain-Class"
                    for row in result["rejected"]
                )
            )

    def test_rejects_recognized_premain_from_wrong_agent_family(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            repository = root / "m2"
            disguised = (
                repository
                / "com/splunk/splunk-otel-javaagent/2.3.0"
                / "splunk-otel-javaagent-2.3.0.jar"
            )
            write_agent(
                disguised,
                version="splunk-2.3.0-otel-2.3.0",
                premain=UPSTREAM_PREMAIN,
            )

            result = self.run_resolver(project, maven_repo=repository)

            self.assertEqual(result["status"], "unresolved")
            self.assertIsNone(result["selected"])
            self.assertTrue(
                any(
                    row["path"] == str(disguised)
                    and row["reason"]
                    == "Premain-Class-does-not-match-splunk-agent-family"
                    for row in result["rejected"]
                )
            )

    def test_explicit_filename_family_mismatch_cannot_win_version_ranking(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            agents = project / ".observe" / "eval-java-agents"
            upstream = agents / "opentelemetry-javaagent-2.1.0+build.7.jar"
            prerelease = agents / "opentelemetry-javaagent-2.1.0-beta.2.jar"
            malicious = agents / "opentelemetry-javaagent-9.0.0.jar"
            wrong_family = agents / "splunk-otel-javaagent-8.0.0.jar"
            write_agent(upstream, version="2.1.0+build.7")
            write_agent(prerelease, version="2.1.0-beta.2")
            write_agent(
                malicious,
                version="9.0.0",
                premain="example.malicious.Agent",
            )
            write_agent(wrong_family, version="8.0.0")
            candidates = (upstream, prerelease, malicious, wrong_family)

            result = self.run_resolver(
                project,
                maven_repo=root / "missing-m2",
                extra=tuple(
                    argument
                    for candidate in candidates
                    for argument in ("--candidate", str(candidate))
                ),
                unset_env=tuple(
                    RESOLVER_MODULE.ENV_AGENT_PATHS
                    + RESOLVER_MODULE.ENV_AGENT_OPTIONS
                ),
            )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["selected"]["path"], str(upstream.resolve()))
        self.assertEqual(result["selected"]["artifact_version"], "2.1.0+build.7")
        rejected = {row["path"]: row["reason"] for row in result["rejected"]}
        self.assertEqual(rejected[str(malicious)], "unrecognized-Premain-Class")
        self.assertEqual(
            rejected[str(wrong_family)],
            "Premain-Class-does-not-match-splunk-agent-family",
        )

    def test_selects_exact_prerelease_and_preserves_build_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            repository = root / "m2"
            alpha = (
                repository
                / "io/opentelemetry/javaagent/opentelemetry-javaagent/2.3.0-alpha+build.1"
                / "opentelemetry-javaagent-2.3.0-alpha+build.1.jar"
            )
            beta = (
                repository
                / "io/opentelemetry/javaagent/opentelemetry-javaagent/2.3.0-beta+build.2"
                / "opentelemetry-javaagent-2.3.0-beta+build.2.jar"
            )
            write_agent(alpha, version="2.3.0-alpha+build.1")
            write_agent(beta, version="2.3.0-beta+build.2")

            result = self.run_resolver(
                project,
                maven_repo=repository,
                extra=("--expected-version", "2.3.0-beta+build.2"),
            )

            self.assertEqual(result["status"], "resolved")
            self.assertEqual(result["selected"]["path"], str(beta.resolve()))
            self.assertEqual(
                result["selected"]["artifact_version"],
                "2.3.0-beta+build.2",
            )
            self.assertEqual(
                result["claims"]["repository_configuration_match"],
                "exact",
            )

    def test_expected_beta_rejects_alpha_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            repository = root / "m2"
            alpha = (
                repository
                / "io/opentelemetry/javaagent/opentelemetry-javaagent/2.3.0-alpha"
                / "opentelemetry-javaagent-2.3.0-alpha.jar"
            )
            write_agent(alpha, version="2.3.0-alpha")

            result = self.run_resolver(
                project,
                maven_repo=repository,
                extra=("--expected-version", "2.3.0-beta"),
            )

            self.assertEqual(result["status"], "unresolved")
            self.assertIsNone(result["selected"])
            self.assertEqual(
                result["claims"]["repository_configuration_match"],
                "mismatch",
            )
            self.assertIn(
                "matches the required repository version 2.3.0-beta",
                result["message"],
            )

    def test_unresolved_config_variable_still_constrains_family_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            variable = "OBSTUDIO_TEST_UNSET_AGENT_DIR"
            (project / "Dockerfile").write_text(
                'ENV JAVA_TOOL_OPTIONS="-javaagent:${'
                f"{variable}"
                '}/opentelemetry-javaagent-2.3.0.jar"\n',
                encoding="utf-8",
            )
            repository = root / "m2"
            splunk = (
                repository
                / "com/splunk/splunk-otel-javaagent/2.3.0"
                / "splunk-otel-javaagent-2.3.0.jar"
            )
            write_agent(
                splunk,
                version="splunk-2.3.0-otel-2.3.0",
                premain=SPLUNK_PREMAIN,
            )

            result = self.run_resolver(
                project,
                maven_repo=repository,
                unset_env=(variable,),
            )

            self.assertEqual(result["status"], "unresolved")
            self.assertIsNone(result["selected"])
            self.assertEqual(result["expected"]["family"], "opentelemetry")
            self.assertEqual(result["expected"]["version"], "2.3.0")
            self.assertTrue(
                any(
                    "${" + variable + "}" in row["path"]
                    and row["source"] == "project_config"
                    for row in result["rejected"]
                )
            )

    def test_configured_family_conflict_requires_cli_disambiguation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "Dockerfile").write_text(
                'ENV JAVA_TOOL_OPTIONS="'
                "-javaagent:/opt/splunk-otel-javaagent-2.3.0.jar "
                '-javaagent:/opt/opentelemetry-javaagent-2.3.0.jar"\n',
                encoding="utf-8",
            )
            repository = root / "m2"
            splunk = (
                repository
                / "com/splunk/splunk-otel-javaagent/2.3.0"
                / "splunk-otel-javaagent-2.3.0.jar"
            )
            write_agent(
                splunk,
                version="splunk-2.3.0-otel-2.3.0",
                premain=SPLUNK_PREMAIN,
            )

            ambiguous = self.run_resolver(project, maven_repo=repository)

            self.assertEqual(ambiguous["status"], "ambiguous")
            self.assertIsNone(ambiguous["selected"])
            self.assertEqual(
                ambiguous["expected"]["unresolved_conflicts"],
                ["repository runtime configuration names multiple agent families"],
            )

            resolved = self.run_resolver(
                project,
                maven_repo=repository,
                extra=("--expected-family", "splunk"),
            )

            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["selected"]["family"], "splunk")
            self.assertEqual(resolved["expected"]["unresolved_conflicts"], [])

    def test_configured_version_conflict_requires_cli_disambiguation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "Dockerfile").write_text(
                'ENV JAVA_TOOL_OPTIONS="'
                "-javaagent:/opt/opentelemetry-javaagent-2.2.0.jar "
                '-javaagent:/opt/opentelemetry-javaagent-2.3.0.jar"\n',
                encoding="utf-8",
            )
            repository = root / "m2"
            upstream = (
                repository
                / "io/opentelemetry/javaagent/opentelemetry-javaagent/2.3.0"
                / "opentelemetry-javaagent-2.3.0.jar"
            )
            write_agent(upstream, version="2.3.0")

            ambiguous = self.run_resolver(project, maven_repo=repository)

            self.assertEqual(ambiguous["status"], "ambiguous")
            self.assertIsNone(ambiguous["selected"])
            self.assertEqual(
                ambiguous["expected"]["unresolved_conflicts"],
                ["repository runtime configuration names multiple agent versions"],
            )

            resolved = self.run_resolver(
                project,
                maven_repo=repository,
                extra=("--expected-version", "2.3.0"),
            )

            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["selected"]["artifact_version"], "2.3.0")
            self.assertEqual(resolved["expected"]["unresolved_conflicts"], [])

    def test_relative_output_is_project_anchored_and_replaces_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            project = base / "project"
            project.mkdir()
            repository = base / "m2"
            output = project / ".observe" / "java-agent-resolution.json"
            output.parent.mkdir()
            output.write_text("old\n", encoding="utf-8")
            unrelated_cwd = base / "cwd"
            unrelated_cwd.mkdir()

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RESOLVER),
                    "--project",
                    str(project),
                    "--maven-repo",
                    str(repository),
                    "--gradle-cache",
                    str(base / "missing-gradle"),
                    "--output",
                    ".observe/java-agent-resolution.json",
                ],
                cwd=unrelated_cwd,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), str(output))
            self.assertEqual(json.loads(output.read_text())["project"], str(project))
            self.assertFalse((unrelated_cwd / ".observe").exists())

    def test_relative_output_rejects_project_local_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            project = base / "project"
            project.mkdir()
            outside = base / "outside"
            outside.mkdir()
            (project / ".observe").symlink_to(outside, target_is_directory=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RESOLVER),
                    "--project",
                    str(project),
                    "--maven-repo",
                    str(base / "m2"),
                    "--gradle-cache",
                    str(base / "gradle"),
                    "--output",
                    ".observe/java-agent-resolution.json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("symlink", completed.stderr.lower())
            self.assertFalse((outside / "java-agent-resolution.json").exists())

    def test_output_rejects_symlink_target_and_project_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            project = base / "project"
            project.mkdir()
            outside = base / "outside.json"
            outside.write_text("must survive\n", encoding="utf-8")
            target = project / "java-agent-resolution.json"
            target.symlink_to(outside)
            common = [
                sys.executable,
                str(RESOLVER),
                "--maven-repo",
                str(base / "m2"),
                "--gradle-cache",
                str(base / "gradle"),
            ]

            target_result = subprocess.run(
                [
                    *common,
                    "--project",
                    str(project),
                    "--output",
                    "java-agent-resolution.json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            project_link = base / "project-link"
            project_link.symlink_to(project, target_is_directory=True)
            project_result = subprocess.run(
                [*common, "--project", str(project_link)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(target_result.returncode, 2)
            self.assertIn("symlink", target_result.stderr.lower())
            self.assertEqual(outside.read_text(encoding="utf-8"), "must survive\n")
            self.assertEqual(project_result.returncode, 2)
            self.assertIn("symlink", project_result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
