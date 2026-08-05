---
name: observer-status
description: >-
  Report whether the local Obstudio Observer is installed, bootstrapped, and
  reachable, including the MCP endpoint and browser URL.
---

# Observer Status

Use this skill to check the local Obstudio setup state.

This skill is read-only. It may inspect plugin state and health endpoints, but
it must not restart or stop anything.

## Steps

1. Check whether the plugin bootstrap state exists and matches the current
   plugin version.
2. Check whether the configured health endpoint is reachable. Prefer
   `http://127.0.0.1:3000/api/health` unless the Codex MCP config explicitly
   points to a different host.
3. Report the Observer URL, MCP endpoint, and whether the setup looks healthy.
   Use `127.0.0.1` in user-facing default URLs instead of `localhost`.
4. If the runtime is shared or externally owned, say so explicitly and do not
   imply ownership.
5. If a sandboxed `localhost` probe fails but the configured `127.0.0.1`
   endpoint is healthy, report: `Local sandbox cannot reach localhost, but the
   configured 127.0.0.1 endpoint is healthy.`
