from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_configure_output.py"
SPEC = importlib.util.spec_from_file_location("validate_configure_output", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WorkingMetricsTest(unittest.TestCase):
    def test_reads_working_metric_on_python_39_compatible_path(self) -> None:
        report = """## Tested And Working
| OTel item | Type | Added or modified | Working status | How it was tested | Evidence |
|---|---|---|---|---|---|
| `http.server.request.duration` | Metric | Exporter | Working | OTLP | collector |
| `http.server.active_requests` | Metric | Exporter | Not proven | OTLP | absent |
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "otel-verify.md"
            path.write_text(report, encoding="utf-8")
            self.assertEqual(
                MODULE.working_metrics(path),
                {"http.server.request.duration"},
            )


if __name__ == "__main__":
    unittest.main()
