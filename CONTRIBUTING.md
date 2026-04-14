# Contributing

This repository contains:

- `observer/` -- Go-based Observer built on the OTel Collector framework (REST API, MCP server, Web UI)
- `extension/` -- VS Code extension that packages the Observer
- `skills/` -- AI agent skills (composable observability workflows)

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Go | 1.25+ | observer collector |
| Node.js | 20+ | observer client dev/test and VS Code extension |
| npm | latest | Package management |
| uv | latest | Python example apps and skill evals |
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
| skill-evals | `make eval` (golden structural, semconv, consistency) |

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
- Skills require probabilistic evals with fuzzy verification against golden results.

## Skill Evals

Skills are evaluated with two layers: deterministic pytest tests and
LLM-based deepeval tests. All test modules live in `evals/`.
Dependencies (pytest, deepeval, boto3) are managed by `uv` with a
lockfile (`evals/pyproject.toml` and `evals/uv.lock`).

### Running evals

```sh
make eval                                            # all golden + performance tests (CI-safe)
make eval-fixture APP=examples/python/flask-basic    # post-skill fixture tests (local)
```

Or run pytest directly for finer control:

```sh
cd evals
uv run pytest                              # all tests
uv run pytest test_semconv.py -v           # semconv tests only
uv run pytest -k "performance" -v          # performance tests only
uv run pytest --app=../examples/python/flask-basic   # include fixture tests
```

### Test suites

| Test file | What it validates | LLM? |
|-----------|-------------------|-------|
| `test_structural.py` | Golden properties (language, packages) and fixture SDK init / deps | No |
| `test_semconv.py` | Metric name format, span cardinality, high-cardinality attribute scan | No |
| `test_golden.py` | Signal sections present, unique names, valid categories, golden-vs-fixture comparison | No |
| `test_performance.py` | Skill token budgets, reference budgets, combined context window limits | No |
| `test_llm.py` | Trigger routing (35 cases) and golden comparison (4 cases) via LLM-as-judge, parametrized across multiple generator models | Yes |

Tests are parametrized across all golden directories (Python, Node, Go).
Fixture-mode tests auto-skip when `--app` is not provided, making
`make eval` safe for CI.

### Adding a new eval fixture

1. Create the example app under `examples/<language>/<app-name>/`.
2. Run `/splunk-audit` (or `/splunk-observe`) to generate
   `.observe/inventory.md`.
3. Review the generated inventory for correctness.
4. Copy the signal tables and structural properties into a golden file
   at `evals/golden/<language>/<app-name>/inventory.md`.
5. Run `make eval` -- the new golden is auto-discovered by pytest.

### LLM-based evals

LLM-based evals use deepeval with Bedrock models. They require
AWS credentials.

```sh
make eval-llm                                       # all LLM evals
cd evals
uv run pytest test_llm.py -m trigger -v             # trigger tests only
uv run pytest test_llm.py -m golden -v              # golden comparison only
```

See [evals/README.md](evals/README.md) for full details on test
architecture, helpers, and the golden file format.

### CI integration

The `skill-evals` job installs `uv` via `astral-sh/setup-uv` and runs
`make eval`. See [.github/workflows/ci.yml](.github/workflows/ci.yml).
LLM-based evals (`make eval-llm`) can run in CI when AWS credentials
are configured via IAM role or secrets.

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

## Quality Tooling

Enable all automated tooling that helps maintain high-quality code:
linters, vulnerability checkers, security scanners, and similar tools.
