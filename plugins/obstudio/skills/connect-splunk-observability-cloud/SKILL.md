---
name: connect-splunk-observability-cloud
description: >-
  Open the already-running local Obstudio Observer Cloud tab so a user can
  connect an existing or newly ready Splunk Observability Cloud organization
  by entering its URL and access token outside agent context. Use when a user
  asks to connect, configure, or provide credentials for Splunk Observability
  Cloud, Splunk O11y, or SignalFx outside the Obstudio IDE extension. Do not use
  this skill to create a Free Edition account.
---

# Connect Splunk Observability Cloud

Hand credential entry to the existing local Observer Cloud UI. The agent must
never collect or transmit the access token itself.

## Guardrails

- Open the Cloud UI only after the user explicitly asks to connect or configure
  an organization.
- Do not use this skill for signup. Use `$create-splunk-free-account` when the
  user still needs a Free Edition account.
- Never ask the user to paste the Observability Cloud URL or access token into
  agent chat. If either value was already pasted, do not repeat it or pass it
  onward.
- Never place an access token in an MCP or other tool argument, native agent
  form, shell command or process argument, environment assignment, URL path,
  query, or fragment, log, or telemetry. Do not call
  `observer_splunk_metrics_export_configure` with a raw token obtained through
  model context.
- Do not call `observer_splunk_free_account_region_detect` or
  `observer_splunk_free_account_create` during this connection workflow.
- Do not start, stop, or restart Observer or launch another Observer process.

## Open the existing Cloud tab

1. Call `observer_status` once with no arguments and read only
   `endpoints.rest`.
2. Require an `http` URL whose host is loopback. Normalize a wildcard listener
   host from `0.0.0.0` to `127.0.0.1` or from `::` to `::1`. Reject a
   non-loopback host for this local credential handoff. Remove any credentials,
   path, query, or fragment from the returned URL.
3. Append `/?tab=cloud` to the normalized origin. The normal standalone result
   is exactly:

   ```text
   http://127.0.0.1:3000/?tab=cloud
   ```

   Use the port already reported by the running Observer. Never allocate,
   probe for, or choose a new dynamic port.
4. When the current client exposes a host-provided browser or open-URL
   capability, use it to open the Cloud-tab URL. Do not shell out to
   platform-specific commands such as `open`, `xdg-open`, or `start`.
5. If no host-provided browser capability exists, provide the Cloud-tab URL as
   a clickable fallback. Do not launch an operating-system browser without the
   user's explicit approval.
6. Tell the user to enter both **Realm or Observability Cloud URL** and
   **Access token** directly in that local UI, then select **Connect**. Stop and
   wait while the user completes the form.
7. In the same handoff, explicitly state: `This connection applies to the
   current running standalone Observer process and must be entered again after
   Observer restarts.`
8. Also state that opening the tab only presents the credential-entry surface
   and does not mean the organization is connected. Connection success requires
   a later local Cloud UI or Observer backend result.

If `observer_status` is unavailable, `endpoints.rest` is missing or invalid, or
the Cloud tab cannot be opened, explain the specific limitation and stop. An
inconclusive browser render is not proof that Observer is unhealthy.

Do not claim the organization is connected merely because the page opened. If
the user later asks to confirm the configuration, call
`observer_splunk_connection_realm` with no arguments. A non-empty realm proves
only that Observer has a consistent local connection configuration; it does
not prove remote token validity or that export is enabled. Never request the
token to investigate an empty result.
