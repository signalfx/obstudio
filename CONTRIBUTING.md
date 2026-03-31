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

## Pull Requests

Create Pull Requests for all changes. Ensure the PR description is included and the commit message mirrors it. PR descriptions are for humans -- it is OK to use AI to produce them but they must be accurate and concise (under one page for most changes). When applicable, include the AI Agent Plan in the PR description. If the plan is too large, commit it as a design doc under `docs/`.

Request a Copilot review on every PR. Address suggestions that are reasonable; use your judgement when ignoring Copilot's opinion.

Pre-merge human reviews are not required. If the author is satisfied with their PR and with Copilot's review, they can merge it themselves. The quality of the merged code is the author's responsibility.

Post-merge reviews are highly encouraged for knowledge sharing. Teammates can review PRs after they are merged. Comments on merged PRs are welcome and should be addressed by the author in a follow-up PR if necessary.

If you need a second opinion, request a pre-merge review from another human. Major design decisions will likely go through this path, with discussion happening before decisions are made. While waiting for a human review, switch to a different task and continue working.

## Design and Architecture Decisions

Design documents should be committed to the repo under `docs/`. Discussion happens via PRs, live calls, or offline PR comments.

## Automated Testing

Since the project relies heavily on AI tools and reduces human reviews, good testing coverage is essential to compensate.

- Every PR must include tests that verify newly added functionality. As an author, you are responsible for ensuring the necessary tests are present.
- All tests must run as GitHub Actions. PRs cannot be merged if tests are failing.
- Unstable or flaky tests are bugs and must be fixed immediately.
- Code coverage tools will be used to identify untested functionality. See `AGENTS.md` for how AI agents should incorporate coverage analysis.
- Skills (under `skills/`) must also have automated tests and evaluations. Because skill operation is non-deterministic, use probabilistic evaluation with fuzzy result verification that allows a controlled degree of deviation from golden expected results.

## Quality Tooling

Enable all automated tooling that helps maintain high-quality code: linters, vulnerability checkers, security scanners, and similar tools.

## Releases

- Weekly releases, automated as much as possible.
- A changelog is required for each release.
- A demo is recorded for each release showing all new features.
