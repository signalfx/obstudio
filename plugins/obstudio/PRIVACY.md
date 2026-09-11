# Observability Studio plugin privacy

This document describes the current data flows for the `obstudio` plugin when
used with Codex or Claude Code. The host, model provider, package managers,
operating system, and user-invoked tools have their own privacy behavior.

## What this plugin contains

| Capability | Data and network behavior |
|---|---|
| Core workflow skills: `$otel-audit`, `$otel-instrument`, `$otel-verify`, `$splunk-configure`, and `$splunk-dashboard` | Can read or edit repository files and generate local reports or Terraform. They do not manage a background Observer or create live Splunk resources. |
| Observer and MCP controls: the bundled MCP configuration, SessionStart hook, and `$observer-open`, `$observer-status`, `$observer-restart`, and `$observer-stop` | Interact with local endpoints and may download, start, or manage Observer. Health or control checks may require narrow elevated access. The command skills use the default Observer endpoint and do not follow, probe, or control custom MCP endpoints automatically. |
| Splunk publishers: `$splunk-detector-publish`, `$splunk-dashboard-publish`, and their deprecated `-sync` aliases | Call Splunk Observability Cloud APIs only when explicitly invoked. They can create dashboards or detectors and require credentials with the corresponding API permissions. |

## What the plugin does not add

- The plugin package does not enable token telemetry or repository correlation
  unless the user explicitly opts in with `obstudio token-telemetry enable`.
- The plugin package does not automatically upload workspace contents to
  Splunk Observability Cloud.
- The plugin package does not publish dashboards or detectors to Splunk unless
  the user explicitly invokes the publish skills with usable Splunk
  credentials.

Codex or Claude Code may still send prompts, file context, tool output, and
user-approved command results according to that host's settings and product
behavior.

## Bootstrap and local Observer

When the SessionStart hook is reviewed and trusted, Observability Studio may
bootstrap the managed Observer. The bootstrap may download an Observability
Studio release binary, verify `checksums.txt`, extract the release into plugin
data, and start a local Observer process.

When token telemetry is enabled and no repository-correlation mode has been
recorded, correlation defaults to `path`; `off` disables it and `name` omits
filesystem paths. The SessionStart hook sends one content-free OTLP log to the
configured loopback Observer. In `name` mode it contains the provider,
session or task identity, hook type, and repository name. In `path` mode it
additionally contains the canonical repository path and active workspace path.
It does not contain prompts, tool arguments, tool results, or file contents.
The hook rejects non-loopback correlation endpoints, and a failed correlation
send does not prevent the host session from starting.

These modes govern the correlation hook and normalized token-usage results.
Raw provider telemetry is preserved and may independently contain fields such
as a provider-emitted working directory; use the provider's telemetry controls
when raw-signal collection must also be disabled.

The managed Observer may bind host-local endpoints such as:

- `http://127.0.0.1:3000/`
- `http://127.0.0.1:3000/api/health`
- `http://127.0.0.1:3000/mcp`
- `127.0.0.1:4317`
- `127.0.0.1:4318`

These endpoints are intended for local development. Disable managed startup in
the plugin to prevent it from starting Observer. Disconnecting the MCP
integration does not stop an Observer process that is already running.

Observer command skills do not automatically follow a non-default MCP endpoint.
They verify or control only the default loopback Observer at
`127.0.0.1:3000`.

## Local data

The skills may create local `.observe/` reports, JSON sidecars, Terraform
files, and temporary local report servers bound to `127.0.0.1` for reviewing
generated HTML reports. Markdown, JSON, and Terraform artifacts remain local
files unless the user explicitly shares them or invokes tooling that sends them
elsewhere.

OTLP data received by the local Observer stays local unless the user configures
forwarding or export endpoints such as Splunk Observability Cloud ingest or
another OTLP destination.

Provider usage records, completed task accounting, token metrics, and optional
repository-correlation events are retained in separate bounded in-memory rings.
They are removed by ring overwrite, explicit Observer clear, or process exit.

## External calls

The plugin can run project commands selected by the user or required by the
invoked skill workflow. Package managers, tests, application runtimes, and
configured exporters may perform their own network requests.

The Splunk publish skills call Splunk Observability Cloud APIs only when the
user explicitly invokes them and provides usable credentials. Those skills
should show the live diff and confirmed gaps before creating dashboards,
charts, or detectors.

Host-local checks are optional, one-time verification or control probes. Codex
and Claude Code may prompt for user approval before a shell command accesses
host-local endpoints. Health checks use
`http://127.0.0.1:3000/api/health`, not the MCP endpoint. Control or listener
checks should be limited to the default loopback Observer ports:
`127.0.0.1:3000`, `127.0.0.1:4317`, and `127.0.0.1:4318`.

If elevated access is denied or the endpoint cannot be verified from the
available context, report `sandbox-unverified`; it does not prove that the
Observer is unhealthy.

If a project command, package manager, test runtime, OTLP exporter, or user
configuration performs network access, that traffic belongs to the selected
tooling or project configuration, not to plugin telemetry code.
