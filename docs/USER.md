# Observability Studio user guide

Observability Studio gives coding agents an OpenTelemetry workflow and provides
a local Observer for inspecting the resulting traces, metrics, logs, and
validation evidence.

## Quick start

Download and extract the archive for your platform from
[GitHub Releases](https://github.com/signalfx/obstudio/releases/latest). This
guide uses the release binary as `./obstudio`; for a source build, use
`./build/obstudio` instead. Choose how Observer will run.

### Agent-managed Observer

Stop any running Observer before installing in this mode; otherwise setup
reuses the detected Observer. Then install the integration and let the agent
start its own Observer:

```bash
cd obstudio_<version>_<os>_<arch>
./obstudio install --target=codex
```

Restart each configured agent and begin a new task. The generated MCP
configuration starts Observer, so do not also launch a standalone Observer on
the same ports.

### Shared standalone Observer

Start one background Observer, then connect integrations to its MCP endpoint:

```bash
cd obstudio_<version>_<os>_<arch>
./obstudio start
./obstudio install --target=codex --shared-url=http://127.0.0.1:3000/mcp
```

The shared Observer must be running when you pass `--shared-url`. If it is
already running before installation, omitting the flag also lets setup detect
it automatically. Restart each configured agent and begin a new task.

To configure more than one target, replace `codex` in the command for your
chosen model with a comma-separated list such as
`codex,claude-code,cursor,kiro,windsurf,copilot`. Keep the `--shared-url` option
when using the shared model. Use that model when multiple configured agents may
run concurrently because only one agent-started Observer can use the default
ports at a time.

## Agent targets

Use `--target=windsurf` for Windsurf or Devin Desktop.

| Target | Skill command |
|---|---|
| `codex` | `$otel-audit` |
| `claude-code`, `cursor`, or `kiro` | `/otel-audit` |
| `windsurf` with Devin Local | `/otel-audit` |
| `windsurf` with legacy Cascade | `@otel-audit` |
| `copilot` | MCP only; no bundled skill |

The `windsurf` skill bundle is available to Devin Local and legacy Cascade; the
target configures Cascade automatically. For Devin Local, install the [Devin
CLI](https://docs.devin.ai/cli), make sure `devin` is on `PATH`, and add the
running Observer:

```bash
devin mcp add -s user obstudio OBSERVER_BASE_URL/mcp
```

Replace `OBSERVER_BASE_URL` with the Observer base URL and keep the `/mcp`
suffix.

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

## Manage a shared Observer

Skip this section when an agent starts Observer from its MCP configuration.

Start Observer in the foreground:

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

Installing a new build does not restart a running Observer. The lifecycle
commands manage only the standalone background process, not foreground or
extension-managed instances.

The [Observer guide](https://github.com/signalfx/obstudio/blob/main/observer/README.md)
documents endpoints, service exporter setup, views, validation, runtime
configuration, and APIs.

## Forward to Splunk Observability Cloud

Observer can forward received traces and metrics while keeping the Observer UI
available. Logs remain local.

Create `~/.obstudio/env` with these values:

```dotenv
OBSTUDIO_SPLUNK_METRICS_EXPORT=true
OBSTUDIO_SPLUNK_TRACES_EXPORT=true
SPLUNK_REALM=<your-realm>
SPLUNK_ACCESS_TOKEN=<org-ingest-token>
```

Protect the file, then restart a managed background Observer. If Observer is
running in the foreground, stop it and launch it again instead.

```bash
chmod 600 ~/.obstudio/env
./obstudio restart
```

The default env file is loaded automatically when present. Shell environment
variables take precedence; use `./obstudio --env-file <path>` for another file.
Forwarding requires an organization access token with ingest scope.

Generating Terraform does not change Splunk; the publish skills described in
[Using the skills](#using-the-skills) show a live diff and require confirmation
before creating resources. Both generator skills write Terraform under
`.observe/terraform/`. `$splunk-dashboard` also writes
`.observe/dashboards.preview.json` for the local preview.

The local dashboard preview is approximate because SignalFlow runs in Splunk
Observability Cloud. Publisher skills require an API token with permission to
create their resources; an ingest-only token is not sufficient.

## Troubleshooting

- **An agent cannot find skills or MCP:** restart the agent and open a new task.
  Existing processes keep their startup configuration.
- **A configured local Observer does not connect:** confirm that it is
  reachable and its version is compatible with the client.

For runtime startup, telemetry, or validation problems, see the Observer
[troubleshooting section](https://github.com/signalfx/obstudio/blob/main/observer/README.md#troubleshooting).
For editor-managed issues, see the extension's
[troubleshooting section](https://github.com/signalfx/obstudio/blob/main/extension/README.md#troubleshooting).

## Security and data handling

Observer stores telemetry in bounded local memory.

For the bundled plugin, review its
[security](https://github.com/signalfx/obstudio/blob/main/plugins/obstudio/SECURITY.md)
and [privacy](https://github.com/signalfx/obstudio/blob/main/plugins/obstudio/PRIVACY.md)
documentation.

## Resources

- [Observer guide](https://github.com/signalfx/obstudio/blob/main/observer/README.md)
- [Prompt examples](examples.md)
- [Skill sources](https://github.com/signalfx/obstudio/tree/main/skills)
- [Contributing](https://github.com/signalfx/obstudio/blob/main/CONTRIBUTING.md)
