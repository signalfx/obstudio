---
name: observer-restart
description: >-
  Explain how to refresh or restart the local Obstudio Observer when the UI is
  stale, the MCP endpoint is unavailable, or the bootstrap state needs to be
  refreshed.
---

# Restart Observer

Use this skill when the local Observer needs to be refreshed.

Ownership rules:

- `managed`: the current plugin started the Observer and may restart it.
- `shared`: the Observer is reused across repos or sessions; do not restart it
  unless the current plugin explicitly owns it.
- `external`: the Observer was started outside the plugin; do not restart it.

If ownership is unclear, do not restart anything. Report the current state and
recommend manual recovery instead.

Prefer the live health endpoint and listener over stale log output or an old
saved PID. If health is good and the bundled Observer binary is already
listening, update the saved PID and stop; do not start a second copy.

## Steps

1. Check whether the Observer is `managed`, `shared`, or `external`.
2. Check `http://localhost:3000/api/health`. If the in-sandbox localhost check
   fails with a connection or permission error, retry the same localhost-only
   health check outside the sandbox before treating the Observer as down.
3. If health is good and the bundled Observer is already listening, update the
   saved PID to match the live process and stop; do not restart it.
4. If health is down and the state identifies the bundled binary, restart that
   binary only. If the saved PID is stale or missing, reconcile it with the
   live listener before restarting.
5. If startup fails because one of the expected ports is already in use,
   inspect only ports `3000`, `4317`, and `4318`.
6. If the ports belong to another binary, or ownership cannot be determined,
   treat it as `shared` or `external`; do not kill or restart it. Report the
   conflicting PID/port and recommend manual recovery.
