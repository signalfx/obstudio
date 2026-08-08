# AGENTS.md

Repo instructions for coding and reviewing agents. Keep changes small,
evidence-based, and aligned with the existing project structure. Read
`CONTRIBUTING.md` before coding or reviewing; it owns the full development and
pull request workflow.

## Project Map

- `observer/` -- Go collector, OTLP receiver, REST API, MCP server, and React UI.
- `extension/` -- VS Code-compatible extension for Visual Studio Code, Kiro, and Cursor that packages the collector.
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

## Coding Agent Definition of Done

Before handing work back:

- Keep the final diff focused on the requested scope. Re-read the request,
  inspect the diff against the merge base, and remove unrelated edits without
  disturbing pre-existing user work.
- Add or update the narrowest useful test when behavior changes. Use available
  coverage output to find untested changed branches; do not chase an arbitrary
  repository-wide percentage with unrelated tests.
- Run the narrowest relevant check first, followed by the broader checks that
  match the risk and the applicable nested `AGENTS.md` file.
- For skill behavior changes, update the canonical source under `skills/` and
  add or update the smallest relevant eval. If existing coverage is sufficient,
  record why.
- In the handoff, list changed behavior, exact validation commands and results,
  skipped checks with reasons, and any residual risk.

## Reviewer Routing

Apply this file and every more-specific instruction file that covers the
changed path:

- `observer/AGENTS.md` -- Go collector, OTLP, REST, MCP, storage, and serving.
- `observer/client/AGENTS.md` -- React Telemetry Explorer.
- `extension/AGENTS.md` -- VS Code-compatible editor extension and packaging.
- `skills/AGENTS.md` -- canonical skill sources and skill-level tests.
- `evals/AGENTS.md` -- eval fixtures, checks, configs, and reports.

Treat review as read-only unless the user explicitly asks for fixes. Review the
merge-base diff, start with actionable findings ordered by severity, and focus
on correctness, regressions, security, data loss, and missing proof. Each
finding must cite a narrow file and line range, explain the concrete failure
mode, and describe the smallest safe correction path. Name the applicable
`OBS-*` rule when the finding concerns a repository-specific rule; ordinary
correctness, security, or reliability defects do not need a forced rule ID. Do
not report style-only nits. If there are no findings, say so and identify any
tests or risks that remain unverified.

## Code Review Rules

### OBS-SCOPE -- Keep the diff within the requested scope

Flag changes that do not serve the stated goal, cross an ownership boundary
without need, or edit generated/vendor output instead of its source. The safe
path is to remove or split unrelated work while preserving pre-existing user
changes.

### OBS-TEST -- Prove changed behavior

Flag behavior changes without a focused regression test, checks that do not
exercise the changed failure path, or unsupported claims that validation
passed. Documentation-only changes may use structural and link checks instead
of product tests. The safe path is the smallest relevant test or static check,
followed by the exact command and result. Use coverage to locate missed changed
branches, not as an arbitrary global threshold.

### OBS-SKILL -- Keep skill sources, discovery, and evals aligned

Flag skill behavior edited outside canonical `skills/`, missing or mismatched
discovery links, and behavior changes without an eval update or a documented
reason that existing coverage is sufficient. Every `.agents/skills/<name>`
entry must be a relative link to `../../skills/<name>`, and the Available
Skills table below must match canonical `skills/*/SKILL.md` directories. The
safe path is to edit the canonical source, repair the relative link or table,
and add the narrowest meaningful eval.

### OBS-PRESERVE -- Preserve compatibility and user work

Flag changes that silently remove supported behavior, public API or schema
compatibility, persisted data, telemetry semantics, supported platforms, or
unrelated user work. The safe path is a backward-compatible change; when that
is impossible, require an explicit migration or rollback path and regression
proof.

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

## Confluence Document Updates

- Use Confluence ADF/API structural updates whenever possible.
- Before publishing, validate that tables contain no headings, heading order is
  correct, and all expected tables and images are present.
- Use Chrome only for the final **Update without notifying watchers** action
  when the API cannot suppress watcher notifications.
- If the Confluence API token path returns permission errors, use browser repair
  as a fallback and validate the published DOM before finishing.

## Available Skills

| Skill | Purpose |
|---|---|
| `$otel-audit` | Read-only observability coverage scan |
| `$otel-instrument` | Add OpenTelemetry auto-instrumentation and targeted custom signals |
| `$otel-verify` | Prove instrumentation with project-runtime, app-code, and optional OTLP checks |
| `$splunk-configure` | Generate Splunk O11y detector Terraform from audit report |
| `$splunk-dashboard` | Generate Splunk O11y dashboard Terraform from audit and verification reports |
| `$splunk-detector-publish` | Diff local detector Terraform against live Splunk detectors and create only the gaps |
| `$splunk-dashboard-publish` | Diff local dashboard Terraform against live Splunk dashboards and create only the gaps |
| `$splunk-sync` | (deprecated, use `$splunk-detector-publish`) Backward-compatible alias |
| `$splunk-dashboard-sync` | (deprecated, use `$splunk-dashboard-publish`) Backward-compatible alias |
