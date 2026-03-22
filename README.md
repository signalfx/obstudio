# obstudio

`obstudio` is a local OpenTelemetry observability workspace.

The repository contains:

- `observer/`: a standalone Observer application with a server, client UI, and shared OTLP bindings
- `extension/`: a VS Code extension that packages and runs the Observer inside VS Code

The Observer accepts telemetry over OTLP/HTTP and OTLP/gRPC, stores it in memory, and exposes a UI for exploring traces, metrics, and logs locally during development.

## Build

From the repository root:

```sh
npm run build
```

This builds the Observer client, the Observer server, and the VS Code extension.
