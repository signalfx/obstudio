"""Run each real logging SDK/bridge fixture three times in fresh processes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go", default="go")
    parser.add_argument("--maven", default="mvn")
    parser.add_argument("--java-home")
    parser.add_argument("--maven-settings")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["GOTOOLCHAIN"] = "local"
    if args.java_home:
        env["JAVA_HOME"] = str(Path(args.java_home).resolve())
    maven = [str(Path(args.maven).resolve())] if "/" in args.maven else [args.maven]
    if args.maven_settings:
        maven += ["-s", str(Path(args.maven_settings).resolve())]
    commands = {
        "python": [sys.executable, "test_logging_contract.py"],
        "go": [str(Path(args.go).resolve()) if "/" in args.go else args.go, "test", "-count=1", "-json", "./..."],
        "node": ["npm", "test"],
        "java": maven + ["test"],
    }
    results = []
    for language, command in commands.items():
        fixture = root / language / "logging-contract"
        for trial in range(1, 4):
            started = time.monotonic()
            result = subprocess.run(command, cwd=fixture, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
            log = args.output / f"{language}-{trial}.log"
            log.write_text(result.stdout)
            count = 0
            if language == "python":
                match = re.search(r"Ran (\d+) tests", result.stdout)
                count = int(match[1]) if match else 0
            elif language == "go":
                events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
                count = sum(event.get("Action") == "pass" and "Test" in event for event in events)
            elif language == "node":
                match = re.search(r"(?:ℹ|#) pass (\d+)", result.stdout)
                count = int(match[1]) if match else 0
            else:
                report = fixture / "target/surefire-reports/TEST-LoggingContractTest.xml"
                if report.exists():
                    count = int(ET.parse(report).getroot().attrib["tests"])
            row = {"language": language, "trial": trial, "command": command, "cwd": str(fixture), "exit_code": result.returncode, "passed_tests": count, "seconds": round(time.monotonic() - started, 3), "log": str(log), "passed": result.returncode == 0 and count == 6}
            results.append(row)
            print(json.dumps(row), flush=True)
    (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    return 0 if all(row["passed"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
