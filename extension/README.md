# Splunk Observability Studio

Give your coding agent an evidence-backed OpenTelemetry workflow, then inspect the proof without leaving your editor.

Splunk Observability Studio combines agent skills for auditing, instrumenting, verifying, and operationalizing telemetry with a local Observer for traces, metrics, logs, services, validation, dashboard previews, and optional Splunk Observability Cloud export.

![Audit, selection, instrumentation, and verification workflow](assets/marketplace-skills-workflow.gif)

## Editor compatibility

| Editor | Extension status | Install from |
|---|---|---|
| Cursor | Supported | [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) |
| Kiro | Supported | [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) |
| Visual Studio Code | Supported on `1.82.0` or later | [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=Splunk.observability-studio) |
| Windsurf / Devin Desktop | Supported | [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) |

The Observer panel follows one host-neutral path in every listed Code-OSS editor: the extension loads the same bundled React application as a top-level `WebviewPanel` and uses the same request bridge. It does not replace native paste or intercept editor modifier shortcuts. Cloud fields therefore remain normal editable inputs, while a missing or failed host control capability disables only the cloud mutation controls that depend on it; the rest of Observer remains usable.

### Coding-agent integration

Editor compatibility and coding-agent integration are separate. Setup for Cursor and Kiro is built into the extension. In Visual Studio Code, the extension configures Claude Code and Codex; GitHub Copilot uses the standalone CLI. Windsurf / Devin Desktop agent setup is also CLI-only: the current `windsurf` target configures legacy Cascade automatically, while Devin Local needs one additional MCP command. See [Commands](#commands) for the exact local targets.

## Quick start

### Cursor

1. Install from [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) in Cursor's Extensions view.
2. Run **Splunk Observability Studio: Open Observer**.
3. Accept the detected Cursor prompt. If it does not appear, run **Splunk Observability Studio: Enable Cursor Integration**.
4. Restart Cursor so it reloads the installed skills and local Observer connection.

### Kiro

1. Install from [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) in Kiro's Extensions view.
2. Run **Splunk Observability Studio: Open Observer**.
3. Accept the detected Kiro prompt. If it does not appear, run **Splunk Observability Studio: Enable Kiro Integration**.
4. Restart Kiro so it reloads the installed skills and local Observer connection.

### Visual Studio Code

1. Install from the [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=Splunk.observability-studio).
2. Run **Splunk Observability Studio: Open Observer**.
3. Accept the detected integration prompt. If it does not appear, run **Splunk Observability Studio: Enable Claude Code Integration** or **Enable Codex Integration** for the agent you use.
4. Fully restart Claude Code or Codex, then start a fresh task so it reloads the installed skills, local Observer connection, and telemetry routing. An already-open task does not acquire newly configured MCP tools when its URL is reopened.

The enable command records a non-secret fingerprint of the MCP entry it writes.
When an extension-managed Observer restarts and rotates its control token, the
extension refreshes the credential only if that endpoint and complete MCP entry
are unchanged. User-edited, malformed, differently routed, and unowned entries
are never replaced automatically; the extension offers the enable prompt
instead. Run the enable command once after upgrading from an older build so an
existing entry can participate in guarded automatic refresh.

Agent integration does not change provider OTLP settings. To collect token usage,
install the standalone `obstudio` CLI from the
[latest GitHub release](https://github.com/signalfx/obstudio/releases/latest),
then opt in and restart the selected provider:

```bash
obstudio token-telemetry enable --target=codex,claude-code
```

The explicit enable command always takes over recognized provider OTLP routing;
there is no separate force flag. Use `obstudio token-telemetry status` or
`disable` with the same `--target` value to inspect the route or remove unchanged
Obstudio-managed values. Replaced prior destinations are not retained for later
disable or restored; values edited after enable are preserved. New targets default
repository correlation to `path`, which supports exact path queries. Use
`name` to omit filesystem paths or `off` to disable correlation. Omitting the flag
for an already configured target preserves its recorded setting.
Claude's `ENABLE_BETA_TRACING_DETAILED` and `BETA_TRACING_ENDPOINT` pair
overrides the standard logs and traces exporters. Setup owns and normalizes an
active pair to Observer. Existing generic Claude
OTLP endpoint/protocol values are also redirected and owned, and required
signal-specific routes are written locally even when matching values are
inherited. A local override re-enables an inherited or configured disabled OTel
SDK. Existing interval, temporality, TLS, header, and unrelated settings remain
unchanged. Removing a local Claude override can expose an unchanged inherited or
higher-precedence route again; Obstudio does not restore that route. For Codex,
setup owns matching or nonmatching inline exporter
assignments and canonical table endpoint/protocol values. When an exporter is
absent, setup adds an Obstudio-owned local exporter. When a canonical
`[otel.exporter.otlp-http]`, `[otel.trace_exporter.otlp-http]`, or
`[otel.metrics_exporter.otlp-http]` table exists with no endpoint and uses the
compatible `binary` protocol (or has no protocol), setup fills only its missing
endpoint and protocol values. Unsupported, malformed, or multiply defined Codex
exporter shapes fail closed instead of risking an invalid config.
Codex uses the same `~/.codex/config.toml` for CLI, IDE, and Desktop processes,
and each process must be restarted to load an exporter change. While enabled,
its single log, trace, and metrics exporters point to Observer; disable removes
the managed routes when their values are unchanged and does not recover prior destinations.
Claude Desktop launches embedded Code sessions with its active Setup profile as
higher-precedence managed settings. `--target=claude-code` does not inspect or
edit that profile. If it routes OTLP to another collector or disables trace
export, the running Desktop process will not appear in local Observer even when
the user-level status is enabled. Services lists received telemetry producers,
not running processes; a locally routed Desktop session appears under its
reported resource name, commonly `claude-code` or `claude-code-desktop`.

For a non-destructive Desktop test, keep any required organization profile and
use an intentionally local, editable Setup profile that enables Claude
telemetry and enhanced traces and routes OTLP/HTTP protobuf logs, traces, and
metrics to `http://127.0.0.1:4318`. Fully restart the Desktop Code session after
switching profiles. If the active profile is organization-locked or must keep a
corporate OTLP destination, use a separately started Claude Code CLI process or
ask the organization or profile administrator to route through Observer; only
that administrator can change an organization-locked destination. Obstudio
cannot override and does not silently replace that destination.
Codex token histograms are visible in Metrics Explorer, but current points lack
a stable thread or turn identifier and are not added to correlated task totals;
the token-usage tool uses richer Codex logs and task spans instead.
Observer retains recent native Codex and Claude traces in one shared bounded
provider ring outside the generic span ring and de-duplicates them into trace
views. A compacted trace is labeled as a retained lower bound such as `8+`; its
representative spans do not alter raw service aggregates or validation input.
The projection protects recent provider traces from unrelated ring pressure
while the producer is connected; process disconnect removes its live traces,
logs, and metrics from Observer views. Keep the provider process running while
demonstrating those views. Completed token accounting is retained in a separate
bounded history and remains queryable through `observer_token_usage_overview`
after disconnect until Observer is cleared, exits, or overwrites that history.

### Windsurf / Devin Desktop

1. Install from [Open VSX](https://open-vsx.org/extension/splunk/observability-studio) in the Extensions view.
2. Run **Splunk Observability Studio: Open Observer**.
3. Install the standalone `obstudio` CLI from the [latest GitHub release](https://github.com/signalfx/obstudio/releases/latest), then run `obstudio install --target windsurf` in a terminal. This installs skills for Devin Local and legacy Cascade; on Windows, enable Developer Mode or use an elevated terminal so the installer can create skill links.
4. Devin Local is the default agent for new tabs. Make sure the `devin` command is on your `PATH` using the [Devin CLI quick start](https://docs.devin.ai/cli). Copy the base URL shown by **Observer Status**, replace `OBSERVER_BASE_URL` below, and keep the `/mcp` suffix:

   ```text
   devin mcp add -s user obstudio OBSERVER_BASE_URL/mcp
   ```

   Legacy Cascade does not need this extra command because the `windsurf` target configures its MCP file.
5. Restart the agent so it reloads the installed skills and local Observer connection.

### Start here — run the audit

Open your service directory, then enter the matching command in your coding agent chat—not in the terminal.

**Codex**

```text
$otel-audit
```

**Claude Code, Cursor, or Kiro**

```text
/otel-audit
```

**Windsurf / Devin Desktop — Devin Local**

```text
/otel-audit
```

**Windsurf / Devin Desktop — legacy Cascade**

```text
@otel-audit
```

The GIF begins at Step 1 after this command returns the audit report. Review the prioritized findings, select the work, and run the generated instrumentation command. Use `/otel-instrument` in a slash-command agent, including Devin Local, or `@otel-instrument` in legacy Cascade where the report shows `$otel-instrument`; keep its generated IDs, decisions, and service path unchanged.

## Choose the skill for the job

Use the skills as a guided path from source code to proven telemetry:

```text
audit → review and select → instrument → verify → configure → publish
```

The table uses Codex `$` notation. Replace the leading `$` with `/` in Claude Code, Cursor, Devin Local, or Kiro, and with `@` in legacy Cascade; keep the skill name and arguments unchanged.

| Skill | Use it when you want to… |
|---|---|
| `$otel-audit` | Read the codebase without changing application code, find coverage gaps, and review a prioritized interactive report. |
| `$otel-instrument` | Implement only the approved findings or a concrete telemetry request. Verification runs by default after the change. |
| `$otel-verify` | Recheck existing instrumentation with project-runtime, app-code, and optional local OTLP proof. |
| `$splunk-dashboard` | Generate dashboard Terraform from source-backed metrics in the audit report and preview the layout against local data in Observer. |
| `$splunk-configure` | Generate evidence-backed detector and dashboard Terraform, while calling out instrumentation prerequisites that still block safe resources. |
| `$splunk-detector-publish` | Diff detector specs against live Splunk state, confirm the gaps, and create only what is missing. |
| `$splunk-dashboard-publish` | Diff dashboard groups, dashboards, and charts, confirm the gaps, and publish them safely. |

### Continue the workflow

1. When the audit finishes, open the interactive report link shown in agent chat.
2. Review the prioritized findings and select the work you approve.
3. Copy the report's generated instrumentation command. Run it in agent chat using the prefix shown above; do not remove its generated IDs, decisions, or service path.
4. Review the verification result that runs by default after instrumentation.
5. Use `$splunk-dashboard` to preview a dashboard, then `$splunk-dashboard-publish` to review the live diff and create only confirmed gaps.

You can also ask naturally, for example: “Audit this checkout service, let me approve the plan, then instrument only the selected gaps.”

## See the proof locally

When the extension starts its bundled Observer, it exposes these local endpoints:

| Service | Extension-managed endpoint |
|---|---|
| OTLP/HTTP | `http://127.0.0.1:4318` |
| OTLP/gRPC | `127.0.0.1:4317` |
| Observer UI and REST | `http://127.0.0.1:3000` by default |
| Local Observer MCP | `http://127.0.0.1:3000/mcp` by default |

If the extension reuses a shared Observer, use that Observer's configured UI, MCP, and OTLP receiver endpoints. A manually configured `sharedObserverUrl` does not remap or validate the shared Observer's OTLP ports.

The extension-managed Observer keeps telemetry local unless you explicitly enable Splunk Observability Cloud export. A shared Observer follows its own export configuration.

Observer provides seven focused views:

| View | What it helps you prove |
|---|---|
| **Metrics** | Series, dimensions, retained points, distributions, and resource metadata. |
| **Traces** | End-to-end waterfalls, downstream latency, errors, span attributes, and GenAI agent flow. |
| **Logs** | Structured messages, severity, resources, attributes, and trace correlation. |
| **Services** | Trace and span volume, errors, and client/server duration by service. |
| **Validation** | OpenTelemetry semantic-convention findings across metrics, spans, logs, and resources. |
| **Dashboards** | An approximate local-data preview of Terraform generated by the dashboard skills. |
| **Cloud** | Optional Splunk Observability Cloud connection and export controls. |

### Investigate a checkout trace

Open a trace to see the complete waterfall and identify the slow dependency.

![Checkout trace waterfall](assets/marketplace-traces-tab.gif)

### Preview a generated dashboard

Use `$splunk-dashboard`, then inspect the generated layout against the telemetry retained locally. The preview is clearly labeled approximate because SignalFlow executes in Splunk Observability Cloud. An extension-managed Observer reads the first editor workspace folder captured when its process starts. In a multi-root workspace, open the service in its own window or make it the first workspace folder, then run **Restart Observer**. Also restart after switching a single-root workspace or repository. If you reuse a shared Observer, relaunch that process from the intended workspace, then run **Restart Observer** to reconnect.

![Local dashboard preview](assets/marketplace-dashboards-tab.gif)

### Inspect metrics and logs

Filter a metric by service, open the retained series, and compare values without leaving the editor.

![Metric inspection](assets/marketplace-metrics-tab.gif)

Filter structured logs to the affected service, then inspect the message, resource, scope, and attributes.

![Structured log detail](assets/marketplace-logs-tab.gif)

### Validate semantic conventions

Run the bundled OpenTelemetry Weaver validator, filter findings by severity and signal, then open an issue for actionable detail.

![OpenTelemetry validation results](assets/marketplace-validation-tab.gif)

## Commands

- **Splunk Observability Studio: Open Observer** — open the local visualization panel.
- **Splunk Observability Studio: Observer Status** — reopen, restart, or inspect the Observer runtime.
- **Splunk Observability Studio: Start Observer**, **Stop Observer**, **Restart Observer** — manage the extension-owned process, or connect, disconnect, and reconnect when using a shared Observer.
- **Splunk Observability Studio: Enable Claude Code Integration** — install the bundled skills and configure the local MCP endpoint for Claude Code.
- **Splunk Observability Studio: Enable Codex Integration** — install the bundled skills and configure the local MCP endpoint for Codex.
- **Splunk Observability Studio: Enable Cursor Integration** — install the bundled skills and configure the local MCP endpoint for Cursor.
- **Splunk Observability Studio: Enable Kiro Integration** — install the bundled skills and configure the local MCP endpoint for Kiro.

The standalone release CLI also supports integrations that are not offered as extension Command Palette actions:

- `obstudio install --target copilot` configures the local MCP connection for GitHub Copilot in Visual Studio Code. Agent-skill installation is not supported for this target.
- `obstudio install --target windsurf` installs the bundled skills used by Devin Local and legacy Cascade, and configures the local MCP connection for legacy Cascade. Add the running Observer to Devin Local with the `devin mcp add` command in its [quick start](#windsurf--devin-desktop).

Use the **Live** control, or press `P` while Observer is focused, to pause telemetry while inspecting a row. Standard editor shortcuts such as `Cmd+P` and `Ctrl+P` continue to work.

## Configuration

Move the extension-managed Observer UI and MCP endpoint to another local port with:

```json
{
  "observability-studio.managedObserverPort": 41234
}
```

For an extension-managed Observer, the OTLP receivers remain fixed at `4318` and `4317`. Set `observability-studio.sharedObserverUrl` to reuse an Observer you already manage, then send telemetry to the receiver endpoints configured by that Observer.

## Local by default

- An extension-managed Observer retains incoming telemetry locally for development inspection. A shared Observer follows its own retention and export configuration.
- The Cloud tab exports metrics and traces only. Its connection field accepts a realm or a Splunk Observability Cloud UI, API, ingest, or other documented service URL on either the current `observability.splunkcloud.com` domain or the legacy `signalfx.com` domain. Observer leaves the user's entry visible while connecting or retrying, resolves URLs to a canonical realm internally, stores only that realm, and never sends the access token during URL resolution. Its key is stored in IDE secret storage, and a new connection leaves remote export off until you explicitly enable it.
- In the IDE extension, the Cloud tab can submit a Free Edition signup from separate first-name and last-name fields, an email address, one of the public form's United States, Europe, or Asia Pacific hosting options, and explicit Terms acceptance. The submit action is blocked only while that request is in flight; after it returns, the user can explicitly submit another request with the same email. Observer keeps no email-keyed submission history and does not suppress duplicate email addresses. Observer calls Splunk's GeoIP endpoint without an IP-address parameter; Splunk derives coarse country, state, city, postal code, and sales region from the request's network source IP. Observer sends the four matching location fields in the signup payload and uses country code plus sales region only to preselect a supported hosting region. Explicit Terms acceptance is sent upstream as `privacyPolicyCheck: "1"`. Observer does not call Cisco OpenDNS and neither receives nor explicitly transmits a raw IP value; region selection does not use application telemetry. Splunk still processes the request's source IP. A remote/shared Observer can reflect that host's network rather than the laptop. The flow falls back atomically to United States/California, empty city/postal code, and the United States signup region when GeoIP lookup is blocked, times out, or is incomplete, or when returned values are unrecognized by the region map. Observer's local signup diagnostics record only the upstream HTTP status and an allowlisted response classification; they never record request or response payloads, personal information, IP addresses, headers, or raw response bodies.
- Optional remote Splunk MCP setup is separate from telemetry export. Its automatic connector supports Claude Code, Codex, Cursor, and GitHub Copilot in Visual Studio Code; it does not configure Devin Local, Kiro, or legacy Cascade. Those agents can still be configured manually when they support the remote MCP transport.
- Publishing skills show a diff and require confirmation before creating missing detectors or dashboards.
- Access tokens are not part of the demo media and should be supplied only through the supported local configuration flow.

## Troubleshooting

- If the extension-managed Observer cannot start, check its configured UI/MCP port (`managedObserverPort`, `3000` by default) and the fixed receiver ports `4318` and `4317`. Choose another `managedObserverPort` if its UI/MCP port is already used.
- If the extension cannot connect to a shared Observer, verify `sharedObserverUrl`. If its UI loads but telemetry does not arrive, use the OTLP receiver endpoints configured by that Observer.
- Fully restart your coding agent after enabling an integration or after the extension reports that it refreshed Observer credentials. Then use a fresh task so it reloads the skills, MCP settings, and telemetry routing. Existing tasks keep their startup tool set.
- Use **Observer Status** to restart the extension-managed runtime, reconnect a shared Observer, or open the extension logs.

## Requirements and links

- Cursor (compatible release), Kiro, Visual Studio Code `1.82.0` or later (declared as `^1.82.0`), or Windsurf / Devin Desktop.
- No separate collector, web runtime, or Weaver installation is required for normal extension use.
- [User guide](https://github.com/signalfx/obstudio/blob/main/docs/USER.md)
- [Skill documentation](https://github.com/signalfx/obstudio/tree/main/skills)
- [Source and releases](https://github.com/signalfx/obstudio)
- [Contributing](https://github.com/signalfx/obstudio/blob/main/CONTRIBUTING.md)
