# Splunk Observability Studio

Give your coding agent an evidence-backed OpenTelemetry workflow, then inspect
the proof without leaving your editor. The extension bundles agent skills and a
local Observer for traces, metrics, logs, services, validation, dashboard
previews, and optional Splunk Observability Cloud export.

![Audit, selection, instrumentation, and verification workflow](assets/marketplace-skills-workflow.gif)

## Install

| Editor | Install from |
|---|---|
| Cursor | [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) |
| Kiro | [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) |
| Visual Studio Code 1.82+ | [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=Splunk.observability-studio) |
| Windsurf / Devin Desktop | [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) |

After installing:

1. Run **Splunk Observability Studio: Open Observer**.
2. Accept the detected agent-integration prompt, or run the matching enable
   command from the Command Palette.
3. Fully restart the agent and start a new task so it reloads its skills and
   local MCP connection.

The extension provides the Cursor, Kiro, Claude Code, and Codex commands below.
For Copilot or Windsurf, download and extract the standalone CLI from
[GitHub Releases](https://github.com/signalfx/obstudio/releases/latest), then
run the listed command from that directory.

- **Cursor:** run **Enable Cursor Integration**.
- **Kiro:** run **Enable Kiro Integration**.
- **Claude Code in VS Code:** run **Enable Claude Code Integration**.
- **Codex in VS Code:** run **Enable Codex Integration**.
- **GitHub Copilot:** run `./obstudio install --target=copilot` from the
  extracted release. This target configures MCP only.
- **Windsurf or Devin Desktop:** run
  `./obstudio install --target=windsurf` from the extracted release.

For Devin Local, also add the running Observer. Copy the base URL from
**Observer Status** and keep the `/mcp` suffix:

```bash
devin mcp add -s user obstudio \
  OBSERVER_BASE_URL/mcp
```

The `windsurf` target configures MCP for legacy Cascade. On Windows, enable
Developer Mode or use an elevated terminal so the installer can create skill
links.

## Run the workflow

Enter skill commands in your coding-agent chat, not in a terminal:

| Agent | Command form |
|---|---|
| Codex | `$otel-audit` |
| Claude Code, Cursor, Kiro, or Devin Local | `/otel-audit` |
| Legacy Cascade | `@otel-audit` |

The skills form one guided path:
**audit → select → instrument → verify → configure → publish**.

- `$otel-audit` finds observability gaps without changing application code.
- `$otel-instrument` implements approved SDK, auto-instrumentation, and
  custom-signal changes.
- `$otel-verify` rechecks instrumentation with project, code, and optional
  local OTLP proof.
- `$splunk-dashboard` generates dashboard Terraform and previews it against
  local telemetry.
- `$splunk-configure` generates evidence-backed detector and dashboard
  Terraform.
- `$splunk-detector-publish` compares detector specs with Splunk and creates
  confirmed gaps.
- `$splunk-dashboard-publish` compares dashboards and charts with Splunk and
  creates confirmed gaps.
- `$connect-splunk-observability-cloud` opens the Cloud view for secure
  connection setup.
- `$create-splunk-free-account` submits a consent-gated Free Edition signup.

The skill names above use Codex `$` syntax. Replace `$` with `/` or `@` for the
agents shown above; keep the skill name and arguments unchanged.

Start with the audit:

1. Run the audit command shown for your agent: `$otel-audit`, `/otel-audit`, or
   `@otel-audit`.
2. Open the returned local report and approve the findings to address.
3. Run its generated `otel-instrument` command without changing the finding
   IDs, decisions, or service path.
4. Review the verification that runs by default.
5. Generate Terraform, inspect the live diff, and publish only confirmed gaps.

The audit and instrumentation reports are separate, self-contained HTML files.
The skills return tokenized local links and never open them automatically.
Structured JSON and Markdown reports remain in the service's `.observe/`
directory.

## Inspect the proof

An extension-managed Observer exposes these default endpoints:

| Service | Default endpoint |
|---|---|
| Observer UI and REST API | `http://127.0.0.1:3000` |
| MCP | `http://127.0.0.1:3000/mcp` |
| OTLP/HTTP | `http://127.0.0.1:4318` |
| OTLP/gRPC | `127.0.0.1:4317` |

Observer includes these views:

| View | What it shows |
|---|---|
| **Overview** | Instrumentation score, audit findings, and workflow shortcuts. |
| **Services** | Trace and span volume, errors, and client/server duration by service. |
| **Traces** | Waterfalls, dependency latency, errors, attributes, and agent flow. |
| **Metrics** | Series, dimensions, retained points, and resource metadata. |
| **Logs** | Structured messages, severity, attributes, and trace correlation. |
| **Validation** | OpenTelemetry semantic-convention findings across all signals. |
| **Dashboards** | An approximate local-data preview of generated Terraform. |
| **Cloud** | Optional Splunk Observability Cloud connection and export controls. |

### Trace a request

Open a trace to inspect its waterfall and slow dependencies.

![Checkout trace waterfall](assets/marketplace-traces-tab.gif)

### Preview a dashboard

Use `$splunk-dashboard`, then compare the generated layout with local telemetry.
The preview is approximate because SignalFlow runs in Splunk Observability
Cloud.

![Local dashboard preview](assets/marketplace-dashboards-tab.gif)

### Inspect metrics and logs

Filter retained metric series and structured logs without leaving the editor.

![Metric inspection](assets/marketplace-metrics-tab.gif)

![Structured log detail](assets/marketplace-logs-tab.gif)

### Validate semantic conventions

Run the bundled OpenTelemetry Weaver validator and inspect actionable findings
by signal and severity.

![OpenTelemetry validation results](assets/marketplace-validation-tab.gif)

## Collect coding-agent token telemetry

The integration commands listed above install skills and MCP configuration
only. There is currently no editor command for token telemetry. Download and
extract the standalone `obstudio` CLI from
[GitHub Releases](https://github.com/signalfx/obstudio/releases/latest), then
run it from that directory to enable token telemetry for Codex, Claude Code, or
both:

```bash
./obstudio token-telemetry enable \
  --target=codex,claude-code
./obstudio token-telemetry status \
  --target=codex,claude-code
./obstudio token-telemetry disable \
  --target=codex,claude-code
```

`enable` takes ownership of recognized provider OTLP routes; there is no force
flag. Replaced destinations are not retained or restored. `disable` removes
only unchanged Obstudio-managed values, and values edited after enablement are
preserved.

New targets default to `--repository-correlation=path`:

| Mode | Repository data |
|---|---|
| `path` | Includes repository and workspace paths; supports exact-path queries. |
| `name` | Includes the repository name without filesystem paths. |
| `off` | Disables normalized repository correlation. |

Omitting the option for an existing target preserves its recorded mode. Raw
provider telemetry is unchanged and may still contain a provider-supplied
working directory.

Restart every affected Codex or Claude process after a routing change. Codex
CLI, IDE, and Desktop processes share `~/.codex/config.toml`. Claude Desktop's
active Setup profile has higher precedence than user-level Claude Code settings,
and the `claude-code` target does not edit that profile. For a Desktop test, use
an editable profile that enables telemetry and enhanced traces, sends OTLP/HTTP
protobuf logs, traces, and metrics to `http://127.0.0.1:4318`, and then restart
the Code session. Otherwise, use a separate Claude Code CLI process or ask the
administrator to change an organization-locked profile.

Keep the producer running while demonstrating live signals. Completed token
accounting remains queryable after disconnect until Observer clears, exits, or
overwrites its bounded history.

See the [token-usage guide](https://github.com/signalfx/obstudio/blob/main/observer/README.md#audit-token-usage-demo)
for exporter precedence, supported configuration shapes, and detailed Desktop
diagnostics.

## Commands and configuration

| Command Palette action | Purpose |
|---|---|
| **Open Observer** | Open the local Observer panel. |
| **Observer Status** | Inspect the runtime, logs, and recovery actions. |
| **Start / Stop / Restart Observer** | Manage the extension-owned process or reconnect another local Observer. |

Extension settings use the `observability-studio.` prefix:

- `managedObserverPort` moves the extension-managed UI, REST API, and MCP
  endpoint. Its OTLP receivers remain fixed at `4318` and `4317`.
- `sharedObserverUrl` reuses another local Observer. It must report the same
  version bundled with the extension; send telemetry to that Observer's own
  receiver endpoints.

## Security and data handling

An extension-managed Observer keeps received telemetry local unless you enable
Cloud export. A separately managed local Observer follows its own
configuration. Cloud export sends traces and metrics, not logs, and the
extension stores its access token in IDE secret storage.

See the extension's [security](https://github.com/signalfx/obstudio/blob/main/plugins/obstudio/SECURITY.md)
and [privacy](https://github.com/signalfx/obstudio/blob/main/plugins/obstudio/PRIVACY.md)
contracts for its trust and telemetry-handling details.

## Troubleshooting

- If Observer cannot start, check the selected UI/MCP port and the fixed OTLP
  ports `4318` and `4317`. Changing `managedObserverPort` does not move the OTLP
  receivers; stop the conflicting process or reuse another local Observer.
- If `sharedObserverUrl` does not connect, confirm that the configured local
  Observer is reachable and its version matches the extension.
- After enabling an integration or changing token routing, fully restart the
  agent and start a new task. Existing processes keep their startup settings.
- Dashboard previews use the first workspace folder captured when Observer
  starts. Open the service in its own window or make it the first folder, then
  run **Restart Observer** after switching repositories.
- Use **Observer Status** to restart, reconnect, or open extension logs.

## Requirements and links

No separate collector, web runtime, or Weaver installation is required for
normal extension use.

- [User guide](https://github.com/signalfx/obstudio/blob/main/docs/USER.md)
- [Skill documentation](https://github.com/signalfx/obstudio/tree/main/skills)
- [Source and releases](https://github.com/signalfx/obstudio)
- [Contributing](https://github.com/signalfx/obstudio/blob/main/CONTRIBUTING.md)
