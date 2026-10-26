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
| Splunk publishers: `$splunk-detector-publish` and `$splunk-dashboard-publish` | Can call Splunk Observability Cloud APIs and create confirmed detector or dashboard gaps when explicitly invoked with credentials that have the required permissions. |

Configured OTLP exporters can send telemetry to their configured destinations.
Repository edits, project commands, process control, and Splunk publishing
require explicit user intent and remain subject to the active host's approval
policy. Process control should require ownership evidence, and local listener
checks should use only the documented Splunk Observability Studio health
endpoint and ports.

## Local listener exposure

The managed Splunk Observability Studio instance is intended to bind
loopback-local endpoints, including `127.0.0.1:17900`, `127.0.0.1:4317`, and
`127.0.0.1:4318`. The UI, REST API, MCP endpoint, and OTLP receivers should not
be exposed on public interfaces by default.

The bundled MCP server config points to `http://127.0.0.1:17900/mcp`. Splunk
Observability Studio command skills do not automatically follow non-default MCP
endpoints; they verify or control only the default loopback instance at
`127.0.0.1:17900`.

Health checks use `http://127.0.0.1:17900/api/health`, not the MCP endpoint.
When either host needs a shell-based host-local health or control check, it
should request the narrow permission required by that host before probing. If
permission is denied or the endpoint cannot be verified from the available
context, report `sandbox-unverified`, not unhealthy.

## Managed bootstrap boundary

The SessionStart hook requires Python 3 on `PATH` (`python3`, `python`, or
Windows `py -3`) to run the shared bootstrap. If no supported interpreter is
available, the hook exits with code 2 and the managed runtime is not prepared.

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

## Reviewer summary: what runs, what is downloaded, which credentials are read

This section answers directory-review findings (`MCP_FORWARDS_CREDENTIAL_ENV`
and `RUNTIME_FETCH_EXEC`) from the repository alone. Nothing leaves the machine
by default: every network call the plugin code makes goes to loopback, except
the one-time release download from GitHub described below.

### What runs locally

| Component | What it does |
|---|---|
| `hooks/bootstrap_claude.cjs` and `hooks/bootstrap_obstudio.py` (SessionStart) | Prepare and start the local Studio process, then exit. |
| Studio binary (`obstudio`) | Started by the hook with `HOST=127.0.0.1`. Serves the UI, REST API, MCP, and OTLP receivers on loopback only. |
| `.mcp.json` | One HTTP MCP server at `http://127.0.0.1:17900/mcp`. It has no `env`, no `headers`, and no `${...}` expansion, so it forwards no credential. |
| `.claude-plugin/plugin.json` | Points at the hook and `.mcp.json`. It declares no `env` or `userConfig` and carries no secrets. |
| `skills/**` | Markdown instructions that the host agent reads. Any command they mention runs only if the user approves it under the host's own policy. |
| `skills/otel-instrument/scripts/resolve_ao_resources.py` | Resolves or creates an AO project and agent stream through the installed `splunk_ao` SDK or a loopback-only Studio API origin. It downloads nothing and executes nothing: it imports no `subprocess`, never calls `urlopen`, and never uses `exec`, `eval`, or `__import__`. Its only write is an evidence JSON file named by `--output`. |

### What is downloaded, and how it is verified

- Studio release zip (bootstrap hook). Fetched from
  `https://github.com/signalfx/obstudio/releases` using the release matching the
  plugin version, together with that release's `checksums.txt`. Before anything
  is extracted or executed, the hook checks the zip entries for path traversal and
  verifies the archive SHA-256 against `checksums.txt`. If the pinned release is
  not found, the hook falls back to the latest release and records
  `runtimePinFallback` in its state. Pinning the checksum inside the plugin
  itself, so it no longer comes from the same origin as the archive, is tracked
  in BORN-286.
- OpenTelemetry Java agent (documentation only). `java.md` shows a template for
  the user's build or setup step. It requires an explicit pinned version from
  Maven Central and a SHA-256 the user records for that version, checked before
  the JVM loads the jar, and it forbids `latest` URLs. The plugin ships no
  version or hash of its own and never runs this command.
- No other plugin code downloads anything. Skill text that mentions package
  installation (`pip`, `npm`, Maven, Gradle) describes dependency changes made
  in the user's own project under the host's approval flow.

### Which credentials are read, and where they go

- The hook reads no credentials. The environment variables it reads are
  `OBSTUDIO_HEALTH_URL`, `OBSTUDIO_PLUGIN_HOST`, `PLUGIN_ROOT`,
  `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, `PLUGIN_DATA`,
  `OBSTUDIO_HOOK_EXECUTION_DEADLINE_SECONDS`,
  `OBSTUDIO_TOKEN_TELEMETRY_STATE_PATH`, and `CLAUDE_CONFIG_DIR`.
- `CLAUDE_CONFIG_DIR` is used only to locate a plugin data directory
  (`<config dir>/plugins/data/obstudio`, default `~/.claude`). The hook reads no
  file from that directory for configuration or secrets.
- Files read: the plugin manifest, `.mcp.json`, `~/.obstudio/token-telemetry.json`
  (repository-correlation settings, no credentials), and for Codex only
  `~/.codex/config.toml`.
- The repository-correlation event is POSTed only to a loopback
  `/v1/logs` endpoint. The hook rejects any other host or path.
- The Studio child process receives an allowlisted environment (`PATH`, `HOME`,
  temp and locale variables, proxy and CA-bundle variables, and `SPLUNK_*`,
  `SIGNALFX_*`, `OBSTUDIO_*`, `OTLP_*`). It does not inherit unrelated variables
  such as `ANTHROPIC_*`, `AWS_*`, `OPENAI_*`, or `GITHUB_TOKEN`.
- `resolve_ao_resources.py` reads `SPLUNK_AO_PROJECT`, `SPLUNK_AO_PROJECT_ID`,
  `SPLUNK_AO_AGENT_STREAM`, and `SPLUNK_AO_AGENT_STREAM_ID` (resource names, not
  secrets). The `splunk_ao` SDK reads its own `SPLUNK_AO_*` settings and sends
  them only to the user's Splunk organization. The Studio API path sends the
  public marker header `X-SF-Token: local-gateway`, not a real secret, and only
  to loopback.
- `OTEL_EXPORTER_OTLP_HEADERS` and `OTEL_EXPORTER_OTLP_LOGS_HEADERS` appear in
  the Python instrumentation guidance. The generated code only checks whether
  they are set so it can refuse to export logs to the local receiver. It never
  copies, logs, or forwards their values.
- The Splunk publisher skills use the user's own Splunk Observability Cloud
  credentials, supplied by the user, and send them only to that organization's
  API.

## User controls

Use your agent's plugin and MCP settings to disable the integration. Manage the
Splunk Observability Studio process separately with the product lifecycle
commands.

## Reporting a security concern

The plugin is maintained by the Splunk Observability Studio team at Cisco.
Report suspected vulnerabilities or other security concerns by email to
bkovuri@cisco.com. Include the plugin version, the host (Codex or Claude Code),
and steps to reproduce. Please do not open a public issue for a vulnerability
that has not been fixed.
