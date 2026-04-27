# AGENTS.md

Repo instructions for Codex agents. Keep changes small, evidence-based, and
aligned with the existing project structure. Read `CONTRIBUTING.md` when you
need the full development workflow.

## Project Map

- `observer/` -- Go collector, OTLP receiver, REST API, MCP server, and React UI.
- `extension/` -- VS Code extension that packages the collector.
- `skills/` -- canonical OpenTelemetry agent skill sources.
- `.agents/skills/` -- repo-scoped Codex skill links for local use.
- `skills/references/` -- shared language and signal references loaded on demand.
- `evals/` -- fixture services and JSON eval cases collected by pytest.
- `pytest-codex-evals/` -- reusable pytest plugin for Codex eval harnessing.
- `eval-reports/` -- latest summarized eval reports.
- `docs/` -- design docs and usage notes.

## Working Rules

- Read surrounding code before editing.
- Match existing style, patterns, and ownership boundaries.
- Prefer editing existing files over adding new files.
- Avoid drive-by refactors and narration comments.
- Use `rg` for search.
- Use `npm` for JavaScript work and respect lockfiles.
- Use `uv` and `pytest` for the Python eval harness.
- Never revert unrelated user changes.

## Testing

- Add or update tests when behavior changes.
- Run the narrowest relevant test first, then broader tests when risk warrants it.
- Treat flaky tests as bugs.

Common targets:

```bash
make test
make test-client
make test-extension
make test-eval-harness
make test-pytest-plugin
```

## Skill Evals

Skill evals follow the OpenAI eval-skill maintenance pattern: run real tasks,
capture traces, grade deterministic outcomes, and use schema-constrained
qualitative grading.

Eval files live next to their fixture services:

```text
evals/<language>/<service>/audit_eval.json
evals/<language>/<service>/instrument_eval.json
```

Each eval file contains a `prompts[]` array of task variants. `skill-eval`
validates JSON and fixture shape; `skill-eval-ab` runs each variant as
`with_skill` and `baseline`. `PROMPT=<id>` filters to one variant.

Use these commands:

```bash
make skill-eval-list
make skill-eval SKILL=skills/otel-audit
make skill-eval SKILL=skills/otel-instrument CASE=go/kvstore
make skill-eval SKILL=skills/otel-instrument CASE=go/kvstore PROMPT=direct
make skill-eval-ab SKILL=skills/otel-audit MODEL=gpt-5.2 NO_QUALITATIVE=1
make skill-eval-all
```

`skill-eval-ab` runs A/B comparisons:

- `with_skill`: copied fixture plus temporary `.agents/skills` entries.
- `baseline`: same copied fixture with no repo skills visible.

Outputs:

- Full artifacts: `.workspace/codex-evals/<skill>/<run-id>/`
- Latest summaries: `eval-reports/<skill>/REPORT.md` and `benchmark.json`

## Skill Maintenance

- Keep `skills/` as the source of truth.
- Keep `.agents/skills/` as repo-local Codex discovery links only.
- Add or update evals when skill instructions change or a real failure is found.
- Keep deterministic checks tied to observable artifacts: files, final output,
  commands, JSONL traces, and baseline contamination checks.
- Keep A/B baseline checks simple; detailed artifact checks should default to
  `with_skill` unless a baseline assertion is intentional.
- Keep A/B skill-loading guards in the harness: `skills-loaded` for
  `with_skill`, and `skills-not-loaded` for `baseline`.
- Use qualitative checks for semantic convention quality, workflow correctness,
  code minimality, and judgment-heavy requirements.
- Load only the reference file needed for the detected language.

## Available Skills

| Skill | Purpose |
|---|---|
| `$otel-audit` | Read-only observability coverage scan |
| `$otel-instrument` | Add OpenTelemetry auto-instrumentation and targeted custom signals |
