# Obstudio Codex Plugin

This directory is the repo-local Codex plugin scaffold for Obstudio.

It packages the canonical skill sources from `../../skills/`, points Codex
at the local Observer MCP endpoint via [`.mcp.json`](./.mcp.json), and includes
a plugin-root SessionStart hook manifest for first-run bootstrap.

Current scope:

- bundled skills for audit, instrumentation, verification, and Splunk publish workflows
- Codex marketplace entry under [`.agents/plugins/marketplace.json`](../../.agents/plugins/marketplace.json)
- MCP server configuration for a local Observer at `http://127.0.0.1:3000/mcp`
- one-time SessionStart hook manifest in [`hooks/hooks.json`](./hooks/hooks.json)
  that calls a dedicated bootstrap script
- [`hooks/bootstrap_obstudio.py`](./hooks/bootstrap_obstudio.py) downloads the
  release archive when needed, verifies the release checksum, runs
  `obstudio install --target=codex`, and starts the local Observer process if
  the Codex config is using the bundled HTTP MCP endpoint
- the bootstrapper expects the release pipeline to publish a `checksums.txt`
  asset alongside the zip archives and validates the archive before extraction

The plugin is intentionally self-contained from Codex’s point of view:

- Codex can see the bundled skills immediately after installation.
- The plugin’s bootstrap script can bootstrap the release archive and Codex
  MCP config on first session start.
- The hook is non-managed, so Codex will ask you to review and trust it before
  it runs the first time.
