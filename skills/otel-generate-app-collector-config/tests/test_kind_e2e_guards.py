from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


RUN = Path(__file__).resolve().parent / "kind_e2e" / "run.sh"


class KindE2EGuardTest(unittest.TestCase):
    def test_credential_environment_aliases_fail_without_echoing_values(self) -> None:
        sentinel = "SENTINEL_KIND_CREDENTIAL_MUST_NOT_ECHO"
        for variable in (
            "SPLUNK_HEC_TOKEN",
            "SIGNALFX_API_TOKEN",
            "OTEL_EXPORTER_OTLP_HEADERS",
        ):
            with self.subTest(variable=variable):
                env = os.environ.copy()
                env[variable] = sentinel
                result = subprocess.run(
                    ["bash", str(RUN)],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=env,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("credential environment variable", result.stderr)
                self.assertNotIn(sentinel, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
