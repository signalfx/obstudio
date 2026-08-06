---
name: observer-open
description: >-
  Open the local Obstudio Observer in the built-in browser at
  http://127.0.0.1:3000/ and confirm the UI is reachable.
---

# Open Observer

Use this skill to open the local Obstudio UI in Codex.

This skill is read-only. It must not start, stop, or restart any Observer
process.

## Steps

1. Open the configured Observer UI URL. Prefer `http://127.0.0.1:3000/`
   unless the Codex MCP config explicitly points to a different host.
2. Confirm the Telemetry Explorer loads.
3. If the page is unreachable, check whether the bootstrap hook ran and
   whether the local Observer is running.
