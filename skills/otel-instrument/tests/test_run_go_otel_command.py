from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


RUNNER = Path(__file__).parents[1] / "scripts" / "run_go_otel_command.py"
RESOLVER = RUNNER.with_name("resolve_go_otel_versions.py")
SPEC = importlib.util.spec_from_file_location("run_go_otel_command", RUNNER)
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
ARTIFACTS = ("mod", "info", "zip", "ziphash")
PLAN_ENV_KEYS = (
    "CGO_ENABLED",
    "GOCACHE",
    "GOARCH",
    "GOENV",
    "GOFLAGS",
    "GOMODCACHE",
    "GONOPROXY",
    "GONOSUMDB",
    "GOOS",
    "GOPATH",
    "GOPRIVATE",
    "GOPROXY",
    "GOSUMDB",
    "GOTELEMETRY",
    "GOTOOLCHAIN",
    "GOVCS",
    "GOWORK",
    "HOME",
)
SCRUBBED_BUILD_ENV_KEYS = (
    "AR",
    "CC",
    "CGO_CFLAGS",
    "CGO_CXXFLAGS",
    "CGO_LDFLAGS",
    "CXX",
    "PKG_CONFIG",
)
LOG_ENV_KEYS = PLAN_ENV_KEYS + SCRUBBED_BUILD_ENV_KEYS


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
    def setUp(self) -> None:
        self.plan_digests: dict[Path, str] = {}

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
            "module example.test/bootstrap\n\ngo 1.23\n\n"
            "require example.test/project-dependency v1.0.0\n",
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
                    (
                        (missing_module, "v1.0.0"),
                        ("github.com/bazelbuild/rules_go", "v0.50.1"),
                        ("github.com/go-logr/logr", "v1.4.2"),
                        ("github.com/go-logr/stdr", "v1.2.2"),
                        ("github.com/yuin/goldmark", "v1.7.8"),
                    )
                    if module == "go.opentelemetry.io/otel/sdk"
                    else ()
                ),
            )
        # The invocation-owned proxy stages every artifact in the bounded
        # import closure. The failure fixture removes one required zip.
        write_proxy_module(
            cache,
            missing_module,
            "v1.0.0",
            go_version="1.20",
        )
        if missing_otel_transitive:
            missing_artifact.unlink()
        for module, version in (
            ("github.com/bazelbuild/rules_go", "v0.50.1"),
            ("github.com/yuin/goldmark", "v1.7.8"),
        ):
            write_proxy_module(
                cache,
                module,
                version,
                go_version="1.20",
            )
            artifact(cache, module, version, "zip").unlink()
            artifact(cache, module, version, "ziphash").unlink()
        write_proxy_module(
            cache,
            "github.com/go-logr/logr",
            "v1.4.2",
            go_version="1.20",
        )
        write_proxy_module(
            cache,
            "github.com/go-logr/stdr",
            "v1.2.2",
            go_version="1.20",
            requirements=(("github.com/go-logr/logr", "v1.2.2"),),
        )
        write_proxy_module(
            cache,
            "github.com/go-logr/logr",
            "v1.2.2",
            go_version="1.18",
        )
        artifact(cache, "github.com/go-logr/logr", "v1.2.2", "zip").unlink()
        artifact(cache, "github.com/go-logr/logr", "v1.2.2", "ziphash").unlink()
        write_proxy_module(
            cache,
            "example.test/project-dependency",
            "v1.0.0",
            go_version="1.20",
        )
        return project.resolve(), cache.resolve(), missing_artifact.resolve()

    def make_fake_go(self, root: Path) -> Path:
        fake_bin = root / "fake bin"
        fake_bin.mkdir()
        script = fake_bin / "go"
        script.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "if sys.argv[1:] == ['version']:\n"
            "  version_payload = {\n"
            "    'cwd': os.getcwd(),\n"
            f"    'env': {{key: os.environ.get(key) for key in {LOG_ENV_KEYS!r}}},\n"
            "    'inherited_gomod': os.environ.get('GOMOD'),\n"
            "  }\n"
            "  if os.environ.get('FAKE_GO_VERSION_LOG'):\n"
            "    with Path(os.environ['FAKE_GO_VERSION_LOG']).open('a', encoding='utf-8') as stream:\n"
            "      stream.write(json.dumps(version_payload) + '\\n')\n"
            "  if os.environ.get('FAKE_GO_WRITE_VERSION_TELEMETRY'):\n"
            "    telemetry = Path(os.environ['HOME']) / 'Library/Application Support/go/telemetry/local'\n"
            "    telemetry.mkdir(parents=True, exist_ok=True)\n"
            "    (telemetry / 'weekends').write_text('1', encoding='utf-8')\n"
            "  print(os.environ.get('FAKE_GO_VERSION_OVERRIDE', 'go version go1.23.0 test/amd64'))\n"
            "  raise SystemExit(0)\n"
            f"keys = {LOG_ENV_KEYS!r}\n"
            "payload = {\n"
            "  'argv': sys.argv[1:],\n"
            "  'cwd': os.getcwd(),\n"
            "  'env': {key: os.environ.get(key) for key in keys},\n"
            "  'inherited_gomod': os.environ.get('GOMOD'),\n"
            "  'go_mod': (Path('go.mod').read_text(encoding='utf-8') if Path('go.mod').is_file() else None),\n"
            "  'main_go': (Path('main.go').read_text(encoding='utf-8') if Path('main.go').is_file() else None),\n"
            "}\n"
            "Path(os.environ['FAKE_GO_LOG']).write_text(json.dumps(payload), encoding='utf-8')\n"
            "if os.environ.get('FAKE_GO_SEQUENCE_LOG'):\n"
            "  with Path(os.environ['FAKE_GO_SEQUENCE_LOG']).open('a', encoding='utf-8') as stream:\n"
            "    stream.write(json.dumps(payload) + '\\n')\n"
            "required = os.environ.get('FAKE_GO_REQUIRE_ARTIFACT')\n"
            "if required and not Path(required).is_file():\n"
            "  print('file proxy artifact missing', file=sys.stderr)\n"
            "  raise SystemExit(19)\n"
            "required_relative = os.environ.get('FAKE_GO_REQUIRE_PROXY_RELATIVE')\n"
            "if required_relative:\n"
            "  from urllib.parse import unquote, urlparse\n"
            "  proxy = Path(unquote(urlparse(os.environ['GOPROXY']).path))\n"
            "  if not (proxy / required_relative).is_file():\n"
            "    print('staged file proxy artifact missing', file=sys.stderr)\n"
            "    raise SystemExit(19)\n"
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
            "    blocked = os.environ.get('FAKE_GO_BLOCK_GO_GET_ROLLBACK')\n"
            "    if blocked:\n"
            "      Path(f'.{blocked}.{os.getppid()}.tmp').write_text('blocked', encoding='utf-8')\n"
            "    print('go get failed after edit')\n"
            "    print('go get failed after edit', file=sys.stderr)\n"
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
            "control_argv = list(sys.argv[1:])\n"
            "if control_argv[:1] == ['build']:\n"
            "  output_args = [item for item in control_argv if item.startswith('-o=')]\n"
            "  if len(output_args) > 1 or (os.environ.get('FAKE_GO_WRITE_BUILD_OUTPUT') and len(output_args) != 1):\n"
            "    print('isolated build output missing', file=sys.stderr)\n"
            "    raise SystemExit(32)\n"
            "  if output_args:\n"
            "    output = Path(output_args[0].split('=', 1)[1])\n"
            "    if os.environ.get('FAKE_GO_WRITE_BUILD_OUTPUT'):\n"
            "      (output / 'fake-service').write_text('binary', encoding='utf-8')\n"
            "    control_argv.remove(output_args[0])\n"
            "command = ' '.join(control_argv)\n"
            "if os.environ.get('FAKE_GO_MUTATE_PROXY_SOURCE') and command != 'version':\n"
            "  from urllib.parse import unquote, urlparse\n"
            "  source = Path(os.environ['FAKE_GO_MUTATE_PROXY_SOURCE'])\n"
            "  source.write_bytes(b'mutated after runner check')\n"
            "  proxy = Path(unquote(urlparse(os.environ['GOPROXY']).path))\n"
            "  staged = proxy / os.environ['FAKE_GO_PROXY_RELATIVE']\n"
            "  if staged.read_bytes() != os.environ['FAKE_GO_PROXY_EXPECTED'].encode():\n"
            "    print('staged proxy did not preserve checked bytes', file=sys.stderr)\n"
            "    raise SystemExit(31)\n"
            "if os.environ.get('FAKE_GO_MUTATE_LEDGER_COMMAND') == command:\n"
            "  ledger = Path('.observe/tmp/go-otel-resolver/accepted-plan.json')\n"
            "  ledger.write_text(json.dumps(json.loads(ledger.read_text()), indent=2) + '\\n', encoding='utf-8')\n"
            "if os.environ.get('FAKE_GO_MUTATE_SOURCE_COMMAND') == command:\n"
            "  Path('generated.go').write_text('package generated\\n', encoding='utf-8')\n"
            "if os.environ.get('FAKE_GO_MUTATE_MANIFEST_COMMAND') == command:\n"
            "  with Path('go.mod').open('a', encoding='utf-8') as stream:\n"
            "    stream.write('\\n// failed command drift\\n')\n"
            "  with Path('go.sum').open('a', encoding='utf-8') as stream:\n"
            "    stream.write('failed command drift\\n')\n"
            "  blocked = os.environ.get('FAKE_GO_BLOCK_MANIFEST_ROLLBACK')\n"
            "  if blocked:\n"
            "    Path(f'.{blocked}.{os.getppid()}.tmp').write_text('blocked', encoding='utf-8')\n"
            "if os.environ.get('FAKE_GO_MUTATE_OBSERVE_COMMAND') == command:\n"
            "  marker = Path('.observe/runtime-marker')\n"
            "  marker.parent.mkdir(parents=True, exist_ok=True)\n"
            "  marker.write_text('changed', encoding='utf-8')\n"
            "if os.environ.get('FAKE_GO_DIAGNOSTIC'):\n"
            "  print(os.environ['FAKE_GO_DIAGNOSTIC'], file=sys.stderr)\n"
            "if os.environ.get('FAKE_GO_OUTPUT_BYTES'):\n"
            "  size = int(os.environ['FAKE_GO_OUTPUT_BYTES'])\n"
            "  sentinel = os.environ.get('FAKE_GO_SECRET', 'TOP-SECRET').encode()\n"
            "  os.write(1, sentinel + b'x' * size)\n"
            "  os.write(2, sentinel + b'y' * size)\n"
            "print('fake-go-stdout')\n"
            "print('fake-go-stderr', file=sys.stderr)\n"
            "if os.environ.get('FAKE_GO_FAIL_COMMAND') == command:\n"
            "  raise SystemExit(int(os.environ.get('FAKE_GO_FAIL_EXIT', '23')))\n"
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
        plan: Path | None = None,
        plan_sha256: str | None = None,
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
        if plan is None or plan_sha256 is None:
            plan, plan_sha256 = self.ensure_plan(project, cache, fake_bin)
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--project",
                str(project),
                "--gomodcache",
                str(cache),
                "--plan",
                str(plan),
                "--plan-sha256",
                plan_sha256,
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def ensure_plan(
        self, project: Path, cache: Path, fake_bin: Path
    ) -> tuple[Path, str]:
        plan = project / ".observe" / "tmp" / "go-otel-version-plan.json"
        if project not in self.plan_digests:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RESOLVER),
                    "--project",
                    str(project),
                    "--gomodcache",
                    str(cache),
                    "--go-executable",
                    str(fake_bin / "go"),
                    "--output",
                    str(plan),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.plan_digests[project] = summary["plan_sha256"]
        return plan, self.plan_digests[project]

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
                extra_env={
                    "FAKE_GO_EDIT_PROJECT": "1",
                    "CGO_ENABLED": "1",
                    "CC": "/hostile/cc",
                    "CXX": "/hostile/cxx",
                    "CGO_CFLAGS": "-DHOSTILE",
                    "GOOS": "plan9",
                    "GOARCH": "386",
                },
            )
            invocation = json.loads(log.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(invocation["cwd"], str(project))
        self.assertEqual(invocation["argv"][0], "get")
        self.assertEqual(
            invocation["argv"][-1], f"{OTELHTTP}@v0.59.0"
        )
        self.assertEqual(set(invocation["env"]), set(LOG_ENV_KEYS))
        self.assertTrue(
            all(invocation["env"][key] is not None for key in PLAN_ENV_KEYS)
        )
        self.assertTrue(
            all(invocation["env"][key] is None for key in SCRUBBED_BUILD_ENV_KEYS)
        )
        self.assertEqual(invocation["env"]["CGO_ENABLED"], "0")
        self.assertEqual(invocation["env"]["GOOS"], "test")
        self.assertEqual(invocation["env"]["GOARCH"], "amd64")
        self.assertEqual(invocation["env"]["GOVCS"], "*:off")
        self.assertEqual(invocation["env"]["GOTELEMETRY"], "off")
        self.assertEqual(invocation["env"]["GOFLAGS"], "")
        self.assertIsNone(invocation["inherited_gomod"])
        notice = json.loads(completed.stdout.splitlines()[0])
        self.assertEqual(notice["action"], "go-get")
        self.assertEqual(notice["selection"]["version"], "v0.59.0")

    def test_runner_uses_bound_plan_when_cache_gains_newer_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            plan, plan_sha256 = self.ensure_plan(project, cache, fake_bin)
            write_proxy_module(
                cache,
                OTELHTTP,
                "v0.63.0",
                go_version="1.23.0",
                core_version="v1.38.0",
            )
            for module in COMPANIONS:
                write_proxy_module(
                    cache,
                    module,
                    "v1.38.0",
                    go_version="1.23.0",
                )
            log = root / "go.json"

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                log,
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
                plan=plan,
                plan_sha256=plan_sha256,
            )
            invocation = json.loads(log.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(f"{OTELHTTP}@v0.59.0", invocation["argv"])
        self.assertNotIn(f"{OTELHTTP}@v0.63.0", invocation["argv"])

    def test_runner_rejects_plan_content_and_cache_binding_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            plan, plan_sha256 = self.ensure_plan(project, cache, fake_bin)
            plan.write_bytes(plan.read_bytes() + b"\n")
            log = root / "must-not-run.json"

            changed_plan = self.run_command(
                project,
                cache,
                fake_bin,
                log,
                "--action",
                "go-get",
                plan=plan,
                plan_sha256=plan_sha256,
            )
            other_cache = root / "other-cache"
            other_cache.mkdir()
            cache_drift = self.run_command(
                project,
                other_cache,
                fake_bin,
                log,
                "--action",
                "go-get",
                plan=plan,
                plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
            )

        self.assertEqual(changed_plan.returncode, 2)
        self.assertIn("plan SHA-256 drift", changed_plan.stderr)
        self.assertEqual(cache_drift.returncode, 2)
        self.assertIn("module-cache drift", cache_drift.stderr)
        self.assertFalse(log.exists())

    def test_applied_ledger_rejects_rebound_plan_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            plan, plan_sha256 = self.ensure_plan(project, cache, fake_bin)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
                plan=plan,
                plan_sha256=plan_sha256,
            )
            plan.write_bytes(plan.read_bytes() + b"\n")
            rebound_sha256 = hashlib.sha256(plan.read_bytes()).hexdigest()
            log = root / "must-not-run.json"
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                log,
                "--action",
                "validate",
                plan=plan,
                plan_sha256=rebound_sha256,
            )

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("persisted resolver plan drift", completed.stderr)
        self.assertFalse(log.exists())

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

    def test_validate_serializes_fixed_gate_with_compact_digest_bound_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            sequence = root / "sequence.jsonl"
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "last.json",
                "--action",
                "validate",
                extra_env={
                    "FAKE_GO_SEQUENCE_LOG": str(sequence),
                    "FAKE_GO_TIDY_APPEND": "1",
                    "CGO_ENABLED": "1",
                    "CC": "/hostile/cc",
                    "CXX": "/hostile/cxx",
                    "CGO_LDFLAGS": "-L/hostile",
                    "GOOS": "plan9",
                    "GOARCH": "386",
                },
            )
            invocations = [
                json.loads(line)
                for line in sequence.read_text(encoding="utf-8").splitlines()
            ]
            evidence_path = (
                project / ".observe" / "evidence" / "go-otel-validation.json"
            )
            evidence_payload = evidence_path.read_bytes()
            evidence = json.loads(evidence_payload)
            summary = json.loads(completed.stdout)

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(invocations[0]["argv"], ["mod", "tidy"])
        self.assertEqual(invocations[1]["argv"][0], "build")
        self.assertTrue(invocations[1]["argv"][1].startswith("-o="))
        self.assertFalse(
            Path(invocations[1]["argv"][1].removeprefix("-o=")).is_relative_to(
                project
            )
        )
        self.assertEqual(invocations[1]["argv"][2:], ["./..."])
        self.assertEqual(invocations[2]["argv"], ["test", "./..."])
        for key in ("GOCACHE", "GOMODCACHE", "GOPATH", "HOME"):
            self.assertEqual(len({item["env"][key] for item in invocations}), 1)
        self.assertEqual(invocations[0]["env"]["GOFLAGS"], "")
        self.assertEqual(invocations[1]["env"]["GOFLAGS"], "-mod=readonly")
        self.assertEqual(invocations[2]["env"]["GOFLAGS"], "-mod=readonly")
        for invocation in invocations:
            self.assertEqual(invocation["env"]["CGO_ENABLED"], "0")
            self.assertEqual(invocation["env"]["GOOS"], "test")
            self.assertEqual(invocation["env"]["GOARCH"], "amd64")
            for key in SCRUBBED_BUILD_ENV_KEYS:
                self.assertIsNone(invocation["env"][key])
        self.assertEqual(summary["action"], "validate")
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["commands_completed"], 3)
        self.assertEqual(
            summary["evidence"], ".observe/evidence/go-otel-validation.json"
        )
        self.assertEqual(
            summary["evidence_sha256"],
            hashlib.sha256(evidence_payload).hexdigest(),
        )
        self.assertNotIn("fake-go-stdout", completed.stdout)
        self.assertNotIn("fake-go-stderr", completed.stderr)
        self.assertEqual(evidence["status"], "passed")
        runtime_environment = evidence["runtime"]["environment"]
        self.assertEqual(runtime_environment["CGO_ENABLED"], "0")
        self.assertEqual(runtime_environment["GOOS"], "test")
        self.assertEqual(runtime_environment["GOARCH"], "amd64")
        self.assertIsNone(runtime_environment["CC"])
        self.assertIsNone(runtime_environment["CXX"])
        self.assertIsNone(runtime_environment["CGO_LDFLAGS"])
        self.assertEqual(
            [row["environment"]["GOFLAGS"] for row in evidence["commands"]],
            ["", "-mod=readonly", "-mod=readonly"],
        )
        self.assertEqual(
            [item["argv"] for item in evidence["commands"]],
            [
                [str((fake_bin / "go").resolve()), "mod", "tidy"],
                [
                    str((fake_bin / "go").resolve()),
                    "build",
                    "-o=$INVOCATION/build-output",
                    "./...",
                ],
                [str((fake_bin / "go").resolve()), "test", "./..."],
            ],
        )
        self.assertTrue(
            all(
                item["stdout_bytes"] == len(b"fake-go-stdout\n")
                for item in evidence["commands"]
            )
        )
        self.assertTrue(
            all(
                item["stderr_bytes"] == len(b"fake-go-stderr\n")
                for item in evidence["commands"]
            )
        )
        self.assertTrue(
            all("stdout" not in item and "stderr" not in item for item in evidence["commands"])
        )
        self.assertEqual(
            evidence["accepted_plan"]["sha256_after"],
            summary["accepted_plan_sha256"],
        )
        self.assertNotEqual(
            evidence["accepted_plan"]["sha256_before"],
            evidence["accepted_plan"]["sha256_after"],
        )

    def test_validate_stops_after_first_failure_and_saves_full_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            sequence = root / "sequence.jsonl"
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "last.json",
                "--action",
                "validate",
                extra_env={
                    "FAKE_GO_SEQUENCE_LOG": str(sequence),
                    "FAKE_GO_FAIL_COMMAND": "build ./...",
                    "FAKE_GO_FAIL_EXIT": "23",
                },
            )
            invocations = [
                json.loads(line)
                for line in sequence.read_text(encoding="utf-8").splitlines()
            ]
            evidence = json.loads(
                (
                    project
                    / ".observe"
                    / "evidence"
                    / "go-otel-validation.json"
                ).read_text(encoding="utf-8")
            )
            summary = json.loads(completed.stdout)

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 23, completed.stderr)
        self.assertEqual(invocations[0]["argv"], ["mod", "tidy"])
        self.assertEqual(invocations[1]["argv"][0], "build")
        self.assertTrue(invocations[1]["argv"][1].startswith("-o="))
        self.assertEqual(invocations[1]["argv"][2:], ["./..."])
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["failed_command"], "build")
        self.assertEqual(summary["exit_code"], 23)
        self.assertEqual(evidence["status"], "failed")
        self.assertEqual(evidence["failed_command"], "build")
        self.assertEqual(len(evidence["commands"]), 2)
        self.assertEqual(evidence["commands"][1]["exit_code"], 23)
        self.assertEqual(
            evidence["commands"][1]["stderr_sha256"],
            hashlib.sha256(b"fake-go-stderr\n").hexdigest(),
        )

    def test_validation_failure_returns_bounded_structured_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            diagnostic_line = (
                'kvstore/telemetry.go:11:2: "codes" imported and not used'
            )
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "last.json",
                "--action",
                "validate",
                extra_env={
                    "FAKE_GO_DIAGNOSTIC": diagnostic_line,
                    "FAKE_GO_FAIL_COMMAND": "build ./...",
                    "FAKE_GO_FAIL_EXIT": "23",
                },
            )
            evidence = json.loads(
                (project / MODULE.VALIDATION_EVIDENCE).read_text(encoding="utf-8")
            )
            summary = json.loads(completed.stdout)

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 23, completed.stderr)
        diagnostic = summary["diagnostic"]
        self.assertEqual(diagnostic, evidence["commands"][1]["diagnostic"])
        self.assertEqual(diagnostic["category"], "compile_error")
        self.assertEqual(
            diagnostic["location"],
            {"path": "kvstore/telemetry.go", "line": 11, "column": 2},
        )
        self.assertEqual(diagnostic["excerpt"], diagnostic_line)
        self.assertEqual(diagnostic["source"], "stderr")
        self.assertFalse(diagnostic["truncated"])
        self.assertLessEqual(
            len(diagnostic["excerpt"]), MODULE.MAX_DIAGNOSTIC_EXCERPT_CHARS
        )

    def test_validation_failure_redacts_secret_and_caps_huge_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            secret = "sentinel-do-not-persist"
            size = 100_000
            diagnostic_line = (
                "kvstore/telemetry.go:12:3: Authorization: Bearer " + secret
            )
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "last.json",
                "--action",
                "validate",
                extra_env={
                    "FAKE_GO_DIAGNOSTIC": diagnostic_line,
                    "FAKE_GO_FAIL_COMMAND": "build ./...",
                    "FAKE_GO_FAIL_EXIT": "23",
                    "FAKE_GO_OUTPUT_BYTES": str(size),
                    "FAKE_GO_SECRET": secret,
                },
            )
            evidence_payload = (project / MODULE.VALIDATION_EVIDENCE).read_bytes()
            evidence = json.loads(evidence_payload)
            summary = json.loads(completed.stdout)

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 23, completed.stderr)
        self.assertNotIn(secret, completed.stdout)
        self.assertNotIn(secret, completed.stderr)
        self.assertNotIn(secret.encode(), evidence_payload)
        diagnostic = summary["diagnostic"]
        self.assertEqual(diagnostic, evidence["commands"][1]["diagnostic"])
        self.assertEqual(diagnostic["category"], "compile_error")
        self.assertEqual(
            diagnostic["excerpt"],
            "kvstore/telemetry.go:12:3: <redacted sensitive diagnostic>",
        )
        self.assertTrue(diagnostic["redacted"])
        self.assertTrue(diagnostic["truncated"])
        self.assertLessEqual(
            len(diagnostic["excerpt"]), MODULE.MAX_DIAGNOSTIC_EXCERPT_CHARS
        )
        failed = evidence["commands"][1]
        self.assertFalse(any(key.startswith("_diagnostic_") for key in failed))
        stdout = secret.encode() + b"x" * size + b"fake-go-stdout\n"
        stderr = (
            diagnostic_line.encode()
            + b"\n"
            + secret.encode()
            + b"y" * size
            + b"fake-go-stderr\n"
        )
        self.assertEqual(failed["stdout_bytes"], len(stdout))
        self.assertEqual(failed["stdout_sha256"], hashlib.sha256(stdout).hexdigest())
        self.assertEqual(failed["stderr_bytes"], len(stderr))
        self.assertEqual(failed["stderr_sha256"], hashlib.sha256(stderr).hexdigest())

    def test_validation_build_output_is_external_and_disposable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            sequence = root / "sequence.jsonl"
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "validate.json",
                "--action",
                "validate",
                extra_env={
                    "FAKE_GO_SEQUENCE_LOG": str(sequence),
                    "FAKE_GO_WRITE_BUILD_OUTPUT": "1",
                },
            )
            invocations = [
                json.loads(line)
                for line in sequence.read_text(encoding="utf-8").splitlines()
            ]
            output = Path(invocations[1]["argv"][1].removeprefix("-o="))
            project_output_exists = (project / "fake-service").exists()
            external_output_exists = output.exists()
            evidence = json.loads(
                (project / MODULE.VALIDATION_EVIDENCE).read_text(encoding="utf-8")
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(output.is_relative_to(project))
        self.assertFalse(project_output_exists)
        self.assertFalse(external_output_exists)
        self.assertEqual(
            evidence["commands"][1]["argv"][2],
            "-o=$INVOCATION/build-output",
        )
        self.assertEqual(
            evidence["runtime"]["build_output"], "$INVOCATION/build-output"
        )

    def test_validation_large_secret_output_is_digest_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            secret = "sentinel-do-not-persist"
            size = 2_000_000
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "last.json",
                "--action",
                "validate",
                extra_env={
                    "FAKE_GO_OUTPUT_BYTES": str(size),
                    "FAKE_GO_SECRET": secret,
                },
            )
            evidence_payload = (
                project / MODULE.VALIDATION_EVIDENCE
            ).read_bytes()
            evidence = json.loads(evidence_payload)

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn(secret, completed.stdout)
        self.assertNotIn(secret, completed.stderr)
        self.assertNotIn(secret.encode(), evidence_payload)
        stdout = secret.encode() + b"x" * size + b"fake-go-stdout\n"
        stderr = secret.encode() + b"y" * size + b"fake-go-stderr\n"
        for row in evidence["commands"]:
            self.assertNotIn("stdout", row)
            self.assertNotIn("stderr", row)
            self.assertEqual(row["stdout_bytes"], len(stdout))
            self.assertEqual(row["stdout_sha256"], hashlib.sha256(stdout).hexdigest())
            self.assertEqual(row["stderr_bytes"], len(stderr))
            self.assertEqual(row["stderr_sha256"], hashlib.sha256(stderr).hexdigest())

    def test_validation_restores_semantic_ledger_replacement_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            self.run_command(
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
                root / "last.json",
                "--action",
                "validate",
                extra_env={"FAKE_GO_MUTATE_LEDGER_COMMAND": "build ./..."},
            )
            evidence = json.loads((project / MODULE.VALIDATION_EVIDENCE).read_bytes())
            ledger_payload = (
                project / MODULE.OWNED_DIRECTORY / MODULE.LEDGER_NAME
            ).read_bytes()

        self.assertEqual(completed.returncode, 2)
        self.assertIn("exact-byte identity drift", evidence["runner_error"])
        self.assertEqual(
            hashlib.sha256(ledger_payload).hexdigest(),
            evidence["accepted_plan"]["sha256_after"],
        )
        self.assertNotIn(b"\n  ", ledger_payload)

    def test_check_validation_rejects_source_and_runtime_drift_but_not_observe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            (project / "service.go").write_text("package service\n", encoding="utf-8")
            fake_bin = self.make_fake_go(root)
            self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            validated = self.run_command(
                project,
                cache,
                fake_bin,
                root / "last.json",
                "--action",
                "validate",
                extra_env={"FAKE_GO_MUTATE_OBSERVE_COMMAND": "test ./..."},
            )
            fresh = self.run_command(
                project, cache, fake_bin, root / "check.json", "--action", "check-validation"
            )
            (project / "service.go").write_text("package service\n// drift\n", encoding="utf-8")
            source_drift = self.run_command(
                project, cache, fake_bin, root / "check2.json", "--action", "check-validation"
            )
            (project / "service.go").write_text("package service\n", encoding="utf-8")
            executable = fake_bin / "go"
            executable.write_bytes(executable.read_bytes() + b"\n# runtime drift\n")
            runtime_drift = self.run_command(
                project, cache, fake_bin, root / "check3.json", "--action", "check-validation"
            )

        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertEqual(source_drift.returncode, 2)
        self.assertIn("source-tree drift", source_drift.stderr)
        self.assertEqual(runtime_drift.returncode, 2)
        self.assertIn("runtime fingerprint drift", runtime_drift.stderr)

    def test_persisted_plan_rejects_selected_proxy_byte_drift_before_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            plan, plan_sha256 = self.ensure_plan(project, cache, fake_bin)
            selected_zip = artifact(cache, OTELHTTP, "v0.59.0", "zip")
            original = selected_zip.read_bytes()
            selected_zip.write_bytes(b"x" * len(original))
            action_log = root / "must-not-run.json"

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                action_log,
                "--action",
                "go-get",
                plan=plan,
                plan_sha256=plan_sha256,
            )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("source content drift while staging", completed.stderr)
        self.assertFalse(action_log.exists())

    def test_consuming_action_uses_invocation_owned_proxy_after_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            selected_zip = artifact(cache, OTELHTTP, "v0.59.0", "zip")
            source_proxy = cache / "cache" / "download"
            relative = selected_zip.relative_to(source_proxy).as_posix()

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "staged-get.json",
                "--action",
                "go-get",
                extra_env={
                    "FAKE_GO_EDIT_PROJECT": "1",
                    "FAKE_GO_MUTATE_PROXY_SOURCE": str(selected_zip),
                    "FAKE_GO_PROXY_RELATIVE": relative,
                    "FAKE_GO_PROXY_EXPECTED": "fixture zip",
                },
            )
            invocation = json.loads(
                (root / "staged-get.json").read_text(encoding="utf-8")
            )
            mutated_source = selected_zip.read_bytes()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(mutated_source, b"mutated after runner check")
        self.assertNotEqual(
            invocation["env"]["GOPROXY"], source_proxy.resolve().as_uri()
        )

    def test_applied_ledger_cannot_override_persisted_candidate_or_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            plan, plan_sha256 = self.ensure_plan(project, cache, fake_bin)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
                plan=plan,
                plan_sha256=plan_sha256,
            )
            ledger_path = project / MODULE.OWNED_DIRECTORY / MODULE.LEDGER_NAME
            original_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            resolver = MODULE.load_resolver()

            changed_candidate = dict(original_ledger)
            changed_candidate["candidate"] = {
                **changed_candidate["candidate"],
                "version": "v0.60.0",
                "core_version": "v1.35.0",
            }
            changed_candidate["modules"] = resolver.candidate_modules(
                changed_candidate["candidate"]
            )
            ledger_path.write_text(
                json.dumps(changed_candidate, separators=(",", ":"), sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            candidate_result = self.run_command(
                project,
                cache,
                fake_bin,
                root / "candidate-must-not-run.json",
                "--action",
                "validate",
                plan=plan,
                plan_sha256=plan_sha256,
            )

            alternate_root = root / "alternate"
            alternate_root.mkdir()
            alternate_bin = self.make_fake_go(alternate_root)
            plan_value = json.loads(plan.read_text(encoding="utf-8"))
            changed_runtime = dict(original_ledger)
            changed_runtime["runtime"] = resolver.go_runtime_fingerprint(
                alternate_bin / "go",
                cwd=project,
                environment=plan_value["go_commands"]["env"],
            )
            ledger_path.write_text(
                json.dumps(changed_runtime, separators=(",", ":"), sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            runtime_result = self.run_command(
                project,
                cache,
                fake_bin,
                root / "runtime-must-not-run.json",
                "--action",
                "validate",
                plan=plan,
                plan_sha256=plan_sha256,
            )

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(candidate_result.returncode, 2)
        self.assertIn("resolver candidate drift", candidate_result.stderr)
        self.assertEqual(runtime_result.returncode, 2)
        self.assertIn("Go runtime drift", runtime_result.stderr)

    def test_validation_freshness_binds_non_go_build_inputs_and_rejects_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            inputs = {
                "bin/generated.go": b"package generated\n",
                "build/generated.go": b"package generated\n",
                "dist/embedded.txt": b"distribution input\n",
                "embed.txt": b"embedded\n",
                "native/helper.c": b"int helper(void) { return 1; }\n",
                "native/helper.s": b"TEXT helper(SB),$0-0\n",
                "native/object.syso": b"bounded-object\n",
                "out/generated.go": b"package generated\n",
                "target/embedded.txt": b"target input\n",
                "testdata/input.json": b"{}\n",
            }
            for relative, payload in inputs.items():
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            fake_bin = self.make_fake_go(root)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            validated = self.run_command(
                project,
                cache,
                fake_bin,
                root / "validate.json",
                "--action",
                "validate",
            )
            drift_results: list[subprocess.CompletedProcess[str]] = []
            for index, (relative, payload) in enumerate(inputs.items()):
                path = project / relative
                path.write_bytes(payload + b"drift\n")
                drift_results.append(
                    self.run_command(
                        project,
                        cache,
                        fake_bin,
                        root / f"check-{index}.json",
                        "--action",
                        "check-validation",
                    )
                )
                path.write_bytes(payload)
            outside = root / "outside-input"
            outside.write_text("outside", encoding="utf-8")
            (project / "linked-input").symlink_to(outside)
            link_result = self.run_command(
                project,
                cache,
                fake_bin,
                root / "link-check.json",
                "--action",
                "check-validation",
            )

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertTrue(drift_results)
        for result in drift_results:
            self.assertEqual(result.returncode, 2)
            self.assertIn("source-tree drift", result.stderr)
        self.assertEqual(link_result.returncode, 2)
        self.assertIn("project input is a link", link_result.stderr)

    def test_check_validation_rejects_symlink_ancestor_for_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            validated = self.run_command(
                project, cache, fake_bin, root / "validate.json", "--action", "validate"
            )
            evidence_parent = project / MODULE.VALIDATION_EVIDENCE.parent
            real_parent = root / "moved-evidence"
            evidence_parent.rename(real_parent)
            evidence_parent.symlink_to(real_parent, target_is_directory=True)
            checked = self.run_command(
                project,
                cache,
                fake_bin,
                root / "must-not-run.json",
                "--action",
                "check-validation",
            )

        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertEqual(checked.returncode, 2)
        self.assertIn("symlink ancestor or reparse point", checked.stderr)
        self.assertIn("Go validation evidence", checked.stderr)

    def test_runtime_fingerprint_uses_bound_cwd_env_and_rechecks_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            plan = project / ".observe" / "tmp" / "go-otel-version-plan.json"
            version_log = root / "versions.jsonl"
            resolver_env = os.environ.copy()
            resolver_env.update(
                {
                    "PATH": f"{fake_bin}{os.pathsep}{resolver_env.get('PATH', '')}",
                    "FAKE_GO_VERSION_LOG": str(version_log),
                    "GOMOD": "/hostile/go.mod",
                    "GOTOOLCHAIN": "auto",
                    "GOENV": "/hostile/goenv",
                    "GOWORK": "/hostile/go.work",
                }
            )
            resolved = subprocess.run(
                [
                    sys.executable,
                    str(RESOLVER),
                    "--project",
                    str(project),
                    "--gomodcache",
                    str(cache),
                    "--go-executable",
                    str(fake_bin / "go"),
                    "--output",
                    str(plan),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=resolver_env,
            )
            summary = json.loads(resolved.stdout)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={
                    "FAKE_GO_EDIT_PROJECT": "1",
                    "FAKE_GO_VERSION_LOG": str(version_log),
                },
                plan=plan,
                plan_sha256=summary["plan_sha256"],
            )
            validated = self.run_command(
                project,
                cache,
                fake_bin,
                root / "validate.json",
                "--action",
                "validate",
                extra_env={"FAKE_GO_VERSION_LOG": str(version_log)},
                plan=plan,
                plan_sha256=summary["plan_sha256"],
            )
            probes = [
                json.loads(line)
                for line in version_log.read_text(encoding="utf-8").splitlines()
            ]
            drifted = self.run_command(
                project,
                cache,
                fake_bin,
                root / "must-not-run.json",
                "--",
                "go",
                "test",
                "./...",
                extra_env={
                    "FAKE_GO_VERSION_OVERRIDE": "go version go1.24.0 test/amd64"
                },
                plan=plan,
                plan_sha256=summary["plan_sha256"],
            )
            persisted = json.loads(plan.read_text(encoding="utf-8"))

        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertGreaterEqual(len(probes), 3)
        for probe in probes:
            self.assertEqual(probe["cwd"], str(project))
            self.assertEqual(probe["env"]["GOTOOLCHAIN"], "local")
            self.assertEqual(probe["env"]["GOENV"], "off")
            self.assertEqual(probe["env"]["GOWORK"], "off")
            self.assertIsNone(probe["inherited_gomod"])
        self.assertTrue(
            any(probe["env"]["GOFLAGS"] == "-mod=readonly" for probe in probes)
        )
        self.assertEqual(
            persisted["go_runtime"]["effective_toolchain"], "go1.23.0"
        )
        self.assertEqual(drifted.returncode, 2)
        self.assertIn("runtime fingerprint drift", drifted.stderr)

    def test_failed_build_restores_manifests_and_preserves_rollback_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            before_mod = (project / "go.mod").read_bytes()
            before_sum = (project / "go.sum").read_bytes()
            failed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "build.json",
                "--action",
                "validate",
                extra_env={
                    "FAKE_GO_MUTATE_MANIFEST_COMMAND": "build ./...",
                    "FAKE_GO_FAIL_COMMAND": "build ./...",
                    "FAKE_GO_FAIL_EXIT": "23",
                },
            )
            restored_mod = (project / "go.mod").read_bytes()
            restored_sum = (project / "go.sum").read_bytes()
            evidence = json.loads((project / MODULE.VALIDATION_EVIDENCE).read_bytes())
            build = evidence["commands"][1]

            failed_test = self.run_command(
                project,
                cache,
                fake_bin,
                root / "test.json",
                "--action",
                "validate",
                extra_env={
                    "FAKE_GO_MUTATE_MANIFEST_COMMAND": "test ./...",
                    "FAKE_GO_FAIL_COMMAND": "test ./...",
                    "FAKE_GO_FAIL_EXIT": "29",
                },
            )
            test_restored_mod = (project / "go.mod").read_bytes()
            test_restored_sum = (project / "go.sum").read_bytes()
            test_evidence = json.loads(
                (project / MODULE.VALIDATION_EVIDENCE).read_bytes()
            )
            test_row = test_evidence["commands"][2]

            rollback_failed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "build-rollback.json",
                "--action",
                "validate",
                extra_env={
                    "FAKE_GO_MUTATE_MANIFEST_COMMAND": "build ./...",
                    "FAKE_GO_FAIL_COMMAND": "build ./...",
                    "FAKE_GO_FAIL_EXIT": "23",
                    "FAKE_GO_BLOCK_MANIFEST_ROLLBACK": "go.mod",
                },
            )
            rollback_evidence = json.loads(
                (project / MODULE.VALIDATION_EVIDENCE).read_bytes()
            )
            rollback_build = rollback_evidence["commands"][1]

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(failed.returncode, 23, failed.stderr)
        self.assertEqual(restored_mod, before_mod)
        self.assertEqual(restored_sum, before_sum)
        self.assertEqual(build["child_exit_code"], 23)
        self.assertEqual(build["exit_code"], 23)
        self.assertEqual(build["manifest_rollback"], "restored")
        self.assertNotIn("rollback_error", build)
        self.assertEqual(failed_test.returncode, 29, failed_test.stderr)
        self.assertEqual(test_restored_mod, before_mod)
        self.assertEqual(test_restored_sum, before_sum)
        self.assertEqual(test_row["child_exit_code"], 29)
        self.assertEqual(test_row["exit_code"], 29)
        self.assertEqual(test_row["manifest_rollback"], "restored")
        self.assertNotIn("rollback_error", test_row)
        self.assertEqual(rollback_failed.returncode, 23, rollback_failed.stderr)
        self.assertEqual(rollback_build["child_exit_code"], 23)
        self.assertEqual(rollback_build["exit_code"], 23)
        self.assertIn("rollback_error", rollback_build)
        self.assertIn("temporary path already exists", rollback_build["rollback_error"])

    def test_validation_accepts_only_bounded_build_and_test_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            sequence = root / "sequence.jsonl"
            accepted = self.run_command(
                project,
                cache,
                fake_bin,
                root / "last.json",
                "--build-arg=-tags=otel",
                "--build-arg=./cmd/...",
                "--test-arg=-run=TestHTTP",
                "--test-arg=./internal/...",
                "--action",
                "validate",
                extra_env={"FAKE_GO_SEQUENCE_LOG": str(sequence)},
            )
            rejected = self.run_command(
                project,
                cache,
                fake_bin,
                root / "must-not-run.json",
                "--test-arg=-exec=wrapper",
                "--action",
                "validate",
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            invocations = [json.loads(line)["argv"] for line in sequence.read_text().splitlines()]

        self.assertEqual(
            invocations,
            [
                ["mod", "tidy"],
                [
                    "build",
                    invocations[1][1],
                    "-tags=otel",
                    "./cmd/...",
                ],
                ["test", "-run=TestHTTP", "./internal/..."],
            ],
        )
        self.assertTrue(invocations[1][1].startswith("-o="))
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("unsafe test validation flag", rejected.stderr)

    def test_validate_requires_an_applied_accepted_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            sequence = root / "must-not-run.jsonl"

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "must-not-run.json",
                "--action",
                "validate",
                extra_env={"FAKE_GO_SEQUENCE_LOG": str(sequence)},
            )
            evidence_exists = (
                project / ".observe" / "evidence" / "go-otel-validation.json"
            ).exists()

        self.assertEqual(completed.returncode, 2)
        self.assertIn("exact pinned go-get", completed.stderr)
        self.assertFalse(sequence.exists())
        self.assertFalse(evidence_exists)

    def test_validate_rejects_symlinked_evidence_path_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            applied = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={"FAKE_GO_EDIT_PROJECT": "1"},
            )
            outside = root / "outside-evidence"
            outside.mkdir()
            evidence_parent = project / ".observe" / "evidence"
            evidence_parent.symlink_to(outside, target_is_directory=True)
            sequence = root / "must-not-run.jsonl"
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "must-not-run.json",
                "--action",
                "validate",
                extra_env={"FAKE_GO_SEQUENCE_LOG": str(sequence)},
            )
            outside_entries = list(outside.iterdir())

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("symlink component", completed.stderr)
        self.assertFalse(sequence.exists())
        self.assertEqual(outside_entries, [])

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
                ("--", "go", "test", "--exec=/tmp/helper", "./..."),
                ("--", "go", "build", "-toolexec", "/tmp/helper", "./..."),
                ("--", "go", "build", "--toolexec", "/tmp/helper", "./..."),
                ("--", "go", "test", "-vettool=/tmp/helper", "./..."),
                ("--", "go", "test", "--vettool=/tmp/helper", "./..."),
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

    def test_atomic_write_works_without_unix_fchmod(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            with mock.patch.object(
                MODULE, "descriptor_mode_supported", return_value=False
            ), mock.patch.object(
                MODULE.os,
                "fchmod",
                side_effect=AssertionError("Unix fchmod must not be called"),
                create=True,
            ):
                MODULE.atomic_write(target, b'{"ok":true}\n')

            self.assertEqual(target.read_bytes(), b'{"ok":true}\n')

    def test_atomic_write_rejects_substituted_temporary_identity(self) -> None:
        if not MODULE.descriptor_publication_supported():
            self.skipTest("requires descriptor-relative publication")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "accepted-plan.json"
            temporary = target.with_name(
                f".{target.name}.{os.getpid()}.tmp"
            )
            original_stat = MODULE.os.stat
            substituted = False

            def substitute_before_identity_check(path, *args, **kwargs):
                nonlocal substituted
                if (
                    not substituted
                    and path == temporary.name
                    and kwargs.get("dir_fd") is not None
                ):
                    parent = kwargs["dir_fd"]
                    MODULE.os.unlink(path, dir_fd=parent)
                    attacker = MODULE.os.open(
                        path,
                        MODULE.os.O_WRONLY
                        | MODULE.os.O_CREAT
                        | MODULE.os.O_EXCL,
                        0o600,
                        dir_fd=parent,
                    )
                    try:
                        MODULE.os.write(attacker, b"attacker\n")
                    finally:
                        MODULE.os.close(attacker)
                    substituted = True
                return original_stat(path, *args, **kwargs)

            with mock.patch.object(
                MODULE.os, "stat", side_effect=substitute_before_identity_check
            ):
                with self.assertRaisesRegex(
                    MODULE.CommandError, "temporary file identity changed"
                ):
                    MODULE.atomic_write(target, b"trusted\n")

            self.assertTrue(substituted)
            self.assertFalse(target.exists())
            self.assertEqual(temporary.read_bytes(), b"attacker\n")

    def test_bookkeeping_cleanup_has_portable_no_dir_fd_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self.make_fixture(root)
            owned = project / MODULE.OWNED_DIRECTORY
            owned.mkdir(parents=True)
            (owned / MODULE.LEDGER_NAME).write_text(
                "portable\n", encoding="utf-8"
            )

            with mock.patch.object(
                MODULE, "descriptor_cleanup_supported", return_value=False
            ):
                count, errors = MODULE.remove_bookkeeping(project)

            tombstones = list(
                owned.parent.glob(f"{MODULE.RETIRED_DIRECTORY_PREFIX}*")
            )
            self.assertEqual((count, errors), (0, []))
            self.assertFalse(owned.exists())
            self.assertEqual(len(tombstones), 1)
            self.assertEqual(
                (tombstones[0] / "retired" / MODULE.LEDGER_NAME).read_text(
                    encoding="utf-8"
                ),
                "portable\n",
            )

    def test_bookkeeping_cleanup_never_recurses_after_nested_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self.make_fixture(root)
            owned = project / MODULE.OWNED_DIRECTORY
            owned.mkdir(parents=True)
            (owned / MODULE.LEDGER_NAME).write_text("{}\n", encoding="utf-8")
            nested = owned / "gomodcache" / "nested"
            nested.mkdir(parents=True)
            owned_payload = nested / "cache.a"
            owned_payload.write_text("owned\n", encoding="utf-8")
            moved = nested.with_name("renamed-nested")
            real_listdir = os.listdir
            swapped = False

            def swap_before_listing(descriptor: int) -> list[str]:
                nonlocal swapped
                names = real_listdir(descriptor)
                if not swapped:
                    nested.rename(moved)
                    nested.mkdir()
                    (nested / "externally-injected").write_text(
                        "safe\n", encoding="utf-8"
                    )
                    swapped = True
                return names

            with mock.patch.object(MODULE.os, "listdir", swap_before_listing):
                count, errors = MODULE.remove_bookkeeping(project)

            self.assertGreater(count, 0)
            self.assertTrue(any("non-recursive cleanup" in error for error in errors))
            self.assertEqual(
                (nested / "externally-injected").read_text(encoding="utf-8"),
                "safe\n",
            )
            self.assertEqual(
                (moved / owned_payload.name).read_text(encoding="utf-8"),
                "owned\n",
            )

    def test_bookkeeping_cleanup_tombstones_exact_ledger_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self.make_fixture(root)
            owned = project / MODULE.OWNED_DIRECTORY
            owned.mkdir(parents=True)
            ledger = owned / MODULE.LEDGER_NAME
            ledger.write_text("original\n", encoding="utf-8")
            original_root = owned.with_name("original-owned-tree")
            real_rename = os.rename
            swapped = False

            def substitute_then_rename(
                source: str,
                target: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                nonlocal swapped
                if source == MODULE.OWNED_DIRECTORY.name and target == "retired":
                    real_rename(owned, original_root)
                    owned.mkdir()
                    (owned / MODULE.LEDGER_NAME).write_text(
                        "externally injected\n", encoding="utf-8"
                    )
                    swapped = True
                real_rename(
                    source,
                    target,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with mock.patch.object(MODULE.os, "rename", substitute_then_rename):
                count, errors = MODULE.remove_bookkeeping(project)

            quarantine_root = project / ".observe" / "tmp"
            quarantines = list(
                quarantine_root.glob(".go-otel-resolver.retired.*")
            )
            self.assertTrue(swapped)
            self.assertGreater(count, 0)
            self.assertTrue(any("namespace changed" in error for error in errors))
            self.assertEqual(
                (original_root / MODULE.LEDGER_NAME).read_text(encoding="utf-8"),
                "original\n",
            )
            self.assertEqual(len(quarantines), 1)
            self.assertEqual(
                (
                    quarantines[0] / "retired" / MODULE.LEDGER_NAME
                ).read_text(encoding="utf-8"),
                "externally injected\n",
            )

    def test_bookkeeping_cleanup_fails_closed_on_ancestor_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, _ = self.make_fixture(root)
            owned = project / MODULE.OWNED_DIRECTORY
            owned.mkdir(parents=True)
            (owned / MODULE.LEDGER_NAME).write_text(
                "original\n", encoding="utf-8"
            )
            observe = project / ".observe"
            moved_observe = project / ".observe-original"
            real_rename = os.rename
            swapped = False

            def swap_ancestor_then_rename(
                source: str,
                target: str,
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                nonlocal swapped
                if source == MODULE.OWNED_DIRECTORY.name and target == "retired":
                    real_rename(observe, moved_observe)
                    replacement = project / MODULE.OWNED_DIRECTORY
                    replacement.mkdir(parents=True)
                    (replacement / MODULE.LEDGER_NAME).write_text(
                        "replacement\n", encoding="utf-8"
                    )
                    swapped = True
                real_rename(
                    source,
                    target,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with mock.patch.object(
                MODULE.os, "rename", swap_ancestor_then_rename
            ):
                count, errors = MODULE.remove_bookkeeping(project)

            replacement_ledger = project / MODULE.OWNED_DIRECTORY / MODULE.LEDGER_NAME
            quarantines = list(
                (moved_observe / "tmp").glob(
                    f"{MODULE.RETIRED_DIRECTORY_PREFIX}*"
                )
            )
            self.assertTrue(swapped)
            self.assertGreater(count, 0)
            self.assertTrue(
                any("canonical ancestor namespace changed" in error for error in errors)
            )
            self.assertEqual(
                replacement_ledger.read_text(encoding="utf-8"),
                "replacement\n",
            )
            self.assertEqual(len(quarantines), 1)
            self.assertEqual(
                (
                    quarantines[0] / "retired" / MODULE.LEDGER_NAME
                ).read_text(encoding="utf-8"),
                "original\n",
            )

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
            plan, plan_sha256 = self.ensure_plan(project, cache, fake_bin)

            applied = subprocess.run(
                [
                    sys.executable,
                    str(launcher),
                    "--project",
                    str(project),
                    "--gomodcache",
                    str(cache),
                    "--plan",
                    str(plan),
                    "--plan-sha256",
                    plan_sha256,
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
                    "--plan",
                    str(plan),
                    "--plan-sha256",
                    plan_sha256,
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

    def test_child_output_is_digest_only_and_exit_code_is_preserved(self) -> None:
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
        summary = json.loads(completed.stdout)
        self.assertEqual(summary["stdout"]["bytes"], len(b"fake-go-stdout\n"))
        self.assertEqual(summary["stderr"]["bytes"], len(b"fake-go-stderr\n"))
        self.assertNotIn("fake-go-stdout", completed.stdout)
        self.assertNotIn("fake-go-stderr", completed.stderr)

    def test_bootstrap_probe_stages_fixed_imports_and_writes_probed_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, irrelevant_artifact = self.make_bootstrap_fixture(root)
            irrelevant_artifact.unlink()
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
            plan = json.loads(
                (project / ".observe" / "tmp" / "go-otel-version-plan.json").read_text(
                    encoding="utf-8"
                )
            )
            plan_bindings = {
                f"{row['module']}@{row['version']}": row
                for row in (
                    plan["bootstrap_probe"]["verification"]
                    + plan["bootstrap_probe"]["graph_metadata"]
                )
            }
            expected_bound_digest = MODULE.proxy_content_digest(
                [
                    plan_bindings[pin]
                    for pin in ledger["probe_bound_modules"]
                ]
            )
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
        self.assertFalse(Path(invocation["cwd"]).is_relative_to(project))
        self.assertEqual(invocation["env"]["GOTOOLCHAIN"], "local")
        self.assertEqual(invocation["env"]["GOVCS"], "*:off")
        self.assertEqual(invocation["env"]["GOSUMDB"], "off")
        self.assertTrue(invocation["env"]["GOPROXY"].startswith("file://"))
        self.assertIn('go.opentelemetry.io/otel/sdk/trace', invocation["main_go"])
        self.assertIn('go.opentelemetry.io/otel/sdk/metric', invocation["main_go"])
        self.assertEqual(result["status"], "accepted")
        self.assertIn("import-reachable", result["proof_boundary"])
        self.assertEqual(ledger["state"], "probed")
        self.assertEqual(ledger["schema_version"], 5)
        self.assertEqual(
            set(ledger["probe_resolved_modules"]), set(result["modules"])
        )
        self.assertRegex(ledger["probe_proxy_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(ledger["probe_proxy_sha256"], expected_bound_digest)
        self.assertIn(
            "example.test/project-dependency@v1.0.0",
            ledger["probe_bound_modules"],
        )
        self.assertNotIn(
            "example.test/project-dependency@v1.0.0",
            ledger["probe_resolved_modules"],
        )
        self.assertIn(
            "github.com/go-logr/logr@v1.2.2",
            ledger["probe_graph_metadata_modules"],
        )
        self.assertNotIn(
            "github.com/go-logr/logr@v1.4.2",
            ledger["probe_graph_metadata_modules"],
        )
        lower_logr = next(
            row
            for row in plan["bootstrap_probe"]["graph_metadata"]
            if row["module"] == "github.com/go-logr/logr"
            and row["version"] == "v1.2.2"
        )
        self.assertEqual(set(lower_logr["artifacts"]), {"mod", "info"})
        selected_logr = next(
            row
            for row in plan["bootstrap_probe"]["verification"]
            if row["module"] == "github.com/go-logr/logr"
        )
        self.assertEqual(selected_logr["version"], "v1.4.2")
        self.assertEqual(set(selected_logr["artifacts"]), set(ARTIFACTS))
        transitive = next(
            row
            for row in plan["bootstrap_probe"]["verification"]
            if row["module"] == "example.test/transitive"
        )
        self.assertEqual(transitive["missing_artifacts"], ["ziphash"])
        dev_only = {
            row["module"]: row["missing_artifacts"]
            for row in plan["bootstrap_probe"]["verification"]
            if row["module"]
            in {"github.com/bazelbuild/rules_go", "github.com/yuin/goldmark"}
        }
        self.assertEqual(
            dev_only,
            {
                "github.com/bazelbuild/rules_go": ["zip", "ziphash"],
                "github.com/yuin/goldmark": ["zip", "ziphash"],
            },
        )
        self.assertNotIn(
            "example.test/transitive@v1.0.0",
            ledger["probe_resolved_modules"],
        )
        self.assertEqual(ledger["go_mod_sha256"], project_mod_sha)
        self.assertFalse(stage_exists)
        self.assertFalse(probe_cache_exists)

    def test_bootstrap_required_missing_artifact_fails_tidy_without_project_edits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, missing = self.make_bootstrap_fixture(
                root, missing_otel_transitive=True
            )
            fake_bin = self.make_fake_go(root)
            log = root / "probe.json"
            self.ensure_plan(project, cache, fake_bin)
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
        self.assertEqual(blocker["exit_code"], 19)
        self.assertFalse(log.exists())
        self.assertEqual(before, after)

    def test_bootstrap_go_get_stages_bound_project_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            probed = self.probe(project, cache, fake_bin, root / "probe.json")

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={
                    "FAKE_GO_EDIT_PROJECT": "1",
                    "FAKE_GO_REQUIRE_PROXY_RELATIVE": (
                        "example.test/project-dependency/@v/v1.0.0.mod"
                    ),
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

        self.assertEqual(probed.returncode, 0, probed.stderr)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(ledger["state"], "applied")
        self.assertIn(
            "example.test/project-dependency@v1.0.0",
            ledger["probe_bound_modules"],
        )
        self.assertNotIn(
            "example.test/project-dependency@v1.0.0",
            ledger["probe_resolved_modules"],
        )

    def test_bootstrap_missing_required_project_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            artifact(
                cache,
                "example.test/project-dependency",
                "v1.0.0",
                "zip",
            ).unlink()
            probed = self.probe(project, cache, fake_bin, root / "probe.json")
            original_mod = (project / "go.mod").read_bytes()
            original_sum_exists = (project / "go.sum").exists()

            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "get.json",
                "--action",
                "go-get",
                extra_env={
                    "FAKE_GO_EDIT_PROJECT": "1",
                    "FAKE_GO_REQUIRE_PROXY_RELATIVE": (
                        "example.test/project-dependency/@v/v1.0.0.zip"
                    ),
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
            restored_sum_exists = (project / "go.sum").exists()

        self.assertEqual(probed.returncode, 0, probed.stderr)
        self.assertEqual(completed.returncode, 19, completed.stderr)
        self.assertEqual(restored_mod, original_mod)
        self.assertEqual(restored_sum_exists, original_sum_exists)
        self.assertEqual(ledger["state"], "probed")

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

    def test_failed_go_get_reports_child_output_and_rollback_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache = self.make_fixture(root)
            fake_bin = self.make_fake_go(root)
            completed = self.run_command(
                project,
                cache,
                fake_bin,
                root / "failed-get.json",
                "--action",
                "go-get",
                extra_env={
                    "FAKE_GO_EDIT_PROJECT": "1",
                    "FAKE_GO_FAIL_AFTER_EDIT": "17",
                    "FAKE_GO_BLOCK_GO_GET_ROLLBACK": "go.mod",
                },
            )
            result = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 17, completed.stderr)
        self.assertEqual(result["child_exit_code"], 17)
        self.assertEqual(result["exit_code"], 17)
        self.assertGreater(result["stdout"]["bytes"], 0)
        self.assertEqual(len(result["stdout"]["sha256"]), 64)
        self.assertGreater(result["stderr"]["bytes"], 0)
        self.assertEqual(len(result["stderr"]["sha256"]), 64)
        self.assertEqual(result["manifest_rollback"], "attempted")
        self.assertIn("temporary path already exists", result["rollback_error"])

    def test_bootstrap_rejects_one_and_two_dash_mutation_flags(self) -> None:
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
            cases = (
                ("single-mod", "-mod=mod"),
                ("double-mod", "--mod=mod"),
                ("single-modfile", "-modfile=/tmp/alternate.mod"),
                ("double-modfile", "--modfile=/tmp/alternate.mod"),
                ("single-overlay", "-overlay=/tmp/overlay.json"),
                ("double-overlay", "--overlay=/tmp/overlay.json"),
            )
            results = []
            for name, flag in cases:
                log = root / f"must-not-run-{name}.json"
                completed = self.run_command(
                    project,
                    cache,
                    fake_bin,
                    log,
                    "--",
                    "go",
                    "test",
                    flag,
                    "./...",
                )
                results.append((completed, log.exists()))

        self.assertEqual(applied.returncode, 0, applied.stderr)
        for completed, log_exists in results:
            self.assertEqual(completed.returncode, 2)
            self.assertIn(
                "dependency-mutating Go flags are not allowed",
                completed.stderr,
            )
            self.assertFalse(log_exists)

    def test_failed_bootstrap_tidy_preserves_exit_and_rolls_back(self) -> None:
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
            before_mod = (project / "go.mod").read_bytes()
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
                    "FAKE_GO_EXIT": "17",
                },
            )
            restored_mod = (project / "go.mod").read_bytes()
            restored_sum = (project / "go.sum").read_bytes()
            restored_ledger = ledger_path.read_bytes()

        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(completed.returncode, 17, completed.stderr)
        self.assertEqual(restored_mod, before_mod)
        self.assertEqual(restored_sum, before_sum)
        self.assertEqual(restored_ledger, before_ledger)

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
        self.assertIn("project go.mod drift", existing.stderr)

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

    def test_cleanup_blocks_on_unexpected_read_only_repository_tree(self) -> None:
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
            payload_survived = payload.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 3)
        self.assertEqual(completed.stdout, "")
        self.assertIn("non-recursive cleanup", completed.stderr)
        self.assertTrue(owned_exists)
        self.assertEqual(payload_survived, "cache")

    def test_version_probe_telemetry_state_does_not_block_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            probed = self.probe(
                project,
                cache,
                fake_bin,
                root / "probe.json",
                extra_env={"FAKE_GO_WRITE_VERSION_TELEMETRY": "1"},
            )
            owned = project / ".observe" / "tmp" / "go-otel-resolver"
            project_home_exists = (owned / "home").exists()

            cleaned = self.run_command(
                project,
                cache,
                fake_bin,
                root / "cleanup.json",
                "--action",
                "cleanup",
                extra_env={"FAKE_GO_WRITE_VERSION_TELEMETRY": "1"},
            )
            owned_exists = owned.exists()

        self.assertEqual(probed.returncode, 0, probed.stderr)
        self.assertFalse(project_home_exists)
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        self.assertFalse(owned_exists)

    def test_bookkeeping_cleanup_is_idempotent_and_retains_one_tombstone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, cache, _ = self.make_bootstrap_fixture(root)
            fake_bin = self.make_fake_go(root)
            probe = self.probe(project, cache, fake_bin, root / "probe.json")

            first = self.run_command(
                project,
                cache,
                fake_bin,
                root / "first-cleanup.json",
                "--action",
                "cleanup",
            )
            second = self.run_command(
                project,
                cache,
                fake_bin,
                root / "second-cleanup.json",
                "--action",
                "cleanup",
            )
            parent = project / ".observe" / "tmp"
            tombstones = list(parent.glob(f"{MODULE.RETIRED_DIRECTORY_PREFIX}*"))

        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(first.stdout)["status"], "complete")
        self.assertEqual(json.loads(second.stdout)["status"], "complete")
        self.assertEqual(len(tombstones), 1)

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
