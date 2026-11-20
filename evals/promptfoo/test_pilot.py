from __future__ import annotations

import json
import subprocess
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
    assert gate([{"id": "rubric-1", "status": status, "reason": "why", "evidence": "app.py:1 source"}],
                ["rubric-1"], [{"passed": True}], [])


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
