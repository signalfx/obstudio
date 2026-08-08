# Obstudio Codex Plugin Privacy

This document describes the current data flows for the `obstudio` Codex plugin.
Codex, model providers, package managers, the operating system, and
user-invoked tools have their own privacy behavior.

## What This Plugin Contains

The plugin contains three capability groups.

Core workflow skills:

- `$obstudio-help`
- `$otel-audit`
- `$otel-instrument`
- `$otel-verify`
- `$splunk-configure`
- `$splunk-dashboard`

These can read and write repo files through skills like instrumentation and can
generate local reports and Terraform. They do not manage a local background
Observer process and do not call live Splunk APIs to create resources.

Observer and MCP controls:

- MCP server config for `http://127.0.0.1:3000/mcp`
- SessionStart bootstrap hook, if managed startup is kept enabled
- `$observer-open`
- `$observer-status`
- `$observer-restart`
- `$observer-stop`

These interact with host-local endpoints, may download/start/manage the local
Observer, and may need narrow elevated/outside-sandbox access for localhost
health or control checks. Command skills are limited to the default loopback
Observer and do not probe or control custom MCP endpoints automatically.

Splunk publish skills:

- `$splunk-detector-publish`
- `$splunk-dashboard-publish`
- `$splunk-sync` deprecated alias
- `$splunk-dashboard-sync` deprecated alias

These call Splunk Observability Cloud APIs when explicitly invoked, can create
live dashboard or detector resources, and require Splunk credentials with the
required API permissions.

## What the Plugin Does Not Add

- The plugin package does not add analytics or usage telemetry code of its own.
- The plugin package does not automatically upload workspace contents to
  Splunk Observability Cloud.
- The plugin package does not publish dashboards or detectors to Splunk unless
  the user explicitly invokes the publish skills with usable Splunk
  credentials.

Codex may still send prompts, file context, tool output, and user-approved
command results according to Codex's own settings and product behavior.

## Bootstrap and Local Observer

When the SessionStart hook is reviewed and trusted, Obstudio may bootstrap the
managed Observer. The bootstrap may download an Obstudio release binary,
verify `checksums.txt`, extract the release into plugin data, and start a local
Observer process.

The managed Observer may bind host-local endpoints such as:

- `http://127.0.0.1:3000/`
- `http://127.0.0.1:3000/api/health`
- `http://127.0.0.1:3000/mcp`
- `127.0.0.1:4317`
- `127.0.0.1:4318`

These endpoints are intended for local development. Disable the hook or the
Obstudio MCP server if you do not want Codex to manage or connect to the local
Observer.

Users may configure a non-default Obstudio MCP URL in Codex, but Observer
command skills do not automatically follow that custom endpoint. They report
the custom MCP URL when detected, then verify or control only the default
loopback Observer at `127.0.0.1:3000`.

## Local Data

The skills may create local `.observe/` reports, JSON sidecars, Terraform
files, and temporary local report servers bound to `127.0.0.1` for reviewing
generated HTML reports. Markdown, JSON, and Terraform artifacts remain local
files unless the user explicitly shares them or invokes tooling that sends them
elsewhere.

OTLP data received by the local Observer stays local unless the user configures
forwarding or export endpoints such as Splunk Observability Cloud ingest or
another OTLP destination.

## External Calls

The plugin can run project commands selected by the user or required by the
invoked skill workflow. Package managers, tests, application runtimes, and
configured exporters may perform their own network requests.

The Splunk publish skills call Splunk Observability Cloud APIs only when the
user explicitly invokes them and provides usable credentials. Those skills
should show the live diff and confirmed gaps before creating dashboards,
charts, or detectors.

Outside-sandbox localhost checks are optional, one-time verification or control
probes. They require user approval when Codex needs elevated execution to reach
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
