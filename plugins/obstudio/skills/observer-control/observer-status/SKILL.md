---
name: observer-status
description: >-
  Report whether the local Obstudio Observer is installed, bootstrapped, and
  reachable, including the MCP endpoint and browser URL.
---

# Observer Status

Use this skill to check the local Obstudio setup state.

This skill is read-only. It may inspect plugin state and health endpoints, but
it must not restart or stop anything. Endpoint checks are limited to the
loopback Observer health endpoint at `http://127.0.0.1:3000/api/health`.

## Steps

1. Check whether the plugin bootstrap state exists and matches the current
   plugin version.
2. If Obstudio MCP is configured to a non-default endpoint, report:
   `Obstudio MCP is configured to a non-default endpoint: <url>. For safety,
   this command skill only verifies or controls the default loopback Observer
   at 127.0.0.1:3000. I will not probe or control the custom endpoint. Use the
   MCP server directly, update the config back to the default local Observer,
   or manually verify the custom Observer.`
3. Before probing host-local endpoints from a shell command, request narrow
   elevated/outside-sandbox permission. Do not first try the check from inside
   the sandbox.
4. Check only `http://127.0.0.1:3000/api/health` for Observer health. Do not
   use the MCP endpoint as a health check and do not follow alternate hosts
   from MCP or user config.
5. Report the Observer URL, MCP endpoint, and whether the setup looks healthy.
   Use `127.0.0.1` in user-facing default URLs instead of `localhost`.
   The default MCP endpoint is `http://127.0.0.1:3000/mcp`.
6. If elevated access is denied or the endpoint cannot be verified from the
   available context, report `sandbox-unverified`; do not report the Observer
   as unhealthy based only on sandbox-local reachability.
7. If the runtime is shared or externally owned, say so explicitly and do not
   imply ownership.
