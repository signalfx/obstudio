# Splunk Observability Studio user guide

Splunk Observability Studio gives coding agents an OpenTelemetry workflow and
provides a local runtime for inspecting the resulting traces, metrics, logs,
and validation evidence.

## Quick start

Download and extract the archive for your platform from
[GitHub Releases](https://github.com/signalfx/obstudio/releases/latest). This
guide uses the release binary as `./obstudio`; for a source build, use
`./build/obstudio` instead. Choose how Splunk Observability Studio will run.

### Agent-managed Splunk Observability Studio

Stop any running instance before installing in this mode; otherwise setup
reuses the detected instance. Then install the integration and let the agent
start Splunk Observability Studio:

```bash
cd obstudio_<version>_<os>_<arch>
./obstudio install --target=codex
```

Restart each configured agent and begin a new task. The generated MCP
configuration starts Splunk Observability Studio, so do not also launch a
standalone instance on the same ports.

### Shared standalone Splunk Observability Studio

Start one background instance, then connect integrations to its MCP endpoint:

```bash
cd obstudio_<version>_<os>_<arch>
./obstudio start
./obstudio install --target=codex --shared-url=http://127.0.0.1:17900/mcp
```

The shared instance must be running when you pass `--shared-url`. If it is
already running before installation, omitting the flag also lets setup detect
it automatically. Restart each configured agent and begin a new task.

To configure more than one target, replace `codex` with a comma-separated list.
Keep `--shared-url` when using a shared instance. Use this mode when multiple
configured agents may run concurrently because only one agent-started instance
can use the default ports at a time.

> **Concurrent agents must use `--shared-url` (HTTP), not stdio.** A stdio MCP
> integration spawns its own `obstudio`. Only the first such process binds the
> ports; every later one detects the already-running instance and exits cleanly
> (exit 0) *before* the MCP handshake, so a second stdio agent sees its server
> die at startup — silently. Point concurrent agents at the shared HTTP endpoint
> `http://127.0.0.1:17900/mcp` instead. The fixed `17900` port keeps that URL
> valid across restarts.

## Agent targets

Use `--target=windsurf` for Windsurf or Devin Desktop.

To connect every supported target to the running shared instance:

```bash
./obstudio install --target=codex,claude-code,cursor,kiro,windsurf,copilot --shared-url=http://127.0.0.1:17900/mcp
```

| Target | Skill command |
|---|---|
| `codex` | `$otel-audit` |
| `claude-code`, `cursor`, or `kiro` | `/otel-audit` |
| `windsurf` with Devin Local | `/otel-audit` |
| `windsurf` with legacy Cascade | `@otel-audit` |
| `copilot` | MCP only; no bundled skill |

The CLI `copilot` target above configures MCP only. **Copilot in VS Code 1.109+**
can instead discover all nine skills directly from the installed
[VS Code extension](../extension/README.md#github-copilot-in-vs-code), without
copying skills into the project or user profile. Use `/otel-audit` in a new
agent chat. Configure the local MCP server separately when using runtime tools.

The `windsurf` skill bundle is available to Devin Local and legacy Cascade; the
target configures Cascade automatically. For Devin Local, install the [Devin
CLI](https://docs.devin.ai/cli), make sure `devin` is on `PATH`, and add the
running Splunk Observability Studio:

```bash
devin mcp add -s user obstudio OBSERVER_BASE_URL/mcp
```

Replace `OBSERVER_BASE_URL` with the Splunk Observability Studio base URL and
keep the `/mcp` suffix.

Where supported, installation copies the bundled skills, `obstudio`, and
`weaver` into the selected agent's managed directory and updates its MCP
configuration.

## Using the skills

The normal workflow is
**audit → select → instrument → verify → configure → publish**.

- `$otel-audit` finds observability gaps without changing application code.
- `$otel-instrument` implements approved SDK, auto-instrumentation, and
  custom-signal changes.
- `$otel-verify` rechecks instrumentation and refreshes proof.
- `$splunk-dashboard` generates dashboard Terraform and a local preview.
- `$splunk-configure` generates detector and dashboard Terraform from audit
  evidence.
- `$splunk-detector-publish` compares detectors with Splunk and creates
  confirmed gaps.
- `$splunk-dashboard-publish` compares dashboards and charts with Splunk and
  creates confirmed gaps.

The skill names above use Codex syntax. Use the prefix shown for your target
and keep the skill name and arguments unchanged.

### Audit, select, and instrument

1. Run `$otel-audit` from the service root.
2. Open the returned audit report.
3. Select the findings to fix and copy the generated `$otel-instrument`
   command.
4. Run that command without changing its finding IDs, decisions, or service
   path.
5. Review the verification proof that `$otel-instrument` produces by default.

If you already know the finding IDs, you can select them directly:

```text
$otel-instrument --ids OTEL-001,OTEL-004
```

Run `$otel-verify` later whenever application or runtime evidence has changed.

| Stage | Generated files |
|---|---|
| Audit | `.observe/otel-audit.json` and the interactive `.observe/otel.html` report |
| Selection | `.observe/otel-selection.json`, including findings, decisions, and dependency-complete scope |
| Instrumentation | `.observe/otel-instrumentation.md`, `.observe/otel-instrumentation.json`, and `.observe/otel-instrumentation.html` |
| Verification | `.observe/otel-verify.md` and `.observe/otel-verify.json` |

Audit and instrumentation are separate reports. Their JSON and Markdown
artifacts remain in `.observe/`. See
[OTel Verify](https://github.com/signalfx/obstudio/blob/main/docs/otel-verify.md)
for direct verification guidance.

## Manage a shared Splunk Observability Studio

Skip this section when an agent starts Splunk Observability Studio from its MCP
configuration.

Start Splunk Observability Studio in the foreground:

```bash
./obstudio
```

Or manage a background process:

```bash
./obstudio start
./obstudio status
./obstudio restart
./obstudio stop
```

Installing a new build does not restart a running instance. The lifecycle
commands manage only the standalone background process, not foreground or
extension-managed instances.

The [Splunk Observability Studio guide](https://github.com/signalfx/obstudio/blob/main/observer/README.md)
documents endpoints, service exporter setup, views, validation, runtime
configuration, and APIs.

## Forward to Splunk

Splunk Observability Studio can forward metrics and traces to Observability Cloud
and logs to Splunk Platform. Received telemetry stays available locally.

- Open **Cloud** in Splunk Observability Studio.
- Each connection has its own export switch. Use the switch to pause or resume
  forwarding for that destination. Logs received while paused or disconnected
  stay local; enabling export sends new logs.
- Studio saves connection settings in `~/.obstudio/connections.json` and keeps
  tokens in the operating system credential store. Linux requires an unlocked
  Secret Service provider.
- Use **Edit token** to update a connection or **Disconnect** to forget its token.
- Saved connections and export preferences persist across restarts.
- If secure storage refuses a save, follow the setup link below the token field
  and restart Studio, or choose **Connect for this session** to keep the
  token in memory until Studio stops.
  Enter the token again after Studio restarts. Session mode leaves saved
  settings intact; restoring a saved connection requires access to secure storage.

### Observability Cloud metrics and traces

Enter the realm and an organization access token with ingest scope,
then select **Connect**. Metrics and traces share this connection and token.

### Secure token storage

Studio uses secure storage on the computer running the collector:

- **macOS:** Unlock the login keychain in [Keychain Access](https://support.apple.com/guide/keychain-access/welcome/mac).
- **Windows:** Use [Credential Manager](https://support.microsoft.com/en-us/windows/security/credential-manager-in-windows) in your Windows user session. If access is restricted, contact your system administrator.
- **Linux:** Run a Secret Service provider in the collector’s desktop D-Bus session with an unlocked login or default keyring. Your distribution provides installation instructions. For GNOME, see [Unlock your keyrings](https://help.gnome.org/seahorse/keyring-unlock.html).

Generating Terraform does not change Splunk; the publish skills described in
[Using the skills](#using-the-skills) show a live diff and require confirmation
before creating resources. Both generator skills write Terraform under
`.observe/terraform/`. `$splunk-dashboard` also writes
`.observe/dashboards.preview.json` for the local preview.

The local dashboard preview is approximate because SignalFlow runs in Splunk
Observability Cloud. Publisher skills require an API token with permission to
create their resources; an ingest-only token is not sufficient. Set
`SPLUNK_ACCESS_TOKEN` and, optionally, `SPLUNK_REALM` in the coding agent's
environment before starting the agent. The Cloud UI keeps its saved export
token in the operating system credential store.

### Splunk Platform logs (HEC)

1. **Prepare HEC.** Enable HTTP Event Collector and its token in Splunk. The
   destination index must exist, and the token must be allowed to write to it.
2. **Enter the connection.** In **Cloud → Splunk Platform**, paste the full
   **HEC endpoint** and **HEC token**, then enter the **Logs index**.
3. **Connect.** Studio sends one test log to check the endpoint, token and
   index before saving. A new connection enables export; editing an existing
   connection preserves its export switch.

**Endpoint format.** Use HTTPS with the path `/services/collector` or
`/services/collector/event`, without a query string or fragment. Plain HTTP
is supported only for loopback hosts, such as `127.0.0.1` or `localhost`.

| Deployment example | HEC endpoint |
|---|---|
| Splunk Cloud on AWS, port 443 | `https://http-inputs-<stack>.splunkcloud.com:443/services/collector` |
| Splunk Enterprise, port 8088 | `https://<hec-host>:8088/services/collector/event` |

Use the HEC hostname and port supplied for your deployment. Cloud hostnames
vary by hosting platform; Cloud free trials can use port 8088, and Enterprise
can use a custom port. See Splunk's [HEC endpoint reference](https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-cloud-platform/set-up-and-use-http-event-collector-in-splunk-web).

- **Source.** The form retains the saved source or defaults to `otel`;
  sourcetype defaults to `otel:logs`. These fields are not shown in the form.
- **TLS.** New endpoints verify the server certificate. Editing the same
  endpoint retains its saved TLS setting. The form has no option to skip
  certificate verification.
- **Forwarding.** Only logs received while export is enabled are forwarded,
  apart from the explicit connection test. Paused or disconnected logs stay
  local and are not replayed on resume. Pause, Disconnect and destination
  changes stop pending remote sends. Local retention is bounded.
- **Find logs.** Use **Search index** when Studio can identify the Splunk Cloud
  Web address from an HTTPS HEC endpoint on port 443 or 8088. For Enterprise or
  other endpoints, open Splunk Web and search the index manually. Accepted
  counts show HEC acceptance; search results confirm that events were indexed.

Replace `your-index` with the configured index and use a recent time range:

```spl
index="your-index" earliest=-15m
```

Add `source="otel"` when using the default source.

#### HEC troubleshooting

- **Edit token.** In **Cloud → Splunk Platform**, select **Edit token** to
  replace a rejected token, then select **Save changes**.
- **Export counts.** Counts show logs accepted by HEC. Search Splunk to confirm
  that the logs are searchable.
- **Paused export.** Logs stay local while export is paused. Enabling export
  sends new logs; it does not replay logs collected while paused.

For token permissions, indexes, endpoints and certificate setup, follow Splunk's
HEC guidance for [Splunk Cloud Platform](https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-cloud-platform/set-up-and-use-http-event-collector-in-splunk-web)
or [Splunk Enterprise](https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-enterprise/set-up-and-use-http-event-collector-in-splunk-web).

## Troubleshooting

- **An agent cannot find skills or MCP:** restart the agent and open a new task.
  Existing processes keep their startup configuration.
- **A configured local instance does not connect:** confirm that it is reachable
  and its version is compatible with the client.

For runtime startup, telemetry, or validation problems, see the Splunk
Observability Studio [troubleshooting section](https://github.com/signalfx/obstudio/blob/main/observer/README.md#troubleshooting).
For editor-managed issues, see the extension's
[troubleshooting section](https://github.com/signalfx/obstudio/blob/main/extension/README.md#troubleshooting).

## Security and data handling

Splunk Observability Studio stores telemetry in bounded local memory.

For the bundled plugin, review its
[security](https://github.com/signalfx/obstudio/blob/main/plugins/obstudio/SECURITY.md)
and [privacy](https://github.com/signalfx/obstudio/blob/main/plugins/obstudio/PRIVACY.md)
documentation.

## Resources

- [Splunk Observability Studio guide](https://github.com/signalfx/obstudio/blob/main/observer/README.md)
- [Prompt examples](examples.md)
- [Skill sources](https://github.com/signalfx/obstudio/tree/main/skills)
- [Contributing](https://github.com/signalfx/obstudio/blob/main/CONTRIBUTING.md)
