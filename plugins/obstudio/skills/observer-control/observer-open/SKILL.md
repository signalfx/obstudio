---
name: observer-open
description: >-
  Open the local Splunk Observability Studio at http://127.0.0.1:3000/ using a
  host-provided browser when available, with a safe clickable-URL fallback.
---

# Open Splunk Observability Studio

Open only the loopback Studio UI at `http://127.0.0.1:3000/`. This skill is
read-only and must not start, stop, or restart Studio.

## Steps

1. If Studio MCP uses a non-default endpoint, report its URL and explain that
   this skill only verifies the default loopback Studio at `127.0.0.1:3000`.
   Do not probe or control the custom endpoint; use MCP directly, restore the
   default, or verify it manually.
2. If a host-provided browser is available, open `http://127.0.0.1:3000/` in
   it. Do not follow alternate hosts from MCP or user config. Confirm the
   Telemetry Explorer only when the browser shows it loaded; otherwise report
   browser verification as inconclusive.
3. If no host-provided browser is available, provide the clickable URL
   `http://127.0.0.1:3000/`. Do not launch an OS browser without the user's
   explicit approval.
4. If a shell probe is needed, explicitly say that narrow
   elevated/outside-sandbox approval is required before running it, and check only
   `http://127.0.0.1:3000/` or `http://127.0.0.1:3000/api/health`.
5. If access is denied or verification is unavailable, report
   `sandbox-unverified`; endpoint reachability does not prove the UI rendered,
   and sandbox-local failure alone does not prove Studio unhealthy.
