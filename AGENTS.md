# AGENTS.md

Guidelines for AI agents working in this repo. Read `CONTRIBUTING.md` for the full dev process.

## Repo Layout

- `observer/` -- Observer app (React client, Node/Express server, shared OTLP bindings)
- `extension/` -- VS Code extension that packages the Observer
- `skills/` -- agent skills (e.g., OpenTelemetry instrumentation)
- `docs/` -- design docs and examples

## Code

- Match existing style, patterns, and conventions. Read before writing.
- Edit existing files; don't create new ones unless necessary.
- No narration comments. Only document non-obvious intent.
- Minimal, focused changes. No drive-by refactors.
- Use `npm`. Respect lockfiles. Justify new dependencies.

## Testing

- Every change must include tests for the new or changed functionality.
- Use code coverage analysis to find gaps and generate tests for uncovered paths.
- All tests run in CI. Failing tests block merge. Flaky tests are bugs -- fix immediately.
- Skills require probabilistic evals with fuzzy verification against golden results.

## PRs

- Accurate, concise descriptions (under one page). Commit message mirrors the description.
- Include the agent plan. If too large, commit it as a design doc under `docs/`.

## Skills

Follow the pattern in `skills/observe/SKILL.md`:

- `SKILL.md` entry point with `name`/`description` frontmatter.
- Define workflow, implementation rules, and verification checklist.
- Language-specific guidance in `languages/<lang>.md`, loaded on-demand.
- Reference material in `references/`, loaded only when a workflow step needs it.
- Each skill must have automated tests and evals.
