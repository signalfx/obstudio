"""Exercise the fixture boundary with the real bundled resource CLI."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

def default_resolver():
    fixture = Path(__file__).resolve().parent
    relative = Path("otel-instrument/scripts/resolve_ao_resources.py")
    # Support both the canonical fixture and the harness's isolated service copy.
    for candidate in (
        fixture.parent / ".agents/skills" / relative,
        fixture.parents[2] / "skills" / relative,
    ):
        if candidate.is_file():
            return candidate
    return None


RESOLVER = default_resolver()


class GatewayContractTests(unittest.TestCase):
    def test_real_cli_resolves_reuses_creates_and_recovers_uncertain_create(self):
        from probe import Gateway, PROJECT, STREAM

        for existing, uncertain in [(True, False), (False, False), (False, True)]:
            with self.subTest(existing=existing, uncertain=uncertain):
                gateway = Gateway(existing=existing, uncertain=uncertain)
                try:
                    environment = {k: v for k, v in os.environ.items() if not k.startswith("SPLUNK_AO_")}
                    command = [
                        sys.executable, str(RESOLVER), "--studio-api-origin", gateway.origin,
                        "--project-name", "original-project", "--agent-stream-name", "production",
                        "--native-otel-binding",
                    ]
                    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    evidence = json.loads(result.stdout)
                    self.assertEqual(evidence["status"], "resolved")
                    binding = evidence["native_otel_binding"]
                    self.assertEqual(binding["headers"], {"projectid": PROJECT, "logstreamid": STREAM})
                    self.assertEqual(binding["resource_attributes"], {
                        "splunk_ao.project.id": PROJECT, "splunk_ao.logstream.id": STREAM,
                    })
                    creates = [path for method, path in gateway.requests if method == "POST"]
                    self.assertEqual(len(creates), 0 if existing else 2)
                    repeated = subprocess.run(command + ["--reuse-only"], env=environment, capture_output=True, text=True, timeout=15)
                    self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                    self.assertEqual([path for method, path in gateway.requests if method == "POST"], creates)
                finally:
                    gateway.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolver", type=Path, default=RESOLVER)
    args, remaining = parser.parse_known_args()
    if args.resolver is None or not args.resolver.is_file():
        parser.error("provide --resolver pointing to the loaded skill's resolve_ao_resources.py")
    RESOLVER = args.resolver.resolve()
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
