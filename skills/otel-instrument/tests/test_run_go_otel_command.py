from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RUNNER = Path(__file__).parents[1] / "scripts" / "run_go_otel_command.py"
OTELHTTP = "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
COMPANIONS = (
    "go.opentelemetry.io/otel",
    "go.opentelemetry.io/otel/sdk",
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp",
    "go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp",
)
ARTIFACTS = ("mod", "info", "zip", "ziphash")
PLAN_ENV_KEYS = (
    "GOCACHE",
    "GOENV",
    "GOFLAGS",
    "GOMODCACHE",
    "GONOPROXY",
    "GONOSUMDB",
    "GOPATH",
    "GOPRIVATE",
    "GOPROXY",
    "GOSUMDB",
    "GOTOOLCHAIN",
    "GOVCS",
    "GOWORK",
    "HOME",
)


def artifact(cache: Path, module: str, version: str, suffix: str) -> Path:
    return (
        cache
        / "cache"
        / "download"
        / Path(*module.split("/"))
        / "@v"
        / f"{version}.{suffix}"
    )


def write_proxy_module(
    cache: Path,
    module: str,
    version: str,
    *,
    go_version: str,
    core_version: str | None = None,
    requirements: tuple[tuple[str, str], ...] = (),
) -> None:
    lines = [f"module {module}", "", f"go {go_version}"]
    if core_version is not None:
        lines.extend(["", f"require go.opentelemetry.io/otel {core_version}"])
    if requirements:
        lines.extend(
            [
                "",
                "require (",
                *(f"\t{module} {required_version}" for module, required_version in requirements),
                ")",
            ]
        )
    mod_text = "\n".join(lines) + "\n"
    for suffix in ARTIFACTS:
        path = artifact(cache, module, version, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        if suffix == "mod":
            path.write_text(mod_text, encoding="utf-8")
        elif suffix == "info":
            path.write_text(
                json.dumps({"Version": version, "Time": "2025-01-01T00:00:00Z"}),
                encoding="utf-8",
            )
        elif suffix == "zip":
            path.write_bytes(b"fixture zip")
        else:
            path.write_text("h1:fixture\n", encoding="utf-8")


class RunGoOtelCommandTest(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path]:
        project = root / "project with spaces"
        project.mkdir()
        (project / "go.mod").write_text(
            "module example.test/service\n\ngo 1.23\n", encoding="utf-8"
        )
        cache = root / "source cache with spaces"
        write_proxy_module(
            cache,
            OTELHTTP,
            "v0.59.0",
            go_version="1.22.0",
            core_version="v1.34.0",
        )
        for module in COMPANIONS:
            write_proxy_module(
                cache,
                module,
                "v1.34.0",
                go_version="1.22.0",
            )
        return project.resolve(), cache.resolve()

    def make_bootstrap_fixture(
        self, root: Path, *, missing_otel_transitive: bool = False
    ) -> tuple[Path, Path, Path]:
        project = root / "bootstrap project with spaces"
        project.mkdir()
        (project / "go.mod").write_text(
            "module example.test/bootstrap\n\ngo 1.23\n",
            encoding="utf-8",
        )
        cache = root / "bootstrap source cache"
        missing_module = "example.test/transitive"
        missing_artifact = artifact(
            cache,
            missing_module,
            "v1.0.0",
            "zip" if missing_otel_transitive else "ziphash",
        )
        write_proxy_module(
            cache,
            OTELHTTP,
            "v0.59.0",
            go_version="1.22.0",
            core_version="v1.34.0",
        )
        for module in COMPANIONS:
            write_proxy_module(
                cache,
                module,
                "v1.34.0",
                go_version="1.22.0",
                requirements=(
                    ((missing_module, "v1.0.0"),)
                    if module == "go.opentelemetry.io/otel/sdk"
                    else ()
                ),
            )
        # The resolver conservatively requires the internal ziphash file, but
        # the file-proxy protocol needs only mod/info/zip. The success fixture
        # therefore leaves ziphash absent; the failure fixture leaves zip
        # absent so the staged Go command cannot resolve the SDK dependency.
        write_proxy_module(
            cache,
            missing_module,
            "v1.0.0",
            go_version="1.20",
        )
        missing_artifact.unlink()
        return project.resolve(), cache.resolve(), missing_artifact.resolve()

    def make_fake_go(self, root: Path) -> Path:
        fake_bin = root / "fake bin"
        fake_bin.mkdir()
        script = fake_bin / "go"
        script.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            f"keys = {PLAN_ENV_KEYS!r}\n"
            "payload = {\n"
            "  'argv': sys.argv[1:],\n"
            "  'cwd': os.getcwd(),\n"
            "  'env': {key: os.environ.get(key) for key in keys},\n"
            "  'inherited_gomod': os.environ.get('GOMOD'),\n"
            "  'go_mod': (Path('go.mod').read_text(encoding='utf-8') if Path('go.mod').is_file() else None),\n"
            "  'main_go': (Path('main.go').read_text(encoding='utf-8') if Path('main.go').is_file() else None),\n"
            "}\n"
            "Path(os.environ['FAKE_GO_LOG']).write_text(json.dumps(payload), encoding='utf-8')\n"
            "required = os.environ.get('FAKE_GO_REQUIRE_ARTIFACT')\n"
            "if required and not Path(required).is_file():\n"
            "  print('file proxy artifact missing', file=sys.stderr)\n"
            "  raise SystemExit(19)\n"
            "if sys.argv[1:2] == ['get'] and os.environ.get('FAKE_GO_EDIT_PROJECT'):\n"
            "  go_mod = Path('go.mod')\n"
            "  pins = [item.rsplit('@', 1) for item in sys.argv[2:]]\n"
            "  block = '\\nrequire (\\n' + ''.join(f'\\t{module} {version}\\n' for module, version in pins) + ')\\n'\n"
            "  go_mod.write_text(go_mod.read_text(encoding='utf-8') + block, encoding='utf-8')\n"
            "  Path('go.sum').write_text('generated sum\\n', encoding='utf-8')\n"
            "  if os.environ.get('FAKE_GO_DIRECTIVE_DRIFT'):\n"
            "    go_mod.write_text(go_mod.read_text(encoding='utf-8').replace('go 1.23', 'go 1.24'), encoding='utf-8')\n"
            "  if os.environ.get('FAKE_GO_BLOCK_LEDGER_TEMP'):\n"
            "    ledger_dir = Path('.observe/tmp/go-otel-resolver')\n"
            "    (ledger_dir / f'.accepted-plan.json.{os.getppid()}.tmp').write_text('blocked', encoding='utf-8')\n"
            "  if os.environ.get('FAKE_GO_FAIL_AFTER_EDIT'):\n"
            "    raise SystemExit(int(os.environ['FAKE_GO_FAIL_AFTER_EDIT']))\n"
            "if sys.argv[1:] == ['mod', 'tidy'] and os.environ.get('FAKE_GO_TIDY_DRIFT'):\n"
            "  go_mod = Path('go.mod')\n"
            "  go_mod.write_text(go_mod.read_text(encoding='utf-8').replace('v1.34.0', 'v1.99.0').replace('v0.59.0', 'v0.99.0'), encoding='utf-8')\n"
            "if sys.argv[1:] == ['mod', 'tidy'] and os.environ.get('FAKE_GO_TIDY_APPEND'):\n"
            "  with Path('go.sum').open('a', encoding='utf-8') as stream:\n"
            "    stream.write('tidied sum\\n')\n"
            "  if os.environ.get('FAKE_GO_BLOCK_LEDGER_TEMP'):\n"
            "    ledger_dir = Path('.observe/tmp/go-otel-resolver')\n"
            "    (ledger_dir / f'.accepted-plan.json.{os.getppid()}.tmp').write_text('blocked', encoding='utf-8')\n"
            "if os.environ.get('FAKE_GO_CLEAN'):\n"
            "  cache = Path(os.environ['GOCACHE'])\n"
            "  cache.mkdir(parents=True, exist_ok=True)\n"
            "  (cache / 'README').write_text('bookkeeping', encoding='utf-8')\n"
            "  (cache / 'trim.txt').write_text('bookkeeping', encoding='utf-8')\n"
            "  if os.environ['FAKE_GO_CLEAN'] == 'unexpected':\n"
            "    (cache / 'payload.a').write_text('bad', encoding='utf-8')\n"
            "  if os.environ['FAKE_GO_CLEAN'] == 'unexpected-dir':\n"
            "    (cache / 'unexpected-empty').mkdir(exist_ok=True)\n"
            "print('fake-go-stdout')\n"
            "print('fake-go-stderr', file=sys.stderr)\n"
            "raise SystemExit(int(os.environ.get('FAKE_GO_EXIT', '0')))\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return fake_bin

    def run_command(
        self,
        project: Path,
        cache: Path,
        fake_bin: Path,
        log: Path,
        *arguments: str,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
                "FAKE_GO_LOG": str(log),
                "GOMOD": "/hostile/outside/go.mod",
                "GOFLAGS": "-mod=vendor",
            }
        )
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--project",
                str(project),
                "--gomodcache",
                str(cache),
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def probe(
        self,
        project: Path,
        cache: Path,
        fake_bin: Path,
        log: Path,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            project,
            cache,
            fake_bin,
            log,
            "--action",
            "probe-bootstrap",
            extra_env=extra_env,
        )

    def test_go_get_uses_resolver_argv_exact_env_and_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            log = root / "go.json"

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                log,
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            invocation = json.loads(log.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(invocation["cwd"], str(project))
        self.assertEqual(invocation["argv"][0], "get")
        self.assertEqual(
            invocation["argv"][-1], f"{OTELHTTP}@v0.59.0"
        )
        self.assertEqual(set(invocation["env"]), set(PLAN_ENV_KEYS))
        self.assertTrue(all(value is not None for value in invocation["env"].values()))
        self.assertEqual(invocation["env"]["GOVCS"], "*:off")
        self.assertEqual(invocation["env"]["GOFLAGS"], "")
        self.assertIsNone(invocation["inherited_gomod"])
        notice = json.loads(completed.stdout.splitlines()[0])
        self.assertEqual(notice["action"], "go-get")
        self.assertEqual(notice["selection"]["version"], "v0.59.0")

    def test_complete_plan_go_get_rolls_back_then_persists_followup_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            original_mod = (project / "go.mod").read_bytes()

            failed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "failed-get.json",
                "--action",
                "go-get",
                extra_env={
                    "FAKE_GO_EDIT_PROJECT": "1",
                    "FAKE_GO_FAIL_AFTER_EDIT": "17",
                },
            )
            failed_mod = (project / "go.mod").read_bytes()
            failed_sum_exists = (project / "go.sum").exists()
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "applied-get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            followup = self.run_command(
                project,
                cache,
                fake_bin,
                root / "run.json",
                "--",
                "go",
                "run",
                "./cmd/service",
            )
            cleanup = self.run_command(
                project,
                cache,
                fake_bin,
                root / "cleanup-must-not-run.json",
                "--action",
                "cleanup",
            )
            owned_exists = (
                project / ".observe" / "tmp" / "go-otel-resolver"
            ).exists()

        self.assertEqual(failed.returncode, 17, failed.stderr)
        self.assertEqual(failed_mod, original_mod)
        self.assertFalse(failed_sum_exists)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(followup.returncode, 0, followup.stderr)
        self.assertEqual(cleanup.returncode, 0, cleanup.stderr)
        self.assertFalse(owned_exists)

    def test_complete_plan_ledger_write_failure_rolls_back_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            original_mod = (project / "go.mod").read_bytes()

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={
                    "FAKE_GO_EDIT_PROJECT": "1",
                    "FAKE_GO_BLOCK_LEDGER_TEMP": "1",
                },
            )
            restored_mod = (project / "go.mod").read_bytes()
            sum_exists = (project / "go.sum").exists()
            ledger = json.loads(
                (
                    project
                    / ".observe"
                    / "tmp"
                    / "go-otel-resolver"
                    / "accepted-plan.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("temporary path already exists", completed.stderr)
        self.assertEqual(restored_mod, original_mod)
        self.assertFalse(sum_exists)
        self.assertEqual(ledger["state"], "probed")

    def test_allowed_followup_preserves_literal_shell_metacharacters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            log = root / "go.json"
            marker = root / "must-not-exist"
            literal = f"$(touch {marker})"
            (project / "literal-match").write_text("x", encoding="utf-8")

            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                log,
                "--",
                "go",
                "test",
                "*",
                literal,
            )
            invocation = json.loads(log.read_text(encoding="utf-8"))

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(invocation["argv"], ["test", "*", literal])
        self.assertFalse(marker.exists())

    def test_complete_plan_rejects_followup_before_go_get_without_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            log = root / "must-not-run.json"
            ledger = (
                project
                / ".observe"
                / "tmp"
                / "go-otel-resolver"
                / "accepted-plan.json"
            )

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                log,
                "--",
                "go",
                "mod",
                "tidy",
                extra_env={"FAKE_GO_TIDY_APPEND": "1"},
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("exact pinned go-get", completed.stderr)
        self.assertFalse(log.exists())
        self.assertFalse((project / "go.sum").exists())
        self.assertFalse(ledger.exists())

    def test_rejects_unbounded_or_non_go_commands_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            log = root / "must-not-exist.json"
            cases = (
                ("--", "go", "mod", "edit", "-go=9.99"),
                ("--", "go", "env", "-w", "GOPROXY=evil"),
                ("--", "go", "clean", "-modcache"),
                ("--", "sh", "-c", "echo bad"),
                ("--", "go", "test", "-exec=/tmp/helper", "./..."),
                ("--", "go", "build", "-toolexec", "/tmp/helper", "./..."),
                ("--", "go", "test", "-vettool=/tmp/helper", "./..."),
            )

            results = [
                self.run_command(project, cache, fake_bin, log, *case)
                for case in cases
            ]

        self.assertTrue(all(result.returncode == 2 for result in results))
        self.assertFalse(log.exists())

    def test_symlinked_owned_cache_is_rejected_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            log = root / "must-not-exist.json"
            resolver_parent = project / ".observe" / "tmp"
            resolver_parent.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            (resolver_parent / "go-otel-resolver").symlink_to(
                outside, target_is_directory=True
            )

            completed = self.run_command(
                project, cache, fake_bin, log, "--action", "go-get"
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("symlink component", completed.stderr)
        self.assertFalse(log.exists())

    def test_symlink_launcher_cannot_replace_trusted_sibling_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            log = root / "go.json"
            attacker = root / "attacker"
            attacker.mkdir()
            launcher = attacker / "run_go_otel_command.py"
            launcher.symlink_to(RUNNER)
            marker = root / "malicious-resolver-loaded"
            (attacker / "resolve_go_otel_versions.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('loaded')\n"
                "raise RuntimeError('malicious resolver loaded')\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
                    "FAKE_GO_LOG": str(log),
                    "FAKE_GO_EDIT_PROJECT": "1",
                }
            )

            applied = subprocess.run(
                [
                    sys.executable,
                    str(launcher),
                    "--project",
                    str(project),
                    "--gomodcache",
                    str(cache),
                    "--action",
                    "go-get",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(launcher),
                    "--project",
                    str(project),
                    "--gomodcache",
                    str(cache),
                    "--",
                    "go",
                    "test",
                    "./...",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            marker_loaded = marker.exists()

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(marker_loaded)

    def test_child_output_and_exit_code_are_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            log = root / "go.json"

            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                log,
                "--",
                "go",
                "build",
                "./...",
                extra_env={"FAKE_GO_EXIT": "17"},
            )

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 17)
        self.assertIn("fake-go-stdout", completed.stdout)
        self.assertIn("fake-go-stderr", completed.stderr)

    def test_bootstrap_probe_stages_fixed_imports_and_writes_probed_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            log = root / "probe.json"

            completed = self.probe(project, cache, fake_bin, log)
            invocation = json.loads(log.read_text(encoding="utf-8"))
            result = json.loads(completed.stdout)
            ledger_path = (
                project
                / ".observe"
                / "tmp"
                / "go-otel-resolver"
                / "accepted-plan.json"
            )
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            project_mod_sha = hashlib.sha256(
                (project / "go.mod").read_bytes()
            ).hexdigest()
            stage_exists = (
                project
                / ".observe"
                / "tmp"
                / "go-otel-resolver"
                / "bootstrap-stage"
            ).exists()
            probe_cache_exists = (
                project
                / ".observe"
                / "tmp"
                / "go-otel-resolver"
                / "gomodcache"
            ).exists()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(invocation["argv"], ["mod", "tidy"])
        self.assertTrue(invocation["cwd"].endswith("bootstrap-stage"))
        self.assertEqual(invocation["env"]["GOTOOLCHAIN"], "local")
        self.assertEqual(invocation["env"]["GOVCS"], "*:off")
        self.assertEqual(invocation["env"]["GOSUMDB"], "off")
        self.assertTrue(invocation["env"]["GOPROXY"].startswith("file://"))
        self.assertIn('go.opentelemetry.io/otel/sdk/trace', invocation["main_go"])
        self.assertIn('go.opentelemetry.io/otel/sdk/metric', invocation["main_go"])
        self.assertEqual(result["status"], "accepted")
        self.assertIn("import-reachable", result["proof_boundary"])
        self.assertEqual(ledger["state"], "probed")
        self.assertEqual(ledger["go_mod_sha256"], project_mod_sha)
        self.assertFalse(stage_exists)
        self.assertFalse(probe_cache_exists)

    def test_bootstrap_missing_proxy_artifact_is_compact_and_edits_no_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, missing = self.make_bootstrap_fixture(
                root, missing_otel_transitive=True
            )
            fake_bin = self.make_fake_go(root)
            log = root / "probe.json"
            before = {
                path.relative_to(project): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }

            completed = self.probe(
                project,
                cache,
                fake_bin,
                log,
                extra_env={"FAKE_GO_REQUIRE_ARTIFACT": str(missing)},
            )
            after = {
                path.relative_to(project): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }

        self.assertEqual(completed.returncode, 19)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(len(completed.stderr.splitlines()), 1)
        blocker = json.loads(completed.stderr)
        self.assertEqual(blocker["reason"], "go-mod-tidy-failed")
        self.assertIn("artifact missing", blocker["detail"])
        self.assertEqual(before, after)

    def test_bootstrap_rejects_post_tidy_pin_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)

            completed = self.probe(
                project,
                cache,
                fake_bin,
                root / "probe.json",
                extra_env={"FAKE_GO_TIDY_DRIFT": "1"},
            )
            owned_exists = (
                project / ".observe" / "tmp" / "go-otel-resolver"
            ).exists()

        self.assertEqual(completed.returncode, 4)
        self.assertEqual(completed.stdout, "")
        blocker = json.loads(completed.stderr)
        self.assertEqual(
            blocker["reason"], "probe-post-tidy-invariant-failed"
        )
        self.assertIn("pins changed", blocker["detail"])
        self.assertFalse(owned_exists)

    def test_bootstrap_directive_drift_rolls_back_successful_go_get(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            probe_log = root / "probe.json"
            get_log = root / "get.json"
            self.assertEqual(
                self.probe(project, cache, fake_bin, probe_log).returncode, 0
            )
            original_mod = (project / "go.mod").read_bytes()

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                get_log,
                "--action",
                "go-get",
                extra_env={
                    "FAKE_GO_EDIT_PROJECT": "1",
                    "FAKE_GO_DIRECTIVE_DRIFT": "1",
                },
            )
            ledger = json.loads(
                (
                    project
                    / ".observe"
                    / "tmp"
                    / "go-otel-resolver"
                    / "accepted-plan.json"
                ).read_text(encoding="utf-8")
            )
            restored_mod = (project / "go.mod").read_bytes()
            sum_exists = (project / "go.sum").exists()

        self.assertEqual(completed.returncode, 2)
        self.assertIn("directives changed", completed.stderr)
        self.assertEqual(restored_mod, original_mod)
        self.assertFalse(sum_exists)
        self.assertEqual(ledger["state"], "probed")

    def test_bootstrap_go_get_failure_rolls_back_mod_and_sum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            self.probe(project, cache, fake_bin, root / "probe.json")
            (project / "go.sum").write_text("original sum\n", encoding="utf-8")
            # Re-probe binds the now-present go.sum into a fresh probed ledger.
            self.probe(project, cache, fake_bin, root / "reprobe.json")
            original_mod = (project / "go.mod").read_bytes()
            original_sum = (project / "go.sum").read_bytes()

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={
                    "FAKE_GO_EDIT_PROJECT": "1",
                    "FAKE_GO_FAIL_AFTER_EDIT": "17",
                },
            )
            restored_mod = (project / "go.mod").read_bytes()
            restored_sum = (project / "go.sum").read_bytes()

        self.assertEqual(completed.returncode, 17, completed.stderr)
        self.assertEqual(restored_mod, original_mod)
        self.assertEqual(restored_sum, original_sum)

    def test_bootstrap_state_machine_applies_pins_advances_tidy_and_rejects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            self.probe(project, cache, fake_bin, root / "probe.json")

            premature = self.run_command(
                project,
                cache,
                fake_bin,
                root / "premature.json",
                "--",
                "go",
                "test",
                "./...",
            )
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            ledger_path = (
                project
                / ".observe"
                / "tmp"
                / "go-otel-resolver"
                / "accepted-plan.json"
            )
            applied_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            tidied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "tidy.json",
                "--",
                "go",
                "mod",
                "tidy",
                extra_env={"FAKE_GO_TIDY_APPEND": "1"},
            )
            tidy_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            (project / "go.mod").write_text(
                (project / "go.mod").read_text(encoding="utf-8") + "\n// drift\n",
                encoding="utf-8",
            )
            drifted = self.run_command(
                project,
                cache,
                fake_bin,
                root / "must-not-run.json",
                "--",
                "go",
                "test",
                "./...",
            )

        self.assertEqual(premature.returncode, 2)
        self.assertIn("exact pinned go-get", premature.stderr)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(applied_ledger["state"], "applied")
        self.assertEqual(tidied.returncode, 0, tidied.stderr)
        self.assertNotEqual(applied_ledger["go_sum"], tidy_ledger["go_sum"])
        self.assertEqual(drifted.returncode, 2)
        self.assertIn("go.mod SHA drift", drifted.stderr)

    def test_bootstrap_tidy_ledger_failure_rolls_back_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            self.probe(project, cache, fake_bin, root / "probe.json")
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            ledger_path = (
                project
                / ".observe"
                / "tmp"
                / "go-otel-resolver"
                / "accepted-plan.json"
            )
            before_sum = (project / "go.sum").read_bytes()
            before_ledger = ledger_path.read_bytes()

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "tidy.json",
                "--",
                "go",
                "mod",
                "tidy",
                extra_env={
                    "FAKE_GO_TIDY_APPEND": "1",
                    "FAKE_GO_BLOCK_LEDGER_TEMP": "1",
                },
            )
            restored_sum = (project / "go.sum").read_bytes()
            restored_ledger = ledger_path.read_bytes()

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("temporary path already exists", completed.stderr)
        self.assertEqual(restored_sum, before_sum)
        self.assertEqual(restored_ledger, before_ledger)

    def test_bootstrap_probe_rejects_symlink_escape_and_existing_otel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            outside = root / "outside"
            outside.mkdir()
            resolver_parent = project / ".observe" / "tmp"
            resolver_parent.mkdir(parents=True)
            (resolver_parent / "go-otel-resolver").symlink_to(
                outside, target_is_directory=True
            )

            escaped = self.probe(
                project, cache, fake_bin, root / "must-not-run.json"
            )
            (resolver_parent / "go-otel-resolver").unlink()
            (project / "go.mod").write_text(
                "module example.test/bootstrap\n\ngo 1.23\n\n"
                "require go.opentelemetry.io/otel v1.34.0\n",
                encoding="utf-8",
            )
            existing = self.probe(
                project, cache, fake_bin, root / "still-must-not-run.json"
            )

        self.assertEqual(escaped.returncode, 2)
        self.assertIn("symlink component", escaped.stderr)
        self.assertEqual(existing.returncode, 2)
        self.assertIn("no OTel requirements", existing.stderr)

    def test_bootstrap_rejects_source_cache_overlapping_owned_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            overlap = (
                project
                / ".observe"
                / "tmp"
                / "go-otel-resolver"
                / "gomodcache"
            )
            overlap.parent.mkdir(parents=True)
            cache.rename(overlap)
            marker = overlap / "source-cache-marker"
            marker.write_text("must survive", encoding="utf-8")

            completed = self.probe(
                project, overlap, fake_bin, root / "must-not-run.json"
            )
            source_survived = marker.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("overlaps the runner-owned directory", completed.stderr)
        self.assertEqual(source_survived, "must survive")

    def test_bootstrap_rejects_file_proxy_symlink_targeting_owned_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            proxy = cache / "cache" / "download"
            source_target = (
                project
                / ".observe"
                / "tmp"
                / "go-otel-resolver"
                / "source-proxy"
            )
            source_target.parent.mkdir(parents=True)
            proxy.rename(source_target)
            proxy.symlink_to(source_target, target_is_directory=True)
            marker = source_target / "source-cache-marker"
            marker.write_text("must survive", encoding="utf-8")

            completed = self.probe(
                project, cache, fake_bin, root / "must-not-run.json"
            )
            source_survived = marker.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("file proxy overlaps", completed.stderr)
        self.assertEqual(source_survived, "must survive")

    def test_bootstrap_cleanup_removes_read_only_owned_tree_compactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            self.probe(project, cache, fake_bin, root / "probe.json")
            owned = project / ".observe" / "tmp" / "go-otel-resolver"
            nested = owned / "gomodcache" / "read-only"
            nested.mkdir(parents=True)
            payload = nested / "module.a"
            payload.write_text("cache", encoding="utf-8")
            payload.chmod(0o400)
            nested.chmod(0o500)

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "must-not-run.json",
                "--action",
                "cleanup",
            )
            owned_exists = owned.exists()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(completed.stdout.splitlines()), 1)
        self.assertEqual(json.loads(completed.stdout)["status"], "complete")
        self.assertFalse(owned_exists)

    def test_cleanup_accepts_only_allowlisted_bookkeeping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            allowed_log = root / "allowed.json"
            bad_log = root / "bad.json"

            allowed = self.run_command(
                project,
                cache,
                fake_bin,
                allowed_log,
                "--action",
                "cleanup",
                extra_env={"FAKE_GO_CLEAN": "allowed"},
            )
            bad = self.run_command(
                project,
                cache,
                fake_bin,
                bad_log,
                "--action",
                "cleanup",
                extra_env={"FAKE_GO_CLEAN": "unexpected"},
            )

        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(bad.returncode, 3)
        self.assertIn("unexpected cache payloads", bad.stderr)

    def test_cleanup_rejects_unexpected_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "cleanup.json",
                "--action",
                "cleanup",
                extra_env={"FAKE_GO_CLEAN": "unexpected-dir"},
            )

        self.assertEqual(completed.returncode, 3)
        self.assertIn("directory:", completed.stderr)


if __name__ == "__main__":
    unittest.main()
