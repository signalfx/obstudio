from __future__ import annotations

import hashlib
import importlib.util
import json
import os
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

    def test_alpha_candidate_does_not_exact_match_expected_beta(self) -> None:
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

            self.assertEqual(result["status"], "resolved")
            self.assertEqual(
                result["selected"]["artifact_version"], "2.3.0-alpha"
            )
            self.assertEqual(
                result["claims"]["repository_configuration_match"],
                "mismatch",
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
