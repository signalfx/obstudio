"""Scoring must preserve false positives, misses, and application clustering."""

import os

import pytest

from audit_accuracy import check_python_runtime, cluster_interval, confusion, environment, f1, grade, resolve_binary, source_hashes, write_json


def test_confusion_keeps_each_error_direction():
    units = [{"id": key, "gap": gap} for key, gap in [("tp", True), ("fp", False), ("tn", False), ("fn", True)]]
    assert confusion(units, dict(tp=True, fp=True, tn=False, fn=False)) == dict(tp=1, fp=1, tn=1, fn=1)
    assert f1(dict(tp=1, fp=1, tn=1, fn=1)) == 0.5


@pytest.mark.parametrize("predictions", [{}, {"gap": 1}, {"gap": True, "extra": False}])
def test_missing_or_untyped_predictions_do_not_pass(predictions):
    with pytest.raises(ValueError):
        confusion([{"id": "gap", "gap": True}], predictions)


def test_healthy_control_penalizes_any_false_finding():
    assert f1(dict(tp=0, fp=0, tn=7, fn=0)) == 1
    assert f1(dict(tp=0, fp=1, tn=6, fn=0)) == 0
    assert f1(dict(tp=0, fp=0, tn=6, fn=1)) == 0


def test_cluster_interval_retains_application_disagreement():
    assert cluster_interval([0] * 6) == [0, 0]
    low, high = cluster_interval([-1, 1])
    assert low == -1 and high == 1
    assert cluster_interval([0.2] * 6)[0] == pytest.approx(0.2)
    with pytest.raises(ValueError):
        cluster_interval([])


def test_hashes_bind_source_but_exclude_agent_outputs(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("print('first')\n")
    before = source_hashes(tmp_path)
    (tmp_path / ".observe").mkdir()
    (tmp_path / ".observe/report.py").write_text("output only")
    assert source_hashes(tmp_path) == before
    source.write_text("print('changed')\n")
    assert source_hashes(tmp_path) != before


def test_grading_waits_for_complete_pairs(tmp_path, monkeypatch):
    write_json(tmp_path / "protocol.json", {"cases": {"pending-app": {}}})
    write_json(tmp_path / "jobs.json", [
        dict(id=f"{version}-{repeat}", case="pending-app", repeat=repeat, version=version)
        for repeat in range(2) for version in ["baseline", "candidate"]
    ])
    def unexpected_model_call(*args, **kwargs):
        pytest.fail("An incomplete audit pair must not be graded")
    monkeypatch.setattr("audit_accuracy.invoke", unexpected_model_call)
    grade(tmp_path, tmp_path / "unused-home", 1)
    assert not (tmp_path / "grading").exists()


def test_explicit_runtime_override_wins_over_path(monkeypatch):
    monkeypatch.setenv("AUDIT_ACCURACY_GO_BIN", "/selected/go")
    monkeypatch.setattr("audit_accuracy.shutil.which", lambda name: "/other/go")
    assert resolve_binary("go", "AUDIT_ACCURACY_GO_BIN") == "/selected/go"
    monkeypatch.delenv("AUDIT_ACCURACY_GO_BIN")
    assert resolve_binary("go", "AUDIT_ACCURACY_GO_BIN") == "/other/go"


def test_missing_runtime_does_not_add_cwd_to_path(tmp_path, monkeypatch):
    monkeypatch.setattr("audit_accuracy.GO", "go")
    monkeypatch.setattr("audit_accuracy.NODE_BIN", "")
    monkeypatch.setenv("PATH", "/existing/bin")
    result = environment(tmp_path)
    assert "." not in result["PATH"].split(os.pathsep)
    assert result["PATH"].endswith("/existing/bin")
    assert result["OBSTUDIO_SKILL_MCP_ENDPOINT"] == "none"


@pytest.mark.parametrize("installed", ["1.45.1", "1.46.0"])
def test_truth_requires_declared_sdk_version(tmp_path, monkeypatch, installed):
    (tmp_path / "requirements.txt").write_text("opentelemetry-sdk==1.45.1\n")
    monkeypatch.setattr("audit_accuracy.importlib.metadata.version", lambda package: installed)
    if installed == "1.45.1":
        check_python_runtime(tmp_path)
    else:
        with pytest.raises(ValueError, match="fixture requires 1.45.1"):
            check_python_runtime(tmp_path)
