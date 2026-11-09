"""Prepare native logging fixtures and verify three fresh trials per language."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from logging_receiver import LogsReceiver


EXPECTED_TEST_COUNTS = {"python": 21, "go": 18, "node": 18, "java": 22}
NONPASSING_COUNTS = (
    "failed_tests", "error_tests", "skipped_tests", "cancelled_tests", "todo_tests",
)


@dataclass
class CommandResult:
    exit_code: int
    output: str
    timed_out: bool = False


def run_command(command: list[str], cwd: Path, env: dict[str, str], timeout: float) -> CommandResult:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
    except OSError as error:
        return CommandResult(127, f"Cannot start {command[0]}: {error}\n")
    try:
        output, _ = process.communicate(timeout=timeout)
        return CommandResult(process.returncode, output)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired as cleanup_error:
            output = cleanup_error.output or ""
            if isinstance(output, bytes):
                output = output.decode(errors="replace")
            if process.stdout is not None:
                process.stdout.close()
        if isinstance(error, KeyboardInterrupt):
            raise
        return CommandResult(124, output, timed_out=True)


def parse_results(language: str, output: str, report_dir: Path) -> dict[str, int]:
    if language in {"python", "java"}:
        reports = sorted(report_dir.glob("*.xml"))
        if not reports:
            raise ValueError("No fresh JUnit/Surefire report; tests may have been skipped")
        cases = [case for path in reports for case in ET.parse(path).getroot().iter("testcase")]
        names = [(case.get("classname"), case.get("name")) for case in cases]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate testcases in fresh reports")
        counts = {"executed_tests": len(cases)}
        outcomes = (("failed_tests", "failure"), ("error_tests", "error"), ("skipped_tests", "skipped"))
        for key, tag in outcomes:
            counts[key] = sum(case.find(tag) is not None for case in cases)
        counts["passed_tests"] = len(cases) - sum(counts[key] for key, _ in outcomes)
        return counts
    if language == "go":
        events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
        counts = {}
        for key, action in (("executed_tests", "run"), ("passed_tests", "pass")):
            counts[key] = sum(
                event.get("Action") == action and "Test" in event and "/" not in event["Test"]
                for event in events
            )
        counts["failed_tests"] = sum(event.get("Action") == "fail" and "Test" in event for event in events)
        counts["skipped_tests"] = sum(event.get("Action") == "skip" and "Test" in event for event in events)
        return counts
    counts = {}
    outcomes = (
        ("executed_tests", "tests"), ("passed_tests", "pass"), ("failed_tests", "fail"),
        ("skipped_tests", "skipped"), ("cancelled_tests", "cancelled"), ("todo_tests", "todo"),
    )
    for key, label in outcomes:
        match = re.search(rf"^# {label} (\d+)\s*$", output, re.MULTILINE)
        if match is None:
            raise ValueError(f"Missing Node TAP count: {label}")
        counts[key] = int(match[1])
    return counts


def save_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def fixture_sources(fixture: Path) -> dict[str, str]:
    patterns = ("*.py", "*.go", "*.cjs", "go.mod", "go.sum", "package*.json", "pom.xml", "src/test/java/*.java")
    paths = sorted({path for pattern in patterns for path in fixture.glob(pattern) if path.is_file()})
    return {str(path.relative_to(fixture)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def executable(value: str) -> str:
    return os.path.abspath(value) if "/" in value or "\\" in value else value


def shared_sources(root: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("run_logging_contract.py", "logging_receiver.py")
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go", default="go")
    parser.add_argument("--maven", default="mvn")
    parser.add_argument("--npm", default="npm")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--java-home")
    parser.add_argument("--maven-settings")
    parser.add_argument("--languages", nargs="+", choices=tuple(EXPECTED_TEST_COUNTS))
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.trials < 1 or args.timeout <= 0:
        parser.error("trials and timeout must be positive")
    root = Path(__file__).resolve().parent
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    env["GOTOOLCHAIN"] = "local"
    if args.java_home:
        env["JAVA_HOME"] = str(Path(args.java_home).resolve())
    maven = [executable(args.maven)]
    if args.maven_settings:
        maven += ["-s", str(Path(args.maven_settings).resolve())]
    commands = {
        "python": [executable(args.python), "-m", "pytest", "-q", "."],
        "go": [executable(args.go), "test", "-race", "-count=1", "-json", "-timeout=30s", "./..."],
        "node": [executable(args.npm), "test"],
        "java": maven + ["test"],
    }
    setup_commands = {
        "python": [executable(args.python), "-c", "import pytest; from opentelemetry.instrumentation.logging.handler import LoggingHandler; from opentelemetry.sdk._logs import LoggerProvider"],
        "go": [executable(args.go), "mod", "download", "all"],
        "node": [executable(args.npm), "ci", "--ignore-scripts"],
        "java": maven + ["test-compile", "-DskipTests=true", "-Dmaven.test.skip=false"],
    }
    results = []
    metadata = {
        "preflight": {},
        "fixture_sources": {},
        "excluded_environment_keys": sorted(key for key in os.environ if key.startswith("OTEL_")),
        "shared_sources": shared_sources(root),
    }
    receiver = None
    try:
        receiver = LogsReceiver(output / "otlp-receipts.json")
        receiver.start()
        for language in dict.fromkeys(args.languages or commands):
            fixture = root / language / "logging-contract"
            setup_command = setup_commands[language]
            setup = run_command(setup_command, fixture, env, args.timeout)
            setup_log = output / f"{language}-setup.log"
            setup_log.write_text(setup.output)
            metadata["preflight"][language] = {
                "command": setup_command, "exit_code": setup.exit_code,
                "timed_out": setup.timed_out, "log": str(setup_log),
            }
            sources = fixture_sources(fixture)
            metadata["fixture_sources"][language] = sources
            save_json(output / "run.json", metadata)
            for trial in range(1, args.trials + 1):
                report_dir = Path(tempfile.mkdtemp(prefix=f"{language}-{trial}-", dir=output))
                command = list(commands[language])
                if language == "java":
                    command.append(f"-Dlogging.contract.reportsDirectory={report_dir}")
                elif language == "python":
                    command.append(f"--junitxml={report_dir / 'python.xml'}")
                log = output / f"{language}-{trial}.log"
                row = {
                    "language": language, "trial": trial, "command": command,
                    "cwd": str(fixture), "exit_code": None, "passed_tests": 0,
                    "expected_tests": EXPECTED_TEST_COUNTS[language], "status": "running",
                    "passed": False, "log": str(log), "report_dir": str(report_dir),
                    "receiver_url": f"{receiver.url}/{language}-{trial}",
                }
                results.append(row)
                save_json(output / "results.json", results)
                if setup.exit_code != 0:
                    row.update(
                        status="blocked", log=str(setup_log),
                        reason=f"Dependency/runtime preflight failed; see {setup_log}",
                    )
                    save_json(output / "results.json", results)
                    print(json.dumps(row), flush=True)
                    continue
                started = time.monotonic()
                trial_env = {**env, "LOGGING_CONTRACT_RECEIVER_URL": row["receiver_url"]}
                completed = run_command(command, fixture, trial_env, args.timeout)
                log.write_text(completed.output)
                row.update(
                    exit_code=completed.exit_code,
                    seconds=round(time.monotonic() - started, 3),
                    timed_out=completed.timed_out,
                )
                try:
                    row.update(parse_results(language, completed.output, report_dir))
                except (ValueError, ET.ParseError, OSError) as error:
                    row["validation_error"] = str(error)
                if fixture_sources(fixture) != sources:
                    row["validation_error"] = "Fixture source changed after preflight; rerun against one frozen revision"
                if shared_sources(root) != metadata["shared_sources"]:
                    row["validation_error"] = "Shared runner/receiver source changed during the run"
                expected = row["expected_tests"]
                row["passed"] = (
                    completed.exit_code == 0 and not completed.timed_out
                    and "validation_error" not in row
                    and row.get("executed_tests") == row["passed_tests"] == expected
                    and all(row.get(key, 0) == 0 for key in NONPASSING_COUNTS)
                )
                row["status"] = "pass" if row["passed"] else "fail"
                save_json(output / "results.json", results)
                print(json.dumps(row), flush=True)
    except KeyboardInterrupt:
        if results and results[-1]["status"] == "running":
            results[-1]["status"] = "cancelled"
        return 130
    except OSError as error:
        metadata["runner_error"] = str(error)
        return 1
    finally:
        try:
            if receiver is not None:
                receiver.close()
        finally:
            save_json(output / "results.json", results)
            save_json(output / "run.json", metadata)
    return 0 if results and all(row["passed"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
