# Splunk Observability Studio

Splunk Observability Studio brings a local OpenTelemetry collector and Telemetry Explorer into VS Code.

When the extension activates, it reuses or starts a bundled `obstudio` backend, exposes OTLP receivers on localhost, and opens an embedded Observer UI so you can inspect telemetry without leaving the editor.

## Metrics Explorer

Inspect live metric series, compare dimensions, and drill into retained points directly inside VS Code.

![Metrics Explorer](https://github.com/signalfx/obstudio/raw/HEAD/extension/assets/marketplace-metrics-tab.gif)

## Trace Investigation

Open recent traces, expand the waterfall, and use the detail view to see where time was spent and which downstream call failed.

![Trace Investigation](https://github.com/signalfx/obstudio/raw/HEAD/extension/assets/marketplace-traces-tab.gif)

## Log Inspection

Review structured logs alongside severity, resource metadata, and trace correlation details.

![Log Inspection](https://github.com/signalfx/obstudio/raw/HEAD/extension/assets/marketplace-logs-tab.gif)

## Validation

Validation is a quick quality check for your telemetry. It runs the bundled OpenTelemetry Weaver validator against the spans, metrics, logs, and resources currently retained in Observer, then points out places where your instrumentation may be missing important context or using the wrong shape.

In simple terms, it helps answer questions like:

- Did I miss an expected HTTP attribute such as method, route, or status code?
- Did I name this metric or field in a way that tools may not understand?
- Am I sending telemetry that works, but could be more useful with a little more context?

The results are grouped by metric, span, log, or resource so you can focus on one signal type at a time.

Use it like this:

1. Send telemetry to the local Observer.
2. Open the Validation tab.
3. Click `Run Validation` or `Re-run Validation`.
4. Start with the signal you care about most, then open an issue to see the plain-language finding.

The severity levels are meant to be easy to read:

- `Violation` usually means something expected is missing or incorrect.
- `Improvement` means your telemetry is usable, but adding more detail would make it better.
- `Information` is lighter guidance for optional or situation-specific context.

![Validation](https://github.com/signalfx/obstudio/raw/HEAD/extension/assets/marketplace-validation-tab.gif)

## Features

- Reuses a healthy shared observer at `http://127.0.0.1:3000` or starts a bundled local observer automatically on activation.
- Detects local Codex, Claude Code, and Cursor installs and offers a one-time prompt to enable integration.
- Exposes stable OTLP endpoints for local applications:
  - OTLP/HTTP on `127.0.0.1:4318`
  - OTLP/gRPC on `127.0.0.1:4317`
- Opens the Telemetry Explorer in a VS Code webview panel.
- Keeps a status bar entry available so you can reopen the explorer quickly.
- Includes commands for starting, stopping, restarting, and reusing the shared observer runtime.
- Includes helper commands to enable agent integrations against the shared observer endpoint.

## Commands

- `Splunk Observability Studio: Open Observer` — opens the Observer webview panel.
- `Splunk Observability Studio: Observer Status` — opens the quick status menu.
- `Splunk Observability Studio: Start Observer` — starts the shared observer runtime.
- `Splunk Observability Studio: Stop Observer` — stops the shared observer runtime.
- `Splunk Observability Studio: Restart Observer` — restarts the shared observer runtime.
- `Splunk Observability Studio: Enable Codex Integration` — installs bundled skills and writes Codex MCP settings for the shared observer.
- `Splunk Observability Studio: Enable Claude Code Integration` — installs bundled skills and writes Claude Code MCP settings for the shared observer.
- `Splunk Observability Studio: Enable Cursor Integration` — installs bundled skills and writes Cursor MCP settings for the shared observer.

## How It Works

The extension packages a pre-built observer binary (Go) into the extension bundle under `dist/observer/obstudio`. The binary embeds its own web UI via Go's `//go:embed` directive.

At startup, the extension:

1. Uses `observability-studio.sharedObserverUrl` when it is configured.
2. Otherwise reuses a healthy observer already serving `http://127.0.0.1:3000` when one is available.
3. If no shared observer is already running, verifies that `managedObserverPort`, `4317`, and `4318` are available.
4. Launches the bundled observer binary on the managed local endpoint `http://127.0.0.1:<managedObserverPort>`.
5. When a supported agent home is detected, offers a one-time prompt to install bundled skills and point that agent at the shared Observer MCP endpoint.
6. Connects the VS Code webview to the Observer UI via an iframe.

If the managed endpoint or either OTLP port is already in use by an incompatible service, the extension reports a startup error.

## Requirements

- VS Code `^1.110.0`
- Node.js and `npm`
- Go compiler for building from source

No additional runtime setup is required for normal extension use.

## Development

From the `extension` directory:

- `npm run compile` — type-checks, lints, builds the Go binary, and bundles the extension.
- `npm run package` — production build.
- `npm run build:vsix` — packages the extension into a `.vsix` file.
- `npm run test:unit` — runs unit tests.
- `npm run test:all` — runs unit, integration, and VS Code host tests.

## Known Limitations

- The managed local observer expects `127.0.0.1:<managedObserverPort>`, `127.0.0.1:4318`, and `127.0.0.1:4317` to be free unless you point the extension at an existing shared observer with `observability-studio.sharedObserverUrl`.
