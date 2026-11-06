# Splunk Observability Studio plugin privacy

This document describes the current data flows for the `obstudio` plugin when
used with Codex or Claude Code. The host, model provider, package managers,
operating system, and user-invoked tools have their own privacy behavior.

## What this plugin contains

| Capability | Data and network behavior |
|---|---|
| Core workflow skills: `$otel-audit`, `$otel-instrument`, `$otel-verify`, `$splunk-configure`, and `$splunk-dashboard` | Can read or edit repository files and generate local reports or Terraform. They do not manage a background Splunk Observability Studio instance or create live Splunk resources. |
| Splunk Observability Studio and MCP controls: the bundled MCP configuration, SessionStart hook, and `$observer-open`, `$observer-status`, `$observer-restart`, and `$observer-stop` | Interact with local endpoints and may download, start, or manage Splunk Observability Studio. Health or control checks may require narrow elevated access. The command skills use the default Splunk Observability Studio endpoint and do not follow, probe, or control custom MCP endpoints automatically. |
| Splunk publishers: `$splunk-detector-publish` and `$splunk-dashboard-publish` | Call Splunk Observability Cloud APIs only when explicitly invoked. They can create dashboards or detectors and require credentials with the corresponding API permissions. |

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

## Bootstrap and local Splunk Observability Studio

When the SessionStart hook is reviewed and trusted, it may bootstrap the managed
Splunk Observability Studio runtime. The bootstrap may download a release
binary, verify `checksums.txt`, extract the release into plugin data, and start
a local process.

When token telemetry is enabled and no repository-correlation mode has been
recorded, correlation defaults to `path`; `off` disables it and `name` omits
filesystem paths. The SessionStart hook sends one content-free OTLP log to the
configured loopback Splunk Observability Studio instance. In `name` mode it
contains the provider, session or task identity, hook type, and repository
name. In `path` mode it additionally contains the canonical repository path and
active workspace path.
It does not contain prompts, tool arguments, tool results, or file contents.
The hook rejects non-loopback correlation endpoints, and a failed correlation
send does not prevent the host session from starting.

These modes govern the correlation hook and normalized token-usage results.
Raw provider telemetry is preserved and may independently contain fields such
as a provider-emitted working directory; use the provider's telemetry controls
when raw-signal collection must also be disabled.

The managed instance may bind host-local endpoints such as:

- `http://127.0.0.1:17900/`
- `http://127.0.0.1:17900/api/health`
- `http://127.0.0.1:17900/mcp`
- `127.0.0.1:4317`
- `127.0.0.1:4318`

These endpoints are intended for local development. Disable managed startup in
the plugin to prevent it from starting Splunk Observability Studio.
Disconnecting the MCP integration does not stop an instance that is already
running.

Splunk Observability Studio command skills do not automatically follow a
non-default MCP endpoint. They verify or control only the default loopback
instance at `127.0.0.1:17900`.

## Local data

The skills may create local `.observe/` reports, JSON sidecars, Terraform
files, and temporary local report servers bound to `127.0.0.1` for reviewing
generated HTML reports. Markdown, JSON, and Terraform artifacts remain local
files unless the user explicitly shares them or invokes tooling that sends them
elsewhere.

OTLP data received by the local Splunk Observability Studio instance stays local
unless the user configures forwarding or export endpoints such as Splunk
Observability Cloud ingest or another OTLP destination.

Provider usage records, completed task accounting, token metrics, and optional
repository-correlation events are retained in separate bounded in-memory rings.
They are removed by ring overwrite, an explicit clear, or process exit.

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
`http://127.0.0.1:17900/api/health`, not the MCP endpoint. Control or listener
checks should be limited to the default Splunk Observability Studio loopback ports:
`127.0.0.1:17900`, `127.0.0.1:4317`, and `127.0.0.1:4318`.

If elevated access is denied or the endpoint cannot be verified from the
available context, report `sandbox-unverified`; it does not prove that the
Splunk Observability Studio is unhealthy.

If a project command, package manager, test runtime, OTLP exporter, or user
configuration performs network access, that traffic belongs to the selected
tooling or project configuration, not to plugin telemetry code.

## Outbound network flows

The flows below are the plugin and Studio code paths that contact a remote
host. Nothing here is analytics, telemetry about the plugin itself, or an
update check; none of that was found.

### Release download (bootstrap hook)

- Destination: `github.com/signalfx/obstudio/releases` (the release zip and its
  `checksums.txt`) and, when the pinned release is not found,
  `api.github.com/repos/signalfx/obstudio/releases/latest`.
- Trigger: the SessionStart hook, when the managed runtime is missing or does
  not match the plugin version and the hook is trusted.
- Data sent: plain GET requests with no user payload. GitHub sees the source IP
  address and normal HTTP headers.
- Opt-out: do not trust the hook, or disable managed startup.

### Splunk Observability Cloud Free Edition signup

- Destination: `www.splunk.com/api/bin/user/location` (GET, no body; splunk.com
  sees the source IP address) and `www.splunk.com/api/bin/observability/sfx-signup`
  (POST).
- Trigger: only after the user explicitly consents to create a free account.
- Data sent: the first name, last name, and email the user supplies, an optional
  region, and terms acceptance, plus the country, state, city, and postal code
  returned by the location lookup. Fixed fields are also sent: title
  `Developer`, a default company name, an empty phone number, and
  `MarketingOptIn` set to 0.
- Persistence: the plugin package does not store these values.
- Opt-out: decline or do not invoke the signup skill.

### Connecting a Splunk Observability Cloud organization

- Destination: the organization URL the user enters, the ingest endpoint
  `ingest.<realm>.observability.splunkcloud.com`, and the app endpoint
  `app.<realm>.observability.splunkcloud.com` (used by the Agent Observability
  proxy).
- Trigger: the user types the URL and access token into the Cloud tab of the
  local Studio UI. They are never entered in chat.
- Data sent: an unauthenticated GET to the entered URL. The token is sent as the
  `X-SF-Token` header to the ingest and app endpoints. The connection test to
  ingest has an empty body. After that, the user's metrics and traces are
  exported to ingest while the Observability Cloud export toggle is enabled.
- Credential storage: the token is stored in the operating system credential
  store (for example macOS Keychain, Windows Credential Manager, or the Linux
  Secret Service over D-Bus). `~/.obstudio/connections.json` holds only a
  reference to it, plus the realm, enable flags, and endpoints. There is no
  plaintext fallback: if the credential store refuses the token, the connection
  is session-only, kept in memory, and lost when Studio restarts.
- Opt-out: do not connect an organization, turn the export toggle off, or
  disconnect in the Cloud tab.

### Splunk Platform HEC log delivery

- Destination: the HTTP Event Collector URL the user enters, an HTTPS URL whose
  path is `/services/collector` or `/services/collector/event`. A loopback host
  may use HTTP.
- Trigger: the user enters the URL, token, and index in the Cloud tab and
  enables log export. This is off by default and is a separate toggle from
  Observability Cloud metrics and traces export; either can be on without the
  other. Connecting sends one test log event.
- Data sent: after the test, OTLP logs received by the local Studio instance are
  exported as HEC events with an `Authorization: Splunk <token>` header, to the
  chosen index, with sourcetype `otel:logs` and source `otel` unless the user
  changes them. Log bodies and attributes are sent as received, so they can
  contain whatever the user's applications log.
- Credential storage: the HEC token is stored in the operating system
  credential store, with the same reference and session-only behavior as above.
- TLS: an optional setting skips certificate verification for self-signed
  Splunk certificates. It is off by default.
- Opt-out: do not configure it, turn the logs toggle off, or disconnect.

### Access tokens from the environment

Studio no longer reads `SPLUNK_ACCESS_TOKEN` or `SPLUNK_REALM`. The SessionStart
hook does not pass `SPLUNK_*` or `OBSTUDIO_SPLUNK_*` variables to the Studio
process, and the `obstudio` managed lifecycle no longer records them in
`~/.obstudio/managed-observer.json`.

<!-- TODO(confirm): whether an older managed-observer.json written by a previous
release can still contain SPLUNK_ACCESS_TOKEN until it is rewritten, and whether
Studio scrubs it. Also confirm Studio restores a stored connection from its
credential-store reference after restart. -->

## Privacy policy and contact

The privacy policy for this plugin is the
[Cisco Online Privacy Statement](https://www.cisco.com/c/en/us/about/legal/privacy-full.html).
For questions about the data flows in this document, email
bkovuri@cisco.com.
