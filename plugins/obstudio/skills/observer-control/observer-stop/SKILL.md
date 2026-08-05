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

## Steps

1. Check whether the Observer is `managed`, `shared`, or `external`.
2. Check the configured health endpoint. Prefer
   `http://127.0.0.1:3000/api/health` unless the Codex MCP config explicitly
   points to a different host. If a sandboxed `localhost` probe fails but the
   configured `127.0.0.1` endpoint is healthy, treat the Observer as healthy and
   say: `Local sandbox cannot reach localhost, but the configured 127.0.0.1
   endpoint is healthy.`
3. If health is good and the bundled Observer is already listening, update the
   saved PID to match the live process, then continue applying the ownership
   rules below.
4. If it is `shared` or `external`, do not stop it unless the current plugin
   explicitly owns it.
5. If it is `managed`, stop only the process that the current plugin started.
6. Record `"status": "stopped"` in the plugin `bootstrap-state.json` so the
   next `SessionStart` hook does not restart the managed Observer.
7. Confirm the `api/health` endpoint is no longer reachable if the goal was to
   fully shut down the local runtime.
