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


def raw_canonical_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def test_example_report_companions_are_exact_and_raw_hash_bound() -> None:
    example_root = ROOT / "docs" / "example-reports"
    fixture_root = ROOT / "evals" / "go" / "chi-basic" / "eval" / "inputs"
    names = (
        "otel-audit.json",
        "otel-selection.json",
        "otel-instrumentation.json",
        "otel-verify.json",
    )
    for name in names:
        assert (example_root / name).read_bytes() == (fixture_root / name).read_bytes()

    audit = json.loads((fixture_root / "otel-audit.json").read_bytes())
    selection = json.loads((fixture_root / "otel-selection.json").read_bytes())
    instrumentation = json.loads(
        (fixture_root / "otel-instrumentation.json").read_bytes()
    )
    verification = json.loads((fixture_root / "otel-verify.json").read_bytes())

    audit_digest = raw_canonical_digest(audit)
    assert selection["audit_sha256"] == audit_digest
    assert instrumentation["audit_sha256"] == audit_digest
    assert verification["audit_sha256"] == audit_digest
    assert instrumentation["selection_sha256"] == raw_canonical_digest(selection)
    assert verification["instrumentation_sha256"] == raw_canonical_digest(
        instrumentation
    )


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
    assert "--action cleanup" in guide
    assert "accepted-plan ledger, probe stage, and read-only owned caches" in normalized
    assert "with a compact result" in normalized
    assert "Defer cleanup until all source and report edits" in normalized
    assert "final code review" in normalized
    assert "repeat every affected runner-backed validation" in normalized
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
    skill_path = ROOT / "skills" / "otel-instrument" / "SKILL.md"
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    # The canonical audit/selection gate now precedes discovery, but language
    # and dependency routing must still be in the opening preflight section.
    front = " ".join("\n".join(lines[:200]).split())
    assert "Immediately load exactly one matching language reference" in front
    assert "Go standard-HTTP bootstrap gate" in front
    assert "scripts/resolve_go_otel_versions.py" in front
    assert "scripts/run_go_otel_command.py" in front
    assert "Only when adding the standard `otelhttp`" in front
    assert "`bootstrap_probe.eligible` is true" in front
    assert "`--action probe-bootstrap`" in front
    assert "A blocked probe is terminal" in front
    assert "Skip the fixed-bundle workflow" in front
    assert "existing OTel pins, non-HTTP services" in front
    assert "nonexistent official `otelchi` module" in front
    assert "Never transcribe its env map" in front
    assert "cleanup is the final project command" in front


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
    assert "--action go-get" in guide
    assert "--action cleanup" in guide
    assert "rather than a shell" in normalized
    assert "Never copy `go_get.env`" in normalized
    assert "Only `go mod tidy`, `go test`, `go build`, `go list`, and `go run`" in normalized
    assert "external-tool flags such as `-exec`, `-toolexec`, and `-vettool`" in normalized
    assert "argv-safe and cache-isolated, not a sandbox" in normalized
    assert "or another cleanup command" in normalized
    assert "drift-bound accepted-plan ledger" in normalized
    assert "rolls both back" in normalized
    assert "A blocked result is terminal" in normalized
    assert "Do not read `candidate_rejections` to choose a version" in normalized
    assert "Do not run `rm`, any `find` inspection/deletion" in normalized


def test_go_metric_guidance_requires_version_specific_proof() -> None:
    skill = (
        ROOT / "skills" / "otel-instrument" / "SKILL.md"
    ).read_text(encoding="utf-8")
    guide = (
        ROOT / "skills" / "otel-instrument" / "references" / "languages" / "go.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join((skill + "\n" + guide).split())
    assert "version- and semantic-convention-mode-dependent" in normalized
    assert "do not claim `http.server.active_requests`" in normalized
    assert "never infer `http.server.active_requests`" in normalized
    assert "v0.68.0" in (
        ROOT / "evals" / "go" / "chi-partial" / "go.mod"
    ).read_text(encoding="utf-8")
    assert (
        "Use `otelhttp.WithRouteTag` only when that exact source exports it"
        in normalized
    )
    assert "v0.65.0 and later do not" in normalized
    assert "trace.SpanFromContext(r.Context()).SetAttributes" in normalized
    assert "otelhttp.LabelerFromContext" in normalized
    assert "This annotator must not start a span" in normalized
    assert "http.HandlerFunc(getTask)" in normalized
    assert ").ServeHTTP" in normalized
    assert "It does **not** rename the span" in normalized
    assert "one server span per request" in normalized
    assert (
        "HTTP server/client spans, `http.server.request.duration`, "
        "`http.server.active_requests`"
        not in guide
    )


def test_go_http_outcome_guidance_groups_collisions_without_misclassifying_4xx() -> None:
    skill = (
        ROOT / "skills" / "otel-instrument" / "SKILL.md"
    ).read_text(encoding="utf-8")
    guide = (
        ROOT / "skills" / "otel-instrument" / "references" / "languages" / "go.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join((skill + "\n" + guide).split())
    partial_eval = json.loads(
        (
            ROOT
            / "evals"
            / "go"
            / "chi-partial"
            / "eval"
            / "qual"
            / "instrument.json"
        ).read_text(encoding="utf-8")
    )
    rubric = " ".join(partial_eval["rubric"])

    assert "one bounded pass over the service's non-success response call sites" in normalized
    assert "group them by stable `(method, route, status code)`" in normalized
    assert "never broadens canonical selected scope" in normalized
    assert "selected finding's expected telemetry authors that attribute" in normalized
    assert "leave code untouched, record the scope mismatch" in normalized
    assert "legacy no-audit request" in normalized
    assert "same-route/same-status collision" in normalized
    assert "asserts the distinct `outcome.reason` values" in normalized
    assert "ordinary handled 4xx response leaves span status unset" in normalized
    assert "Do not add `RecordError`/`SetStatus` merely" in normalized
    assert "leaves ordinary handled 4xx SERVER responses unset" in rubric
    assert "records errors/status on failure paths" not in rubric


def test_python_guidance_does_not_map_plain_starlette_to_fastapi() -> None:
    references = (
        ROOT / "skills" / "otel-audit" / "references" / "languages" / "python.md",
        ROOT
        / "skills"
        / "otel-instrument"
        / "references"
        / "languages"
        / "python.md",
    )
    for reference in references:
        text = reference.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        assert "| `fastapi` | `opentelemetry-instrumentation-fastapi` |" in text
        assert "| `starlette` | `opentelemetry-instrumentation-starlette` |" in text
        assert "`fastapi` / `starlette`" not in text
        assert "Do not substitute the FastAPI instrumentor for a plain Starlette" in normalized


def test_python_guidance_splits_aiohttp_client_and_server_surfaces() -> None:
    references = (
        ROOT / "skills" / "otel-audit" / "references" / "languages" / "python.md",
        ROOT
        / "skills"
        / "otel-instrument"
        / "references"
        / "languages"
        / "python.md",
    )
    for reference in references:
        text = reference.read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        assert (
            "| `aiohttp.ClientSession` (client) | "
            "`opentelemetry-instrumentation-aiohttp-client` |"
        ) in text
        assert (
            "| `aiohttp.web` (server) | "
            "`opentelemetry-instrumentation-aiohttp-server` |"
        ) in text
        assert "| `aiohttp` | `opentelemetry-instrumentation-aiohttp-client` |" not in text
        assert "an application using both surfaces needs both packages" in normalized


def test_go_audit_distinguishes_route_attributes_from_span_names() -> None:
    guide = (
        ROOT / "skills" / "otel-audit" / "references" / "languages" / "go.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(guide.split())
    assert "bounded `http.route`" in normalized
    assert "Use `otelhttp.WithRouteTag` only when that exact source exports it" in normalized
    assert "the API is absent in v0.65.0 and later" in normalized
    assert "trace.SpanFromContext" in normalized
    assert "otelhttp.LabelerFromContext" in normalized
    assert "`WithRouteTag`, when available, does not rename" in normalized
    assert "renaming the current outer server span after route matching" in normalized
    assert "do not start a second server span" in normalized
    assert "for bounded route names" not in normalized


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
    assert "Do not stack two span-producing server middleware" in normalized


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
    flow = (ROOT / "skills" / "references" / "report-flow-contract.md").read_text(
        encoding="utf-8"
    )
    instrument_handoff = (
        ROOT
        / "skills"
        / "otel-instrument"
        / "references"
        / "json-approval-handoff.md"
    ).read_text(encoding="utf-8")
    verify_handoff = (
        ROOT / "skills" / "otel-verify" / "references" / "json-approval-handoff.md"
    ).read_text(encoding="utf-8")
    normalized_instrument = " ".join(instrument.split())
    normalized_verify = " ".join(verify.split())
    normalized_flow = " ".join(flow.split())
    normalized_instrument_handoff = " ".join(instrument_handoff.split())
    normalized_verify_handoff = " ".join(verify_handoff.split())

    assert (
        "verification as a repair loop, not a terminal handoff"
        in normalized_instrument
    )
    assert "Pre-finalization Repair Gate" in instrument
    assert (
        "failure -> failing source/config -> selected finding -> ownership -> evidence"
        in normalized_instrument
    )
    assert (
        "pre-existing OTel code/config defect inside the dependency-closed selected scope"
        in normalized_instrument
    )
    assert (
        "make a concrete code/config repair and continue until the affected check passes"
        in normalized_instrument
    )
    assert (
        "failed verification artifact produced during this loop is an intermediate artifact"
        in normalized_instrument
    )
    assert (
        "Do not finalize while any safe in-scope instrumentation-owned failure remains"
        in normalized_instrument
    )
    assert (
        "an unchanged selected OTel wiring defect is pre-existing but instrumentation-owned"
        in normalized_instrument
    )
    assert "relabel an executed failure as `not_proven`" in normalized_instrument
    assert "Do not ask the user to invoke `$otel-instrument` a second time" in normalized_instrument
    assert "Exact scenario IDs are verifier-owned technical scope" in normalized_instrument
    assert "write `remaining` as a repair-only list" in normalized_verify
    assert "never repairs application code" in normalized_verify
    assert "Do not tell the user to execute each scenario manually" in normalized_verify
    assert "For a standalone verification request" in normalized_verify
    assert "return a repair packet to that workflow" in normalized_verify
    assert "Do not emit the terminal reader-facing handoff yet" in normalized_verify
    assert (
        "do not enter the optional permanent-test-authoring or dependency-edit paths"
        in normalized_verify
    )
    assert (
        "an unchanged selected OTel wiring defect is `pre-existing`, not `instrumentation-introduced`"
        in normalized_verify
    )
    assert "pre-existing OTel defects inside selected scope" in normalized_flow
    assert "make a concrete repair attempt" in normalized_flow
    assert "failing verification overlay written during this loop is intermediate" in normalized_flow
    assert (
        "make a concrete repair for each safe in-scope instrumentation-owned failure"
        in normalized_instrument_handoff
    )
    assert "instrumentation_sha256" in normalized_instrument
    assert "selection_sha256" in normalized_instrument
    assert "instrumentation-final-gate" in normalized_instrument
    assert "meta.lifecycle: intermediate" in normalized_verify
    assert "instrumentation_sha256" in normalized_verify_handoff
    assert "selection_sha256" in normalized_verify_handoff
    assert (
        "For a child invocation from an active instrumentation workflow"
        in normalized_verify_handoff
    )
    assert "return control without presenting a terminal user handoff" in normalized_verify_handoff
    assert "Never use **pending** as an umbrella for a failed verification" in normalized_flow
    assert "**Verification failures**" in normalized_flow
    assert "**What verification found**" in normalized_flow
    assert "**Code repair required**" in normalized_flow
    assert "**How the repair is confirmed**" in normalized_flow
    assert "Do not render that automatic recheck as a second repair bullet" in normalized_flow
    assert "**Telemetry change / What was observed / Status**" in normalized_flow
    assert "**Coverage details**" in normalized_flow
    assert "`blocking_reason`" in normalized_flow
    assert "`unobserved_outcome`" in normalized_flow
    assert "**Runtime verification unavailable**" in normalized_flow
    assert "**Already proven**" in normalized_flow
    assert "**Still unobserved**" in normalized_flow
    assert "never use it as the blocker explanation" in normalized_verify
    assert "State local delivery and target-product check scope once" in normalized_flow
    assert "Do not render generic per-finding lines" in normalized_flow
    assert "do not repeat it on every finding" in normalized_instrument
    assert "do not repeat it per finding" in normalized_verify
    assert "do not render the finding's `remaining` list as a user checklist" in normalized_flow
    assert "A direct successful unit, application, or runtime observation proves" in normalized_instrument
    assert "mark that item `working`" in normalized_verify
    assert "audit scenarios' human `trigger` text" in normalized_flow
    assert "Never put unexplained `x/y`" in normalized_flow
    assert "Do not render aggregate statistic cards" in normalized_flow
    assert "These canonical and compatibility artifacts, not the HTML, are the downstream handoff" in normalized_flow
    assert (
        "Keep stable scenario IDs, commands, acceptance criteria, and exact counts in the canonical JSON and generated Markdown proof ledgers"
        in normalized_instrument
    )
    assert "Do not render aggregate statistic cards" in normalized_instrument
    assert "Technical closure ledger" in normalized_instrument
    assert "do not add aggregate statistic cards" in normalized_verify
    assert "never collapse it into `proof_mode: not_run`" in normalized_verify
    assert "denies any OTLP pipeline or export path" in normalized_instrument
    assert "no OTLP pipeline or export path exists" in normalized_verify
    assert "Reconcile delivery claims across that join" in normalized_flow
    assert "never fall back to stale instrumentation-phase next steps" in normalized_flow


def test_go_template_preserves_startup_resources_and_cleanup() -> None:
    guide = (
        ROOT / "skills" / "otel-instrument" / "references" / "languages" / "go.md"
    ).read_text(encoding="utf-8")
    assert "resource.WithFromEnv()" in guide
    assert "resource.WithTelemetrySDK()" in guide
    assert 'Value(attribute.Key("service.name"))' in guide
    assert "combineErrors(tp.Shutdown(ctx), mp.Shutdown(ctx))" in guide
    assert "combineErrors(err, tp.Shutdown(ctx))" in guide
    assert "func combineErrors(primary, secondary error) error" in guide
    assert 'fmt.Errorf("%w; additional error: %v", primary, secondary)' in guide
    assert '"errors"' not in guide
    assert "return errors.Join" not in guide
    assert 'log.Printf("telemetry disabled: %v", err)' in guide
    assert "log.Fatalf" not in guide
    assert '"go.opentelemetry.io/contrib/instrumentation/runtime"' not in guide
    assert "minimal HTTP setup intentionally" in guide


def test_go_references_use_versioned_redisotel_traces_and_metrics() -> None:
    audit_guide = (
        ROOT / "skills" / "otel-audit" / "references" / "languages" / "go.md"
    ).read_text(encoding="utf-8")
    instrument_guide = (
        ROOT
        / "skills"
        / "otel-instrument"
        / "references"
        / "languages"
        / "go.md"
    ).read_text(encoding="utf-8")
    for guide in (audit_guide, instrument_guide):
        assert "`github.com/redis/go-redis/v9`" in guide
        assert "`github.com/redis/go-redis/extra/redisotel/v9`" in guide
        assert "spans + metrics" in guide
        assert "github.com/redis/go-redis/extra/redisotel`" not in guide


def test_env_example_is_only_added_for_an_authorized_env_file_surface() -> None:
    guide = (
        ROOT / "skills" / "otel-instrument" / "SKILL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(guide.split())
    assert "repository already has an env-file workflow" in normalized
    assert "do not authorize adding `.env.example`" in normalized
    assert "existing/requested env-file surface" in normalized


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
