---
name: observer-status
description: >-
  Report whether the local Splunk Observability Studio is installed, bootstrapped, and
  reachable, including the MCP endpoint and browser URL.
---

# Splunk Observability Studio Status

Check local Studio setup state.

This skill is read-only. It may inspect plugin state and health endpoints, but
it must not restart or stop anything. Endpoint checks are limited to the
loopback health endpoint at `http://127.0.0.1:3000/api/health`.

## Steps

1. Check whether the plugin bootstrap state exists and matches the current
   plugin version.
2. If Studio MCP uses a non-default endpoint, report its URL and explain that
   this skill only verifies default loopback Studio at `127.0.0.1:3000`. Do not
   probe or control the custom endpoint; use MCP directly, restore the default,
   or verify it manually.
3. Before probing host-local endpoints from a shell command, request narrow
   elevated/outside-sandbox permission. Do not first try the check from inside
   the sandbox.
4. Check only `http://127.0.0.1:3000/api/health` for Studio health. Do not
   use the MCP endpoint as a health check and do not follow alternate hosts
   from MCP or user config.
5. Report the Studio URL, MCP endpoint, and whether setup looks healthy.
   Use `127.0.0.1` in user-facing default URLs instead of `localhost`.
   The default MCP endpoint is `http://127.0.0.1:3000/mcp`.
6. If access is denied or verification is unavailable, report
   `sandbox-unverified`; sandbox-local reachability alone does not prove Studio
   unhealthy.
7. If the runtime is shared or externally owned, say so explicitly and do not
   imply ownership.
