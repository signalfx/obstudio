---
name: observer-open
description: >-
  Open the local Splunk Observability Studio at http://127.0.0.1:3000/ using a
  host-provided browser when available, with a safe clickable-URL fallback.
---

# Open Splunk Observability Studio

Use this skill to open the local Splunk Observability Studio UI.

This skill is read-only. It must not start, stop, or restart any Splunk Observability Studio
process. It is limited to the loopback Splunk Observability Studio UI at
`http://127.0.0.1:3000/`.

## Steps

1. If Splunk Observability Studio MCP is configured to a non-default endpoint, report:
   `Splunk Observability Studio MCP is configured to a non-default endpoint: <url>. For safety,
   this command skill only verifies or controls the default loopback Splunk Observability Studio
   at 127.0.0.1:3000. I will not probe or control the custom endpoint. Use the
   MCP server directly, update the config back to the default local Splunk Observability Studio,
   or manually verify the custom Splunk Observability Studio.`
2. If a host-provided browser is available, open `http://127.0.0.1:3000/` in
   it. Do not follow alternate hosts from MCP or user config. Confirm the
   Telemetry Explorer only when the browser shows it loaded; otherwise report
   browser verification as inconclusive.
3. If no host-provided browser is available, provide the clickable URL
   `http://127.0.0.1:3000/`. Do not launch an OS browser without the user's
   explicit approval.
4. If a shell probe is needed, request narrow elevated/outside-sandbox approval
   before running it, and check only
   `http://127.0.0.1:3000/` or `http://127.0.0.1:3000/api/health`.
5. If elevated access is denied or the endpoint cannot be verified from the
   available context, report `sandbox-unverified`; do not report Splunk Observability Studio
   as unhealthy based only on sandbox-local reachability.
