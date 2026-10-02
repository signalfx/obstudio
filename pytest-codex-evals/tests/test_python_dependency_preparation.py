from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from pytest_codex_evals.backends import (
    CodexBackend,
    StreamedCommandResult,
    _prepare_eval_python_dependencies,
)


def test_python_dependency_preparation_is_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = tmp_path / "service"
    service.mkdir()
    (service / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    monkeypatch.delenv("CODEX_EVAL_PREPARE_PYTHON", raising=False)

    def unexpected_run(*_args, **_kwargs):
        raise AssertionError("dependency setup must remain opt-in")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    _prepare_eval_python_dependencies(tmp_path)


def test_python_dependency_preparation_uses_isolated_public_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = tmp_path / "service"
    service.mkdir()
    (service / "pyproject.toml").write_text(
        "[project]\nname='demo'\n[dependency-groups]\ndev=['pytest']\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_EVAL_PREPARE_PYTHON", "1")
    monkeypatch.setenv("PIP_INDEX_URL", "https://private.example.invalid/simple")
    monkeypatch.setenv("GH_TOKEN", "secret")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "synced", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _prepare_eval_python_dependencies(tmp_path)

    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd == [
        "uv",
        "sync",
        "--no-config",
        "--default-index",
        "https://pypi.org/simple",
        "--group",
        "dev",
    ]
    assert kwargs["cwd"] == service
    assert kwargs["env"]["UV_CACHE_DIR"] == str(tmp_path / ".uv-cache")
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert "GH_TOKEN" not in kwargs["env"]
    assert "private.example.invalid" not in str(kwargs["env"])


def test_python_dependency_preparation_without_dev_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = tmp_path / "service"
    service.mkdir()
    (service / "pyproject.toml").write_text(
        "[project]\nname='demo'\n", encoding="utf-8"
    )
    monkeypatch.setenv("CODEX_EVAL_PREPARE_PYTHON", "1")
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _prepare_eval_python_dependencies(tmp_path)

    assert len(calls) == 2
    assert "--group" not in calls[0]
    assert "dev" not in calls[0]
    assert calls[1] == [
        "uv",
        "pip",
        "install",
        "--python",
        str(
            service
            / ".venv"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        ),
        "--no-config",
        "--default-index",
        "https://pypi.org/simple",
        "pytest>=9.0.3,<10",
    ]


def test_python_dependency_preparation_prefetches_fixture_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = tmp_path / "service"
    requirements = service / "eval" / "inputs" / "python-preflight-requirements.txt"
    requirements.parent.mkdir(parents=True)
    requirements.write_text(
        "opentelemetry-api>=1.45\nopentelemetry-sdk>=1.45\n",
        encoding="utf-8",
    )
    pyproject = service / "pyproject.toml"
    original_pyproject = "[project]\nname='demo'\n"
    pyproject.write_text(original_pyproject, encoding="utf-8")
    monkeypatch.setenv("CODEX_EVAL_PREPARE_PYTHON", "1")
    monkeypatch.setenv("PIP_INDEX_URL", "https://private.example.invalid/simple")
    monkeypatch.setenv("GH_TOKEN", "secret")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _prepare_eval_python_dependencies(tmp_path)

    assert len(calls) == 4
    command, kwargs = calls[-2]
    assert command == [
        "uv",
        "pip",
        "install",
        "--python",
        str(service / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
        "--no-config",
        "--default-index",
        "https://pypi.org/simple",
        "opentelemetry-api>=1.45",
        "opentelemetry-sdk>=1.45",
    ]
    assert kwargs["cwd"] == service
    assert kwargs["env"]["UV_CACHE_DIR"] == str(tmp_path / ".uv-cache")
    assert "GH_TOKEN" not in kwargs["env"]
    assert "private.example.invalid" not in str(kwargs["env"])
    assert calls[-1][0] == [
        "uv",
        "pip",
        "compile",
        "--universal",
        "--no-config",
        "--default-index",
        "https://pypi.org/simple",
        str(requirements),
    ]
    assert pyproject.read_text(encoding="utf-8") == original_pyproject


def test_python_dependency_preparation_rejects_non_public_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = tmp_path / "service"
    requirements = service / "eval" / "inputs" / "python-preflight-requirements.txt"
    requirements.parent.mkdir(parents=True)
    requirements.write_text("--extra-index-url https://private.example.invalid\n", encoding="utf-8")
    (service / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_EVAL_PREPARE_PYTHON", "1")
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="unsupported Python preflight requirement"):
        _prepare_eval_python_dependencies(tmp_path)
    assert calls == []


def test_python_dependency_preparation_runs_before_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = tmp_path / "service"
    service.mkdir()
    (service / "pyproject.toml").write_text(
        "[project]\nname='demo'\n[dependency-groups]\ndev=['pytest']\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_EVAL_PREPARE_PYTHON", "true")
    order = []

    def fake_setup(cmd, **_kwargs):
        order.append("setup")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_agent(_cmd, *, stdout_path, stderr_path, **_kwargs):
        order.append("agent")
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return StreamedCommandResult(0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_setup)
    monkeypatch.setattr("pytest_codex_evals.backends.run_streamed_command", fake_agent)
    CodexBackend().run_agent(prompt="test", exec_dir=tmp_path)

    assert order == ["setup", "agent"]


def test_python_dependency_preparation_failure_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = tmp_path / "service"
    service.mkdir()
    (service / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_EVAL_PREPARE_PYTHON", "1")

    def fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "public package unavailable")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="public package unavailable"):
        _prepare_eval_python_dependencies(tmp_path)
