# Splunk Observability Studio plugin security

This document describes the current security model for the `obstudio` plugin
when used with Codex or Claude Code. It is a behavior contract for this plugin
package, not a guarantee about either host, model providers, package managers,
operating system services, or user-invoked third-party tools.

## Trust boundary

The plugin contains instructions, skills, assets, materialized skill
references, local Splunk Observability Studio MCP configuration, and a
SessionStart bootstrap hook. The active host decides which skills to load,
which tools to call, and which shell commands require approval according to its
configuration and product policy.

## Trust levels

| Capability | Access |
|---|---|
| Core workflow skills: `$otel-audit`, `$otel-instrument`, `$otel-verify`, `$splunk-configure`, and `$splunk-dashboard` | Can read or edit repository files, run project verification commands, and generate local reports or Terraform. These skills do not manage a background Splunk Observability Studio instance or create live Splunk resources. |
| Splunk Observability Studio and MCP controls: the bundled MCP configuration, SessionStart hook, and `$observer-open`, `$observer-status`, `$observer-restart`, and `$observer-stop` | Can connect to local endpoints and may download, start, or manage Splunk Observability Studio. Local health and control checks may require narrow elevated access. The command skills use the default Splunk Observability Studio endpoint and do not follow, probe, or control custom MCP endpoints automatically. |
| Splunk publishers: `$splunk-detector-publish`, `$splunk-dashboard-publish`, and their deprecated `-sync` aliases | Can call Splunk Observability Cloud APIs and create confirmed detector or dashboard gaps when explicitly invoked with credentials that have the required permissions. |

Configured OTLP exporters can send telemetry to their configured destinations.
Repository edits, project commands, process control, and Splunk publishing
require explicit user intent and remain subject to the active host's approval
policy. Process control should require ownership evidence, and local listener
checks should use only the documented Splunk Observability Studio health
endpoint and ports.

## Local listener exposure

The managed Splunk Observability Studio instance is intended to bind
loopback-local endpoints, including `127.0.0.1:3000`, `127.0.0.1:4317`, and
`127.0.0.1:4318`. The UI, REST API, MCP endpoint, and OTLP receivers should not
be exposed on public interfaces by default.

The bundled MCP server config points to `http://127.0.0.1:3000/mcp`. Splunk
Observability Studio command skills do not automatically follow non-default MCP
endpoints; they verify or control only the default loopback instance at
`127.0.0.1:3000`.

Health checks use `http://127.0.0.1:3000/api/health`, not the MCP endpoint.
When either host needs a shell-based host-local health or control check, it
should request the narrow permission required by that host before probing. If
permission is denied or the endpoint cannot be verified from the available
context, report `sandbox-unverified`, not unhealthy.

## Managed bootstrap boundary

If the user trusts the SessionStart hook, the bootstrap may:

- download a Splunk Observability Studio release binary;
- verify it against `checksums.txt`;
- extract the release into plugin data;
- use the bundled plugin `.mcp.json` endpoint policy;
- start or reuse a local Splunk Observability Studio process unless the active
  host's bootstrap controls opt out of managed local startup.

Do not trust the hook if you do not want plugin-managed binary download,
checksum validation, or local process startup.

The editor extension also owns the Splunk Observability Studio version on its
configured managed port. If that port contains a verified `obstudio` running
another version, the extension may stop it and start the bundled version. It
revalidates the listener PID and executable before graceful or forced
termination; ambiguous owners or processes other than `obstudio` are left
running and reported as requiring recovery.

## User controls

Use your agent's plugin and MCP settings to disable the integration. Manage the
Splunk Observability Studio process separately with the product lifecycle
commands.
