# AGENTS.md

Guidelines for AI agents working in this repo. Read `CONTRIBUTING.md` for the full dev process.

## Repo Layout

- `observer-go/` -- Observer: Go backend with OTLP receiver, REST API, MCP server, Web UI, and self-contained React client
- `extension/` -- VS Code extension that packages the Observer
- `skills/` -- agent skills (composable observability workflows)
- `skills/references/` -- shared language guides and reference material (loaded on-demand by skills)
- `demo/` -- sample apps for testing and skill evaluation
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

Skills follow the [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
anatomy: frontmatter (`name`/`description`), Overview, When to Use, Process, Red Flags,
Verification. See any skill under `skills/` for the canonical format.

### Available Skills

| Skill | Purpose |
|-------|---------|
| `/audit` | Analyze a codebase for observability gaps, produce `.observe/inventory.md` |
| `/instrument` | Implement OTel instrumentation for KPIs identified by `/audit` |
| `/verify` | Validate telemetry against the Observer collector |
| `/provision` | Generate Terraform dashboards, detectors, and alert rules |
| `/observe` | Composite orchestrator: audit -> instrument -> verify -> provision |

### Shared References

Language-specific guides and reference material live in `skills/references/`,
shared across all skills:

```
skills/references/
├── languages/
│   ├── go.md
│   ├── node.md
│   └── python.md
├── fault-domain-patterns.md
├── signal-mapping-guide.md
└── observability-template.md
```

Skills load references on-demand. Only the file matching the detected
language is loaded -- never all at once. This keeps token usage minimal.

### Skill Contract

All skills operate on the same `.observe/` directory:
- `/audit` creates it (inventory, placeholders for terraform/alerts)
- `/instrument` updates the KPI table Status column
- `/verify` updates the KPI table Verified column
- `/provision` populates `terraform/`, `alerts/`, and inventory sections 7-8
