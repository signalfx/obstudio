# Contributing

This repository contains:

- `observer/` -- Go-based Observer built on the OTel Collector framework (REST API, MCP server, Web UI)
- `extension/` -- VS Code-compatible extension for Visual Studio Code, Kiro, and Cursor that packages the Observer
- `skills/` -- AI agent skills (composable observability workflows)
- `pytest-codex-evals/` -- reusable pytest plugin for Codex eval harnessing

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Go | 1.25+ | observer collector |
| Node.js | 20+ | observer client dev/test and VS Code-compatible editor extension |
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

### VS Code-Compatible Editor Extension

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

### VS Code-Compatible Editor Extension

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
The `Required CI` status aggregates every mandatory job. A repository
maintainer must configure that exact status as required in the repository
ruleset; until that settings change is made, it is visible on PRs but is not a
hard merge gate. The PR that introduces or changes the aggregate check must
call out this repository-settings follow-up explicitly.

| Job | What it checks |
|-----|---------------|
| observer | `go vet`, `make build`, `make test` |
| interactive-otel-scripts | OTel report/selection tests and pytest eval-input handoff tests |
| extension | `npm run test:all` |
| client | `npx vitest run` |
| agent-policy | Agent instruction routing, review IDs, skill/eval pairing, skill parity, and command references |
| Required CI | Aggregate result for all mandatory CI and policy checks |

See [.github/workflows/ci.yml](.github/workflows/ci.yml).

### Local

```sh
make test-all            # Go + observer client + extension + interactive OTel tests
make agent-policy-check  # agent instruction and repository-policy contracts
npm run build            # root build path for binary + extension
cd extension && npm test # VS Code-hosted extension tests
```

### Testing Policy

- Every PR must include tests for new or changed functionality.
- All tests run in CI. Treat failures as merge-blocking even when the repository
  ruleset does not yet enforce `Required CI`. Flaky tests are bugs -- fix them.
- Use coverage output to identify untested changed behavior, not to satisfy an
  arbitrary repository-wide percentage. See `AGENTS.md` for the coding-agent
  completion and review rules.

## Skill Evals

Skill eval definitions and fixture apps live under `evals/`. See
[`evals/README.md`](evals/README.md) for eval modes, commands, configs, and
report locations. Run `make test-eval-harness` for validation-only checks and
`make test-pytest-plugin` for the reusable plugin tests.

Every addition or modification to shipped skill content must add or
semantically update a matching rubric eval, run
`make eval-validation SKILL=skills/<name>`, and run a representative local
`make eval-rubric SKILL=skills/<name> CASE=<language>/<service>`. Record both
exact commands and results in the pull request. Validation-only collection is
not a substitute for the local rubric result. Shared `skills/references/`
changes must keep `skills/references/consumers.json` aligned and repeat the eval
update and rubric run for every declared affected skill.

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

For changes to `AGENTS.md`, nested agent instructions,
`.github/copilot-instructions.md`, repository policy checks, or GitHub Actions
workflows, request a focused pre-merge review and include the exact
`make agent-policy-check` result. No named reviewer gate is configured at this
time.

For major design decisions, request a pre-merge human review. While
waiting, switch to a different task.

### Recurring Review Lessons

A review of historical Copilot and human comments found these recurring
failure patterns. Apply these guidelines consistently:

- Treat implementation, docs, skills, schemas, fixtures, examples, generated
  artifacts, compatibility aliases, and CI as one contract. Trace a changed
  producer through every consumer instead of leaving a partial migration.
- Test the real public/runtime boundary and its negative, fallback, retry,
  rollback, and recovery branches. Confirm that the named CI target actually
  runs the changed suites.
- Treat UI quality as behavior: controls must accept the supported input,
  remain keyboard/focus accessible, communicate honest state, and render with
  readable hierarchy and sizing at supported widths.
- Preserve target-specific config schemas and user fields. In automatic
  multi-target flows, one plugin or Claude Code, Codex, Cursor, Kiro, or Copilot
  integration failure must not block unrelated targets or the core Observer.
- Preserve state, configuration precedence, ownership, and lifecycle invariants
  across startup, refresh, shared-host reuse, retry, upgrade, concurrency, and
  shutdown.
- Treat file, process, browser/iframe, clipboard, archive, checksum, and secret
  flows as security boundaries; validate the opened or authenticated object,
  not only a path or caller claim.
- Prove OpenTelemetry semantics from the actual producer: names, units,
  attributes, temporality, aggregation, cardinality, and current-versus-desired
  signals must match the relevant contract.
- Distinguish expected absence, malformed input, authorization failure,
  retryable failure, partial results, and offline state. Do not turn uncertainty
  into destructive cleanup, duplicate creation, or a false success.

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
