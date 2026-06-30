---
name: splunk-o11y-onboard
description: >-
  Register a Splunk Observability Cloud Free organization or connect Obstudio,
  Codex, Claude Code, Cursor, and VS Code to an existing organization through
  the shared Obstudio OAuth CLI with realm selection. Use when a user asks to
  register, create a freemium organization, select an O11y region or realm,
  sign in, connect O11y, inspect connection status, switch organizations,
  forget a key, log out, or reconnect telemetry export.
---

# Splunk O11y Onboard

Use the `obstudio cloud` commands as the only onboarding implementation. Do not
collect registration fields in chat, call OAuth endpoints directly, ask the
user to paste a token, or reproduce the PKCE flow in agent instructions.

## Resolve the command

Use `obstudio` from `PATH`. If unavailable, use the installed binary beside the
bundled skill directory. If neither exists, tell the user to install or enable
the Obstudio extension or run `obstudio install --target=<agent>` from an
Obstudio release.

Agent targets are `codex`, `claude-code`, and `cursor`. Installing an agent
integration configures MCP and skills; it does not authenticate the user.

## Choose the flow

### New or freemium organization

1. Run `obstudio cloud register`.
2. Tell the user to complete registration and email verification in the
   browser. Relay the registration URL printed by the command as a clickable
   fallback because an OS browser launcher cannot prove that a visible tab
   opened. Do not request registration values in chat.
3. When the user is ready, ask for their realm if it is not already known. Run
   `obstudio cloud regions` to show the supported realms, cloud regions, and
   direct URLs, then run:

   ```bash
   obstudio cloud login --region <realm>
   ```

4. Let the browser-hosted organization picker and consent page handle account,
   organization, and optional-scope selection.
5. Run `obstudio cloud status` and report only the redacted organization,
   realm, scopes, and storage mode.
6. Restart an already-running standalone Obstudio process so it loads the new
   OS-keychain connection. VS Code and Cursor update their managed Observer
   directly and do not require this restart.

### Existing organization

Ask for the Splunk Observability Cloud realm when absent. If the user does not
know it, run `obstudio cloud regions` and show the command output. Run:

```bash
obstudio cloud login --region <realm>
```

If the user supplies a direct organization, internal, legacy regional, or
loopback development URL, run the explicit issuer pattern instead:

```bash
obstudio cloud login --issuer <issuer-url>
```

Examples include `https://app.us1.signalfx.com`,
`https://app.lab0.signalfx.com`, `https://mon.signalfx.com/#/signin`, and
`http://127.0.0.1:3000`. The CLI canonicalizes trusted page URLs to their origin.
Do not combine `--region` and `--issuer`, and never accept an arbitrary host.

The CLI opens the user's browser, reuses an existing O11y session when
available, performs authorization-code OAuth with PKCE on a random loopback
port, and stores the resulting connection in the OS keychain. The browser
handles multiple eligible organizations and scope approval.

If OAuth discovery returns `404`, explain that the proposed OAuth endpoints are
not deployed in that realm. Do not request or accept a pasted access token.

Restart an already-running standalone Obstudio process after login. Do not
restart an extension-managed Observer; the extension applies its IDE-stored
connection directly.

### Status

Run `obstudio cloud status`. Use `--output=json` only when structured output is
needed. The status command never returns the access token.

### Disconnect or switch organizations

Run `obstudio cloud logout`. This revokes the server-side token before deleting
the OS-keychain connection. Run a new login only after logout succeeds.

Use `--local-only` only when the user explicitly accepts that the server-side
token cannot be revoked and must be removed separately in Splunk Observability
Cloud.

## Security boundaries

- Never run `cloud login --show-token`; it is reserved for the trusted extension
  process that immediately transfers the result into IDE SecretStorage.
- Never print, log, summarize, persist in a file, or place an access token in a
  command argument.
- Treat browser approval as the authorization boundary. Do not auto-approve or
  bypass optional scopes.
- Keep telemetry export disabled after connection until the user enables it.
- Prefer IDE SecretStorage for VS Code and Cursor. Standalone commands use the
  OS keychain. Do not invent a plaintext fallback.
