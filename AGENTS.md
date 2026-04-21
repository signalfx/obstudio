# AGENTS.md

Guidelines for AI agents working in this repo. Read `CONTRIBUTING.md` for the full dev process.

## Repo Layout

- `observer/` -- Observer: Go backend with OTLP receiver, REST API, MCP server, Web UI, and self-contained React client
- `extension/` -- VS Code extension that packages the Observer
- `skills/` -- agent skills (composable observability workflows)
- `skills/references/` -- shared language guides and reference material (loaded on-demand by skills)
- `skills/*/evals/` -- skill evaluation definitions (evals.json per skill)
- `examples/` -- sample apps for testing and skill evaluation, organized by language
- `docs/` -- design docs and examples

## Code

- Match existing style, patterns, and conventions. Read before writing.
- Edit existing files; don't create new ones unless necessary.
- No narration comments. Only document non-obvious intent.
- Minimal, focused changes. No drive-by refactors.
- Use `npm`. Respect lockfiles. Justify new dependencies.

## Testing

- Every change must include tests for the new or changed functionality.
- All tests run in CI. Failing tests block merge. Flaky tests are bugs -- fix immediately.

### Skill Evals

Each skill has an `evals/evals.json` file defining evaluation cases:

- Each eval specifies a prompt, target app, expected output, and concrete expectations.
- Expectations validate instrumentation output: SDK init files, dependency additions, and start-command wiring.
- Example apps in `examples/` serve as test fixtures.
- Run evals via `make skill-eval SKILL=otel-instrument`.

## PRs

- Accurate, concise descriptions (under one page). Commit message mirrors the description.
- Include the agent plan. If too large, commit it as a design doc under `docs/`.

## Skills

Skills follow the [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
anatomy: frontmatter (`name`/`description`), Overview, When to Use, Process, Red Flags,
Verification. See any skill under `skills/` for the canonical format.

### Available Skills

| Skill | Purpose |
|-------|---------|
| `/otel-instrument` | Add OTel auto-instrumentation and optional custom spans/metrics to a service |
| `/otel-audit` | Scan a codebase for observability coverage and report gaps (read-only) |

### Shared References

Language-specific guides and reference material live in `skills/references/`,
shared across all skills:

```
skills/references/
├── languages/
│   ├── go.md
│   ├── java.md
│   ├── node.md
│   └── python.md
└── signal-mapping-guide.md
```

Skills load references on-demand. Only the file matching the detected
language is loaded -- never all at once. This keeps token usage minimal.

### Skill Design

- `/otel-instrument` is the primary skill. It follows a linear workflow: preflight scan, auto-instrumentation, optional custom instrumentation, lightweight verification.
- `/otel-audit` is a read-only companion that reports on current observability posture without modifying code.
- Skills are independent -- neither requires the other to run first.
