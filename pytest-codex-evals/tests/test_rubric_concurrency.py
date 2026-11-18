from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from pytest_codex_evals.backends import AgentResult, CodexBackend
from pytest_codex_evals.definitions import RubricEvalCase
from pytest_codex_evals.graders import rubric as module
from pytest_codex_evals.trace import parse_trace


def case(count=4, **updates):
    return RubricEvalCase(
        id="sample/service/rubric/direct", base_id="sample/service/rubric",
        prompt_id="direct", skill="sample", language="sample", service="service",
        task="Assess the candidate.", rubric=[f"Requirement {i}." for i in range(1, count + 1)],
        strict_rubric_output=True, rubric_dimensions=[
            {"id": f"group-{i}", "criteria": [f"rubric-{i}"]} for i in range(1, count + 1)
        ], **updates,
    )


class Backend:
    name = "test"

    def __init__(self, hook=None):
        self.hook = hook
        self.calls = {}
        self.lock = threading.Lock()
        self.active = self.maximum = 0
        self.finished = []

    def run_judge(self, **kwargs):
        return self.run_judge_cancellable(cancel_event=threading.Event(), **kwargs)

    def run_judge_cancellable(self, *, cancel_event, **kwargs):
        directory = kwargs["output_dir"]
        index = int(directory.name.split("-")[-1])
        result = AgentResult(0, directory / "rubric_trace.jsonl", directory / "rubric_grade.json",
                             directory / "rubric_stderr.txt")
        with self.lock:
            self.calls[index] = kwargs
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        try:
            result.trace_path.write_text(json.dumps({"type": "turn.completed", "usage": {"total_tokens": 1}}))
            result.stderr_path.write_text(f"group {index}")
            payload = {"checks": [{"id": f"rubric-{index}", "result": "pass",
                                   "notes": "Inspected requirement.", "evidence": "answer.md:1"}]}
            result.final_message_path.write_text(json.dumps(payload))
            if self.hook:
                self.hook(index, kwargs, result, cancel_event)
            return result
        finally:
            with self.lock:
                self.active -= 1
                self.finished.append(index)

    def parse_trace(self, path):
        return parse_trace(path)


def grade(tmp_path, backend, *, count=4, workers=2, deadline=None):
    workspace = tmp_path / "task"
    workspace.mkdir(exist_ok=True)
    (workspace / "answer.md").write_text("task evidence")
    path = module.run_rubric_dimensions(
        case=case(count), workspace_dir=workspace, output_dir=tmp_path / "grades",
        model="judge-model", deadline=deadline or time.monotonic() + 15,
        backend=backend, max_workers=workers,
    )
    return json.loads(path.read_text())


def test_parallel_bound_order_prompt_and_output_isolation(tmp_path):
    barrier = threading.Barrier(2)

    def hook(index, kwargs, result, cancel):
        if index in (1, 2):
            barrier.wait(timeout=3)
            if index == 1:
                deadline = time.monotonic() + 3
                while True:
                    progress = json.loads((kwargs["output_dir"].parent / "rubric_result.json").read_text())
                    if progress["dimensions"][1]["status"] == "graded":
                        break
                    assert time.monotonic() < deadline
                    cancel.wait(.01)

    backend = Backend(hook)
    data = grade(tmp_path, backend)
    assert backend.maximum == 2
    assert backend.finished.index(2) < backend.finished.index(1)
    assert [c["id"] for c in data["checks"]] == [f"rubric-{i}" for i in range(1, 5)]
    assert data["acceptance"] == "pass"
    directories = [c["exec_dir"] for c in backend.calls.values()]
    assert len(set(directories)) == 4
    assert all(not p.exists() for p in directories)
    for index, call in backend.calls.items():
        assert call["read_dirs"] == (tmp_path / "task",)
        assert call["model"] == "judge-model"
        assert str(tmp_path / "task") in call["prompt"]
        assert "Do not read other graders' output" in call["prompt"]
        assert call["output_dir"] == tmp_path / "grades" / f"dimension-{index}"
        row = data["dimensions"][index - 1]
        for artifact in row["artifacts"].values():
            assert artifact.startswith(f"dimension-{index}/")
            assert (tmp_path / "grades" / artifact).is_file()
        assert row["usage"]["provider_total_tokens"] == 1
    assert (tmp_path / "task/answer.md").read_text() == "task evidence"


def test_serial_and_parallel_keep_identical_prompts_and_grades(tmp_path):
    workspace = tmp_path / "evidence"
    workspace.mkdir()
    (workspace / "answer.md").write_text("frozen answer")
    before = module._evidence_snapshot(workspace)
    outputs, backends = [], []
    for workers in (1, 2):
        backend = Backend()
        backends.append(backend)
        path = module.run_rubric_dimensions(
            case=case(), workspace_dir=workspace, output_dir=tmp_path / f"grades-{workers}",
            model="judge-model", deadline=time.monotonic() + 15, backend=backend,
            max_workers=workers,
        )
        outputs.append(json.loads(path.read_text()))
    assert module._evidence_snapshot(workspace) == before
    assert {i: c["prompt"] for i, c in backends[0].calls.items()} == {
        i: c["prompt"] for i, c in backends[1].calls.items()
    }
    for key in ("status", "acceptance", "overall_pass", "score", "counts", "checks"):
        assert outputs[0][key] == outputs[1][key]
    assert backends[0].maximum == 1


def test_parallel_preserves_full_checklist_outcomes_and_evidence(tmp_path):
    full_case = RubricEvalCase.model_validate({**case(63).model_dump(), "rubric_dimensions": [
        {"id": f"group-{group}", "criteria": [f"rubric-{i}" for i in range(group, 64, 8)]}
        for group in range(1, 9)
    ]})
    expected = [{"id": f"rubric-{i}", "result": ("pass", "fail", "not_proven", "not_applicable")[(i - 1) % 4],
                 "notes": f"Written finding for item {i}.", "evidence": f"answer.md:{i}"}
                for i in range(1, 64)]

    def hook(index, kwargs, result, cancel):
        result.final_message_path.write_text(json.dumps({"checks": expected[index - 1::8]}))
    workspace = tmp_path / "evidence"
    workspace.mkdir()
    (workspace / "answer.md").write_text("frozen evidence")
    results = []
    prompts = []
    for workers in (1, 2):
        backend = Backend(hook)
        path = module.run_rubric_dimensions(
            case=full_case, workspace_dir=workspace, output_dir=tmp_path / f"grades-{workers}",
            model="judge-model", backend=backend, deadline=time.monotonic() + 15, max_workers=workers,
        )
        results.append(json.loads(path.read_text()))
        prompts.append({i: c["prompt"] for i, c in backend.calls.items()})
    assert prompts[0] == prompts[1]
    for result in results:
        assert [{k: v for k, v in row.items() if k != "dimension"} for row in result["checks"]] == expected
        assert result["counts"] == {"pass": 16, "fail": 16, "not_proven": 16,
                                    "not_applicable": 15, "ungraded": 0, "total": 63}
        assert result["status"] == "complete" and result["acceptance"] == "fail"
        assert result["score"] == 33 and result["overall_pass"] is False


@pytest.mark.parametrize("fault", ["blank_notes", "blank_evidence", "wrong_id", "extra", "malformed", "exit", "exception", "foreign_output"])
def test_bad_parallel_grade_does_not_award_credit_or_stop_peers(tmp_path, fault):
    def hook(index, kwargs, result, cancel):
        if index != 1:
            return
        payload = json.loads(result.final_message_path.read_text())
        if fault.startswith("blank"):
            payload["checks"][0][fault.removeprefix("blank_")] = " \n "
        elif fault == "wrong_id":
            payload["checks"][0]["id"] = "rubric-2"
        elif fault == "extra":
            payload["score"] = 100
        elif fault == "exit":
            result.returncode = 1
        elif fault == "exception":
            raise RuntimeError("unavailable")
        elif fault == "foreign_output":
            result.final_message_path = tmp_path / "foreign.json"
            result.final_message_path.write_text(json.dumps(payload))
        if fault == "malformed":
            result.final_message_path.write_text("not JSON")
        elif fault != "foreign_output":
            result.final_message_path.write_text(json.dumps(payload))
    data = grade(tmp_path, Backend(hook))
    assert data["status"] == "incomplete" and data["overall_pass"] is None
    assert data["counts"]["ungraded"] == 1 and data["counts"]["pass"] == 3
    assert data["dimensions"][0]["status"] == "grader_error"
    assert data["dimensions"][0]["artifacts"]["output"] == "dimension-1/rubric_grade.json"
    assert all(d["status"] == "graded" for d in data["dimensions"][1:])


def test_parallel_mutation_invalidates_started_groups_and_stops_launches(tmp_path):
    barrier = threading.Barrier(2)

    def hook(index, kwargs, result, cancel):
        barrier.wait(3)
        if index == 1:
            (tmp_path / "task/answer.md").write_text("changed")
        else:
            assert cancel.wait(3)
    backend = Backend(hook)
    data = grade(tmp_path, backend)
    assert set(backend.calls) == {1, 2}
    assert [d["status"] for d in data["dimensions"]] == ["grader_error", "grader_error", "not_run", "not_run"]
    assert data["counts"]["ungraded"] == 4
    assert all("modified" in d["error"] for d in data["dimensions"])


def test_parallel_rechecks_evidence_after_workers_exit(tmp_path, monkeypatch):
    shutdown = module.ThreadPoolExecutor.shutdown

    def mutate_after_shutdown(pool, **kwargs):
        shutdown(pool, **kwargs)
        (tmp_path / "task/answer.md").write_text("late change")
    monkeypatch.setattr(module.ThreadPoolExecutor, "shutdown", mutate_after_shutdown)
    data = grade(tmp_path, Backend())
    assert all(d["status"] == "grader_error" for d in data["dimensions"])
    assert data["counts"]["ungraded"] == 4


def test_parallel_uses_one_deadline_and_cancels_active_workers(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    barrier = threading.Barrier(2)

    def hook(index, kwargs, result, cancel):
        if index in (1, 2):
            barrier.wait(3)
        if index == 1:
            now[0] = 105.0
        elif index == 2:
            assert cancel.wait(3)
            raise RuntimeError("Rubric judge cancelled")
        elif index == 3:
            now[0] = 110.5
            assert cancel.wait(3)
            raise subprocess.TimeoutExpired("judge", kwargs["timeout"])
    backend = Backend(hook)
    data = grade(tmp_path, backend, deadline=110.0)
    assert set(backend.calls) == {1, 2, 3}
    assert [backend.calls[i]["timeout"] for i in (1, 2, 3)] == [10, 10, 5]
    assert data["dimensions"][0]["status"] == "graded"
    assert [d["status"] for d in data["dimensions"]][1:] == ["grader_error", "grader_error", "not_run"]
    assert data["counts"]["ungraded"] == 3


def test_parallel_keeps_valid_results_collected_after_deadline(tmp_path, monkeypatch):
    from concurrent.futures import wait

    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def collect_late(active, **kwargs):
        completed, pending = wait(active, timeout=3)
        assert not pending
        now[0] = 110.5
        return completed, pending
    monkeypatch.setattr(module, "wait", collect_late)
    data = grade(tmp_path, Backend(), count=2, deadline=110.0)
    assert data["status"] == "complete" and data["acceptance"] == "pass"
    assert data["counts"]["pass"] == 2 and data["counts"]["ungraded"] == 0


@pytest.mark.parametrize("interrupt", [False, True])
def test_parallel_restores_default_termination_handlers(tmp_path, interrupt):
    signals = [getattr(signal, name) for name in ("SIGTERM", "SIGHUP") if hasattr(signal, name)]
    previous = {sig: signal.getsignal(sig) for sig in signals}

    def hook(index, kwargs, result, cancel):
        if interrupt:
            raise KeyboardInterrupt
    if interrupt:
        with pytest.raises(KeyboardInterrupt):
            grade(tmp_path, Backend(hook))
    else:
        assert grade(tmp_path, Backend(hook))["acceptance"] == "pass"
    assert {sig: signal.getsignal(sig) for sig in signals} == previous


@pytest.mark.parametrize("signal_name", ["SIGINT", "SIGTERM"])
@pytest.mark.parametrize("ignored", [False, True])
def test_parallel_preserves_caller_termination_handler(tmp_path, monkeypatch, ignored, signal_name):
    signum = getattr(signal, signal_name)
    previous = signal.getsignal(signum)
    calls = []
    handler = signal.SIG_IGN if ignored else lambda sig, _frame: calls.append(sig)
    observed = []
    wait = module.wait

    def deliver_signals(*args, **kwargs):
        if not observed:
            observed.append(signal.getsignal(signum))
            signal.raise_signal(signum)
            signal.raise_signal(signum)
        return wait(*args, **kwargs)

    try:
        signal.signal(signum, handler)
        monkeypatch.setattr(module, "wait", deliver_signals)
        assert grade(tmp_path, Backend())["acceptance"] == "pass"
        assert observed == [handler]
        assert calls == ([] if ignored else [signum, signum])
        assert signal.getsignal(signum) == handler
    finally:
        signal.signal(signum, previous)


STOP_PAIRS = [("SIGTERM", "SIGTERM"), ("SIGINT", "SIGINT"),
              ("SIGTERM", "SIGINT"), ("SIGINT", "SIGTERM"),
              ("SIGHUP", "SIGHUP"), ("SIGHUP", "SIGTERM")]


@pytest.mark.skipif(os.name != "posix", reason="Signal delivery requires POSIX")
@pytest.mark.parametrize("first,second", STOP_PAIRS)
def test_repeated_default_signals_wait_for_backend_cleanup(tmp_path, first, second):
    ready = threading.Barrier(3)
    cleaning = [threading.Event(), threading.Event()]
    release = threading.Event()
    finished = threading.Event()
    errors = []
    observed = {}
    defaults = {signal.SIGINT: signal.default_int_handler,
                signal.SIGTERM: signal.SIG_DFL, signal.SIGHUP: signal.SIG_DFL}
    previous = {sig: signal.getsignal(sig) for sig in defaults}

    def hook(index, kwargs, result, cancel):
        ready.wait(3)
        assert cancel.wait(3)
        cleaning[index - 1].set()
        assert release.wait(3)

    backend = Backend(hook)

    def stop_twice():
        try:
            ready.wait(3)
            os.kill(os.getpid(), getattr(signal, first))
            assert all(event.wait(3) for event in cleaning)
            os.kill(os.getpid(), getattr(signal, second))
            time.sleep(.15)
        except BaseException as exc:
            errors.append(exc)
        finally:
            release.set()
            finished.set()

    sender = threading.Thread(target=stop_twice)
    try:
        for sig, handler in defaults.items():
            signal.signal(sig, handler)
        sender.start()
        with pytest.raises(KeyboardInterrupt, match=first):
            try:
                grade(tmp_path, backend)
            except KeyboardInterrupt:
                observed.update(active=backend.active, finished=list(backend.finished))
                raise
        assert observed["active"] == 0 and set(observed["finished"]) == {1, 2}
        data = json.loads((tmp_path / "grades/rubric_result.json").read_text())
        assert data["counts"]["ungraded"] == 4
        assert [d["status"] for d in data["dimensions"]] == ["grader_error", "grader_error", "not_run", "not_run"]
        assert all(first in d["error"] for d in data["dimensions"])
        assert {sig: signal.getsignal(sig) for sig in defaults} == defaults
    finally:
        release.set()
        assert finished.wait(4)
        sender.join(timeout=1)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    assert not errors


@pytest.mark.skipif(os.name != "posix", reason="Signal delivery requires POSIX")
def test_default_signal_during_cleanup_preserves_original_exception(tmp_path):
    ready = threading.Barrier(2)
    observed = []
    previous = signal.getsignal(signal.SIGTERM)

    def hook(index, kwargs, result, cancel):
        ready.wait(3)
        if index == 1:
            raise KeyboardInterrupt("original backend interruption")
        assert cancel.wait(3)
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(.1)

    backend = Backend(hook)
    try:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        with pytest.raises(KeyboardInterrupt, match="original backend interruption"):
            try:
                grade(tmp_path, backend)
            except KeyboardInterrupt:
                observed.append((backend.active, set(backend.finished)))
                raise
        assert observed == [(0, {1, 2})]
        data = json.loads((tmp_path / "grades/rubric_result.json").read_text())
        assert all("original backend interruption" in row["error"] for row in data["dimensions"])
    finally:
        signal.signal(signal.SIGTERM, previous)


def test_default_stop_after_workers_finish_is_not_lost(tmp_path, monkeypatch):
    previous = signal.getsignal(signal.SIGTERM)
    shutdown = module.ThreadPoolExecutor.shutdown
    backend = Backend()

    def stop_after_shutdown(pool, **kwargs):
        shutdown(pool, **kwargs)
        signal.raise_signal(signal.SIGTERM)

    try:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        monkeypatch.setattr(module.ThreadPoolExecutor, "shutdown", stop_after_shutdown)
        with pytest.raises(KeyboardInterrupt, match="SIGTERM"):
            grade(tmp_path, backend)
        assert backend.active == 0 and set(backend.finished) == {1, 2, 3, 4}
        data = json.loads((tmp_path / "grades/rubric_result.json").read_text())
        assert data["status"] == "complete" and data["counts"]["pass"] == 4
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL
    finally:
        signal.signal(signal.SIGTERM, previous)


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="POSIX interval timers required")
@pytest.mark.parametrize("workers", [1, 2])
def test_grading_preserves_caller_timer_and_serial_signal_handlers(tmp_path, workers):
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    previous_stop = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    alarm = lambda *_: None
    started = time.monotonic()

    def hook(*_):
        assert signal.getsignal(signal.SIGALRM) is alarm
        if workers == 1:
            assert {sig: signal.getsignal(sig) for sig in previous_stop} == previous_stop

    try:
        signal.signal(signal.SIGALRM, alarm)
        signal.setitimer(signal.ITIMER_REAL, 30, 2)
        assert grade(tmp_path, Backend(hook), workers=workers)["acceptance"] == "pass"
        remaining, interval = signal.getitimer(signal.ITIMER_REAL)
        assert 0 < remaining <= 30 and interval == 2
        assert signal.getsignal(signal.SIGALRM) is alarm
        assert {sig: signal.getsignal(sig) for sig in previous_stop} == previous_stop
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        remaining, interval = previous_timer
        if remaining:
            remaining = max(.001, remaining - (time.monotonic() - started))
        signal.setitimer(signal.ITIMER_REAL, remaining, interval)


@pytest.mark.parametrize("workers", [1, 2])
def test_background_thread_keeps_serial_support_and_rejects_parallel(tmp_path, workers):
    results, errors = [], []
    backend = Backend()
    def invoke():
        try:
            results.append(grade(tmp_path, backend, workers=workers))
        except ValueError as error:
            errors.append(str(error))
    thread = threading.Thread(target=invoke)
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive()
    if workers == 1:
        assert results[0]["acceptance"] == "pass" and not errors
    else:
        assert len(errors) == 1 and "main thread" in errors[0]
        assert not backend.calls and not (tmp_path / "grades").exists()


def test_parallel_interruption_cancels_peers_before_propagating(tmp_path, monkeypatch):
    ready = threading.Barrier(3)

    def hook(index, kwargs, result, cancel):
        ready.wait(3)
        assert cancel.wait(3)

    def interrupt(*args, **kwargs):
        ready.wait(3)
        raise KeyboardInterrupt
    monkeypatch.setattr(module, "wait", interrupt)
    backend = Backend(hook)
    with pytest.raises(KeyboardInterrupt):
        grade(tmp_path, backend)
    data = json.loads((tmp_path / "grades/rubric_result.json").read_text())
    assert backend.active == 0 and set(backend.finished) == {1, 2}
    assert data["counts"]["ungraded"] == 4
    assert [d["status"] for d in data["dimensions"]][:2] == ["grader_error", "grader_error"]
    assert all("KeyboardInterrupt" in d["error"] for d in data["dimensions"])


def test_result_remains_readable_while_next_snapshot_is_written(tmp_path, monkeypatch):
    write_text = Path.write_text
    observed = []

    def split_write(path, data, **kwargs):
        if path.name == "rubric_result.tmp":
            destination = path.with_suffix(".json")
            with path.open("w", **kwargs) as stream:
                stream.write(data[:len(data) // 2])
                stream.flush()
                if destination.exists():
                    observed.append(json.loads(destination.read_text()))
                stream.write(data[len(data) // 2:])
            return len(data)
        return write_text(path, data, **kwargs)
    monkeypatch.setattr(Path, "write_text", split_write)
    data = grade(tmp_path, Backend())
    assert data["acceptance"] == "pass" and observed
    assert all(len(snapshot["checks"]) == 4 for snapshot in observed)


@pytest.mark.parametrize("workers", [0, 3, True, 1.5])
def test_invalid_worker_count_does_not_start_grading(tmp_path, workers):
    backend = Backend()
    with pytest.raises(ValueError, match="max_workers"):
        grade(tmp_path, backend, workers=workers)
    assert not backend.calls and not (tmp_path / "grades").exists()


def test_backend_must_explicitly_support_concurrent_cancellation(tmp_path):
    class SerialBackend:
        def run_judge(self, **kwargs):
            raise AssertionError("must not launch")
    with pytest.raises(ValueError, match="run_judge_cancellable"):
        grade(tmp_path, SerialBackend())
    assert not (tmp_path / "grades").exists()


@pytest.fixture
def hanging_codex(tmp_path):
    script = tmp_path / "judge-cli"
    child = (
        "import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "signal.signal(signal.SIGINT,signal.SIG_IGN); "
        "p=pathlib.Path('child.ready'); p.write_text('ready'); "
        "\nwhile True: p.write_text(str(time.monotonic())); time.sleep(.02)"
    )
    script.write_text(
        f"#!{sys.executable}\n"
        "import os,sys,signal,subprocess,time\nfrom pathlib import Path\n"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        "signal.signal(signal.SIGINT,signal.SIG_IGN)\n"
        "out=Path(sys.argv[sys.argv.index('--output-last-message')+1]).parent\n"
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}])\n"
        "while not Path('child.ready').exists(): time.sleep(.01)\n"
        "(out/'parent.pid').write_text(str(os.getpid()))\n"
        "(out/'child.pid').write_text(str(child.pid))\n"
        "print('partial trace',flush=True)\nprint('partial diagnostic',file=sys.stderr,flush=True)\n"
        "(out/'ready').write_text('diagnostics flushed')\n"
        "while True: time.sleep(.05)\n"
    )
    script.chmod(0o755)
    yield script
    for path in tmp_path.rglob("parent.pid"):
        try:
            os.killpg(int(path.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass


def assert_stopped(pid):
    deadline = time.monotonic() + 2
    while True:
        info = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
        if not info.stdout.strip() or info.stdout.strip().startswith("Z"):
            return
        assert time.monotonic() < deadline
        time.sleep(.01)


@pytest.mark.skipif(os.name != "posix", reason="Concurrent Codex cleanup requires POSIX process groups")
def test_real_parallel_deadline_reaps_judges_and_stops_descendants(tmp_path, hanging_codex):
    started = time.monotonic()
    data = grade(tmp_path, CodexBackend(command=str(hanging_codex)), deadline=started + 1.8)
    assert time.monotonic() - started < 5
    assert data["counts"]["ungraded"] == 4
    assert len(list((tmp_path / "grades").glob("dimension-*"))) == 2
    for directory in (tmp_path / "grades").glob("dimension-*"):
        for name in ("parent.pid", "child.pid"):
            assert_stopped(int((directory / name).read_text()))
        assert "partial trace" in (directory / "rubric_trace.jsonl").read_text()
        assert "partial diagnostic" in (directory / "rubric_stderr.txt").read_text()


@pytest.mark.skipif(os.name != "posix", reason="Concurrent Codex cleanup requires POSIX process groups")
def test_real_codex_cancellation_retains_raw_diagnostics(tmp_path, hanging_codex):
    output, working = tmp_path / "output", tmp_path / "working"
    output.mkdir()
    working.mkdir()
    cancel = threading.Event()
    errors = []

    def invoke():
        try:
            CodexBackend(command=str(hanging_codex)).run_judge_cancellable(
                prompt="Grade it.", exec_dir=working, output_dir=output,
                timeout=15, cancel_event=cancel,
            )
        except RuntimeError as error:
            errors.append(str(error))
    thread = threading.Thread(target=invoke)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not (output / "ready").exists():
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(.01)
        cancel.set()
        thread.join(timeout=4)
        assert not thread.is_alive() and errors == ["Rubric judge cancelled"]
        for name in ("parent.pid", "child.pid"):
            assert_stopped(int((output / name).read_text()))
        assert "partial trace" in (output / "rubric_trace.jsonl").read_text()
        assert "partial diagnostic" in (output / "rubric_stderr.txt").read_text()
    finally:
        cancel.set()
        thread.join(timeout=4)


@pytest.mark.skipif(os.name != "posix", reason="Concurrent Codex cleanup requires POSIX process groups")
def test_successful_codex_exit_also_stops_its_remaining_children(tmp_path, hanging_codex):
    payload = {"checks": [{"id": "rubric-1", "result": "pass", "notes": "Inspected.", "evidence": "answer.md:1"}]}
    script = hanging_codex.read_text()
    assert "while True: time.sleep(.05)\n" in script
    hanging_codex.write_text(script.replace(
        "while True: time.sleep(.05)\n",
        f"(out/'rubric_grade.json').write_text({json.dumps(payload)!r})\n",
    ))
    output, working = tmp_path / "output", tmp_path / "working"
    output.mkdir()
    working.mkdir()
    result = CodexBackend(command=str(hanging_codex)).run_judge_cancellable(
        prompt="Grade it.", exec_dir=working, output_dir=output,
        timeout=5, cancel_event=threading.Event(),
    )
    assert result.returncode == 0 and json.loads(result.final_message_path.read_text()) == payload
    assert "partial diagnostic" in result.stderr_path.read_text()
    for name in ("parent.pid", "child.pid"):
        assert_stopped(int((output / name).read_text()))


@pytest.mark.skipif(os.name != "posix", reason="Concurrent Codex cleanup requires POSIX process groups")
def test_retired_group_permission_error_preserves_completed_judge(tmp_path, hanging_codex, monkeypatch):
    import pytest_codex_evals.backends as backends

    denied = []
    payload = {"checks": [{"id": "rubric-1", "result": "pass", "notes": "Inspected.", "evidence": "answer.md:1"}]}
    hanging_codex.write_text(
        f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n"
        "output=Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
        f"output.write_text({json.dumps(payload)!r})\n"
    )
    def retired_group(group, sig):
        assert_stopped(group)
        denied.append((group, sig))
        raise PermissionError("retired process group")
    monkeypatch.setattr(backends.os, "killpg", retired_group)
    output, working = tmp_path / "output", tmp_path / "working"
    output.mkdir()
    working.mkdir()
    result = CodexBackend(command=str(hanging_codex)).run_judge_cancellable(
        prompt="Grade it.", exec_dir=working, output_dir=output,
        timeout=5, cancel_event=threading.Event(),
    )
    assert denied and result.returncode == 0
    assert json.loads(result.final_message_path.read_text()) == payload


@pytest.mark.skipif(os.name != "posix", reason="Concurrent Codex cleanup requires POSIX process groups")
def test_permission_error_during_cancellation_reaps_exiting_judge(tmp_path, hanging_codex, monkeypatch):
    import pytest_codex_evals.backends as backends

    hanging_codex.write_text(
        f"#!{sys.executable}\nimport os,sys,time\nfrom pathlib import Path\n"
        "out=Path(sys.argv[sys.argv.index('--output-last-message')+1]).parent\n"
        "(out/'parent.pid').write_text(str(os.getpid()))\n"
        "(out/'ready').write_text('ready')\n"
        "while not (out/'release').exists(): time.sleep(.01)\n"
    )
    output, working = tmp_path / "output", tmp_path / "working"
    output.mkdir()
    working.mkdir()
    cancel = threading.Event()
    errors, denied, reaped = [], [], []
    real_wait = subprocess.Popen.wait

    def deny_signal(group, sig):
        assert group == int((output / "parent.pid").read_text())
        assert sig == signal.SIGINT
        denied.append(group)
        raise PermissionError("group exit is not yet observable")

    def release_before_wait(process, *args, **kwargs):
        if process.args[0] == str(hanging_codex):
            assert denied and process.returncode is None
            (output / "release").write_text("exit during the bounded reap")
            result = real_wait(process, *args, **kwargs)
            reaped.append(process.returncode)
            return result
        return real_wait(process, *args, **kwargs)

    monkeypatch.setattr(backends.os, "killpg", deny_signal)
    monkeypatch.setattr(subprocess.Popen, "wait", release_before_wait)

    def invoke():
        try:
            CodexBackend(command=str(hanging_codex)).run_judge_cancellable(
                prompt="Grade it.", exec_dir=working, output_dir=output,
                timeout=15, cancel_event=cancel,
            )
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}")

    thread = threading.Thread(target=invoke)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not (output / "ready").exists():
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(.01)
        cancel.set()
        thread.join(timeout=4)
        assert not thread.is_alive() and errors == ["RuntimeError: Rubric judge cancelled"]
        assert denied and reaped == [0]
        assert_stopped(int((output / "parent.pid").read_text()))
    finally:
        cancel.set()
        (output / "release").write_text("cleanup")
        thread.join(timeout=4)


@pytest.mark.skipif(os.name != "posix", reason="Concurrent Codex cleanup requires POSIX process groups")
@pytest.mark.parametrize("interrupt_delay", [0, .35])
def test_cancellation_lets_cli_interrupt_its_separate_tool_group(tmp_path, hanging_codex, interrupt_delay):
    hanging_codex.write_text(
        f"#!{sys.executable}\n"
        "import os,sys,signal,subprocess,time\nfrom pathlib import Path\n"
        "out=Path(sys.argv[sys.argv.index('--output-last-message')+1]).parent\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)\n"
        "(out/'parent.pid').write_text(str(os.getpid()))\n"
        "(out/'child.pid').write_text(str(child.pid))\n"
        "def interrupt(*_):\n"
        "    (out/'interrupted').write_text('SIGINT')\n"
        f"    time.sleep({interrupt_delay})\n"
        "    os.killpg(child.pid,signal.SIGKILL)\n"
        "    raise SystemExit(130)\n"
        "signal.signal(signal.SIGINT,interrupt)\n"
        "(out/'ready').write_text('ready')\n"
        "while True: time.sleep(.05)\n"
    )
    output, working = tmp_path / "output", tmp_path / "working"
    output.mkdir()
    working.mkdir()
    cancel = threading.Event()
    errors = []

    def invoke():
        try:
            CodexBackend(command=str(hanging_codex)).run_judge_cancellable(
                prompt="Grade it.", exec_dir=working, output_dir=output,
                timeout=15, cancel_event=cancel,
            )
        except RuntimeError as error:
            errors.append(str(error))
    thread = threading.Thread(target=invoke)
    thread.start()
    child_pid = None
    try:
        deadline = time.monotonic() + 5
        while not (output / "ready").exists():
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(.01)
        child_pid = int((output / "child.pid").read_text())
        parent_pid = int((output / "parent.pid").read_text())
        assert os.getpgid(child_pid) == child_pid != os.getpgid(parent_pid)
        cancel.set()
        thread.join(timeout=4)
        assert not thread.is_alive() and errors == ["Rubric judge cancelled"]
        assert (output / "interrupted").read_text() == "SIGINT"
        assert_stopped(child_pid)
        assert_stopped(parent_pid)
    finally:
        cancel.set()
        thread.join(timeout=4)
        if child_pid is None and (output / "child.pid").exists():
            child_pid = int((output / "child.pid").read_text())
        if child_pid is not None:
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.skipif(os.name != "posix", reason="Concurrent Codex cleanup requires POSIX process groups")
@pytest.mark.parametrize("first,second", STOP_PAIRS)
def test_real_controller_interrupt_stops_both_judge_process_trees(tmp_path, hanging_codex, first, second):
    workspace, output = tmp_path / "task", tmp_path / "grades"
    workspace.mkdir()
    (workspace / "answer.md").write_text("frozen evidence")
    driver = """
import json,sys,time,signal
from pathlib import Path
from pytest_codex_evals.backends import CodexBackend
from pytest_codex_evals.definitions import RubricEvalCase
from pytest_codex_evals.graders.rubric import run_rubric_dimensions
case = RubricEvalCase.model_validate(json.loads(sys.argv[1]))
signal.signal(signal.SIGINT, signal.default_int_handler)
for name in ("SIGTERM", "SIGHUP"):
    signal.signal(getattr(signal, name), signal.SIG_DFL)
run_rubric_dimensions(case=case, workspace_dir=Path(sys.argv[2]), output_dir=Path(sys.argv[3]),
                     model=None, deadline=time.monotonic()+15,
                     backend=CodexBackend(command=sys.argv[4]), max_workers=2)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", driver, case().model_dump_json(), str(workspace), str(output), str(hanging_codex)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5
        while len(list(output.glob("dimension-*/ready"))) < 2:
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(.01)
        os.killpg(process.pid, getattr(signal, first))
        time.sleep(.3)
        assert process.poll() is None
        os.killpg(process.pid, getattr(signal, second))
        _, diagnostics = process.communicate(timeout=5)
        assert process.returncode != 0 and "KeyboardInterrupt" in diagnostics
        result = json.loads((output / "rubric_result.json").read_text())
        assert result["counts"]["ungraded"] == 4
        assert [row["status"] for row in result["dimensions"]] == ["grader_error", "grader_error", "not_run", "not_run"]
        for directory in output.glob("dimension-*"):
            for name in ("parent.pid", "child.pid"):
                assert_stopped(int((directory / name).read_text()))
            assert "partial trace" in (directory / "rubric_trace.jsonl").read_text()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
