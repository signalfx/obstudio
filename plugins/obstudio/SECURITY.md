# Obstudio Plugin Security

This document describes the current security model for the `obstudio` plugin
when used with Codex or Claude Code. It is a behavior contract for this plugin
package, not a guarantee about either host, model providers, package managers,
operating system services, or user-invoked third-party tools.

## Trust Boundary

The plugin contains instructions, skills, assets, materialized skill
references, local Observer MCP configuration, and a SessionStart bootstrap
hook. The active host decides which skills to load, which tools to call, and
which shell commands require approval according to its configuration and
product policy.

## Trust Levels

Core workflow skills:

- `$otel-audit`
- `$otel-instrument`
- `$otel-verify`
- `$splunk-configure`
- `$splunk-dashboard`

Trust model:

- Can read and write repo files through skills like instrumentation.
- Can generate local reports and Terraform.
- Does not manage a local background Observer process.
- Does not call live Splunk APIs to create resources.

Observer and MCP controls:

- MCP server config for `http://127.0.0.1:3000/mcp`
- SessionStart bootstrap hook, if managed startup is kept enabled
- `$observer-open`
- `$observer-status`
- `$observer-restart`
- `$observer-stop`

Trust model:

- Interacts with host-local endpoints.
- May download, start, or manage the local Observer.
- May need narrow elevated/outside-sandbox access for localhost health or
  control checks.
- Command skills are limited to the default loopback Observer and do not probe
  or control custom MCP endpoints automatically.

Splunk publish skills:

- `$splunk-detector-publish`
- `$splunk-dashboard-publish`
- `$splunk-sync` deprecated alias
- `$splunk-dashboard-sync` deprecated alias

Trust model:

- Calls Splunk Observability Cloud APIs when explicitly invoked.
- Can create live dashboard or detector resources.
- Requires Splunk credentials with the required API permissions.

At full enablement, the plugin can help with:

- read and analyze project files;
- write instrumentation changes when `$otel-instrument` is explicitly invoked;
- run verification commands needed for selected workflows;
- generate local reports and Terraform artifacts;
- connect to a local Observer MCP endpoint;
- open, check, restart, or stop a managed Observer when the user asks;
- publish confirmed Splunk dashboard or detector gaps when the user explicitly
  invokes publish skills and provides credentials.

## Local Listener Exposure

The managed Observer is intended to bind loopback-local endpoints, including
`127.0.0.1:3000`, `127.0.0.1:4317`, and `127.0.0.1:4318`. The UI, REST API,
MCP endpoint, and OTLP receivers should not be exposed on public interfaces by
default.

The bundled MCP server config points to `http://127.0.0.1:3000/mcp`. Observer
command skills do not automatically follow non-default MCP endpoints; they
verify or control only the default loopback Observer at `127.0.0.1:3000`.

Health checks use `http://127.0.0.1:3000/api/health`, not the MCP endpoint.
When either host needs a shell-based host-local health or control check, it
should request the narrow permission required by that host before probing. If
permission is denied or the endpoint cannot be verified from the available
context, report `sandbox-unverified`, not unhealthy.

## Managed Bootstrap Boundary

If the user trusts the SessionStart hook, the bootstrap may:

- download an Obstudio release binary;
- verify it against `checksums.txt`;
- extract the release into plugin data;
- use the bundled plugin `.mcp.json` endpoint policy;
- start or reuse a local Observer process unless the active host's bootstrap
  controls opt out of managed local startup.

Do not trust the hook if you do not want plugin-managed binary download,
checksum validation, or local process startup.

## Risky Surfaces

The plugin includes several higher-trust surfaces:

- `otel-instrument` can edit application code and configuration.
- `observer-restart` and `observer-stop` can control a local Observer process
  and should require evidence that the current plugin owns the process.
- `splunk-detector-publish` and `splunk-dashboard-publish` can call live Splunk
  Observability Cloud APIs and create resources.
- Configured OTLP exporters can send telemetry to configured endpoints.
- Verification workflows can run project commands, tests, package managers,
  or local servers.

Destructive or control actions should require explicit user intent, ownership
evidence when controlling a local process, and narrow permissions when the
active host requires approval for localhost access. Observer command skills should
inspect only the default loopback health endpoint and the Observer listener
ports `127.0.0.1:3000`, `127.0.0.1:4317`, and `127.0.0.1:4318`.

## User Controls

Plugin management and MCP connectivity are separate controls. Disabling a
plugin or withholding SessionStart-hook approval prevents plugin-managed
bootstrap. Disabling an MCP server controls whether the host connects to that
endpoint; it does not by itself stop an already trusted hook from starting an
Observer, nor does it stop a pre-existing local Observer process.

### Codex

Disable the Obstudio MCP server in `~/.codex/config.toml`:

```toml
[mcp_servers.obstudio]
enabled = false
url = "http://127.0.0.1:3000/mcp"
```

Disable a specific skill without deleting it:

```toml
[[skills.config]]
path = "/path/to/obstudio/skills/observer-control/observer-restart/SKILL.md"
enabled = false

[[skills.config]]
path = "/path/to/obstudio/skills/splunk-detector-publish/SKILL.md"
enabled = false
```

### Claude Code

Use Claude Code's plugin controls to disable Splunk Observability Studio or withhold SessionStart
hook approval to prevent its managed bootstrap. Use Claude Code's MCP-server
controls to prevent Claude from connecting to the local MCP endpoint, and its
command permission prompts to withhold individual host-local commands. A
disabled Claude MCP server does not stop a previously trusted SessionStart hook
from managing an Observer, and withholding a later hook prompt does not prevent
connection to an already running endpoint. Claude Code manages these controls
under its own plugin and permission model; the Codex configuration examples
above do not apply to Claude Code.
