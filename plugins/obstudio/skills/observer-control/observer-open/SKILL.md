---
name: observer-open
description: >-
  Open the local Obstudio Observer in the built-in browser at
  http://127.0.0.1:3000/ and confirm the UI is reachable.
---

# Open Observer

Use this skill to open the local Obstudio UI.

This skill is read-only. It must not start, stop, or restart any Observer
process. It is limited to the loopback Observer UI at
`http://127.0.0.1:3000/`.

## Steps

1. If Obstudio MCP is configured to a non-default endpoint, report:
   `Obstudio MCP is configured to a non-default endpoint: <url>. For safety,
   this command skill only verifies or controls the default loopback Observer
   at 127.0.0.1:3000. I will not probe or control the custom endpoint. Use the
   MCP server directly, update the config back to the default local Observer,
   or manually verify the custom Observer.`
2. Open `http://127.0.0.1:3000/` in the built-in browser. Do not follow
   alternate hosts from MCP or user config.
3. Confirm the Telemetry Explorer loads.
4. If browser verification is inconclusive and a shell probe is needed, request
   narrow elevated/outside-sandbox permission and check only
   `http://127.0.0.1:3000/` or `http://127.0.0.1:3000/api/health`.
5. If elevated access is denied or the endpoint cannot be verified from the
   available context, report `sandbox-unverified`; do not report the Observer
   as unhealthy based only on sandbox-local reachability.
