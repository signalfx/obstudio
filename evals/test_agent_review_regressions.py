"""Keep the supplied agent audit evidence reproducible from its fixture."""

import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


FIXTURE = Path(__file__).parent / "python/model-directed-agent"
REFERENCE = re.compile(r"(?<![\w/])((?:[\w.-]+/)*[\w.-]+\.(?:py|md|txt))(?::(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*))?")


@pytest.mark.parametrize("name", ["agent-audit", "prior-audit"])
def test_supplied_audit_source_references_exist_and_fit_line_bounds(name):
    audit = json.loads((FIXTURE / "eval/inputs" / f"{name}.json").read_text())

    def inspect(value, field=""):
        if isinstance(value, dict):
            for key, item in value.items():
                inspect(item, key)
        elif isinstance(value, list):
            for item in value:
                inspect(item, field)
        elif isinstance(value, str) and field in {"source", "evidence", "config_evidence", "runner"}:
            for filename, locations in REFERENCE.findall(value):
                source = FIXTURE / filename
                assert source.is_file(), (name, field, filename)
                for location in locations.split(",") if locations else []:
                    first, _, last = location.partition("-")
                    assert 1 <= int(first) <= int(last or first) <= len(source.read_text().splitlines()), (name, field, value)

    inspect(audit)
    serving = next(node for node in ast.walk(ast.parse((FIXTURE / "app.py").read_text()))
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and isinstance(node.func.value, ast.Name) and node.func.value.id == "app"
                   and node.func.attr == "run")
    entry = next(item for item in audit["evidence"] if item["check"] == "Entry point")
    cited = set()
    for filename, locations in REFERENCE.findall(entry["source"]):
        if filename == "app.py":
            for location in locations.split(",") if locations else []:
                first, _, last = location.partition("-")
                cited.update(range(int(first), int(last or first) + 1))
    assert serving.lineno in cited, (name, "Entry point citation misses app.run", serving.lineno)
    for environment in audit["verification"]["environments"]:
        assert "historical_check.py" in environment["runner"]


@pytest.mark.parametrize("layout", ["canonical", "isolated", "missing"])
def test_gateway_contract_resolver_discovery_and_preflight(tmp_path, layout):
    root = Path(__file__).resolve().parents[1]
    fixture = root / "evals/python/agent-connection-demo"
    resolver = root / "skills/otel-instrument/scripts/resolve_ao_resources.py"
    if layout == "canonical":
        service = fixture
    else:
        service = tmp_path / "service"
        service.mkdir()
        for name in ["gateway_contract_check.py", "probe.py"]:
            shutil.copy2(fixture / name, service / name)
        if layout == "isolated":
            staged = tmp_path / ".agents/skills/otel-instrument/scripts"
            staged.mkdir(parents=True)
            shutil.copy2(resolver, staged / resolver.name)
    check = service / "gateway_contract_check.py"
    tree = ast.parse(check.read_text())
    discovery = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "default_resolver")
    namespace = {"__file__": str(check), "Path": Path}
    exec(compile(ast.Module(body=[discovery], type_ignores=[]), str(check), "exec"), namespace)
    found = namespace["default_resolver"]()
    if layout == "missing":
        assert found is None
        result = subprocess.run([sys.executable, str(check)], capture_output=True, text=True, timeout=5)
        assert result.returncode == 2
        assert "provide --resolver" in result.stderr
        assert "Traceback" not in result.stderr
        assert "subTest" not in result.stderr
    else:
        assert found.is_file()
        assert found.read_bytes() == resolver.read_bytes()


def test_model_directed_application_regressions_use_real_sdk_and_stdlib_logs():
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("OTEL_") and key.lower() not in {
                       "http_proxy", "https_proxy", "all_proxy", "no_proxy",
                   }}
    environment["NETRC"] = os.devnull
    result = subprocess.run(
        [sys.executable, str(FIXTURE / "checks/review_regressions.py")],
        env=environment, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    environment["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:9"
    result = subprocess.run(
        [sys.executable, "-c", (
            "import logging,sys\n"
            f"sys.path.insert(0,{str(FIXTURE)!r})\n"
            "import otel_setup\n"
            "handlers=tuple(logging.getLogger().handlers)\n"
            "factory=logging.getLogRecordFactory()\n"
            "install,shutdown=otel_setup.configure_opentelemetry()\n"
            "shutdown();install()\n"
            "assert tuple(logging.getLogger().handlers)==handlers\n"
            "assert logging.getLogRecordFactory() is factory\n"
        )], env=environment, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((FIXTURE.parents[2] / "docs/evidence/agent-stdlib-logging-review.json").read_text())
    for key in ("baseline_setup_source", "regression_check_source"):
        source = receipt[key]
        assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
        ast.parse(source["text"])
    cases = next(node.iter for node in ast.walk(ast.parse(receipt["regression_check_source"]["text"]))
                 if isinstance(node, ast.For) and isinstance(node.target, ast.Name)
                 and node.target.id == "overrides")
    assert len(cases.elts) == receipt["regression_check_source"]["configuration_profiles"] == 14


@pytest.mark.parametrize("case", [
    "test_public_wrapper_and_request_hook_use_actual_wire_binding",
    "test_cached_restart_forwards_without_resource_lookup",
    "test_wire_oracle_still_rejects_missing_headers_and_resource_mismatch",
    "test_public_views_cannot_rewrite_identity_topology_or_operations",
    "test_split_wire_batches_are_collected_for_the_native_turn",
    "test_missing_overlapping_and_duplicate_spans_are_rejected",
    "test_same_pid_selects_the_native_turn_from_a_multi_turn_batch",
    "test_complete_unbound_turn_allows_another_recovery_attempt",
])
def test_connection_probe_public_wire_contract(case):
    check = Path(__file__).parent / "python/agent-connection-demo/checks/probe_regressions.py"
    result = subprocess.run(
        [sys.executable, str(check), f"ProbeTests.{case}"],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_retained_eval_history_counts_include_partial_runs_and_failed_criteria():
    archive = Path(__file__).parents[1] / "docs/evidence/agent-observability-eval-history.json"
    history = json.loads(archive.read_text())
    expected = history["selection"]["tasks_by_skill"]
    identities = set()
    for run in history["runs"]:
        tasks = sorted(grade["task"] for grade in run["grades"])
        assert run["coverage"] == ("complete" if tasks == expected[run["skill"]] else "partial")
        assert run["run_id"] <= history["selection"]["last_included_run_id"]
        for grade in run["grades"]:
            identity = (run["skill"], run["run_id"], grade["task"])
            assert identity not in identities
            identities.add(identity)
            assert grade["overall_pass"] == all(check["pass"] for check in grade["checks"])
            for check in grade["checks"]:
                if not check["pass"]:
                    assert check["notes"] and check["evidence"]

    for scope, expected_counts in history["summary"].items():
        runs = [run for run in history["runs"] if scope == "all" or run["coverage"] == "complete"]
        grades = [grade for run in runs for grade in run["grades"]]
        checks = [check for grade in grades for check in grade["checks"]]
        assert expected_counts == {
            "runs": len(runs), "task_grades": len(grades),
            "fully_passing_task_grades": sum(grade["overall_pass"] for grade in grades),
            "checks_passed": sum(check["pass"] for check in checks), "checks_total": len(checks),
            "distinct_tasks": len({(run["skill"], grade["task"]) for run in runs for grade in run["grades"]}),
            "distinct_tasks_with_failure": len({(run["skill"], grade["task"]) for run in runs for grade in run["grades"] if not grade["overall_pass"]}),
        }
    assert history["summary"]["complete"]["checks_total"] == 373
    assert history["summary"]["all"]["checks_total"] == 431
    for rate in history["task_rates"]:
        pairs = [(run, grade) for run in history["runs"] if run["skill"] == rate["skill"]
                 for grade in run["grades"] if grade["task"] == rate["task"]]
        for scope in ("complete", "all"):
            grades = [grade for run, grade in pairs if scope == "all" or run["coverage"] == "complete"]
            assert rate[scope] == {"runs": len(grades), "failed_tasks": sum(not grade["overall_pass"] for grade in grades)}
        failures = Counter(check["id"] for _, grade in pairs for check in grade["checks"] if not check["pass"])
        assert {check["id"]: check["failures"] for check in rate["failed_criteria"]} == failures
        for criterion in rate["failed_criteria"]:
            assert criterion["run_ids"] == [run["run_id"] for run, grade in pairs
                                            for check in grade["checks"] if check["id"] == criterion["id"] and not check["pass"]]


def test_retained_failure_evidence_survives_without_git_or_local_run_directories():
    root = Path(__file__).parents[1]
    history = json.loads((root / "docs/evidence/agent-observability-eval-history.json").read_text())
    for receipt in history["independent_reproductions"]:
        assert hashlib.sha256(receipt["raw_json"].encode()).hexdigest() == receipt["original_sha256"]
        assert json.loads(receipt["raw_json"])
    for source in history["failing_source_snapshots"]:
        assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
        ast.parse(source["text"])
        assert any(run["skill"] == source["skill"] and run["run_id"] == source["run_id"]
                   and any(grade["task"] == source["task"] and not grade["overall_pass"] for grade in run["grades"])
                   for run in history["runs"])
    baseline = history["baseline"]["reports"]
    summaries = [report["summary"] for report in baseline]
    assert sum(summary["prompt_count"] for summary in summaries) == 15
    assert sum(summary["with_skill"]["rubric"]["passed"] for summary in summaries) == 86
    assert sum(summary["with_skill"]["rubric"]["total"] for summary in summaries) == 93
    assert sum(len(report["failures"]) for report in baseline) == 7
    document = (root / "docs/agent-observability-eval-open-findings.md").read_text()
    assert "evidence/agent-observability-eval-history.json" in document
    for rate in history["task_rates"]:
        complete, all_runs = rate["complete"], rate["all"]
        assert (f"| {rate['skill']} / `{rate['task']}` | {complete['failed_tasks']}/{complete['runs']} | "
                f"{all_runs['failed_tasks']}/{all_runs['runs']} |") in document


def test_content_counterexamples_retain_observed_representation_failures():
    fixture = Path(__file__).parent / "python/existing-otel-agent-demo"
    corpus = json.loads((fixture / "eval/inputs/content-counterexamples.json").read_text())
    cases = {case["id"]: case for case in corpus["cases"]}
    assert json.loads(cases["quoted-email"]["value"]) == "reader@example.invalid"
    assert "reasoning=hidden-value" in json.loads(cases["quoted-labels"]["value"])
    assert "hidden_reasoning=thought-sentinel" in cases["labelled-protected-values"]["value"]
    for name in ("typed-reasoning", "json-typed-reasoning"):
        value = cases[name]["value"]
        if isinstance(value, str):
            value = json.loads(value)
        assert value["parts"] == [{"type": "reasoning", "content": "hidden-reasoning-sentinel"}]
    recipe = cases["aggregate-unicode"]["value_recipe"]
    value = {**recipe["prefix"], **{f"{recipe['field_prefix']}{index}": recipe["unit"] * recipe["repeat"]
                                 for index in range(recipe["field_count"])}}
    encoded = json.dumps(value, ensure_ascii=False).encode()
    assert len(encoded) > cases["aggregate-unicode"]["max_serialized_attribute_bytes"]
    assert corpus["malformed_known_parts"] == [
        {"type": "text"}, {"type": "text", "content": 123},
        {"type": "tool_call", "name": 123}, {"type": "tool_call_response"},
    ]


@pytest.mark.parametrize("snapshot_index", range(4))
def test_archived_sanitizer_failures_replay_from_tracked_data(snapshot_index):
    archive = Path(__file__).parents[1] / "docs/evidence/agent-observability-eval-history.json"
    source = json.loads(archive.read_text())["failing_source_snapshots"][snapshot_index]
    tree = ast.parse(source["text"])
    allowed = {
        "MAX_MESSAGES", "MAX_PARTS", "MAX_BYTES", "MAX_TEXT_BYTES", "MAX_ATTRIBUTE_BYTES",
        "MAX_DEPTH", "MAX_ITEMS", "SENSITIVE", "LABELLED", "_PRIVATE", "_LABEL", "_EMAIL",
        "EMAIL", "CREDENTIAL",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {item.id for target in node.targets for item in ast.walk(target) if isinstance(item, ast.Name)}
            if names and names <= allowed:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {"sanitize", "bounded"}:
            nodes.append(node)
    namespace = {"json": json, "re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), source["original_path"], "exec"), namespace)
    sanitize = namespace["sanitize"]
    if snapshot_index == 0:
        assert "HIDDEN_SENTINEL" in sanitize("hidden_reasoning=HIDDEN_SENTINEL; question=shipment")
        oversized = json.dumps({f"field_{index}": "a" * 2000 for index in range(16)})
        assert len(sanitize(oversized).encode()) > 8192
    elif snapshot_index == 1:
        for scalar in ('"reader@example.invalid"', '"token=fixture-secret;reasoning=hidden"'):
            assert sanitize(scalar) == scalar
    elif snapshot_index == 2:
        assert "thought-sentinel" in sanitize("hidden_reasoning=thought-sentinel")
        assert "hidden-sentinel" in sanitize("private_prompt=hidden-sentinel")
    else:
        reasoning = {"type": "reasoning", "content": "hidden-reasoning-sentinel"}
        assert "hidden-reasoning-sentinel" in json.dumps(sanitize(reasoning))
        assert "hidden-reasoning-sentinel" in sanitize(json.dumps(reasoning))


def test_correction_adjudications_retain_raw_grades_and_effective_applicability():
    archive = Path(__file__).parents[1] / "docs/evidence/agent-observability-correction-runs.json"
    history = json.loads(archive.read_text())
    first = history["rounds"][0]
    for decision in first["adjudications"]:
        run = next(run for run in first["runs"] if run["skill"] == decision["skill"])
        grade = next(grade["grade"] for grade in run["grades"] if grade["task"] == decision["task"])
        assert not next(check["pass"] for check in grade["checks"] if check["id"] == decision["criterion"])
        case = decision["non_agent_control"]
        if decision["decision"] == "confirmed":
            assert "no agent or workflow" in case["role"]
            assert "one agent with model/tool children" in case["lifecycle_and_delivery"][0]["parent_duplicate_rule"]
        else:
            assert decision["decision"] == "false_positive"
            assert case["provisioning_acceptance"]["status"] == "Not applicable"
            assert case["provisioning_acceptance"]["required"]
            for state in case["studio_states"].values():
                for key in ("project_configuration", "stream_configuration", "routing_configuration"):
                    assert state[key]["status"] == "Not applicable"
    repaired = [receipt["proof"] for receipt in history["independent_replays"] if receipt["original_file"].startswith("repaired-")]
    assert {proof["package_versions"]["opentelemetry-sdk"] for proof in repaired} == {"1.44.0", "1.45.1"}
    for proof in repaired:
        assert proof["pass"] and proof["native_span_count"] == proof["wire_span_count"] == 18
        assert proof["wire_matches_native_ids"] and proof["wire_protected_absent"]
        assert proof["original_owners_retained"]
    for source in history["repaired_runtime_files"]:
        assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
    regrade = history["unchanged_actor_regrade"]
    assert regrade["actor_service_unchanged"] and regrade["original_grade_unchanged"]
    assert regrade["supplemental_grade"]["overall_pass"]
    assert len(regrade["supplemental_grade"]["checks"]) == 6
    assert all(check["pass"] for check in regrade["supplemental_grade"]["checks"])
    original = next(grade for run in first["runs"] if run["skill"] == "otel-verify"
                    for grade in run["grades"] if grade["task"] == regrade["task"])
    assert original["sha256"] == regrade["original_grade_sha256"]
    assert not original["grade"]["overall_pass"]
    decision = next(item for item in first["adjudications"] if item["decision"] == "false_positive")
    assert regrade["actor_service_manifest"]["key_files"][".observe/agent-resource-cases.json"] == decision["artifact_sha256"]
    negative = history["applicability_negative_control"]
    assert negative["changed_files"] == [".observe/agent-resource-cases.json"]
    assert negative["source_files_unchanged"] and negative["judge_did_not_change_artifacts"]
    assert not next(check["pass"] for check in negative["grade"]["checks"] if check["id"] == "rubric-3")
    frozen = history["applicability_frozen_definition"]
    assert hashlib.sha256(frozen["text"].encode()).hexdigest() == frozen["sha256"]
    assert frozen["sha256"] == negative["rubric_definition_sha256"] == regrade["rubric_definition_sha256"]


def test_correction_archive_counts_every_grade_and_retains_recovery_sources():
    archive = Path(__file__).parents[1] / "docs/evidence/agent-observability-correction-runs.json"
    history = json.loads(archive.read_text())
    for phase in history["rounds"]:
        for run in phase["runs"]:
            grades = [entry["grade"] for entry in run["grades"]]
            checks = [check for grade in grades for check in grade["checks"]]
            assert len(grades) == run["summary"]["prompt_count"]
            assert len({entry["task"] for entry in run["grades"]}) == len(grades)
            assert all(grade["overall_pass"] == all(check["pass"] for check in grade["checks"])
                       for grade in grades)
            summary = run["summary"]["with_skill"]["rubric"]
            assert (sum(check["pass"] for check in checks), len(checks)) == (summary["passed"], summary["total"])
    latest = {}
    retained = set()
    for phase in history["rounds"]:
        for run in phase["runs"]:
            identity = (run["skill"], run["run_id"])
            assert identity not in retained, identity
            retained.add(identity)
            latest[run["skill"]] = run
    assert {skill: len(run["grades"]) for skill, run in latest.items()} == {
        "otel-audit": 4, "otel-instrument": 9, "otel-verify": 4,
    }
    for source in history["bounded_recovery_integration"]["files"]:
        assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
    assert all(history["bounded_recovery_integration"]["fixture_match"].values())


def test_correction_closure_notes_match_raw_audit_history_and_current_reports():
    root = Path(__file__).parents[1]
    history = json.loads((root / "docs/evidence/agent-observability-correction-runs.json").read_text())
    document = (root / "docs/agent-observability-eval-open-findings.md").read_text()
    audit = [run for phase in history["rounds"] for run in phase["runs"]
             if run["skill"] == "otel-audit"]
    tasks = sorted({entry["task"] for run in audit for entry in run["grades"]})
    for task in tasks:
        grades = [entry["grade"] for run in audit for entry in run["grades"]
                  if entry["task"] == task]
        failed = [[check["id"] for check in grade["checks"] if not check["pass"]]
                  for grade in grades]
        failures = [checks for checks in failed if checks]
        criteria = "; ".join(" + ".join(checks) for checks in failures) or "None"
        assert f"| `{task}` | {len(failures)}/{len(grades)} | {criteria} |" in document
    latest = {}
    for phase in history["rounds"]:
        for run in phase["runs"]:
            latest[run["skill"]] = run
    for skill, label in (("otel-audit", "Audit"), ("otel-instrument", "Instrument"),
                         ("otel-verify", "Verify")):
        report = json.loads((root / f"eval-reports/{skill}/rubric/benchmark.json").read_text())
        run_id = report["metadata"]["run_id"]
        assert latest[skill]["run_id"] == run_id
        assert f"| {label} | `{run_id}` |" in document
    cohort = next(phase for phase in history["rounds"]
                  if phase["label"] == "merged-main coordinated source verification")
    assert {run["skill"] for run in cohort["runs"]} == {"otel-audit", "otel-instrument", "otel-verify"}
    source_files = {}
    for run in cohort["runs"]:
        for name, digest in run["source"]["files"].items():
            assert name not in source_files or source_files[name] == digest
            source_files[name] = digest
    assert source_files == cohort["consistent_source_files"]
    grades = [entry["grade"] for run in cohort["runs"] for entry in run["grades"]]
    checks = [check for grade in grades for check in grade["checks"]]
    assert (f"| Merged-main coordinated source verification | "
            f"{sum(grade['overall_pass'] for grade in grades)}/{len(grades)} | "
            f"{sum(check['pass'] for check in checks)}/{len(checks)} |") in document
    assert "no clean coordinated sweep\nat the corrected source is claimed" in document


def test_routing_acceptance_review_retains_actual_failed_rows_and_checker_blind_spots():
    root = Path(__file__).parents[1]
    receipt = json.loads((root / "docs/evidence/agent-routing-acceptance-review.json").read_text())
    files = receipt["original_files"]
    for source in files.values():
        assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
    grade = json.loads(files["rubric_grade.json"]["text"])
    assert {check["id"] for check in grade["checks"] if not check["pass"]} == {"rubric-2", "rubric-6"}
    assert not grade["overall_pass"]
    report = json.loads(files["service/.observe/agent-resource-cases.json"]["text"])
    go = report["cases"]["fresh_native_fallback"]["routing"]
    assert "ExportSpans(context.Context" in go["required_fix"]
    assert "force_flush/shutdown or supported logger.terminate" in " ".join(go["acceptance_criteria"])
    ordinary = report["cases"]["non_agent_control"]
    assert ordinary["project"]["status"] == ordinary["stream"]["status"] == "N/A"
    assert not ordinary["routing"]["acceptance_refs"]
    assert "actual supported resource result" in " ".join(ordinary["routing"]["acceptance_criteria"])
    checked = json.loads(files["service/.observe/evidence/source-ledger-consistency.json"]["text"])
    assert checked["status"] == "Pass" and not checked["baseline"]["errors"]
    correction = receipt["first_correction"]["files"]
    for source in correction.values():
        assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
    grade = json.loads(correction["rubric_grade.json"]["text"])
    assert {check["id"] for check in grade["checks"] if not check["pass"]} == {"rubric-2"}
    go = json.loads(correction["service/.observe/agent-resource-cases.json"]["text"])["cases"]["fresh_native_fallback"]
    assert not go["provider_exporter_destination_ownership"]["current_components"]
    assert all("preserve current native provider" in row["pattern"]
               for row in go["operation_and_producer_receipt"])
    candidate = receipt["owner_correction"]["files"]
    for source in candidate.values():
        assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
    grade = json.loads(candidate["rubric_grade.json"]["text"])
    assert grade["overall_pass"] and all(check["pass"] for check in grade["checks"])
    checked = json.loads(candidate["service/.observe/source-ledger-consistency.json"]["text"])
    assert checked["status"] == "Pass" and not checked["active_report_errors"]
    assert checked["source_unchanged"]
    assert len(checked["negative_controls"]) == 8
    assert all(control["rejected"] for control in checked["negative_controls"])
    replay = receipt["owner_correction"]["independent_replay"]
    assert replay["returncode"] == 0 and replay["source_unchanged"]
    assert replay["checked_paths"] == len(checked["checked_json_paths"]) == 763
    go = json.loads(candidate["service/.observe/agent-resource-cases.json"]["text"])["source_ledger"]["fresh_native_fallback"]
    assert not go["provider_exporter_destination_ownership"]["current_components"]
    components = {row["id"]: row for row in go["provider_exporter_destination_ownership"]["proposed_components"]}
    for row in go["operation_and_producer_receipt"]:
        assert row["component_phase"] == row["provider_phase"] == "proposed"
        assert components[row["creator_component_id"]]["phase"] == "proposed"
        assert components[row["provider_component_id"]]["phase"] == "proposed"
        assert row["runtime_version_receipt"]["provider_component_id"] == row["provider_component_id"]
        assert row["runtime_version_receipt"]["provider_phase"] == "proposed"


@pytest.mark.parametrize("source_index", range(2))
def test_fresh_genai_and_logs_samples_fix_exact_original_quoted_scalars(source_index):
    archive = Path(__file__).parents[1] / "docs/evidence/agent-observability-correction-runs.json"
    source = json.loads(archive.read_text())["fresh_content_sources"][source_index]
    assert hashlib.sha256(source["text"].encode()).hexdigest() == source["sha256"]
    tree = ast.parse(source["text"])
    constants = {"MAX_MESSAGES", "MAX_PARTS", "MAX_BYTES", "PROTECTED", "LABEL", "EMAIL",
                 "PRIVATE", "LABELLED", "PRIVATE_TOKEN", "OMIT"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {item.id for target in node.targets for item in ast.walk(target) if isinstance(item, ast.Name)}
            if names and names <= constants:
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {"sanitize", "text", "utf8", "encode", "dumps"}:
            nodes.append(node)
    namespace = {"json": json, "re": re, "Any": object}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), source["filename"], "exec"), namespace)
    for scalar in ('"private-prompt-sentinel"', '"reader@example.invalid"', '"token=fixture-secret;reasoning=hidden"'):
        result = namespace["sanitize"](scalar)
        assert all(value not in str(result) for value in ("private-prompt-sentinel", "reader@example.invalid", "fixture-secret", "hidden"))
