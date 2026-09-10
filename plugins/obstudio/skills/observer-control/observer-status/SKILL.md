---
name: observer-status
description: >-
  Report whether the local Splunk Observability Studio is installed, bootstrapped, and
  reachable, including the MCP endpoint and browser URL.
---

# Splunk Observability Studio Status

Use this skill to check the local Splunk Observability Studio setup state.

This skill is read-only. It may inspect plugin state and health endpoints, but
it must not restart or stop anything. Endpoint checks are limited to the
loopback Splunk Observability Studio health endpoint at `http://127.0.0.1:3000/api/health`.

## Steps

1. Check whether the plugin bootstrap state exists and matches the current
   plugin version.
2. If Splunk Observability Studio MCP is configured to a non-default endpoint, report:
   `Splunk Observability Studio MCP is configured to a non-default endpoint: <url>. For safety,
   this command skill only verifies or controls the default loopback Splunk Observability Studio
   at 127.0.0.1:3000. I will not probe or control the custom endpoint. Use the
   MCP server directly, update the config back to the default local Splunk Observability Studio,
   or manually verify the custom Splunk Observability Studio.`
3. Before probing host-local endpoints from a shell command, request narrow
   elevated/outside-sandbox permission. Do not first try the check from inside
   the sandbox.
4. Check only `http://127.0.0.1:3000/api/health` for Splunk Observability Studio health. Do not
   use the MCP endpoint as a health check and do not follow alternate hosts
   from MCP or user config.
5. Report Splunk Observability Studio URL, MCP endpoint, and whether the setup looks healthy.
   Use `127.0.0.1` in user-facing default URLs instead of `localhost`.
   The default MCP endpoint is `http://127.0.0.1:3000/mcp`.
6. If elevated access is denied or the endpoint cannot be verified from the
   available context, report `sandbox-unverified`; do not report Splunk Observability Studio
   as unhealthy based only on sandbox-local reachability.
7. If the runtime is shared or externally owned, say so explicitly and do not
   imply ownership.
