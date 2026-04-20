# AGENTS.md

Guidelines for AI agents working in this repo. Read `CONTRIBUTING.md` for the full dev process.

## Repo Layout

- `observer/` -- Observer: Go backend with OTLP receiver, REST API, MCP server, Web UI, and self-contained React client
- `extension/` -- VS Code extension that packages the Observer
- `skills/` -- agent skills (composable observability workflows)
- `skills/references/` -- shared language guides and reference material (loaded on-demand by skills)
- `tests/` -- skill evaluation suite (deterministic pytest + LLM-based deepeval)
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
- Use code coverage analysis to find gaps and generate tests for uncovered paths.
- All tests run in CI. Failing tests block merge. Flaky tests are bugs -- fix immediately.
- Skills require probabilistic evals with fuzzy verification against golden results.

### Skill Evals

Two layers live in `tests/`:

| Layer | Tool | Command |
|-------|------|---------|
| Deterministic | pytest | `make pytest` (CI-safe) |
| LLM-based | deepeval (pytest) + Bedrock | `make ab-test` (requires AWS creds) |

- Deterministic tests validate structure, semconv, golden consistency, and token budgets.
- LLM tests use deepeval's GEval (LLM-as-judge) with Bedrock Claude for trigger routing and golden comparison.
- All test data (models, trigger cases, golden cases) are inline `pytest.param` tables in `test_llm.py`.
- Tests are parametrized across multiple generator models for cross-model comparison.
- Golden references live in `tests/golden/<language>/<app>/inventory.md`.
- Dependencies are managed by `uv` (`tests/pyproject.toml` + `tests/uv.lock`).

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
| `/splunk-audit` | Analyze a codebase for observability gaps, produce `.observe/inventory.md` |
| `/splunk-instrument` | Implement OTel instrumentation for signals identified by `/splunk-audit` |
| `/splunk-verify` | Validate telemetry against the Observer collector |
| `/splunk-provision` | Generate Terraform dashboards, detectors, and alert rules |
| `/splunk-observe` | Composite orchestrator: audit -> instrument -> verify -> provision |

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
- `/splunk-audit` creates it (SLI definitions, signal tables, placeholders for terraform/alerts)
- `/splunk-instrument` updates the Status column in the Spans, Metrics, and Logs tables
- `/splunk-verify` updates the Verified column in the Spans, Metrics, and Logs tables
- `/splunk-provision` populates `terraform/`, `alerts/`, and inventory sections 10-11
