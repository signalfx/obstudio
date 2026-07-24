from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCANNER = ROOT / "skills" / "references" / "scripts" / "inspect_otel_project.py"
SECURE_OUTPUT = ROOT / "skills" / "references" / "scripts" / "secure_output.py"
LOOPBACK_PROBE = (
    ROOT / "skills" / "references" / "scripts" / "probe_loopback_bind.py"
)
SKILLS = ("otel-audit", "otel-instrument", "otel-verify")
INSTRUMENT_DIR = ROOT / "skills" / "otel-instrument"
INSTRUMENT_SKILL = INSTRUMENT_DIR / "SKILL.md"
INSTRUMENT_GO = INSTRUMENT_DIR / "references" / "languages" / "go.md"
INSTRUMENT_REPAIR = INSTRUMENT_DIR / "references" / "repair-loop.md"
def test_shared_inventory_is_routed_from_all_three_skills() -> None:
    assert SCANNER.is_file()
    for skill in SKILLS:
        text = (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        normalized_lower = normalized.lower()
        assert (
            "<directory-containing-loaded-SKILL.md>/scripts/inspect_otel_project.py"
            in normalized
        )
        assert "direct small-repo path" in normalized_lower
        assert "at most 25 non-ignored files" in normalized_lower
        assert "do not run the inventory helper" in normalized_lower
        assert "run one successful invocation" in normalized_lower
        assert "--output" in normalized
        assert ".observe/tmp/otel-project-inventory.json" in normalized
        assert "complete: true" in normalized
        assert "section_counts" in normalized
        assert "not proof" in normalized_lower
        assert "repository-wide `find` or broad `rg`" in normalized
        assert "resolve every reference and script path" in normalized_lower
        assert "never probe the service root or repository root" in normalized_lower

        wrapper = ROOT / "skills" / skill / "scripts" / "inspect_otel_project.py"
        assert wrapper.is_file()


def test_shared_inventory_runs_from_the_eval_skill_layout() -> None:
    fixture = ROOT / "evals" / "go" / "chi-basic"
    result = subprocess.run(
        [sys.executable, str(SCANNER), str(fixture), "--max-items", "20"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    assert inventory["schema_version"] == 1
    assert {item["route"] for item in inventory["routes"]} == {
        "/health",
        "/tasks",
        "/tasks/{id}",
    }
    assert inventory["summary"]["otel_findings"] == 0


def test_each_skill_wrapper_matches_the_shared_inventory() -> None:
    fixture = ROOT / "evals" / "go" / "chi-basic"
    expected = subprocess.run(
        [sys.executable, str(SCANNER), str(fixture), "--max-items", "20"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    for skill in SKILLS:
        wrapper = ROOT / "skills" / skill / "scripts" / "inspect_otel_project.py"
        result = subprocess.run(
            [sys.executable, str(wrapper), str(fixture), "--max-items", "20"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == json.loads(expected)


def test_go_resolver_guidance_cleans_only_owned_state_compactly() -> None:
    guide = (
        ROOT / "skills" / "otel-instrument" / "references" / "languages" / "go.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(guide.split())
    assert ".observe/tmp/go-otel-version-plan.json" in guide
    assert "summary's `next_action`" in guide
    assert "--plan-sha256" in guide
    assert "does not rescan the cache" in normalized
    assert "alternate plan path" in normalized
    assert "do not print the full plan" in normalized
    assert "Omitting `--output` retains legacy full-JSON stdout" in normalized
    assert "--action cleanup" in guide
    assert "accepted-plan ledger, probe stage, and read-only owned caches" in normalized
    assert "with a compact result" in normalized
    assert "Defer cleanup until all source and report edits" in normalized
    assert "final code review" in normalized
    assert "repeat `--action validate`" in normalized
    assert "as the final project command" in normalized
    assert "After cleanup, do not rerun the resolver, edit the project" in normalized
    assert "any `find` inspection/deletion" in normalized
    assert "Never recover with a manual `GOCACHE`, `GOMODCACHE`, or `go` branch" in normalized
    assert "small local telemetry bookkeeping" in normalized.lower()
    assert "not a build/module cache payload" in normalized.lower()
    assert "Successful cleanup is the terminal boundary" in normalized
    assert "emit the final response immediately" in normalized
    for forbidden_follow_up in (
        "`git status`",
        "`git diff`",
        "a `go.sum` inspection",
        "cache inspection/removal",
        "artifact listings",
        "repeated validators/tests",
    ):
        assert forbidden_follow_up in normalized


def test_instrument_frontloads_language_route_and_scoped_go_resolver_gate() -> None:
    skill_path = INSTRUMENT_SKILL
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    # The canonical audit/selection gate now precedes discovery, but language
    # and dependency routing must still be in the opening preflight section.
    front = " ".join("\n".join(lines[:200]).split())
    assert "Immediately load exactly one matching language reference" in front
    assert "Go standard-HTTP bootstrap gate" in front
    assert "loaded Go reference's `Dependencies` section exactly" in front
    assert "fixed-bundle resolver" in front
    assert "existing OTel pins, non-HTTP services" in front

    guide = " ".join(INSTRUMENT_GO.read_text(encoding="utf-8").split())
    for requirement in (
        "scripts/resolve_go_otel_versions.py",
        ".observe/tmp/go-otel-version-plan.json",
        "--plan-sha256",
        "loads the exact digest-bound persisted plan",
        "do not print the full plan",
        "summary's `next_action`",
        "scripts/run_go_otel_command.py",
        "Use the cache-backed resolver only for the standard HTTP bootstrap",
        "`bootstrap_probe.eligible` is `true`",
        "--action probe-bootstrap",
        "exactly through one runner action",
        "Do not run those three commands separately or in parallel",
        "A blocked result is terminal",
        "skip this fixed-bundle resolver",
        "Never copy `go_get.env`",
        "cleanup is the terminal boundary",
    ):
        assert requirement in guide


def test_go_command_runner_replaces_shell_env_transcription() -> None:
    guide = (
        ROOT / "skills" / "otel-instrument" / "references" / "languages" / "go.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(guide.split())
    runner = (
        ROOT / "skills" / "otel-instrument" / "scripts" / "run_go_otel_command.py"
    )
    assert runner.is_file()
    assert "--action probe-bootstrap" in guide
    assert "requires all four for the fixed direct OTel pins" in normalized
    assert "missing dev/test-only artifact does not fail the fixed-import probe" in normalized
    assert "exact resolved OTel import closure" in normalized
    assert "existing-project-plus-candidate dependency closure" in normalized
    assert "without promoting them into the OTel proof" in normalized
    assert "real command needs an artifact" in normalized
    assert "Every version check places `HOME`, Go caches, and `GOTELEMETRYDIR`" in normalized
    assert "local telemetry cannot enter repository cleanup state" in normalized
    assert "--action go-get" in guide
    assert "--action validate" in guide
    assert "--action cleanup" in guide
    assert guide.count("--plan-sha256") >= 6
    assert "rather than a shell" in normalized
    assert "Never copy `go_get.env`" in normalized
    assert "Only `go mod tidy`, `go test`, `go build`, `go list`, and `go run`" in normalized
    assert "`go mod tidy`, `go build -o <invocation-owned-directory> ./...`, and `go test ./...` in that order" in normalized
    assert "recorded as `$INVOCATION/build-output`" in normalized
    assert "cannot create a binary in the project" in normalized
    assert ".observe/evidence/go-otel-validation.json" in normalized
    assert "Do not run those three commands separately or in parallel" in normalized
    assert "Do not start any Go command concurrently with `--action validate`" in normalized
    assert "external-tool flags such as `-exec`, `-toolexec`, and `-vettool`" in normalized
    assert "argv-safe and cache-isolated, not a sandbox" in normalized
    assert "or another cleanup command" in normalized
    assert "drift-bound accepted-plan ledger" in normalized
    assert "rolls both back" in normalized
    assert "A blocked result is terminal" in normalized
    assert "Do not read `candidate_rejections` to choose a version" in normalized
    assert "Do not run `rm`, any `find` inspection/deletion" in normalized
def test_go_resolver_guidance_requires_full_closure_and_preserves_existing_pins() -> None:
    skill = (ROOT / "skills" / "otel-instrument" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    guide = (
        ROOT / "skills" / "otel-instrument" / "references" / "languages" / "go.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join((skill + "\n" + guide).split())
    assert "full selected dependency closure" in normalized
    assert "direct-bundle-only versions are not runnable candidates" in normalized
    assert "existing-otel-dependencies" in normalized
    assert "does not authorize an upgrade" in normalized
    assert "use only an eligible runner bootstrap probe" in normalized


def test_full_runtime_listener_probe_is_shared_and_bounded() -> None:
    contract = (
        ROOT / "skills" / "references" / "full-runtime-acceptance.md"
    ).read_text(encoding="utf-8")
    assert LOOPBACK_PROBE.is_file()
    assert "run exactly one bounded capability probe" in contract
    assert "scripts/probe_loopback_bind.py" in contract
    assert "`status: blocked`" in contract
    assert "prerequisite check, not startup" in contract

    for skill in ("otel-instrument", "otel-verify"):
        guide = (ROOT / "skills" / skill / "SKILL.md").read_text(
            encoding="utf-8"
        )
        if skill == "otel-instrument":
            assert "references/repair-loop.md" in guide
            guide += "\n" + INSTRUMENT_REPAIR.read_text(encoding="utf-8")
        wrapper = ROOT / "skills" / skill / "scripts" / LOOPBACK_PROBE.name
        assert wrapper.is_file()
        assert "scripts/probe_loopback_bind.py" in guide
        completed = subprocess.run(
            [sys.executable, str(wrapper)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        result = json.loads(completed.stdout)
        assert result["complete"] is True
        assert result["status"] in {"available", "blocked"}


def test_java_agent_resolution_is_boundary_aware_and_proof_bounded() -> None:
    runtime = (
        ROOT
        / "skills"
        / "otel-verify"
        / "references"
        / "project-runtime-resolution.md"
    ).read_text(encoding="utf-8")
    full_runtime = (
        ROOT / "skills" / "references" / "full-runtime-acceptance.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join((runtime + "\n" + full_runtime).split())
    resolver = ROOT / "skills" / "references" / "scripts" / "resolve_java_agent.py"

    assert resolver.is_file()
    assert "Resolve the execution boundary" in normalized
    assert "missing container-internal path" in normalized
    assert "targeted Maven-local and Gradle-cache coordinates" in normalized
    assert "`Premain-Class`" in normalized
    assert "full artifact SemVer" in normalized
    assert "implementation version" in normalized
    assert "SHA-256" in normalized
    assert "one rejected candidate, not evidence that no agent is available" in normalized
    assert "Do not ask the user to provide, locate, install, or download an agent" in normalized
    assert "production_parity.status" in normalized
    assert "verification pin" in normalized

    for skill in ("otel-instrument", "otel-verify"):
        wrapper = ROOT / "skills" / skill / "scripts" / resolver.name
        assert wrapper.is_file()


def test_java_agent_eval_fixtures_are_byte_deterministic(tmp_path: Path) -> None:
    builder = (
        ROOT
        / "evals"
        / "java"
        / "springboot-basic"
        / "eval"
        / "inputs"
        / "build_java_agent_fixtures.py"
    )
    first = tmp_path / "first"
    second = tmp_path / "second"

    for output in (first, second):
        result = subprocess.run(
            [sys.executable, str(builder), str(output)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    first_jars = sorted(path.relative_to(first) for path in first.glob("*.jar"))
    second_jars = sorted(path.relative_to(second) for path in second.glob("*.jar"))
    assert first_jars == second_jars
    assert first_jars
    for relative in first_jars:
        first_bytes = (first / relative).read_bytes()
        second_bytes = (second / relative).read_bytes()
        assert first_bytes == second_bytes
        assert hashlib.sha256(first_bytes).hexdigest() == hashlib.sha256(
            second_bytes
        ).hexdigest()
        with zipfile.ZipFile(first / relative) as archive:
            entries = archive.infolist()
            assert [entry.filename for entry in entries] == [
                "META-INF/MANIFEST.MF"
            ]
            entry = entries[0]
            assert entry.date_time == (1980, 1, 1, 0, 0, 0)
            assert entry.create_system == 3
            assert entry.external_attr >> 16 == 0o100644
            assert entry.compress_type == zipfile.ZIP_STORED


def test_java_provider_and_agent_runtime_proof_use_distinct_live_forks() -> None:
    java = (
        ROOT / "skills" / "otel-instrument" / "references" / "languages" / "java.md"
    ).read_text(encoding="utf-8")
    instrument_runtime = (
        ROOT
        / "skills"
        / "otel-instrument"
        / "references"
        / "project-runtime-validation.md"
    ).read_text(encoding="utf-8")
    verify_runtime = (
        ROOT
        / "skills"
        / "otel-verify"
        / "references"
        / "project-runtime-resolution.md"
    ).read_text(encoding="utf-8")
    witness = (
        ROOT / "skills" / "otel-verify" / "references" / "explorer-witness.md"
    ).read_text(encoding="utf-8")
    full_runtime = (
        ROOT / "skills" / "references" / "full-runtime-acceptance.md"
    ).read_text(encoding="utf-8")
    instrument = (ROOT / "skills" / "otel-instrument" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    verify = (ROOT / "skills" / "otel-verify" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    provider_guidance = " ".join(
        (java + instrument_runtime + verify_runtime + instrument + verify).split()
    )
    live_guidance = " ".join((witness + full_runtime + verify).split())

    assert "SdkTracerProvider" in provider_guidance
    assert "without `-javaagent`" in provider_guidance
    assert "separate agent E2E fork" in provider_guidance
    assert "Never mix a test provider with the agent-owned global" in provider_guidance
    assert "actual `OTEL_*` environment variables" in provider_guidance
    assert "`-Dotel.*` agent properties" in provider_guidance
    assert "keyed to the emitting source PID" in live_guidance
    assert "Hold the emitting JVM open" in live_guidance
    assert "before allowing that process to exit" in live_guidance
    assert "missing visibility proof, not proof" in live_guidance


def test_failed_verification_routes_to_owned_repair_and_automatic_recheck() -> None:
    instrument = (ROOT / "skills" / "otel-instrument" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    verify = (ROOT / "skills" / "otel-verify" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    repair = INSTRUMENT_REPAIR.read_text(encoding="utf-8")
    normalized_instrument = " ".join((instrument + "\n" + repair).split())
    normalized_verify = " ".join(verify.split())

    assert "verification as a repair loop, not a terminal handoff" in normalized_instrument
    assert "references/repair-loop.md" in instrument
    assert "## Failure Ownership" in repair
    assert (
        "failure -> failing source/config -> selected finding -> ownership -> evidence"
        in normalized_instrument
    )
    assert (
        "pre-existing OTel code/config defect inside dependency-closed selected scope"
        in normalized_instrument
    )
    assert (
        "make a concrete code/config repair and continue until the affected check passes or an evidenced stop boundary is reached"
        in normalized_instrument
    )
    assert (
        "failed child overlay written during this loop is intermediate"
        in normalized_instrument
    )
    assert (
        "Do not finalize while a safe in-scope instrumentation-owned failure remains"
        in normalized_instrument
    )
    assert (
        "an unchanged selected OTel wiring defect is pre-existing but instrumentation-owned"
        in normalized_instrument
    )
    assert "relabel an executed failure as `not_proven`" in normalized_instrument
    assert "Do not ask the user to invoke `$otel-instrument` again" in normalized_instrument
    assert "Exact scenario IDs are verifier-owned scope" in normalized_instrument
    assert "never repairs application code" in normalized_verify
    assert "returns its repair packet" in normalized_verify
    assert (
        "An unchanged selected OTel wiring defect is `pre-existing`, not `instrumentation-introduced`"
        in normalized_verify
    )
def test_wrappers_run_from_bundle_with_spaces_and_unrelated_cwd(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "installed bundle with spaces"
    shared_dir = bundle / "references" / "scripts"
    shared_dir.mkdir(parents=True)
    shutil.copy2(SCANNER, shared_dir / SCANNER.name)
    shutil.copy2(SECURE_OUTPUT, shared_dir / SECURE_OUTPUT.name)

    service = tmp_path / "service with spaces"
    shutil.copytree(ROOT / "evals" / "go" / "chi-basic", service)
    unrelated_cwd = tmp_path / "unrelated working directory"
    unrelated_cwd.mkdir()

    expected = subprocess.run(
        [sys.executable, str(SCANNER), str(service), "--max-items", "20"],
        check=True,
        capture_output=True,
        text=True,
        cwd=unrelated_cwd,
    )
    expected_inventory = json.loads(expected.stdout)

    for skill in SKILLS:
        wrapper_dir = bundle / skill / "scripts"
        wrapper_dir.mkdir(parents=True)
        source_wrapper = ROOT / "skills" / skill / "scripts" / SCANNER.name
        wrapper = wrapper_dir / SCANNER.name
        shutil.copy2(source_wrapper, wrapper)
        output = tmp_path / f"{skill} output with spaces.json"
        result = subprocess.run(
            [
                sys.executable,
                str(wrapper),
                str(service),
                "--max-items",
                "20",
                "--output",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=unrelated_cwd,
        )
        assert result.returncode == 0, result.stderr
        summary = json.loads(result.stdout)
        inventory = json.loads(output.read_text(encoding="utf-8"))
        assert inventory == expected_inventory
        assert summary["summary"] == inventory["summary"]
        assert summary["complete"] == inventory["complete"]
        assert summary["warnings"] == inventory["warnings"]
        assert summary["skipped_count"] == inventory["skipped_count"]


def test_wrapper_import_is_inert() -> None:
    for skill in SKILLS:
        wrapper = ROOT / "skills" / skill / "scripts" / SCANNER.name
        code = (
            "import runpy; "
            f"runpy.run_path({str(wrapper)!r}, run_name='wrapper_import_test')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert result.stderr == ""


def test_standalone_wrapper_reports_missing_shared_helper_without_traceback(
    tmp_path: Path,
) -> None:
    standalone = tmp_path / "standalone skill with spaces" / "scripts"
    standalone.mkdir(parents=True)
    source = ROOT / "skills" / "otel-audit" / "scripts" / SCANNER.name
    wrapper = standalone / SCANNER.name
    shutil.copy2(source, wrapper)

    result = subprocess.run(
        [sys.executable, str(wrapper), str(ROOT / "evals" / "go" / "chi-basic")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "project inventory helper is missing" in result.stderr
    assert "complete Obstudio skill bundle" in result.stderr
    assert "Traceback" not in result.stderr


def test_service_local_shared_scanner_cannot_hijack_wrapper(tmp_path: Path) -> None:
    service = tmp_path / "service"
    malicious = service / "references" / "scripts"
    malicious.mkdir(parents=True)
    marker = tmp_path / "hijacked"
    (malicious / SCANNER.name).write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('hijacked', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (service / "go.mod").write_text(
        "module wrapper.test\n\ngo 1.25\n", encoding="utf-8"
    )

    wrapper = ROOT / "skills" / "otel-verify" / "scripts" / SCANNER.name
    result = subprocess.run(
        [sys.executable, str(wrapper), str(service), "--max-items", "2"],
        check=False,
        capture_output=True,
        text=True,
        cwd=service,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["schema_version"] == 1
    assert not marker.exists()
