---
name: observer-stop
description: >-
  Explain how to stop or disconnect from a local Splunk Observability Studio when the
  user intentionally wants to shut down the managed runtime or leave a shared
  Splunk Observability Studio alone.
---

# Stop Splunk Observability Studio

Stop local Studio or disconnect from it safely.

Ownership rules:

- `managed`: the current plugin started Studio and may stop it.
- `shared`: Studio is reused across repos or sessions; do not stop it
  unless the current plugin explicitly owns it.
- `external`: Studio was started outside the plugin; do not stop it.

If ownership is unclear, do not stop anything. Report the current state and
recommend manual recovery instead.

Prefer the live health endpoint and listener over stale log output or an old
saved PID. If health is good and the bundled Studio binary is already
listening, update the saved PID and stop; do not stop or kill a second copy
just because the cached state is stale.

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
7. If it is `shared` or `external`, do not stop it unless the current plugin
   explicitly owns it.
8. If it is `managed`, stop only the process that the current plugin started.
9. Record `"status": "stopped"` in `bootstrap-state.json` so the next
   `SessionStart` hook does not restart managed Studio.
10. Confirm `http://127.0.0.1:3000/api/health` is no longer reachable if the
   goal was to fully shut down the local runtime.
