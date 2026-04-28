# Splunk Observability Studio

Splunk Observability Studio is a VS Code extension for viewing OpenTelemetry data locally while you work.

When the extension activates, it starts a bundled observer binary, exposes OTLP receivers on localhost, and opens an embedded Observer UI inside VS Code.

## Features

- Starts a local observer backend automatically on extension activation.
- Exposes stable OTLP endpoints for local applications:
  - OTLP/HTTP on `127.0.0.1:4318`
  - OTLP/gRPC on `127.0.0.1:4317`
- Opens the Observer UI in a VS Code webview panel.
- Includes a status bar entry to reopen the Observer quickly.

## Commands

- `Splunk Observability Studio: Open Observer` — opens the Observer webview panel.

## How It Works

The extension packages a pre-built observer binary (Go) into the extension bundle under `dist/observer/obstudio`. The binary embeds its own web UI via Go's `//go:embed` directive.

At startup, the extension:

1. Finds an available localhost port for the Observer web UI.
2. Verifies that OTLP ports `4317` and `4318` are available.
3. Launches the observer binary with the assigned ports.
4. Connects the VS Code webview to the local Observer UI via an iframe.

If either OTLP port is already in use, the extension reports a startup error.

## Requirements

- VS Code `^1.110.0`
- Go compiler for building from source

No additional runtime setup is required for normal extension use.

## Development

From the `extension` directory:

- `npm run compile` — type-checks, lints, builds the Go binary, and bundles the extension.
- `npm run package` — production build.
- `npm run build:vsix` — packages the extension into a `.vsix` file.
- `npm run test:unit` — runs unit tests.

## Known Limitations

- The extension expects localhost ports `4317` and `4318` to be free.
- The Observer UI port is dynamic and selected at startup.
