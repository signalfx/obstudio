---
name: observer-stop
description: >-
  Explain how to stop or disconnect from a local Obstudio Observer when the
  user intentionally wants to shut down the managed runtime or leave a shared
  Observer alone.
---

# Stop Observer

Use this skill when you need to stop the local Obstudio Observer or disconnect
from it safely.

Ownership rules:

- `managed`: the current plugin started the Observer and may stop it.
- `shared`: the Observer is reused across repos or sessions; do not stop it
  unless the current plugin explicitly owns it.
- `external`: the Observer was started outside the plugin; do not stop it.

If ownership is unclear, do not stop anything. Report the current state and
recommend manual recovery instead.

Prefer the live health endpoint and listener over stale log output or an old
saved PID. If health is good and the bundled Observer binary is already
listening, update the saved PID and stop; do not stop or kill a second copy
just because the cached state is stale.

Endpoint checks are limited to the Obstudio loopback endpoints:

- health: `http://127.0.0.1:3000/api/health`
- listener inspection: `127.0.0.1:3000`, `127.0.0.1:4317`, and
  `127.0.0.1:4318`

## Steps

1. Check whether the Observer is `managed`, `shared`, or `external`.
2. If Obstudio MCP is configured to a non-default endpoint, report:
   `Obstudio MCP is configured to a non-default endpoint: <url>. For safety,
   this command skill only verifies or controls the default loopback Observer
   at 127.0.0.1:3000. I will not probe or control the custom endpoint. Use the
   MCP server directly, update the config back to the default local Observer,
   or manually verify the custom Observer.`
3. Before probing host-local endpoints or inspecting local listeners from a
   shell command, request narrow elevated/outside-sandbox permission. Do not
   first try the check from inside the sandbox.
4. Check only `http://127.0.0.1:3000/api/health` for Observer health. Do not
   use the MCP endpoint as a health check and do not follow alternate hosts
   from MCP or user config.
5. If elevated access is denied or the endpoint cannot be verified from the
   available context, report `sandbox-unverified`; do not report the Observer
   as unhealthy based only on sandbox-local reachability.
6. If health is good and the bundled Observer is already listening, update the
   saved PID to match the live process, then continue applying the ownership
   rules below.
7. If it is `shared` or `external`, do not stop it unless the current plugin
   explicitly owns it.
8. If it is `managed`, stop only the process that the current plugin started.
9. Record `"status": "stopped"` in the plugin `bootstrap-state.json` so the
   next `SessionStart` hook does not restart the managed Observer.
10. Confirm `http://127.0.0.1:3000/api/health` is no longer reachable if the
   goal was to fully shut down the local runtime.
