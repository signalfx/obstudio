# Splunk Observability Studio plugin for Codex and Claude Code

This directory is the portable Splunk Observability Studio plugin bundle for Codex and
Claude Code.

It packages the canonical skill sources from `../../skills/`, points both hosts
at the local Splunk Observability Studio MCP endpoint via [`.mcp.json`](./.mcp.json), and includes
host-specific SessionStart hook manifests for first-run bootstrap.

## Prerequisites

Python 3 is required for the SessionStart bootstrap. It must be available on
`PATH` as `python3`, `python`, or Windows `py -3`. If none of these interpreters
is available, the hook exits with code 2 and the managed Splunk Observability
Studio runtime cannot be bootstrapped automatically.

## How to get started

1. Install the **Splunk Observability Studio** plugin.
2. Trust the host's `SessionStart` hook when prompted to review it.
3. Try a workflow or Splunk Observability Studio command.

| Purpose | Codex | Claude Code |
| --- | --- | --- |
| Open Splunk Observability Studio | `$observer-open` | `/obstudio:observer-open` |
| Check Splunk Observability Studio status | `$observer-status` | `/obstudio:observer-status` |
| Restart Splunk Observability Studio | `$observer-restart` | `/obstudio:observer-restart` |
| Stop Splunk Observability Studio | `$observer-stop` | `/obstudio:observer-stop` |
| Find telemetry gaps | `$otel-audit` | `/obstudio:otel-audit` |
| Implement selected telemetry improvements | `$otel-instrument` | `/obstudio:otel-instrument` |
| Verify instrumentation | `$otel-verify` | `/obstudio:otel-verify` |
| Generate detectors and dashboards | `$splunk-configure` | `/obstudio:splunk-configure` |
| Generate dashboards only | `$splunk-dashboard` | `/obstudio:splunk-dashboard` |
| Publish detector gaps | `$splunk-detector-publish` | `/obstudio:splunk-detector-publish` |
| Publish dashboard gaps | `$splunk-dashboard-publish` | `/obstudio:splunk-dashboard-publish` |
| Connect an existing Splunk organization | `$connect-splunk-observability-cloud` | `/obstudio:connect-splunk-observability-cloud` |
| Request a Free Edition organization | `$create-splunk-free-account` | `/obstudio:create-splunk-free-account` |

## Plugin contents

The bundle includes the audit, instrumentation, verification, Cloud, and
Splunk publish skills, plus `observer-open`, `observer-status`,
`observer-restart`, and `observer-stop`. It also contains:

- host marketplace entries under [`.agents/plugins/marketplace.json`](../../.agents/plugins/marketplace.json)
  and [`.claude-plugin/marketplace.json`](../../.claude-plugin/marketplace.json);
- the Splunk Observability Studio MCP configuration in [`.mcp.json`](./.mcp.json); and
- SessionStart manifests in [`hooks/codex-hooks.json`](./hooks/codex-hooks.json)
  and [`hooks/claude-hooks.json`](./hooks/claude-hooks.json).

The shared [`hooks/bootstrap_obstudio.py`](./hooks/bootstrap_obstudio.py)
downloads the release when needed, validates its published checksum, and
starts or reuses Splunk Observability Studio when the host permits managed startup.
Claude prefers the Observer release matching its plugin version. If that
release's assets are unavailable, Claude falls back to the latest Observer
with a warning. When a healthy shared Observer is already running at another
version, Claude reports the mismatch and reuses it rather than interrupting
another host. Codex continues to use the latest Observer release.

## Maintainer workflow

Shared workflow skill sources are canonical in the top-level `skills/`
directory. Their copies under `plugins/obstudio/skills/` are materialized so a
repo-local marketplace install works from a fresh checkout without
cross-directory symlinks. Plugin-only observer-control skills are authoritative
under `plugins/obstudio/skills/observer-control/`.

The published Claude marketplace entry uses a SHA-256-pinned release archive.
The release workflow publishes the Claude and Codex plugin archive hashes in a
separate plugin checksum file, then updates the Claude archive URL and checksum
alongside the Claude and Codex plugin manifest versions. Codex's repo-local
marketplace remains a path source.

For Claude development, choose one of these local workflows:

- For marketplace-flow testing, temporarily change the source in
  `.claude-plugin/marketplace.json` to `./plugins/obstudio`. Do not commit that
  source change. This exercises local marketplace installation and live edits.
- To load the checkout directly without marketplace registration, run Claude
  Code with `--plugin-dir ./plugins/obstudio`. This is useful for testing plugin
  contents, but does not test archive installation or marketplace updates.

A sibling file named `marketplace.local.json` is not discovered automatically
by Claude Code as a second marketplace. Claude expects the marketplace manifest
at `.claude-plugin/marketplace.json` within a registered marketplace directory.
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
versioned `obstudio_codex_<version>.zip` and
`obstudio_claude_<version>.zip` archives, pass the release tag:

```bash
make package-obstudio-plugin RELEASE_TAG=v0.0.20
```

The archives are written to `.release/plugins/` with the leading `v` removed
from the filename, for example `obstudio_codex_0.0.20.zip` and
`obstudio_claude_0.0.20.zip`.

Each staged plugin is intentionally self-contained for its host:

- Both hosts can see the bundled skills immediately after installation.
- Published staged bundles omit skill test suites and local tool caches; those
  files remain in the repository for development and CI.
- The plugin’s bootstrap script can bootstrap the release archive and managed
  local Splunk Observability Studio runtime on first session start.
- Each host asks you to review and trust the hook before it runs for the first
  time.
