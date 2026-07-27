# Contributing

This repository contains:

- `observer/` -- Go-based Observer built on the OTel Collector framework (REST API, MCP server, Web UI)
- `extension/` -- Code OSS extension for VS Code, Kiro, and Cursor that packages the Observer
- `skills/` -- AI agent skills (composable observability workflows)
- `pytest-codex-evals/` -- reusable pytest plugin for Codex eval harnessing

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Go | 1.25+ | observer collector |
| Node.js | 20+ | observer client dev/test and Code OSS editor extension |
| npm | latest | Package management |
| uv | latest | Python eval harness and Python fixture apps |
| Docker | latest | Optional runtime eval checks |
| goreleaser | latest | `make release-local` only (optional) |

## Build

### Observer (primary)

```sh
make build    # compile the obstudio binary (skills embedded)
make run      # build and start the collector
```

### Editor Extension (Code OSS)

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

### Editor Extension (Code OSS)

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
| interactive-otel-scripts | OTel report/selection tests and pytest eval-input handoff tests |
| extension | `npm run test:all` |
| client | `npx vitest run` |

See [.github/workflows/ci.yml](.github/workflows/ci.yml).

### Local

```sh
make test-all            # Go + observer client + extension + interactive OTel tests
npm run build            # root build path for binary + extension
cd extension && npm test # VS Code-hosted extension tests
```

### Testing Policy

- Every PR must include tests for new or changed functionality.
- All tests run in CI. Failing tests block merge. Flaky tests are bugs -- fix immediately.
- Code coverage tools will be used to identify untested functionality. See `AGENTS.md` for how AI agents should incorporate coverage analysis.

## Skill Evals

Skill eval definitions and fixture apps live under `evals/`. See
[`evals/README.md`](evals/README.md) for eval modes, commands, configs, and
report locations. Run `make test-eval-harness` for validation-only checks and
`make test-pytest-plugin` for the reusable plugin tests.

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
which cross-compiles for linux/darwin/windows, builds platform-specific VSIX
packages, creates a GitHub Release, uploads both archive types, and publishes
the VSIX packages to Open VSX.

Kiro and Cursor use [Open VSX](https://open-vsx.org/) for extension discovery.
The release workflow verifies the `OVSX_PAT` repository secret before it
creates the GitHub Release. Open VSX publishing failures fail the workflow, and
duplicate versions are skipped so a partial release can be retried safely.

Visual Studio Marketplace publishing is manual. After the release workflow
succeeds, download the four platform-specific VSIX files from the GitHub Release
and upload those exact files to the existing
[Splunk publisher](https://marketplace.visualstudio.com/manage/publishers/Splunk).
Do not rebuild the VSIX files for Marketplace publishing. The release workflow
adds the same reminder to its job summary. The GitHub Release VSIX files also
remain the manual-install fallback.

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
