# Obstudio Codex Plugin

This directory is the repo-local Codex plugin scaffold for Obstudio.

It packages the canonical skill sources from `../../skills/`, points Codex
at the local Observer MCP endpoint via [`.mcp.json`](./.mcp.json), and includes
a plugin-root SessionStart hook manifest for first-run bootstrap.

## How to get started

1. Install the Obstudio plugin.
2. Trust the `SessionStart` hook when Codex prompts you to review it. You can
   also review the Obstudio plugin hooks from Codex plugin settings and trust
   the hook there.
3. Try one of these actions:
   - Open the local Observer with `$observer-open`.
   - Check Observer health with `$observer-status`.
   - Audit this repo for observability gaps with `$otel-audit`.
   - Add instrumentation for selected findings with `$otel-instrument`.
   - Verify emitted telemetry with `$otel-verify`.

Current scope:

- bundled skills for audit, instrumentation, verification, and Splunk publish workflows
- bundled observer control skills:
  - `obstudio-help`
  - `observer-open`
  - `observer-status`
  - `observer-restart`
  - `observer-stop`
- Codex marketplace entry under [`.agents/plugins/marketplace.json`](../../.agents/plugins/marketplace.json)
- MCP server configuration for a local Observer at `http://127.0.0.1:3000/mcp`
- one-time SessionStart hook manifest in [`hooks/hooks.json`](./hooks/hooks.json)
  that calls a dedicated bootstrap script
- [`hooks/bootstrap_obstudio.py`](./hooks/bootstrap_obstudio.py) downloads the
  release archive when needed, verifies the release checksum, and starts the
  local Observer process for the bundled plugin MCP endpoint unless Codex has
  an explicit Obstudio MCP opt-out or custom endpoint
- the bootstrapper expects the release pipeline to publish a `checksums.txt`
  asset alongside the zip archives and validates the archive before extraction

Shared workflow skill sources live in the top-level `skills/` directory. The
plugin keeps a committed, materialized copy under `plugins/obstudio/skills/` so
repo-local marketplace installs work from a fresh checkout without preserving
cross-directory symlinks. Plugin-only command/control skills, such as
`obstudio-help` and `observer-control/*`, live only under
`plugins/obstudio/skills/`. Refresh the shared plugin copy after editing
canonical skills:

```bash
make sync-obstudio-plugin-skills
```

Before publishing, build the staged plugin with materialized skill trees:

```bash
make stage-obstudio-plugin
```

The staged directory is `.release/plugins/obstudio`. To also write
`.release/plugins/obstudio.zip`, run:

```bash
make package-obstudio-plugin
```

The staged plugin is intentionally self-contained from Codex’s point of view:

- Codex can see the bundled skills immediately after installation.
- The plugin’s bootstrap script can bootstrap the release archive and managed
  local Observer runtime on first session start.
- The hook is non-managed, so Codex will ask you to review and trust it before
  it runs the first time.
