# Obstudio Codex and Claude Code Plugin

This directory is the portable Obstudio plugin bundle for Codex and Claude Code.

It packages the canonical skill sources from `../../skills/`, points both hosts
at the local Observer MCP endpoint via [`.mcp.json`](./.mcp.json), and includes
host-specific SessionStart hook manifests for first-run bootstrap.

## How to get started

1. Install the **Splunk Observability Studio** plugin.
2. Trust the host's `SessionStart` hook when prompted to review it.
3. Try a workflow or Observer command.

For Codex:

- `$observer-open`, `$observer-status`
- `$otel-audit`, `$otel-instrument`, `$otel-verify`
- `$connect-splunk-observability-cloud`, `$create-splunk-free-account`

For Claude Code:

- `/obstudio:observer-open`, `/obstudio:observer-status`
- `/obstudio:otel-audit`, `/obstudio:otel-instrument`,
  `/obstudio:otel-verify`
- `/obstudio:connect-splunk-observability-cloud`,
  `/obstudio:create-splunk-free-account`

The `connect-splunk-observability-cloud` skill opens the Cloud view so you can
connect an existing Splunk Observability Cloud organization. The
`create-splunk-free-account` skill starts a Free Edition signup.

## Plugin contents

The bundle includes the audit, instrumentation, verification, Cloud, and
Splunk publish skills, plus `observer-open`, `observer-status`,
`observer-restart`, and `observer-stop`. It also contains:

- host marketplace entries under [`.agents/plugins/marketplace.json`](../../.agents/plugins/marketplace.json)
  and [`.claude-plugin/marketplace.json`](../../.claude-plugin/marketplace.json);
- the Observer MCP configuration in [`.mcp.json`](./.mcp.json); and
- SessionStart manifests in [`hooks/codex-hooks.json`](./hooks/codex-hooks.json)
  and [`hooks/claude-hooks.json`](./hooks/claude-hooks.json).

The shared [`hooks/bootstrap_obstudio.py`](./hooks/bootstrap_obstudio.py)
downloads the release when needed, validates its published checksum, and
starts or reuses Observer when the host permits managed startup.

## Maintainer workflow

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
