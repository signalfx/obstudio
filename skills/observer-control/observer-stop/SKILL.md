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

## Steps

1. Determine whether the Observer is `managed`, `shared`, or `external`.
2. If it is `shared` or `external`, do not stop it unless the current plugin
   explicitly owns it.
3. If it is `managed`, stop only the process that the current plugin started.
4. Confirm the `api/health` endpoint is no longer reachable if the goal was to
   fully shut down the local runtime.
