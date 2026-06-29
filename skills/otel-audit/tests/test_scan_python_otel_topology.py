from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SCANNER = Path(__file__).parents[1] / "scripts" / "scan_python_otel_topology.py"


class ScanPythonOtelTopologyTest(unittest.TestCase):
    def scan(self, root: Path) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, str(SCANNER), str(root)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_detects_topology_patterns_and_skips_excluded_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "provider = TracerProvider(resource=Resource.create({}))\n"
                "trace.set_tracer_provider(provider)\n"
                "exporter = OTLPSpanExporter()\n"
                "provider.force_flush()\n",
                encoding="utf-8",
            )
            (root / "bootstrap.sh").write_text(
                "opentelemetry-instrument python -m service\n"
                "export OTEL_SERVICE_NAME=checkout\n",
                encoding="utf-8",
            )
            (root / "notes.txt").write_text(
                "NoOpMeterProvider should not be scanned from unsupported files\n",
                encoding="utf-8",
            )
            ignored = root / ".venv"
            ignored.mkdir()
            (ignored / "telemetry.py").write_text(
                "logger_provider = LoggerProvider()\n"
                "logs.set_logger_provider(logger_provider)\n"
                "exporter = ConsoleLogExporter()\n"
                "logger_provider.shutdown()\n",
                encoding="utf-8",
            )

            result = self.scan(root)

        self.assertEqual(result["root"], str(root.resolve()))
        self.assertFalse(result["reachability_proven"])
        self.assertEqual(
            result["findings"],
            {
                "provider_construction": [
                    {
                        "path": "service.py",
                        "line": 1,
                        "text": "provider = TracerProvider(resource=Resource.create({}))",
                    }
                ],
                "provider_registration": [
                    {
                        "path": "service.py",
                        "line": 2,
                        "text": "trace.set_tracer_provider(provider)",
                    }
                ],
                "exporter": [
                    {
                        "path": "service.py",
                        "line": 3,
                        "text": "exporter = OTLPSpanExporter()",
                    }
                ],
                "resource": [
                    {
                        "path": "service.py",
                        "line": 1,
                        "text": "provider = TracerProvider(resource=Resource.create({}))",
                    }
                ],
                "automatic_bootstrap": [
                    {
                        "path": "bootstrap.sh",
                        "line": 1,
                        "text": "opentelemetry-instrument python -m service",
                    }
                ],
                "runtime_configuration": [
                    {
                        "path": "bootstrap.sh",
                        "line": 2,
                        "text": "export OTEL_SERVICE_NAME=checkout",
                    }
                ],
                "shutdown_flush": [
                    {
                        "path": "service.py",
                        "line": 4,
                        "text": "provider.force_flush()",
                    }
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()
