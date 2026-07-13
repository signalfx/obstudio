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

## Steps

1. Check whether the Observer is `managed`, `shared`, or `external`.
2. If it is `shared` or `external`, do not restart it unless the current plugin
   explicitly owns it.
3. If it is `managed`, rerun the bootstrap path for the current plugin version
   or the plugin-owned restart flow.
4. Verify the UI and `api/health` endpoint again after the restart.
