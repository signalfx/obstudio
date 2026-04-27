# Contributing

This repository contains:

- `observer/` -- Go-based Observer built on the OTel Collector framework (REST API, MCP server, Web UI)
- `extension/` -- VS Code extension that packages the Observer
- `skills/` -- AI agent skills (composable observability workflows)
- `pytest-codex-evals/` -- reusable pytest plugin for Codex eval harnessing

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Go | 1.25+ | observer collector |
| Node.js | 20+ | observer client dev/test and VS Code extension |
| npm | latest | Package management |
| uv | latest | Python eval harness and Python fixture apps |
| goreleaser | latest | `make release-local` only (optional) |

## Build

### Observer (primary)

```sh
make build    # compile the obstudio binary (skills embedded)
make run      # build and start the collector
```

### VS Code Extension

```sh
cd extension
npm install
npm run compile       # typecheck + lint + esbuild
npm run build:vsix    # produce VSIX package
```

## Development

### Observer

```sh
make build          # build binary
make run            # build and run
make test           # go test ./...
make vet            # go vet
make fmt            # go fmt
make tidy           # go mod tidy
```

### VS Code Extension

```sh
cd extension
npm run watch         # rebuild on change
npm run check-types   # typecheck
npm run lint          # eslint
npm test              # vscode-test
```

## Testing

### CI

GitHub Actions runs on every push to `main` and `feature/**` branches.
PRs cannot be merged if tests are failing.

| Job | What it checks |
|-----|---------------|
| observer | `go vet`, `make build`, `make test` |
| extension | `npm run test:all` |
| client | `npx vitest run` |

See [.github/workflows/ci.yml](.github/workflows/ci.yml).

### Local

```sh
make test-all            # Go + observer client + extension integration tests
npm run build            # root build path for binary + extension
cd extension && npm test # VS Code-hosted extension tests
```

### Testing Policy

- Every PR must include tests for new or changed functionality.
- All tests run in CI. Failing tests block merge. Flaky tests are bugs -- fix immediately.
- Code coverage tools will be used to identify untested functionality. See `AGENTS.md` for how AI agents should incorporate coverage analysis.

## Skill Evals

Skill evals are JSON files collected by the reusable pytest plugin under
`evals/`. Each service fixture owns its eval definitions:
`evals/<language>/<service>/audit_eval.json` and
`evals/<language>/<service>/instrument_eval.json`.

```sh
make skill-eval SKILL=skills/otel-instrument
make skill-eval SKILL=skills/otel-instrument CASE=go/kvstore
make skill-eval-ab SKILL=skills/otel-instrument CASE=go/kvstore
make test-eval-harness
make test-pytest-plugin
```

Live A/B settings, including the qualitative judge model, live in
`evals/codex-evals.ab.toml`.

The reusable pytest plugin is built and published alongside this repository:

```sh
make build-pytest-plugin
make publish-pytest-plugin
```

## Pull Requests

Create Pull Requests for all changes. The PR description must be accurate
and concise (under one page). The commit message mirrors the description.
When applicable, include the AI agent plan. If the plan is too large,
commit it as a design doc under `docs/`.

Request a Copilot review on every PR. Address reasonable suggestions.

Pre-merge human reviews are not required. If the author is satisfied with
the PR and Copilot's review, they can merge. Post-merge reviews are
encouraged for knowledge sharing -- comments should be addressed in a
follow-up PR.

For major design decisions, request a pre-merge human review. While
waiting, switch to a different task.

## Design and Architecture

Design documents live under `docs/`. Discussion happens via PRs, live
calls, or offline PR comments.

## Releases

Releases are automated via GitHub Actions and GoReleaser. To cut a release:

```sh
git tag v0.2.0
git push origin v0.2.0
```

This triggers [.github/workflows/release.yml](.github/workflows/release.yml),
which cross-compiles for linux/darwin/windows, creates a GitHub Release,
and uploads zip archives.

See [.goreleaser.yaml](.goreleaser.yaml) for the full release configuration.

The pytest plugin is versioned in `pytest-codex-evals/pyproject.toml` and can be
published from the same checkout when eval harness changes need a package
release:

```sh
make test-pytest-plugin
make build-pytest-plugin
make publish-pytest-plugin
```

## Quality Tooling

Enable all automated tooling that helps maintain high-quality code:
linters, vulnerability checkers, security scanners, and similar tools.
