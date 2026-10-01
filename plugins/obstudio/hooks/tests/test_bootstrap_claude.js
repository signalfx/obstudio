"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const { spawnSync } = require("node:child_process");

const BOOTSTRAP_CLAUDE = path.join(__dirname, "..", "bootstrap_claude.cjs");
const POSIX_ONLY = "relies on POSIX shebang scripts and PATH lookup semantics";

// claude-hooks.json gives the SessionStart hook a 120s timeout. Bound our own
// wait a little above that so a regression that makes the interpreter probe
// hang shows up as a fast, clear test failure instead of a 120s+ CI hang.
const HOOK_TIMEOUT_MS = 120_000;

// Mirrors BOOTSTRAP_LOCK_FILE / BOOTSTRAP_STATE_FILE in bootstrap_obstudio.py.
// Kept as literals here (rather than imported) since that module is Python
// and this test only needs the filenames to seed/inspect plugin data.
const BOOTSTRAP_LOCK_FILE = "bootstrap.lock";
const BOOTSTRAP_STATE_FILE = "bootstrap-state.json";

// Node's spawnSync searches the PATH of the env object passed in (not the
// inherited process.env), so overriding just PATH here is enough to make
// python3/py/python all resolve to ENOENT without touching the real PATH.
// This holds on Windows too: with PATH empty there is no directory to search,
// so python3/py/python.exe all fail to resolve the same way python3 does on
// POSIX.
function bootstrapEnv(pathValue) {
  const env = { ...process.env };
  delete env.PATH;
  delete env.Path;
  delete env.PATHEXT;
  if (pathValue !== undefined) {
    env.PATH = pathValue;
  }
  return env;
}

function runBootstrapClaude(env, options = {}) {
  return spawnSync(process.execPath, [BOOTSTRAP_CLAUDE], { env, encoding: "utf8", ...options });
}

test("exits 2 with a clear error when no python interpreter is on PATH, within the hook's deadline and without corrupting an existing lock/state file", () => {
  const pluginDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "obstudio-plugin-data-"));

  try {
    // Seed files as if a prior run's bootstrap_obstudio.py had already
    // acquired the lock and recorded state, so we can prove this failure
    // path (which never gets far enough to launch an interpreter) leaves
    // them byte-for-byte untouched rather than merely "absent".
    const lockPath = path.join(pluginDataDir, BOOTSTRAP_LOCK_FILE);
    const statePath = path.join(pluginDataDir, BOOTSTRAP_STATE_FILE);
    const lockContents = "";
    const stateContents = JSON.stringify({
      pluginVersion: "0.1.0",
      owner: "claude-plugin",
      mode: "managed",
      pid: "1234",
    });
    fs.writeFileSync(lockPath, lockContents);
    fs.writeFileSync(statePath, stateContents);

    const env = bootstrapEnv("");
    env.CLAUDE_PLUGIN_DATA = pluginDataDir;

    const result = runBootstrapClaude(env, { timeout: HOOK_TIMEOUT_MS });

    assert.equal(
      result.signal,
      null,
      "bootstrap_claude.cjs should exit on its own well inside the hook's 120s deadline, not be killed for exceeding it",
    );
    assert.equal(result.status, 2);
    assert.match(
      result.stderr,
      /Splunk Observability Studio bootstrap requires Python 3 \(python3, python, or py -3\)\.\s*$/,
    );
    assert.equal(
      fs.readFileSync(lockPath, "utf8"),
      lockContents,
      "a pre-existing lock file from a prior run must not be touched when no interpreter is found",
    );
    assert.equal(
      fs.readFileSync(statePath, "utf8"),
      stateContents,
      "a pre-existing state file from a prior run must not be touched when no interpreter is found",
    );
    assert.deepEqual(
      fs.readdirSync(pluginDataDir).sort(),
      [BOOTSTRAP_STATE_FILE, BOOTSTRAP_LOCK_FILE].sort(),
      "no interpreter was ever launched, so no additional files should appear either",
    );
  } finally {
    fs.rmSync(pluginDataDir, { recursive: true, force: true });
  }
});

test(
  "invokes the first interpreter found on PATH and forwards its exit status",
  { skip: process.platform === "win32" ? POSIX_ONLY : false },
  () => {
    const fakeBinDir = fs.mkdtempSync(path.join(os.tmpdir(), "obstudio-fake-python-"));
    const fakePython3 = path.join(fakeBinDir, "python3");
    fs.writeFileSync(fakePython3, "#!/bin/sh\nexit 7\n", { mode: 0o755 });

    try {
      const result = runBootstrapClaude(bootstrapEnv(fakeBinDir));
      assert.equal(result.status, 7);
    } finally {
      fs.rmSync(fakeBinDir, { recursive: true, force: true });
    }
  },
);
