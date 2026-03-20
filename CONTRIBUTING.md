# Contributing

This repository contains two main parts:

- `observer/`: the local Observer application
- `extension/`: the VS Code extension that packages and runs the Observer

## Prerequisites

Install these tools before working on the repo:

- Node.js 20 or newer
- npm
- VS Code, if you plan to run or test the extension
- `tar`, if you plan to regenerate OTLP protobuf bindings

Notes:

- The extension manifest targets VS Code `^1.110.0`.
- Some packaging tooling may warn on older Node 20 patch releases. Using a current Node 20 release is recommended.

## Initial Setup

Install dependencies in both project directories:

```sh
cd observer
npm install

cd ../extension
npm install
```

## Build

From the repository root:

```sh
npm run build
```

This builds:

- the Observer client
- the Observer server
- the VS Code extension

You can also build each part directly:

```sh
cd observer
npm run build
```

```sh
cd extension
npm run compile
```

To produce a VS Code extension package:

```sh
cd extension
npm run build:vsix
```

## Development

Run the Observer app in development mode:

```sh
cd observer
npm run dev
```

Useful Observer commands:

- `npm run dev:client`
- `npm run dev:server`
- `npm run typecheck`
- `npm run generate:otlp`

Useful extension commands:

```sh
cd extension
npm run watch
```

Other extension build commands:

- `npm run compile`
- `npm run package`
- `npm run build:vsix`

## Testing

There is no single top-level `npm test` command yet. Run the available checks per project.

For the Observer:

```sh
cd observer
npm run typecheck
```

For the extension:

```sh
cd extension
npm run check-types
npm run lint
npm test
```

Notes:

- `extension/npm test` runs the VS Code extension test flow via `vscode-test`.
- `extension/npm run package` is also a useful validation step because it performs type-checking, linting, and a production bundle build before packaging.

## OTLP Bindings

If you change OTLP protobuf inputs or the generation flow, regenerate bindings from the `observer` directory:

```sh
npm run generate:otlp
```

Generated OTLP bindings are written under `observer/shared/otlp/`.
