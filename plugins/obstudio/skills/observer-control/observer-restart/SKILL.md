---
name: observer-restart
description: >-
  Explain how to refresh or restart the local Splunk Observability Studio when the UI is
  stale, the MCP endpoint is unavailable, or the bootstrap state needs to be
  refreshed.
---

# Restart Splunk Observability Studio

Use this skill when local Studio needs to be refreshed.

Ownership rules:

- `managed`: the current plugin started Studio and may restart it.
- `shared`: Studio is reused across repos or sessions; do not restart it
  unless the current plugin explicitly owns it.
- `external`: Studio was started outside the plugin; do not restart it.

If ownership is unclear, do not restart anything. Report the current state and
recommend manual recovery instead.

Prefer the live health endpoint and listener over stale log output or an old
saved PID. If health is good and the bundled Studio binary is already
listening, update the saved PID before applying the ownership rules; do not
start a second copy.

Endpoint checks are limited to Studio's loopback endpoints:

- health: `http://127.0.0.1:3000/api/health`
- listener inspection: `127.0.0.1:3000`, `127.0.0.1:4317`, and
  `127.0.0.1:4318`

## Steps

1. Check whether Studio is `managed`, `shared`, or `external`.
2. If Studio MCP uses a non-default endpoint, report its URL and explain that
   this skill only controls default loopback Studio at `127.0.0.1:3000`. Do not
   probe or control the custom endpoint; use MCP directly, restore the default,
   or verify it manually.
3. Before probing host-local endpoints or inspecting local listeners from a
   shell command, request narrow elevated/outside-sandbox permission. Do not
   first try the check from inside the sandbox.
4. Check only `http://127.0.0.1:3000/api/health` for Studio health. Do not
   use the MCP endpoint as a health check and do not follow alternate hosts
   from MCP or user config.
5. If access is denied or verification is unavailable, report
   `sandbox-unverified`; sandbox-local reachability alone does not prove Studio
   unhealthy.
6. If health is good and bundled Studio is already listening, update the
   saved PID to match the live process, then continue applying the ownership
   rules below.
7. If it is `shared` or `external`, do not restart it unless the current plugin
   explicitly owns it.
8. Clear `"status": "stopped"` from `bootstrap-state.json` before starting
   managed Studio again.
9. If it is `managed`, restart only the process that the current plugin
   started, even when the health endpoint is currently good.
10. If startup fails because one of the expected ports is already in use,
   inspect only `127.0.0.1:3000`, `127.0.0.1:4317`, and `127.0.0.1:4318`.
11. If the ports belong to another binary, or ownership cannot be determined,
   treat it as `shared` or `external`; do not kill or restart it. Report the
   conflicting PID/port and recommend manual recovery.
