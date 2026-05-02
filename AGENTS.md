# AGENTS.md

Repo instructions for Codex agents. Keep changes small, evidence-based, and
aligned with the existing project structure. Read `CONTRIBUTING.md` when you
need the full development workflow.

## Project Map

- `observer/` -- Go collector, OTLP receiver, REST API, MCP server, and React UI.
- `extension/` -- VS Code extension that packages the collector.
- `skills/` -- canonical OpenTelemetry agent skill sources.
- `.agents/skills/` -- repo-scoped Codex skill links for local use.
- `skills/otel-instrument/references/` -- language and signal references loaded by otel-instrument.
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
grade quick sanity checks, use schema-constrained rubric grading, and
optionally run Docker/Observer runtime checks.
Eval files live under `evals/`; see `evals/README.md` for the full command and
reporting model.

Use these commands:

```bash
make skill-eval-list
make eval-validation SKILL=skills/otel-audit
make eval-sanity SKILL=skills/otel-audit
make eval-rubric SKILL=skills/otel-instrument CASE=go/kvstore
make eval-runtime SKILL=skills/otel-instrument
make eval-all-ab SKILL=skills/otel-audit MODEL=gpt-5.5
```

Outputs:

- Full artifacts: `.workspace/codex-evals/<skill>/<run-id>/`
- Latest summaries: `eval-reports/<skill>/<kind>/report.md` and `benchmark.json`

## Skill Maintenance

- Keep `skills/` as the source of truth.
- Keep `.agents/skills/` as repo-local Codex discovery links only.
- Add or update evals when skill instructions change or a real failure is found.
- Keep sanity checks quick and tied to observable artifacts: files, final output,
  commands, and skill-loading guards.
- Keep A/B baseline checks simple; detailed artifact checks should default to
  `with_skill` unless a baseline assertion is intentional.
- Keep A/B skill-loading guards in the harness: `skills-loaded` for
  `with_skill`, and `skills-not-loaded` for `baseline`.
- Use rubric checks for semantic convention quality, workflow correctness,
  code minimality, and judgment-heavy requirements.
- Use runtime checks for end-to-end telemetry proof only when Docker and a
  managed Observer are expected.
- Load only the reference file needed for the detected language.

## Available Skills

| Skill | Purpose |
|---|---|
| `$otel-audit` | Read-only observability coverage scan |
| `$otel-instrument` | Add OpenTelemetry auto-instrumentation and targeted custom signals |
