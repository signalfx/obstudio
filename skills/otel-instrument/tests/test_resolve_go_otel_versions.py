from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


RESOLVER = (
    Path(__file__).parents[1] / "scripts" / "resolve_go_otel_versions.py"
)
SPEC = importlib.util.spec_from_file_location("resolve_go_otel_versions", RESOLVER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
OTELHTTP = "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
COMPANIONS = (
    "go.opentelemetry.io/otel",
    "go.opentelemetry.io/otel/sdk",
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp",
    "go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp",
)
TRANSITIVE_OTEL_MODULES = (
    "go.opentelemetry.io/otel/metric",
    "go.opentelemetry.io/otel/trace",
)
PROXY_ARTIFACTS = ("mod", "info", "zip", "ziphash")


def deterministic_go_runtime() -> dict[str, Any]:
    return {
        "path": "/test/bin/go",
        "size_bytes": 1,
        "sha256": "0" * 64,
        "version": "go version go1.23.0 test/amd64",
        "effective_toolchain": "go1.23.0",
    }


def module_go_mod(cache: Path, module: str, version: str) -> Path:
    parts = module.split("/")
    return cache.joinpath(*parts[:-1]) / f"{parts[-1]}@{version}" / "go.mod"


def download_go_mod(cache: Path, module: str, version: str) -> Path:
    return download_artifact(cache, module, version, "mod")


def download_artifact(
    cache: Path, module: str, version: str, suffix: str
) -> Path:
    return (
        cache
        / "cache"
        / "download"
        / Path(*module.split("/"))
        / "@v"
        / f"{version}.{suffix}"
    )


def write_module(
    cache: Path,
    module: str,
    version: str,
    go_version: str | None,
    *,
    core_version: str | None = None,
    download: bool = False,
    declared_module: str | None = None,
    proxy_artifacts: tuple[str, ...] = (),
    requirements: tuple[tuple[str, str], ...] = (),
    additional_go_versions: tuple[str, ...] = (),
) -> Path:
    path = (
        download_go_mod(cache, module, version)
        if download
        else module_go_mod(cache, module, version)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"module {declared_module or module}"]
    directive_versions = (
        ((go_version,) if go_version is not None else ())
        + additional_go_versions
    )
    for directive_version in directive_versions:
        lines.extend(["", f"go {directive_version}"])
    module_requirements = list(requirements)
    if core_version is not None:
        module_requirements.extend(
            (module, core_version)
            for module in (
                "go.opentelemetry.io/otel/metric",
                "go.opentelemetry.io/otel",
                "go.opentelemetry.io/otel/trace",
            )
        )
    if module_requirements:
        lines.extend(
            [
                "",
                "require (",
                *(
                    f"\t{module} {required_version}"
                    for module, required_version in module_requirements
                ),
                ")",
            ]
        )
    go_mod_text = "\n".join(lines) + "\n"
    path.write_text(go_mod_text, encoding="utf-8")
    for suffix in proxy_artifacts:
        artifact = download_artifact(cache, module, version, suffix)
        artifact.parent.mkdir(parents=True, exist_ok=True)
        if suffix == "mod":
            artifact.write_text(go_mod_text, encoding="utf-8")
        elif suffix == "info":
            artifact.write_text(
                json.dumps(
                    {
                        "Version": version,
                        "Time": "2025-01-01T00:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        elif suffix == "zip":
            artifact.write_bytes(b"fake module zip\n")
        elif suffix == "ziphash":
            artifact.write_text("h1:fake-module-hash\n", encoding="utf-8")
    return path


def write_project(project: Path, go_version: str | None) -> None:
    project.mkdir(parents=True)
    lines = ["module example.test/service"]
    if go_version is not None:
        lines.extend(["", f"go {go_version}"])
    (project / "go.mod").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_complete_bundle(
    cache: Path,
    *,
    otelhttp_version: str,
    otelhttp_go: str,
    core_version: str,
    companion_go: str,
    download: bool = False,
) -> None:
    write_module(
        cache,
        OTELHTTP,
        otelhttp_version,
        otelhttp_go,
        core_version=core_version,
        download=download,
        proxy_artifacts=PROXY_ARTIFACTS,
    )
    for module in (*COMPANIONS, *TRANSITIVE_OTEL_MODULES):
        write_module(
            cache,
            module,
            core_version,
            companion_go,
            download=download,
            proxy_artifacts=PROXY_ARTIFACTS,
        )


class ResolveGoOtelVersionsTest(unittest.TestCase):
    def run_resolver_process(
        self,
        project: Path,
        cache: Path,
        *,
        env: dict[str, str] | None = None,
        explicit_cache: bool = True,
        output: Path | None = None,
        go_executable: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            sys.executable,
            str(RESOLVER),
            "--project",
            str(project),
        ]
        if explicit_cache:
            arguments.extend(["--gomodcache", str(cache)])
        if go_executable is not None:
            arguments.extend(["--go-executable", str(go_executable)])
        if output is not None:
            arguments.extend(["--output", str(output)])
        return subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def run_resolver(
        self,
        project: Path,
        cache: Path,
        *,
        env: dict[str, str] | None = None,
        explicit_cache: bool = True,
        output: Path | None = None,
        go_executable: Path | None = None,
    ) -> dict[str, Any]:
        completed = self.run_resolver_process(
            project,
            cache,
            env=env,
            explicit_cache=explicit_cache,
            output=output,
            go_executable=go_executable,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        return json.loads(completed.stdout)

    def test_output_persists_full_plan_and_prints_compact_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            output = project / ".observe" / "tmp" / "go-otel-version-plan.json"
            write_project(project, "1.23.0")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.63.0",
                otelhttp_go="1.23.0",
                core_version="v1.38.0",
                companion_go="1.23.0",
            )

            summary = self.run_resolver(project, cache, output=output)
            full_plan_bytes = output.read_bytes()
            full_plan = json.loads(full_plan_bytes)

        self.assertEqual(summary["status"], "complete")
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["next_action"], "go-get")
        self.assertEqual(
            summary["selection"],
            {
                "otelhttp_version": "v0.63.0",
                "core_version": "v1.38.0",
            },
        )
        self.assertTrue(summary["go_get_ready"])
        self.assertFalse(summary["bootstrap_probe"]["eligible"])
        self.assertEqual(summary["plan_path"], str(output.resolve()))
        self.assertEqual(
            summary["plan_sha256"],
            hashlib.sha256(full_plan_bytes).hexdigest(),
        )
        self.assertNotIn("verification", summary)
        self.assertNotIn("env", summary)
        self.assertEqual(full_plan["status"], "complete")
        self.assertEqual(len(full_plan["verification"]), 7)
        for module in full_plan["verification"]:
            self.assertEqual(set(module["artifacts"]), set(PROXY_ARTIFACTS))
            self.assertEqual(module["unsafe_artifacts"], [])
            for artifact_state in module["artifacts"].values():
                self.assertGreater(artifact_state["size_bytes"], 0)
                self.assertRegex(artifact_state["sha256"], r"^[0-9a-f]{64}$")
                self.assertIsInstance(artifact_state["device"], int)
                self.assertIsInstance(artifact_state["inode"], int)
                self.assertTrue(artifact_state["link_safe"])
                self.assertTrue(artifact_state["regular"])
        self.assertGreater(
            len(full_plan_bytes),
            10 * len(json.dumps(summary).encode("utf-8")),
        )

    def test_compact_summary_preserves_bootstrap_probe_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            output = project / ".observe" / "tmp" / "go-otel-version-plan.json"
            write_project(project, "1.23.0")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.63.0",
                otelhttp_go="1.23.0",
                core_version="v1.38.0",
                companion_go="1.23.0",
            )
            with (project / "go.mod").open("a", encoding="utf-8") as go_mod:
                go_mod.write("\nrequire example.test/missing v1.0.0\n")

            summary = self.run_resolver(project, cache, output=output)
            full_plan = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "incomplete")
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["next_action"], "probe-bootstrap")
        self.assertFalse(summary["go_get_ready"])
        self.assertEqual(
            summary["bootstrap_probe"],
            {
                "eligible": True,
                "otelhttp_version": "v0.63.0",
                "core_version": "v1.38.0",
            },
        )
        self.assertEqual(
            summary["candidate_rejection_count"],
            len(full_plan["candidate_rejections"]),
        )
        self.assertTrue(full_plan["bootstrap_probe"]["eligible"])

    def test_output_cannot_escape_project_observe_tmp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            outside = root / "outside.json"
            write_project(project, "1.23.0")
            cache.mkdir()

            completed = self.run_resolver_process(
                project,
                cache,
                output=outside,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stdout, "")
            self.assertIn("must be the fixed path", completed.stderr)
            self.assertFalse(outside.exists())

    def test_output_rejects_runner_owned_ledger_path_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            ledger = (
                project
                / ".observe"
                / "tmp"
                / "go-otel-resolver"
                / "accepted-plan.json"
            )
            write_project(project, "1.23.0")
            cache.mkdir()
            ledger.parent.mkdir(parents=True)
            ledger.write_text("accepted ledger\n", encoding="utf-8")

            completed = self.run_resolver_process(
                project,
                cache,
                output=ledger,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("runner-owned and alternate paths are reserved", completed.stderr)
            self.assertEqual(ledger.read_text(encoding="utf-8"), "accepted ledger\n")

    def test_portable_atomic_output_succeeds_and_rejects_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            output = project / MODULE.PLAN_OUTPUT_PATH
            payload = b'{"status":"complete"}\n'

            with mock.patch.object(
                MODULE, "descriptor_publication_supported", return_value=False
            ):
                MODULE.write_plan_atomically(project, output, payload)
            self.assertEqual(output.read_bytes(), payload)

            victim = root / "victim.json"
            victim.write_text("preserve\n", encoding="utf-8")
            output.unlink()
            output.symlink_to(victim)
            with mock.patch.object(
                MODULE, "descriptor_publication_supported", return_value=False
            ), self.assertRaisesRegex(OSError, "regular file"):
                MODULE.write_plan_atomically(project, output, b"attacker\n")
            self.assertEqual(victim.read_text(encoding="utf-8"), "preserve\n")

    def test_portable_atomic_output_rejects_linked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            outside = root / "outside"
            project.mkdir()
            outside.mkdir()
            observe = project / ".observe"
            observe.mkdir()
            (observe / "tmp").symlink_to(outside, target_is_directory=True)
            output = project / MODULE.PLAN_OUTPUT_PATH

            with mock.patch.object(
                MODULE, "descriptor_publication_supported", return_value=False
            ), self.assertRaisesRegex(OSError, "link, reparse point"):
                MODULE.write_plan_atomically(project, output, b"blocked\n")
            self.assertEqual(list(outside.iterdir()), [])

    def test_output_rejects_existing_target_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            output_dir = project / ".observe" / "tmp"
            output = output_dir / "go-otel-version-plan.json"
            victim = root / "victim.json"
            write_project(project, "1.23.0")
            cache.mkdir()
            output_dir.mkdir(parents=True)
            victim.write_text("preserve me\n", encoding="utf-8")
            output.symlink_to(victim)

            completed = self.run_resolver_process(
                project,
                cache,
                output=output,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stdout, "")
            self.assertIn("must be a regular file", completed.stderr)
            self.assertTrue(output.is_symlink())
            self.assertEqual(victim.read_text(encoding="utf-8"), "preserve me\n")
            self.assertEqual(list(output_dir.glob(".go-otel-plan-*.tmp")), [])

    def test_output_rejects_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            outside = root / "outside"
            observe = project / ".observe"
            output = observe / "tmp" / "go-otel-version-plan.json"
            write_project(project, "1.23.0")
            cache.mkdir()
            outside.mkdir()
            observe.mkdir()
            (observe / "tmp").symlink_to(outside, target_is_directory=True)

            completed = self.run_resolver_process(
                project,
                cache,
                output=output,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stdout, "")
            self.assertIn("could not write resolver plan", completed.stderr)
            self.assertFalse((outside / "go-otel-version-plan.json").exists())

    def test_selects_newest_compatible_bundle_and_emits_pinned_argv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project with spaces"
            cache = root / "module cache with spaces"
            write_project(project, "1.23.0")
            write_module(
                cache,
                OTELHTTP,
                "v0.9.0",
                "1.20",
                core_version="v1.20.0",
            )
            write_module(
                cache,
                OTELHTTP,
                "v0.10.0",
                "1.22.0",
                core_version="v1.34.0",
            )
            write_complete_bundle(
                cache,
                otelhttp_version="v0.63.0",
                otelhttp_go="1.23.0",
                core_version="v1.38.0",
                companion_go="1.23.0",
            )
            write_module(
                cache,
                OTELHTTP,
                "v0.64.0",
                "1.24.0",
                core_version="v1.39.0",
            )

            before = {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            marker = root / "go-was-executed"
            fake_go = fake_bin / "go"
            fake_go.write_text(
                f"#!/bin/sh\n: > {str(marker)!r}\n"
                "printf 'go version go1.23.0 test/amd64\\n'\n",
                encoding="utf-8",
            )
            fake_go.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = str(fake_bin)

            result = self.run_resolver(project, cache, env=environment)

            after = {
                path.relative_to(root): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file() and path not in {fake_go, marker}
            }
            marker_created = marker.exists()

        expected_modules = [
            "go.opentelemetry.io/otel@v1.38.0",
            "go.opentelemetry.io/otel/sdk@v1.38.0",
            (
                "go.opentelemetry.io/otel/exporters/otlp/otlptrace/"
                "otlptracehttp@v1.38.0"
            ),
            (
                "go.opentelemetry.io/otel/exporters/otlp/otlpmetric/"
                "otlpmetrichttp@v1.38.0"
            ),
            f"{OTELHTTP}@v0.63.0",
        ]
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["complete"])
        self.assertTrue(result["candidate_only"])
        self.assertEqual(result["selection"]["version"], "v0.63.0")
        self.assertEqual(result["selection"]["core_version"], "v1.38.0")
        self.assertEqual(result["go_get"]["modules"], expected_modules)
        self.assertEqual(
            result["go_get"]["argv"],
            [str(fake_go.resolve()), "get", *expected_modules],
        )
        self.assertTrue(result["go_get"]["ready"])
        local_cache = (
            project.resolve() / ".observe" / "tmp" / "go-otel-resolver"
        )
        self.assertEqual(
            result["go_get"]["env"],
            {
                "CGO_ENABLED": "0",
                "GOCACHE": str(local_cache / "gocache"),
                "GOARCH": "amd64",
                "GOENV": "off",
                "GOFLAGS": "",
                "GOMODCACHE": str(local_cache / "gomodcache"),
                "GONOPROXY": "none",
                "GONOSUMDB": "none",
                "GOOS": "test",
                "GOPATH": str(local_cache / "gopath"),
                "GOPRIVATE": "",
                "GOPROXY": (cache / "cache" / "download").resolve().as_uri(),
                "GOSUMDB": "off",
                "GOTELEMETRY": "off",
                "GOTOOLCHAIN": "local",
                "GOVCS": "*:off",
                "GOWORK": "off",
                "HOME": str(local_cache / "home"),
            },
        )
        self.assertEqual(result["go_commands"]["cwd"], str(project.resolve()))
        self.assertEqual(
            result["go_commands"]["env"], result["go_get"]["env"]
        )
        self.assertEqual(
            result["go_commands"]["cleanup_argv"],
            [str(fake_go.resolve()), "clean", "-cache", "-modcache"],
        )
        self.assertEqual(
            result["go_commands"]["owned_cache_paths"],
            [
                str(local_cache / "gocache"),
                str(local_cache / "gomodcache"),
            ],
        )
        self.assertEqual(
            result["go_commands"]["cleanup_allowed_files"],
            [
                str(local_cache / "gocache" / "README"),
                str(local_cache / "gocache" / "trim.txt"),
            ],
        )
        self.assertIn("go test", result["go_commands"]["reuse_env_for"])
        self.assertTrue(
            all(item["status"] == "ready" for item in result["verification"])
        )
        self.assertEqual(len(result["verification"]), 7)
        self.assertTrue(marker_created)
        self.assertEqual(
            before,
            {
                path: content
                for path, content in after.items()
                if path not in {Path("fake-bin/go")}
            },
        )

    def test_go_language_version_does_not_equal_first_patch_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.59.0",
                otelhttp_go="1.22.0",
                core_version="v1.34.0",
                companion_go="1.22.0",
            )
            write_module(
                cache,
                OTELHTTP,
                "v0.63.0",
                "1.23.0",
                core_version="v1.38.0",
            )

            result = self.run_resolver(project, cache)

        self.assertEqual(result["selection"]["version"], "v0.59.0")
        self.assertEqual(result["scan"]["newer_go_versions"], 1)

    def test_pre_go_121_missing_patch_equals_dot_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.20")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.49.0",
                otelhttp_go="1.20.0",
                core_version="v1.24.0",
                companion_go="1.20.0",
            )

            result = self.run_resolver(project, cache)

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["selection"]["version"], "v0.49.0")

    def test_metadata_only_newer_candidate_is_skipped_for_runnable_bundle(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.59.0",
                otelhttp_go="1.22.0",
                core_version="v1.34.0",
                companion_go="1.22.0",
            )
            write_module(
                cache,
                OTELHTTP,
                "v0.63.0",
                "1.23.0",
                core_version="v1.38.0",
                download=True,
                proxy_artifacts=("mod", "info"),
            )
            write_module(cache, COMPANIONS[0], "v1.38.0", "1.23.0")
            write_module(cache, COMPANIONS[2], "v1.38.0", "1.24.0")
            write_module(cache, COMPANIONS[3], "v1.38.0", "1.23.0")

            result = self.run_resolver(project, cache)

        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["complete"])
        self.assertEqual(result["selection"]["version"], "v0.59.0")
        self.assertEqual(result["selection"]["core_version"], "v1.34.0")
        self.assertTrue(result["go_get"]["ready"])
        self.assertIn(f"{OTELHTTP}@v0.59.0", result["go_get"]["argv"])
        self.assertEqual(result["scan"]["metadata_only_versions"], 1)
        self.assertEqual(result["scan"]["non_runnable_versions"], 1)
        self.assertEqual(result["candidate_rejections"][0]["version"], "v0.63.0")
        rejected = result["candidate_rejections"][0]["not_ready_modules"]
        otelhttp_rejection = next(
            item for item in rejected if item["module"] == OTELHTTP
        )
        self.assertEqual(otelhttp_rejection["missing_artifacts"], ["zip", "ziphash"])

    def test_metadata_only_cache_has_no_ready_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23")
            write_module(
                cache,
                OTELHTTP,
                "v0.60.0",
                "1.22.0",
                core_version="v1.35.0",
                download=True,
                proxy_artifacts=("mod", "info"),
            )
            for module in COMPANIONS:
                write_module(
                    cache,
                    module,
                    "v1.35.0",
                    "1.22.0",
                    proxy_artifacts=PROXY_ARTIFACTS,
                )

            result = self.run_resolver(project, cache)

        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["complete"])
        self.assertIsNone(result["selection"])
        self.assertEqual(result["reasons"], ["no-runnable-cached-bundle"])
        self.assertFalse(result["go_get"]["ready"])
        self.assertEqual(result["go_get"]["env"], {})
        self.assertEqual(result["go_get"]["argv"], [])
        self.assertFalse(result["go_commands"]["ready"])
        self.assertEqual(result["go_commands"]["env"], {})
        self.assertEqual(result["go_commands"]["cleanup_argv"], [])
        self.assertEqual(result["go_commands"]["cleanup_allowed_files"], [])
        self.assertFalse(result["bootstrap_probe"]["eligible"])
        self.assertEqual(
            result["bootstrap_probe"]["reasons"],
            ["no-file-proxy-ready-import-closure"],
        )

    def test_missing_overinclusive_transitive_artifact_keeps_probe_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.63.0",
                otelhttp_go="1.23.0",
                core_version="v1.38.0",
                companion_go="1.23.0",
            )
            write_module(
                cache,
                "go.opentelemetry.io/otel/sdk",
                "v1.38.0",
                "1.23.0",
                requirements=(("example.test/transitive", "v1.2.3"),),
                proxy_artifacts=PROXY_ARTIFACTS,
            )
            write_module(
                cache,
                "example.test/transitive",
                "v1.2.3",
                "1.22.0",
                proxy_artifacts=("mod", "info", "zip"),
            )

            result = self.run_resolver(project, cache)

        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["complete"])
        self.assertEqual(result["reasons"], ["no-runnable-cached-bundle"])
        self.assertFalse(result["go_get"]["ready"])
        self.assertTrue(result["bootstrap_probe"]["eligible"])
        self.assertFalse(result["bootstrap_probe"]["import_closure_complete"])
        self.assertTrue(
            result["bootstrap_probe"]["candidate_closure_inspected"]
        )
        probe_transitive = next(
            item
            for item in result["bootstrap_probe"]["verification"]
            if item["module"] == "example.test/transitive"
        )
        self.assertEqual(probe_transitive["missing_artifacts"], ["ziphash"])
        self.assertEqual(
            set(probe_transitive["artifacts"]), {"mod", "info", "zip"}
        )

    def test_probe_retains_superseded_mvs_go_mod_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            with (project / "go.mod").open("a", encoding="utf-8") as go_mod:
                go_mod.write("\nrequire example.test/project-only v1.0.0\n")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.59.0",
                otelhttp_go="1.22.0",
                core_version="v1.34.0",
                companion_go="1.22.0",
            )
            write_module(
                cache,
                "go.opentelemetry.io/otel/sdk",
                "v1.34.0",
                "1.22.0",
                requirements=(
                    ("github.com/go-logr/logr", "v1.4.2"),
                    ("github.com/go-logr/stdr", "v1.2.2"),
                ),
                proxy_artifacts=PROXY_ARTIFACTS,
            )
            write_module(
                cache,
                "github.com/go-logr/logr",
                "v1.4.2",
                "1.20",
                proxy_artifacts=PROXY_ARTIFACTS,
            )
            write_module(
                cache,
                "github.com/go-logr/stdr",
                "v1.2.2",
                "1.20",
                requirements=(("github.com/go-logr/logr", "v1.2.2"),),
                proxy_artifacts=PROXY_ARTIFACTS,
            )
            write_module(
                cache,
                "github.com/go-logr/logr",
                "v1.2.2",
                "1.18",
                proxy_artifacts=("mod", "info"),
            )

            result = self.run_resolver(project, cache)

        self.assertTrue(result["bootstrap_probe"]["eligible"])
        selected = next(
            row
            for row in result["bootstrap_probe"]["verification"]
            if row["module"] == "github.com/go-logr/logr"
        )
        self.assertEqual(selected["version"], "v1.4.2")
        lower = next(
            row
            for row in result["bootstrap_probe"]["graph_metadata"]
            if row["module"] == "github.com/go-logr/logr"
            and row["version"] == "v1.2.2"
        )
        self.assertEqual(set(lower["artifacts"]), {"mod", "info"})
        self.assertEqual(lower["missing_artifacts"], ["zip", "ziphash"])

    def test_bootstrap_selects_highest_file_proxy_ready_direct_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            with (project / "go.mod").open("a", encoding="utf-8") as go_mod:
                go_mod.write("\nrequire example.test/project-dep v1.0.0\n")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.59.0",
                otelhttp_go="1.22.0",
                core_version="v1.34.0",
                companion_go="1.22.0",
            )
            write_complete_bundle(
                cache,
                otelhttp_version="v0.63.0",
                otelhttp_go="1.23.0",
                core_version="v1.38.0",
                companion_go="1.23.0",
            )
            download_artifact(cache, OTELHTTP, "v0.63.0", "ziphash").unlink()
            write_module(
                cache,
                "example.test/project-dep",
                "v1.0.0",
                "1.20",
                proxy_artifacts=("mod", "info", "zip"),
            )

            result = self.run_resolver(project, cache)

        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(result["bootstrap_probe"]["eligible"])
        self.assertEqual(
            result["bootstrap_probe"]["candidate"]["version"], "v0.59.0"
        )
        self.assertEqual(
            result["bootstrap_probe"]["candidate"]["core_version"],
            "v1.34.0",
        )
        project_dependency = next(
            row
            for row in result["bootstrap_probe"]["verification"]
            if row["module"] == "example.test/project-dep"
        )
        self.assertEqual(project_dependency["missing_artifacts"], ["ziphash"])

    def test_runtime_fingerprint_uses_external_disposable_go_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.63.0",
                otelhttp_go="1.23.0",
                core_version="v1.38.0",
                companion_go="1.23.0",
            )
            home_log = root / "runtime-home.json"
            fake_go = root / "go"
            fake_go.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "home = Path(os.environ['HOME'])\n"
                "telemetry = Path(os.environ['GOTELEMETRYDIR'])\n"
                "(home / 'Library/Application Support/go/telemetry/local').mkdir(parents=True)\n"
                "(home / 'Library/Application Support/go/telemetry/local/weekends').write_text('1')\n"
                "telemetry.mkdir(parents=True)\n"
                "(telemetry / 'weekends').write_text('1')\n"
                "Path(os.environ['FAKE_GO_HOME_LOG']).write_text(json.dumps({'home': str(home), 'telemetry': str(telemetry)}))\n"
                "print('go version go1.26.0 test/amd64')\n",
                encoding="utf-8",
            )
            fake_go.chmod(0o755)
            env = os.environ.copy()
            env["FAKE_GO_HOME_LOG"] = str(home_log)

            completed = self.run_resolver_process(
                project,
                cache,
                env=env,
                go_executable=fake_go,
            )
            result = json.loads(completed.stdout)
            runtime_paths = json.loads(home_log.read_text(encoding="utf-8"))
            project_runtime_home = (
                project / ".observe" / "tmp" / "go-otel-resolver" / "home"
            )
            project_runtime_home_exists = project_runtime_home.exists()
            external_home = Path(runtime_paths["home"])
            external_telemetry = Path(runtime_paths["telemetry"])

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "complete")
        self.assertFalse(project_runtime_home_exists)
        self.assertFalse(external_home.is_relative_to(project))
        self.assertFalse(external_telemetry.is_relative_to(project))

    def test_transitive_module_requiring_newer_go_rejects_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.63.0",
                otelhttp_go="1.23.0",
                core_version="v1.38.0",
                companion_go="1.23.0",
            )
            write_module(
                cache,
                "go.opentelemetry.io/otel/sdk",
                "v1.38.0",
                "1.23.0",
                requirements=(("example.test/transitive", "v1.2.3"),),
                proxy_artifacts=PROXY_ARTIFACTS,
            )
            write_module(
                cache,
                "example.test/transitive",
                "v1.2.3",
                "1.24.0",
                proxy_artifacts=PROXY_ARTIFACTS,
            )

            result = self.run_resolver(project, cache)

        rejection = result["candidate_rejections"][0]
        transitive = next(
            item
            for item in rejection["not_ready_modules"]
            if item["module"] == "example.test/transitive"
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("requires-newer-go", transitive["issues"])

    def test_module_path_major_rules_gate_file_proxy_readiness(self) -> None:
        cases = (
            ("example.test/unstable", "v0.9.0", True),
            ("example.test/stable", "v1.2.3", True),
            ("example.test/legacy", "v2.0.0", False),
            ("example.test/legacy", "v2.0.0+incompatible", True),
            ("example.test/lib/v1", "v1.0.0", False),
            ("example.test/lib/v2", "v1.0.0", False),
            ("example.test/lib/v2", "v2.0.0", True),
            ("gopkg.in/check.v1", "v1.0.0", True),
            ("gopkg.in/check.v2", "v1.0.0", False),
        )
        for module, version, expected_ready in cases:
            with self.subTest(module=module, version=version):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    project = root / "project"
                    cache = root / "cache"
                    write_project(project, "1.23.0")
                    write_complete_bundle(
                        cache,
                        otelhttp_version="v0.63.0",
                        otelhttp_go="1.23.0",
                        core_version="v1.38.0",
                        companion_go="1.23.0",
                    )
                    write_module(
                        cache,
                        "go.opentelemetry.io/otel/sdk",
                        "v1.38.0",
                        "1.23.0",
                        requirements=((module, version),),
                        proxy_artifacts=PROXY_ARTIFACTS,
                    )
                    write_module(
                        cache,
                        module,
                        version,
                        "1.23.0",
                        proxy_artifacts=PROXY_ARTIFACTS,
                    )

                    result = self.run_resolver(project, cache)

                if expected_ready:
                    dependency = next(
                        item
                        for item in result["verification"]
                        if item["module"] == module
                    )
                    self.assertEqual(result["status"], "complete")
                    self.assertEqual(dependency["status"], "ready")
                    self.assertTrue(result["go_get"]["ready"])
                else:
                    rejection = result["candidate_rejections"][0]
                    dependency = next(
                        item
                        for item in rejection["not_ready_modules"]
                        if item["module"] == module
                    )
                    self.assertEqual(result["status"], "incomplete")
                    self.assertIn(
                        "module-path-major-version-mismatch",
                        dependency["issues"],
                    )
                    self.assertFalse(result["go_get"]["ready"])

    def test_transitive_module_without_go_directive_is_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.63.0",
                otelhttp_go="1.23.0",
                core_version="v1.38.0",
                companion_go="1.23.0",
            )
            write_module(
                cache,
                "go.opentelemetry.io/otel/sdk",
                "v1.38.0",
                "1.23.0",
                requirements=(("example.test/legacy", "v1.2.3"),),
                proxy_artifacts=PROXY_ARTIFACTS,
            )
            write_module(
                cache,
                "example.test/legacy",
                "v1.2.3",
                None,
                proxy_artifacts=PROXY_ARTIFACTS,
            )

            result = self.run_resolver(project, cache)

        legacy = next(
            item
            for item in result["verification"]
            if item["module"] == "example.test/legacy"
        )
        self.assertEqual(result["status"], "complete")
        self.assertIsNone(legacy["go_version"])
        self.assertEqual(legacy["go_directive_status"], "absent")
        self.assertTrue(legacy["compatible"])
        self.assertEqual(legacy["status"], "ready")

    def test_malformed_and_duplicate_dependency_go_directives_are_rejected(
        self,
    ) -> None:
        cases = (
            ("not-a-version", (), "go-directive-malformed"),
            ("1.22.0", ("1.21.0",), "go-directive-duplicate"),
        )
        for go_version, additional_versions, expected_issue in cases:
            with self.subTest(expected_issue=expected_issue):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    project = root / "project"
                    cache = root / "cache"
                    write_project(project, "1.23.0")
                    write_complete_bundle(
                        cache,
                        otelhttp_version="v0.63.0",
                        otelhttp_go="1.23.0",
                        core_version="v1.38.0",
                        companion_go="1.23.0",
                    )
                    write_module(
                        cache,
                        "go.opentelemetry.io/otel/sdk",
                        "v1.38.0",
                        "1.23.0",
                        requirements=(("example.test/bad", "v1.2.3"),),
                        proxy_artifacts=PROXY_ARTIFACTS,
                    )
                    write_module(
                        cache,
                        "example.test/bad",
                        "v1.2.3",
                        go_version,
                        additional_go_versions=additional_versions,
                        proxy_artifacts=PROXY_ARTIFACTS,
                    )

                    result = self.run_resolver(project, cache)

                rejection = result["candidate_rejections"][0]
                dependency = next(
                    item
                    for item in rejection["not_ready_modules"]
                    if item["module"] == "example.test/bad"
                )
                self.assertEqual(result["status"], "incomplete")
                self.assertIn(expected_issue, dependency["issues"])

    def test_complete_closure_includes_existing_and_transitive_requirements(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            with (project / "go.mod").open("a", encoding="utf-8") as go_mod:
                go_mod.write("\nrequire example.test/existing v1.0.0\n")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.63.0",
                otelhttp_go="1.23.0",
                core_version="v1.38.0",
                companion_go="1.23.0",
            )
            write_module(
                cache,
                "example.test/existing",
                "v1.0.0",
                "1.22.0",
                requirements=(("example.test/transitive", "v1.2.3"),),
                proxy_artifacts=PROXY_ARTIFACTS,
            )
            write_module(
                cache,
                "example.test/transitive",
                "v1.2.3",
                "1.21.0",
                proxy_artifacts=PROXY_ARTIFACTS,
            )

            result = self.run_resolver(project, cache)

        verified = {
            item["module"]: item for item in result["verification"]
        }
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["complete"])
        self.assertIn("example.test/existing", verified)
        self.assertIn("example.test/transitive", verified)
        self.assertTrue(
            all(item["status"] == "ready" for item in verified.values())
        )
        self.assertEqual(result["scan"]["closure_modules"], 9)

    def test_existing_otel_pin_returns_incomplete_without_selection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            with (project / "go.mod").open("a", encoding="utf-8") as go_mod:
                go_mod.write(
                    "\nrequire go.opentelemetry.io/otel v1.34.0\n"
                )
            cache.mkdir()

            result = self.run_resolver(project, cache)

        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["complete"])
        self.assertEqual(
            result["reasons"], ["existing-otel-dependencies"]
        )
        self.assertEqual(
            result["project"]["existing_otel_requirements"],
            [
                {
                    "module": "go.opentelemetry.io/otel",
                    "version": "v1.34.0",
                    "indirect": False,
                }
            ],
        )
        self.assertIsNone(result["selection"])
        self.assertFalse(result["go_get"]["ready"])
        self.assertFalse(result["bootstrap_probe"]["eligible"])

    def test_existing_indirect_otel_pin_also_stops_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            with (project / "go.mod").open("a", encoding="utf-8") as go_mod:
                go_mod.write(
                    "\nrequire go.opentelemetry.io/otel/trace "
                    "v1.34.0 // indirect\n"
                )
            cache.mkdir()

            result = self.run_resolver(project, cache)

        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["complete"])
        self.assertEqual(result["reasons"], ["existing-otel-dependencies"])
        self.assertEqual(
            result["project"]["existing_otel_requirements"],
            [
                {
                    "module": "go.opentelemetry.io/otel/trace",
                    "version": "v1.34.0",
                    "indirect": True,
                }
            ],
        )
        self.assertIsNone(result["selection"])
        self.assertFalse(result["go_get"]["ready"])

    def test_main_module_replace_and_exclude_are_unsupported(self) -> None:
        cases = (
            (
                "replace example.test/dependency => ../dependency\n",
                "project-replace-directive-unsupported",
            ),
            (
                "exclude example.test/dependency v1.0.0\n",
                "project-exclude-directive-unsupported",
            ),
        )
        for directive, expected_reason in cases:
            with self.subTest(directive=directive):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    project = root / "project"
                    cache = root / "cache"
                    write_project(project, "1.23.0")
                    with (project / "go.mod").open(
                        "a", encoding="utf-8"
                    ) as go_mod:
                        go_mod.write(f"\n{directive}")
                    cache.mkdir()

                    result = self.run_resolver(project, cache)

                self.assertEqual(result["status"], "incomplete")
                self.assertFalse(result["complete"])
                self.assertEqual(result["reasons"], [expected_reason])
                self.assertIsNone(result["selection"])
                self.assertFalse(result["go_get"]["ready"])

    def test_reads_download_cache_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            write_complete_bundle(
                cache,
                otelhttp_version="v0.63.0",
                otelhttp_go="1.23.0",
                core_version="v1.38.0",
                companion_go="1.23.0",
                download=True,
            )

            environment = os.environ.copy()
            environment["GOMODCACHE"] = str(cache)
            result = self.run_resolver(
                project / "go.mod",
                cache,
                env=environment,
                explicit_cache=False,
            )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["gomodcache"]["source"], "GOMODCACHE")
        self.assertEqual(result["selection"]["source"], "download")
        self.assertTrue(
            all(item["source"] == "download" for item in result["verification"])
        )

    def test_no_candidate_and_invalid_project_are_clear_json_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.21")
            write_module(
                cache,
                OTELHTTP,
                "v0.63.0",
                "1.23.0",
                core_version="v1.38.0",
            )

            no_candidate = self.run_resolver(project, cache)
            write_project(root / "missing-directive", None)
            invalid_project = self.run_resolver(root / "missing-directive", cache)

        self.assertEqual(no_candidate["status"], "no-candidate")
        self.assertEqual(
            no_candidate["reasons"], ["no-compatible-cached-otelhttp"]
        )
        self.assertIsNone(no_candidate["selection"])
        self.assertEqual(no_candidate["go_get"]["argv"], [])
        self.assertEqual(invalid_project["status"], "incomplete")
        self.assertEqual(
            invalid_project["reasons"],
            ["project-go-directive-missing-or-invalid"],
        )

    def test_module_directive_mismatch_and_warning_output_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            cache = root / "cache"
            write_project(project, "1.23.0")
            for index in range(40):
                write_module(
                    cache,
                    OTELHTTP,
                    f"v0.{index}.0",
                    "1.22.0",
                    core_version="v1.34.0",
                    declared_module="example.test/wrong",
                )

            result = self.run_resolver(project, cache)

        self.assertEqual(result["status"], "no-candidate")
        self.assertLessEqual(len(result["warnings"]), 32)
        self.assertGreater(result["warnings_omitted"], 0)
        self.assertEqual(result["scan"]["unusable_versions"], 40)

    def test_cache_directory_entry_limit_fails_closed(self) -> None:
        for source in ("extracted", "download"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / "project"
                cache = root / "cache"
                write_project(project, "1.23.0")
                write_complete_bundle(
                    cache,
                    otelhttp_version="v0.63.0",
                    otelhttp_go="1.23.0",
                    core_version="v1.38.0",
                    companion_go="1.23.0",
                    download=source == "download",
                )
                if source == "extracted":
                    parent = cache.joinpath(*OTELHTTP.split("/")[:-1])
                    for index in range(4):
                        (parent / f"unrelated-{index}").mkdir()
                else:
                    download_artifact(
                        cache, OTELHTTP, "v0.63.0", "extra"
                    ).write_text("extra\n", encoding="utf-8")

                with mock.patch.object(
                    MODULE,
                    "go_runtime_fingerprint",
                    return_value=deterministic_go_runtime(),
                ), mock.patch.object(MODULE, "MAX_CACHE_DIRECTORY_ENTRIES", 4):
                    result = MODULE.resolve(project, cache)

            self.assertEqual(result["status"], "incomplete")
            self.assertFalse(result["complete"])
            self.assertIsNone(result["selection"])
            self.assertFalse(result["go_get"]["ready"])
            self.assertEqual(
                result["reasons"], ["otelhttp-cache-scan-failed"]
            )
            self.assertEqual(result["scan"]["cache_entry_limit"], 4)
            self.assertEqual(
                result["scan"]["cache_directories_truncated"], 1
            )
            self.assertEqual(
                result["scan"]["cache_entries_omitted_at_least"], 1
            )
            self.assertTrue(
                any("entry scan limit" in warning for warning in result["warnings"])
            )


if __name__ == "__main__":
    unittest.main()
