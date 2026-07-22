from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


RESOLVER = Path(__file__).parents[1] / "scripts" / "resolve_java_agent.py"
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
                result["production_parity"]["status"], "not_proven"
            )
            self.assertIn("no user-supplied agent is required", result["message"])

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


if __name__ == "__main__":
    unittest.main()
