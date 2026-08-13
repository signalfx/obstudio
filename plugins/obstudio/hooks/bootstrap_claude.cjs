#!/usr/bin/env node
"use strict";

// Claude supports the command/args exec form on every platform, but Python's
// executable name differs between Unix and Windows. Keep that portability
// boundary here and pass the host identity directly to the shared bootstrap.
const { spawnSync } = require("node:child_process");
const path = require("node:path");

const bootstrap = path.join(__dirname, "bootstrap_obstudio.py");
const candidates = [
  ["python3", []],
  ["py", ["-3"]],
  ["python", []],
];

for (const [command, prefix] of candidates) {
  const result = spawnSync(command, [...prefix, bootstrap], {
    env: { ...process.env, OBSTUDIO_PLUGIN_HOST: "claude" },
    stdio: "inherit",
  });
  if (result.error && result.error.code === "ENOENT") {
    continue;
  }
  if (result.error) {
    process.stderr.write(`could not start ${command}: ${result.error.message}\n`);
    process.exit(2);
  }
  process.exit(result.status === null ? 2 : result.status);
}

process.stderr.write("Splunk Observability Studio bootstrap requires Python 3 (python3, python, or py -3).\n");
process.exit(2);
