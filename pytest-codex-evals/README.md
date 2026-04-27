# pytest-codex-evals

Pytest plugin for running Codex evals with JSONL traces, isolated workspaces,
A/B sides, deterministic artifact checks, optional schema-constrained
qualitative grading, and aggregate reports.

## What It Provides

- Pytest collection for `*_eval.json` files.
- One pytest item per `prompts[]` entry.
- Fast validation by default: schema, eval directory, and skill path.
- Optional live Codex A/B runs through TOML config.
- Deterministic checks from final text, files, and JSONL traces.
- Schema-constrained qualitative grading with a configurable judge model.
- Separate validation and live A/B aggregate reports.

## Install

Install from this repository while the plugin is developed:

```toml
[project]
dependencies = ["pytest-codex-evals"]

[tool.uv.sources]
pytest-codex-evals = { path = "../pytest-codex-evals", editable = true }
```

## Eval Files

Put eval JSON files anywhere pytest can collect them:

```text
evals/<suite>/<case>/*_eval.json
```

If a case needs local source files or other fixtures, place them beside the JSON.
If it does not, the directory can contain only the eval JSON.

Minimal shape:

```json
{
  "skill": "sample-skill",
  "prompts": [
    {
      "id": "direct",
      "task": "Review the provided input and report gaps."
    }
  ],
  "deterministic_checks": [],
  "qualitative_checks": []
}
```

The plugin infers `id` and display labels from the file path when they are not
provided. The `skill` value is matched to the directory name passed with
`--skill`.

## Commands

Validate evals without running Codex:

```bash
uv run pytest evals --skill skills/<skill-dir> --codex-eval-config codex-evals.validation.toml
```

List cases:

```bash
uv run pytest evals --collect-only -q --skill skills/<skill-dir>
```

Select cases and prompts with normal pytest selection:

```bash
uv run pytest evals/go/kvstore -k runtime-preserving --skill skills/<skill-dir>
```

Run the loaded-skill side:

```bash
uv run pytest evals --skill skills/<skill-dir> --codex-eval-config codex-evals.toml
```

Run the no-skill baseline side:

```bash
uv run pytest evals --skill skills/<skill-dir> --codex-eval-config codex-evals.baseline.toml
```

Run live Codex A/B:

```bash
uv run pytest evals --skill skills/<skill-dir> --codex-eval-config codex-evals.ab.toml
```

## Config

Default validation config:

```toml
[run]
mode = "validation"
```

With-skill config:

```toml
[run]
mode = "with_skill"
```

With-baseline config:

```toml
[run]
mode = "with_baseline"
```

Live A/B config:

```toml
[run]
mode = "ab"

[qualitative]
enabled = true

[models]
agent = "gpt-5.2"
judge = "gpt-5.2"
```

`[models].agent` configures the task run, `--model` overrides it, and
`[models].judge` configures the qualitative grading pass.

## Outputs

Validation-only runs write:

```text
.workspace/codex-evals/<skill>/<run-id>/validation-report.md
.workspace/codex-evals/<skill>/<run-id>/validation-benchmark.json
eval-reports/<skill>/VALIDATION_REPORT.md
eval-reports/<skill>/validation-benchmark.json
```

Live A/B runs write:

```text
.workspace/codex-evals/<skill>/<run-id>/ab-report.md
.workspace/codex-evals/<skill>/<run-id>/ab-benchmark.json
eval-reports/<skill>/AB_REPORT.md
eval-reports/<skill>/ab-benchmark.json
```

With-skill and with-baseline runs write analogous `with_skill-*` and
`with_baseline-*` reports.

For compatibility, live A/B runs also write `.workspace/.../report.md`,
`.workspace/.../benchmark.json`, `eval-reports/<skill>/REPORT.md`, and
`eval-reports/<skill>/benchmark.json`.

## Publish

The package is versioned independently from consuming projects and can be
published from this directory.

```bash
cd pytest-codex-evals
uv lock
uv run pytest
uv build
uv publish
```

Publishing requires the standard `uv publish` credentials, such as
`UV_PUBLISH_TOKEN`.
