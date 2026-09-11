---
name: observer-restart
description: >-
  Explain how to refresh or restart the local Splunk Observability Studio when the UI is
  stale, the MCP endpoint is unavailable, or the bootstrap state needs to be
  refreshed.
---

# Restart Splunk Observability Studio

Use this skill when the local Splunk Observability Studio needs to be refreshed.

Ownership rules:

- `managed`: the current plugin started Splunk Observability Studio and may restart it.
- `shared`: Splunk Observability Studio is reused across repos or sessions; do not restart it
  unless the current plugin explicitly owns it.
- `external`: Splunk Observability Studio was started outside the plugin; do not restart it.

If ownership is unclear, do not restart anything. Report the current state and
recommend manual recovery instead.

Prefer the live health endpoint and listener over stale log output or an old
saved PID. If health is good and the bundled Splunk Observability Studio binary is already
listening, update the saved PID before applying the ownership rules; do not
start a second copy.

Endpoint checks are limited to the Splunk Observability Studio loopback endpoints:

- health: `http://127.0.0.1:3000/api/health`
- listener inspection: `127.0.0.1:3000`, `127.0.0.1:4317`, and
  `127.0.0.1:4318`

## Steps

1. Check whether Splunk Observability Studio is `managed`, `shared`, or `external`.
2. If Splunk Observability Studio MCP is configured to a non-default endpoint, report:
   `Splunk Observability Studio MCP is configured to a non-default endpoint: <url>. For safety,
   this command skill only verifies or controls the default loopback Splunk Observability Studio
   at 127.0.0.1:3000. I will not probe or control the custom endpoint. Use the
   MCP server directly, update the config back to the default local Splunk Observability Studio,
   or manually verify the custom Splunk Observability Studio.`
3. Before probing host-local endpoints or inspecting local listeners from a
   shell command, request narrow elevated/outside-sandbox permission. Do not
   first try the check from inside the sandbox.
4. Check only `http://127.0.0.1:3000/api/health` for Splunk Observability Studio health. Do not
   use the MCP endpoint as a health check and do not follow alternate hosts
   from MCP or user config.
5. If elevated access is denied or the endpoint cannot be verified from the
   available context, report `sandbox-unverified`; do not report Splunk Observability Studio
   as unhealthy based only on sandbox-local reachability.
6. If health is good and the bundled Splunk Observability Studio is already listening, update the
   saved PID to match the live process, then continue applying the ownership
   rules below.
7. If it is `shared` or `external`, do not restart it unless the current plugin
   explicitly owns it.
8. Clear `"status": "stopped"` from the plugin `bootstrap-state.json` before
   starting a managed Splunk Observability Studio again.
9. If it is `managed`, restart only the process that the current plugin
   started, even when the health endpoint is currently good.
10. If startup fails because one of the expected ports is already in use,
   inspect only `127.0.0.1:3000`, `127.0.0.1:4317`, and `127.0.0.1:4318`.
11. If the ports belong to another binary, or ownership cannot be determined,
   treat it as `shared` or `external`; do not kill or restart it. Report the
   conflicting PID/port and recommend manual recovery.
