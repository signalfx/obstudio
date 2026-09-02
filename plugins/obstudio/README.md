# Obstudio Codex and Claude Code Plugin

This directory is the portable Obstudio plugin bundle for Codex and Claude Code.

It packages the canonical skill sources from `../../skills/`, points both hosts
at the local Observer MCP endpoint via [`.mcp.json`](./.mcp.json), and includes
host-specific SessionStart hook manifests for first-run bootstrap.

## How to get started

1. Install the **Splunk Observability Studio** plugin.
2. Trust the host's `SessionStart` hook when prompted to review it.
3. Try one of these actions:

   | Action | Codex | Claude Code |
   | --- | --- | --- |
   | Open the local Observer | `$observer-open` | `/obstudio:observer-open` |
   | Check Observer health | `$observer-status` | `/obstudio:observer-status` |
   | Get started with Observability Cloud Free Edition | `$create-splunk-free-account` | `/obstudio:create-splunk-free-account` |
   | Connect Observability Cloud | `$connect-splunk-observability-cloud` | `/obstudio:connect-splunk-observability-cloud` |
   | Audit observability gaps | `$otel-audit` | `/obstudio:otel-audit` |
   | Add instrumentation | `$otel-instrument` | `/obstudio:otel-instrument` |
   | Verify emitted telemetry | `$otel-verify` | `/obstudio:otel-verify` |

Current scope:

- bundled skills for Free Edition signup, secure Cloud connection handoff,
  audit, instrumentation, verification, and Splunk publish workflows
- bundled observer control skills:
  - `observer-open`
  - `observer-status`
  - `observer-restart`
  - `observer-stop`
- Codex marketplace entry under [`.agents/plugins/marketplace.json`](../../.agents/plugins/marketplace.json)
- Claude Code marketplace entry under [`.claude-plugin/marketplace.json`](../../.claude-plugin/marketplace.json)
- MCP server configuration for a local Observer at `http://127.0.0.1:3000/mcp`
- one-time SessionStart hook manifests in
  [`hooks/codex-hooks.json`](./hooks/codex-hooks.json) and
  [`hooks/claude-hooks.json`](./hooks/claude-hooks.json), both calling the
  shared bootstrapper
- [`hooks/bootstrap_obstudio.py`](./hooks/bootstrap_obstudio.py) downloads the
  release archive when needed, verifies the release checksum, and starts the
  local Observer process for the bundled plugin MCP endpoint when the active
  host permits managed local startup
- the bootstrapper expects the release pipeline to publish a `checksums.txt`
  asset alongside the zip archives and validates the archive before extraction

The bootstrap starts or reuses Observer but does not edit Codex or Claude Code
OTLP settings. Provider token collection is a separate user opt-in. With the
standalone release CLI installed, enable either provider and restart it:

```bash
obstudio token-telemetry enable --target=codex,claude-code
```

The command leaves matching settings user-owned, refuses conflicting OTLP
routing, and records only values it adds so `token-telemetry disable` can remove
those values without deleting later user changes. New targets default
repository correlation to `path`, which sends the repository name plus canonical
repository and active workspace paths. Use `name` to omit filesystem paths, or
`off` to disable correlation. Omitting the flag for an already configured target
preserves its recorded mode. When enabled, the trusted SessionStart hook sends
a content-free correlation event to the same loopback Observer; prompt and tool
content are not included.

Shared workflow skill sources are canonical in the top-level `skills/`
directory. Their copies under `plugins/obstudio/skills/` are materialized so a
repo-local marketplace install works from a fresh checkout without
cross-directory symlinks. Plugin-only observer-control skills are authoritative
under `plugins/obstudio/skills/observer-control/`.
Refresh the materialized shared copies after editing canonical skills:

```bash
make sync-obstudio-plugin-skills
```

Before publishing, build the staged plugin with materialized skill trees:

```bash
make stage-obstudio-plugin
```

The staged directories are `.release/plugins/obstudio-codex` and
`.release/plugins/obstudio-claude`. To also write the corresponding
`obstudio-codex.zip` and `obstudio-claude.zip` archives, run:

```bash
make package-obstudio-plugin
```

Each staged plugin is intentionally self-contained for its host:

- Both hosts can see the bundled skills immediately after installation.
- The plugin’s bootstrap script can bootstrap the release archive and managed
  local Observer runtime on first session start.
- Each host asks you to review and trust the hook before it runs for the first
  time.
