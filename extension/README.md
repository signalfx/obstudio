# Splunk Observability Studio

Give your coding agent an evidence-backed OpenTelemetry workflow, then inspect
the proof without leaving your editor. The extension bundles agent skills and a
local Splunk Observability Studio runtime for traces, metrics, logs, services,
validation, dashboard previews, and optional Splunk Observability Cloud export.

## Install

| Editor | Install from |
|---|---|
| Cursor | [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) |
| Kiro | [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) |
| Visual Studio Code 1.82+ | [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=Splunk.observability-studio) |
| Windsurf / Devin Desktop | [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) |

After installing:

1. Run **Splunk Observability Studio: Open**.
2. For Cursor, Kiro, Claude Code, or Codex, accept the detected integration
   prompt or run the matching enable command from the Command Palette.
3. After enabling an integration, fully restart the agent and start a new task
   so it reloads its skills and local MCP connection.

The extension provides these integration commands:

| Agent | Command Palette action |
|---|---|
| Cursor | **Enable Cursor Integration** |
| Kiro | **Enable Kiro Integration** |
| Claude Code | **Enable Claude Code Integration** |
| Codex | **Enable Codex Integration** |

For Copilot, Windsurf, and Devin Desktop setup, follow the standalone CLI
instructions in the
[user guide](https://github.com/signalfx/obstudio/blob/main/docs/USER.md#agent-targets).

## Run your first audit

From the service root, enter the audit command in your coding-agent chat:

| Agent | Command form |
|---|---|
| Codex | `$otel-audit` |
| Claude Code, Cursor, Kiro, or Devin Local | `/otel-audit` |
| Legacy Cascade | `@otel-audit` |

Open the returned report and follow the next step it recommends. The
[user guide](https://github.com/signalfx/obstudio/blob/main/docs/USER.md#using-the-skills)
explains the complete audit, instrumentation, verification, and publishing
workflow.

![Audit, selection, instrumentation, and verification workflow](assets/marketplace-skills-workflow.gif)

## Inspect the proof

Run **Splunk Observability Studio: Open** to inspect the evidence inside your
editor. See the [Splunk Observability Studio guide](https://github.com/signalfx/obstudio/blob/main/observer/README.md)
for runtime behavior, endpoints, views, and API details.

**Trace a request.** Open a trace to inspect its waterfall and slow
dependencies.

![Checkout trace waterfall](assets/marketplace-traces-tab.gif)

**Preview a dashboard.** Generate a dashboard with your agent, then compare the
layout with local telemetry. The preview is approximate because SignalFlow
runs in Splunk Observability Cloud.

![Local dashboard preview](assets/marketplace-dashboards-tab.gif)

**Inspect metrics and logs.** Filter retained metric series and structured logs
without leaving the editor.

![Metric inspection](assets/marketplace-metrics-tab.gif)

![Structured log detail](assets/marketplace-logs-tab.gif)

**Validate semantic conventions.** Run the bundled OpenTelemetry Weaver
validator and inspect actionable findings by signal and severity.

![OpenTelemetry validation results](assets/marketplace-validation-tab.gif)

## Commands and configuration

| Command Palette action | Purpose |
|---|---|
| **Splunk Observability Studio: Open** | Open the local panel. |
| **Splunk Observability Studio: Status** | Inspect the runtime, logs, and recovery actions. |
| **Splunk Observability Studio: Start** | Start the extension-owned process. |
| **Splunk Observability Studio: Stop** | Stop the extension-owned process. |
| **Splunk Observability Studio: Restart** | Restart the extension-owned process or reconnect another local instance. |

Extension settings use the `observability-studio.` prefix:

- `managedObserverPort` moves the extension-managed UI, REST API, and MCP
  endpoint. Its OTLP receivers remain fixed at `4318` and `4317`.
- `sharedObserverUrl` reuses another Splunk Observability Studio instance
  running on this machine. Use `localhost` or `127.0.0.1` in the URL. It must
  report the same version bundled with the extension; send telemetry to that
  instance's own receiver endpoints.

## Data and permissions

An extension-managed Splunk Observability Studio instance keeps received
telemetry local unless you enable Cloud export. A separately managed local
instance follows its own configuration. Cloud export sends traces and metrics,
not logs, and the extension stores its access token in IDE secret storage.

For the bundled Codex and Claude Code plugin, see its
[security](https://github.com/signalfx/obstudio/blob/main/plugins/obstudio/SECURITY.md)
and [privacy](https://github.com/signalfx/obstudio/blob/main/plugins/obstudio/PRIVACY.md)
contracts.

## Troubleshooting

- If Splunk Observability Studio cannot start, check the selected UI/MCP port
  and the fixed OTLP ports `4318` and `4317`. Changing `managedObserverPort`
  does not move the OTLP receivers; stop the conflicting process or reuse
  another local instance.
- If `sharedObserverUrl` does not connect, confirm that the configured local
  Splunk Observability Studio is reachable and its version matches the extension.
- After enabling an integration, fully restart the agent and start a new task.
  Existing processes keep their startup settings.
- Dashboard previews use the first workspace folder captured when Splunk
  Observability Studio starts. Open the service in its own window or make it
  the first folder, then run **Splunk Observability Studio: Restart** after
  switching repositories.
- Use **Splunk Observability Studio: Status** to restart, reconnect, or open
  extension logs.

## Resources

No separate collector, web runtime, or Weaver installation is required for
normal extension use.

- [User guide](https://github.com/signalfx/obstudio/blob/main/docs/USER.md)
- [Splunk Observability Studio guide](https://github.com/signalfx/obstudio/blob/main/observer/README.md)
- [Example prompts](https://github.com/signalfx/obstudio/blob/main/docs/examples.md)
- [Source and releases](https://github.com/signalfx/obstudio)
- [Contributing](https://github.com/signalfx/obstudio/blob/main/CONTRIBUTING.md)
