from __future__ import annotations

import json
import subprocess
from contextlib import nullcontext
from pathlib import Path

import pytest

from adapter import GUARD_IDS, JUDGE_SCHEMA, gate
from routing import changed_paths, owners, select


@pytest.mark.parametrize(("path", "expected"), [
    ("skills/otel-audit/SKILL.md", {"otel-audit"}),
    (".agents/skills/otel-audit", {"otel-audit"}),
    ("skills/otel-instrument/SKILL.md", {"otel-instrument"}),
    ("observer/main.go", set()),
    ("skills/references/local-otlp-receiver.md", {"otel-audit", "otel-instrument"}),
    ("skills/references/new-unmapped.md", {"otel-audit"}),
    ("evals/python/flask-basic/app.py", {"otel-audit"}),
    ("evals/python/flask-basic/eval/qual/instrument.json", {"otel-instrument"}),
    ("evals/promptfoo/package-lock.json", {"otel-audit"}),
    ("evals/promptfoo/adapter.py", {"otel-audit"}),
    ("pytest-codex-evals/src/pytest_codex_evals/runner.py", {"otel-audit"}),
    ("evals/codex-evals.toml", {"otel-audit"}),
    (".github/workflows/ci.yml", {"otel-audit"}),
    ("skills/AGENTS.md", {"otel-audit"}),
    ("skills/references/consumers.json", {"otel-audit"}),
    ("evals/go/kvstore/eval/inputs/instrumentation-seed.json", set()),
    ("evals/python/flask-basic/eval/inputs/instrumentation-seed.json", set()),
])
def test_ownership(path, expected):
    assert owners(path, [{"local-otlp-receiver.md": ["otel-audit", "otel-instrument"]}],
                  [{"skill": "otel-instrument"}]) == expected


def test_diff_parser_preserves_old_and_new_paths_and_special_characters():
    assert changed_paths("R100\0old path\0new\nλ\0D\0deleted\0C95\0a\0b\0") == [
        "old path", "new\nλ", "deleted", "a", "b"]
    assert changed_paths("") == []


def command(root: Path, *args: str):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root, filename, contents):
    path = root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    command(root, "add", ".")
    command(root, "commit", "-qm", "test")
    return command(root, "rev-parse", "HEAD")


def test_real_git_merge_base_rename_delete_and_consumer_union(tmp_path):
    command(tmp_path, "init", "-q")
    command(tmp_path, "config", "user.name", "Pilot Test")
    command(tmp_path, "config", "user.email", "pilot@example.invalid")
    metadata = "skills/references/consumers.json"
    base = commit(tmp_path, metadata, json.dumps({"old guide.md": ["otel-audit", "otel-verify"]}))
    base = commit(tmp_path, "skills/references/old guide.md", "guide")
    command(tmp_path, "checkout", "-qb", "feature")
    command(tmp_path, "mv", "skills/references/old guide.md", "moved guide.md")
    head = commit(tmp_path, metadata, json.dumps({"old guide.md": ["otel-instrument"]}))
    command(tmp_path, "checkout", "-qb", "base-advanced", base)
    advanced_base = commit(tmp_path, "unrelated.txt", "advanced base only")
    selected = select(tmp_path, advanced_base, head)
    assert selected["merge_base"] == base
    assert selected["selected"] == ["otel-audit"]
    assert selected["outside_pilot"] == ["otel-instrument", "otel-verify"]
    assert "unrelated.txt" not in selected["reasons"]
    command(tmp_path, "checkout", "-q", "feature")
    (tmp_path / "moved guide.md").unlink()
    deleted = commit(tmp_path, "skills/otel-audit/deleted.txt", "old")
    command(tmp_path, "rm", "skills/otel-audit/deleted.txt")
    head = commit(tmp_path, "observer/main.go", "unrelated")
    assert select(tmp_path, deleted, head)["selected"] == ["otel-audit"]
    with pytest.raises(subprocess.CalledProcessError):
        select(tmp_path, "missing-base", head)


def test_instrument_and_unrelated_only_do_not_run_audit(tmp_path):
    command(tmp_path, "init", "-q")
    command(tmp_path, "config", "user.name", "Pilot Test")
    command(tmp_path, "config", "user.email", "pilot@example.invalid")
    base = commit(tmp_path, "README.md", "base")
    head = commit(tmp_path, "skills/otel-instrument/SKILL.md", "instrument")
    result = select(tmp_path, base, head)
    assert result["selected"] == []
    assert result["state"] == "skipped: not affected"
    assert result["outside_pilot"] == ["otel-instrument"]
    base = head
    head = commit(tmp_path, "observer/main.go", "unrelated")
    assert select(tmp_path, base, head)["selected"] == []


def test_real_git_reads_unicode_newline_eval_definition_ownership(tmp_path):
    command(tmp_path, "init", "-q")
    command(tmp_path, "config", "user.name", "Pilot Test")
    command(tmp_path, "config", "user.email", "pilot@example.invalid")
    base = commit(tmp_path, "README.md", "base")
    head = commit(tmp_path, "evals/python/flask-basic/eval/qual/instrument\nλ.json", '{"skill":"otel-instrument"}')
    result = select(tmp_path, base, head)
    assert result["selected"] == []
    assert result["outside_pilot"] == ["otel-instrument"]


def test_all_affected_participants_are_selected(monkeypatch, tmp_path):
    import routing
    monkeypatch.setattr(routing, "PARTICIPANTS", {"otel-audit", "otel-instrument"})
    command(tmp_path, "init", "-q")
    command(tmp_path, "config", "user.name", "Pilot Test")
    command(tmp_path, "config", "user.email", "pilot@example.invalid")
    base = commit(tmp_path, "skills/references/consumers.json", json.dumps({
        "shared.md": ["otel-audit", "otel-instrument", "otel-verify"]}))
    head = commit(tmp_path, "skills/references/shared.md", "new")
    result = select(tmp_path, base, head)
    assert result["selected"] == ["otel-audit", "otel-instrument"]
    assert result["outside_pilot"] == ["otel-verify"]


@pytest.mark.parametrize("status", ["fail", "not-proven", "not-applicable", "ungraded", None])
def test_nonpass_never_becomes_pass(status):
    reasons = gate([{"id": "rubric-1", "status": status, "reason": "why", "evidence": "app.py:1 source"}],
                   ["rubric-1"], [{"id": name, "passed": True} for name in GUARD_IDS], [])
    assert len(reasons) == 1 and f"rubric-1: {status}" in reasons[0]


def test_gate_requires_complete_evidence_guards_and_clean_execution():
    check = {"id": "rubric-1", "status": "pass", "reason": "matches", "evidence": "app.py:1 source"}
    guards = [{"id": name, "passed": True} for name in GUARD_IDS]
    assert gate([check], ["rubric-1"], guards, []) == []
    for checks in ([], [check, check], [check, {**check, "id": "extra"}],
                   [{**check, "evidence": ""}], [{**check, "reason": ""}]):
        assert gate(checks, ["rubric-1"], guards, [])
    for failed in ([], [{"passed": False}], [{"passed": True, "skipped": True}]):
        assert gate([check], ["rubric-1"], failed, [])
    for error in ("judge exited with 1", "judge timed out", "source inputs changed during evaluation",
                  "canonical audit validator failed", "raw agent evidence changed during grading"):
        assert error in gate([check], ["rubric-1"], guards, [error])


def test_judge_schema_rejects_boolean_status():
    from jsonschema import ValidationError, validate
    with pytest.raises(ValidationError):
        validate({"checks": [{"id": "rubric-1", "status": True,
                              "reason": "why", "evidence": "app.py"}]}, JUDGE_SCHEMA)


def test_proof_fails_on_stale_sources(monkeypatch):
    import report
    rules = json.loads((report.ROOT / "evals/python/flask-basic/eval/qual/audit.json").read_text())["rubric"]
    proof = {"schema_version": 1, "gate": True, "errors": [],
             "guards": [{"id": name, "passed": True} for name in GUARD_IDS],
             "checks": [{"id": f"rubric-{i}", "status": "pass", "reason": "why", "evidence": "app.py:1"}
                        for i in range(1, len(rules) + 1)], "source_files": {"old": "hash"}}
    proof["raw_grade"] = {"checks": proof["checks"]}
    proof["isolation"] = {"active": True, "config_sha256": report.digest(report.ROOT / "evals/codex-eval-home.config.toml"), "home_mode": "fresh-per-actor"}
    monkeypatch.setattr(report, "source_manifest", lambda: {"new": "hash"})
    with pytest.raises(ValueError, match="stale"):
        report.verify(proof)


def test_adapter_preserves_partial_timeout_evidence_and_never_grades_it_pass(monkeypatch, tmp_path):
    import adapter
    calls = []
    def timeout(**kwargs):
        calls.append(kwargs)
        workspace = kwargs["exec_dir"]
        workspace.mkdir(parents=True)
        (workspace / "trace.jsonl").write_text('{"partial":true}\n')
        raise TimeoutError("agent timeout")
    monkeypatch.setattr(adapter, "run_side", timeout)
    monkeypatch.setattr(adapter, "validate_home", lambda: None)
    monkeypatch.setattr(adapter, "isolated_home", nullcontext)
    monkeypatch.setattr(adapter, "source_manifest", lambda: {})
    monkeypatch.setattr(adapter.subprocess, "check_output", lambda *a, **k: "unit-test identity")
    result = adapter.run("$otel-audit", tmp_path / "evidence")
    assert result["gate"] is False
    assert "agent timeout" in result["errors"][0]
    assert (tmp_path / "evidence/agent/trace.jsonl").read_text() == '{"partial":true}\n'
    assert calls[0]["side"] == "with_skill"
    assert calls[0]["rubric"] is False
    assert calls[0]["prompt"].endswith("$otel-audit")
    with pytest.raises(FileExistsError):
        adapter.run("$otel-audit", tmp_path / "evidence")


def test_renderer_fences_untrusted_evidence():
    from report import block
    text = '```\n<script>alert(1)</script>\n[click](https://example.invalid)'
    rendered = block(text)
    assert rendered.startswith('````text\n')
    assert rendered.endswith('\n````')


def test_personal_or_missing_eval_home_is_rejected(monkeypatch):
    from adapter import validate_home
    monkeypatch.delenv("CODEX_EVAL_HOME", raising=False)
    with pytest.raises(ValueError, match="isolated eval config"):
        validate_home()


def test_judge_timeout_preserves_raw_output_in_separate_workspace(monkeypatch, tmp_path):
    import adapter
    from pytest_codex_evals.definitions import GradeResult, SideResult
    from pytest_codex_evals.runner import prepare_side_workspace

    def fake_side(**kwargs):
        side = kwargs["artifact_dir"]
        prepare_side_workspace(adapter.ROOT, kwargs["case"], "with_skill", side)
        (side / "service/.observe").mkdir()
        (side / "service/.observe/otel-audit.json").write_text('{"unit":"fixture"}')
        (side / "service/.observe/otel.html").write_text('unit fixture')
        for name in ("trace.jsonl", "last_message.md", "grade.json"):
            (side / name).write_text('unit evidence')
        return SideResult(side="with_skill", exit_code=0, trace_path=str(side / "trace.jsonl"),
                          final_message_path=str(side / "last_message.md"),
                          grade=GradeResult(checks=[{"id": name, "description": "unit guard", "passed": True}
                                                   for name in GUARD_IDS]))

    class TimeoutJudge:
        def run_judge(self, **kwargs):
            assert not kwargs["exec_dir"].is_relative_to(adapter.ROOT)
            assert not (kwargs["exec_dir"] / ".agents").exists()
            raise subprocess.TimeoutExpired("unit judge", 1, output=b'partial judge trace', stderr=b'timeout stderr')

    monkeypatch.setattr(adapter, "run_side", fake_side)
    monkeypatch.setattr(adapter, "CodexBackend", lambda **kwargs: TimeoutJudge())
    monkeypatch.setattr(adapter, "validate_home", lambda: None)
    monkeypatch.setattr(adapter, "isolated_home", nullcontext)
    monkeypatch.setattr(adapter, "source_manifest", lambda: {})
    monkeypatch.setattr(adapter.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, 'valid', ''))
    monkeypatch.setattr(adapter.subprocess, "check_output", lambda *a, **k: "unit-test identity")
    result = adapter.run("$otel-audit", tmp_path / "evidence")
    assert result["gate"] is False
    assert "TimeoutExpired" in result["errors"][0]
    assert (tmp_path / "evidence/judge/rubric_trace.jsonl").read_text() == 'partial judge trace'
    assert (tmp_path / "evidence/judge/rubric_stderr.txt").read_text() == 'timeout stderr'
    assert (tmp_path / "evidence/agent/trace.jsonl").read_text() == 'unit evidence'


def test_fresh_homes_exclude_ambient_instructions_and_restore_environment(monkeypatch, tmp_path):
    import adapter
    original = tmp_path / "source-home"
    original.mkdir()
    (original / "config.toml").write_bytes((adapter.ROOT / "evals/codex-eval-home.config.toml").read_bytes())
    (original / "auth.json").write_text('{"unit":"not a credential"}')
    (original / "AGENTS.md").write_text('ambient instructions must not be copied')
    monkeypatch.setenv("CODEX_EVAL_HOME", str(original))
    assert adapter.validate_home()
    homes = []
    for _ in range(2):
        with adapter.isolated_home():
            home = Path(adapter.os.environ["CODEX_EVAL_HOME"])
            homes.append(home)
            assert set(p.name for p in home.iterdir()) == {"config.toml", "auth.json"}
            assert home != original
        assert not home.exists()
        assert adapter.os.environ["CODEX_EVAL_HOME"] == str(original)
    assert homes[0] != homes[1]
    (original / "config.toml").write_text('unreviewed config')
    with pytest.raises(ValueError, match="isolated eval config"):
        adapter.validate_home()


def test_dirty_and_untracked_sources_are_refused(monkeypatch):
    import adapter
    for status in (' M input.py\0', '?? input.py\0'):
        monkeypatch.setattr(adapter.subprocess, "check_output", lambda *a, **kw: status)
        with pytest.raises(ValueError, match="commit evaluated source inputs"):
            adapter.require_clean({"input.py": "hash"})


def test_discovery_requires_exact_canonical_relative_target(tmp_path):
    from adapter import discovery_digest
    link = tmp_path / ".agents/skills/otel-audit"
    link.parent.mkdir(parents=True)
    link.symlink_to('/not/canonical')
    with pytest.raises(ValueError, match="canonical skill link"):
        discovery_digest(tmp_path)
    link.unlink()
    link.symlink_to('../../skills/otel-audit')
    assert discovery_digest(tmp_path)
