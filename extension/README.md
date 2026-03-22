# Observability Studio

Observability Studio is a VS Code extension for viewing OpenTelemetry data locally while you work.

When the extension activates, it starts a bundled local observer process, exposes OTLP receivers on localhost, and opens an embedded Observer UI inside VS Code.

## Features

- Starts a local Observer backend automatically on extension activation.
- Exposes stable OTLP endpoints for local applications:
  - OTLP/HTTP on `127.0.0.1:4318`
  - OTLP/gRPC on `127.0.0.1:4317`
- Opens the Observer UI in a VS Code webview panel.
- Includes a status bar entry to reopen the Observer quickly.

## Commands

The extension contributes these commands:

- `Observability Studio: Open Observer`
- `Observability Studio: Hello World`

## How It Works

The extension packages the Observer server and client into the extension bundle under `dist/observer`.

At startup, the extension:

1. Finds an available localhost port for the Observer web UI.
2. Verifies that OTLP ports `4317` and `4318` are available.
3. Launches the packaged Observer process.
4. Connects the VS Code webview to the local Observer UI.

If either OTLP port is already in use, the extension reports a startup error instead of silently failing.

## Requirements

- VS Code `^1.110.0`
- Node.js `>=20` for local development and packaging

No additional runtime setup is required for normal extension use.

## Development

Useful scripts from the `extension` directory:

- `npm run compile` builds the extension in development mode.
- `npm run package` builds the production extension bundle.
- `npm run build:vsix` packages the extension into a `.vsix` file.

## Known Limitations

- The extension expects localhost ports `4317` and `4318` to be free.
- The Observer UI port is dynamic and selected at startup.
- The `Hello World` command is still a scaffold command and not part of the core workflow.
