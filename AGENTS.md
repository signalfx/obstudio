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
- For every addition or modification to shipped skill content, update the
  canonical source under `skills/`, add or semantically update at least one
  matching rubric eval under `evals/*/*/eval/qual/` (or
  `evals/*/*/eval/rubric/`), and run a representative local rubric command such
  as `make eval-rubric SKILL=skills/otel-instrument CASE=go/kvstore`. Record the
  exact command and result. Validation-only collection is required too, but it
  does not replace a rubric run. Shipped content means a skill's `SKILL.md`,
  references, scripts, and assets; test-only changes are not skill behavior.
  Effectively equivalent rubric edits do not satisfy this requirement. This
  includes formatting or key-order changes, same-case relocation, prompt
  reordering, identity-only ID changes, language/service-only metadata changes,
  and omitted-versus-empty input defaults. For a complete skill retirement, remove
  all tracked and non-ignored canonical content, the discovery link, Available
  Skills row, matching eval definitions, and tracked
  `eval-reports/<skill>/` artifacts;
  remove the retired skill from every shared-reference consumer list, deleting
  a map key only when its shared reference is also removed; and update related
  aliases or documentation. Run `make agent-policy-check` and
  `make test-eval-harness`; a local rubric run is not required for a skill that
  no longer exists. Deleting shipped content from a retained skill remains a
  modification and still needs semantic rubric coverage and a local rubric run.
  Ignored local caches are outside the repository contract and need not be
  deleted.
  For shared `skills/references/` changes, identify every affected skill and
  keep `skills/references/consumers.json` aligned, then update and run a
  relevant rubric eval for every retained declared consumer. A consumer retired
  in the same diff follows the complete-retirement cleanup exception instead.
- For UI changes, exercise the affected workflow rather than only rendering
  markup. When the changed flow contains text fields, selects/drop-downs,
  actions, state transitions, or persisted values, prove those affected
  behaviors. Preserve accessible names and roles plus the applicable keyboard
  and focus path. Visually inspect material visual changes at normal and narrow
  widths and in relevant themes, using existing typography, spacing, and
  control sizing so the result is legible, balanced, and neither oversized nor
  cramped.
- For plugin or agent-integration changes, preserve existing public contracts
  and user-owned configuration. Prove the new or changed path alongside at
  least one existing path. When discovery, shared state, lifecycle, execution,
  or multi-target orchestration changes, include a failure case where the
  affected plugin or integration fails without preventing unrelated plugins,
  later integration targets, or the core Observer from continuing safely when
  the host supports that isolation.
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
- `pytest-codex-evals/AGENTS.md` -- reusable pytest plugin and compatibility.

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
discovery links, and any addition or modification to shipped skill content
without a matching rubric eval change and a recorded local rubric run. Every
`.agents/skills/<name>` entry must be a relative link to
`../../skills/<name>`, and the Available Skills table below must match
canonical `skills/*/SKILL.md` directories. The safe path is to edit the
canonical source, repair the relative link or table, add or semantically update
the narrowest matching rubric eval, run
`make eval-rubric SKILL=skills/<name> CASE=<language>/<service>`, and report the
exact result. `eval-validation` alone is not rubric proof. Every shipped shared
reference must appear in `skills/references/consumers.json`; a shared-reference
change requires a changed matching rubric for every retained current or prior
declared consumer; a concurrently retired consumer follows the complete-skill
cleanup exception. Formatting, key ordering, same-case relocation, prompt
reordering, identity-only IDs, language/service-only metadata changes, and empty
default fields are effectively equivalent for coverage rather than semantic eval
updates. A complete skill
retirement instead removes all tracked and non-ignored canonical content,
discovery/table entries, matching eval definitions, tracked eval reports, the
retired skill's consumer-list memberships, and related compatibility surfaces,
then proves the cleanup with agent-policy and eval-harness validation; delete a
consumer-map key only when its shared reference is also removed, and do not
require an impossible rubric run for the removed skill. A deletion inside a
retained skill still follows the normal rubric-update and local-run rule.

### OBS-PRESERVE -- Preserve compatibility and user work

Flag changes that silently remove supported behavior, public API or schema
compatibility, persisted data, telemetry semantics, supported platforms, or
unrelated user work. The safe path is a backward-compatible change; when that
is impossible, require an explicit migration or rollback path and regression
proof.

### OBS-UI -- Prove functional, accessible, and visually balanced UI behavior

Flag UI changes when text fields cannot accept or edit valid values,
select/drop-down controls omit or misapply supported options, actions or state
transitions do not work, or affected loading, empty, and error states are
unproven. Also flag lost semantic names/roles, keyboard or focus behavior,
clipping, overflow, unreadable contrast, weak hierarchy, or layouts and control
sizes that become oversized, undersized, or unusable at supported widths or
themes. The safe path is focused role/name and interaction assertions plus
rendered screenshots or documented manual visual inspection for material
visual changes. CSS/source-string assertions are supplemental, not visual
proof.

### OBS-PLUGIN -- Keep plugins isolated and backward-compatible

Flag new or modified plugin support that changes existing plugin discovery,
registration, CLI/config defaults, schemas, public imports, aliases, caches, or
run state without compatibility proof, or lets one plugin's load or execution
failure prevent unrelated plugins from running where the host supports
independent continuation. The safe path is additive, isolated behavior with
new-plus-existing compatibility proof; add failure-path tests when discovery,
shared state, lifecycle, or execution changes. Breaking public contracts
require explicit versioning, migration, and rollback guidance.

### OBS-INTEGRATION -- Isolate agent integrations and preserve host state

Flag changes to Claude Code, Codex, Cursor, Kiro, Copilot, or other agent/editor
integrations that assume a shared schema, overwrite unrelated settings,
servers, skills, or policy fields, or allow one automatic target failure to
prevent later targets or stop the core Observer. The safe path preserves every
target's schema and user-owned state, keeps successful targets configured,
reports failures per target, and proves a mixed-target path where a middle
integration fails while earlier and later integrations continue. Explicit
single-target commands may fail clearly, but must not corrupt other targets.

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
- For every addition or modification to shipped skill content, add or
  semantically update a matching rubric eval and run the representative local
  `make eval-rubric SKILL=skills/<name> CASE=<language>/<service>` command.
  Effective-equivalent formatting, relocation, identity/default metadata, or
  prompt ordering is not a semantic update. A complete retirement instead
  removes all tracked and non-ignored skill content, discovery/table entries,
  matching eval definitions, tracked eval reports, the retired skill's
  consumer-list memberships, and related compatibility surfaces, then runs
  agent-policy and eval-harness validation. Delete a consumer-map key only when
  its shared reference is also removed; no local rubric run is needed for the
  absent skill.
- Keep `skills/references/consumers.json` exact when shared behavior is added,
  removed, renamed, or consumed by another skill.
- Run `make eval-validation SKILL=skills/<name>` as the deterministic schema and
  fixture check; do not present it as a substitute for the rubric result.
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
