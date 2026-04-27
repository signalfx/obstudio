# pytest-codex-evals

Pytest plugin for running Codex evals with JSONL traces, isolated workspaces,
A/B sides, deterministic artifact checks, optional schema-constrained
qualitative grading, and aggregate reports.

## What It Provides

- Pytest collection for `*_eval.json` files.
- One pytest item per `prompts[]` entry.
- Fast validation by default: schema, fixture directory, and skill path.
- Optional live Codex A/B runs through TOML config.
- Deterministic checks from final text, files, and JSONL traces.
- Schema-constrained qualitative grading with a configurable judge model.
- Aggregate `report.md` and `benchmark.json` outputs.

## Install

Install from this repository while the plugin is developed:

```toml
[project]
dependencies = ["pytest-codex-evals"]

[tool.uv.sources]
pytest-codex-evals = { path = "../pytest-codex-evals", editable = true }
```

## Eval Files

Put eval JSON files next to fixture services:

```text
evals/<domain>/<fixture>/*_eval.json
```

Minimal shape:

```json
{
  "skill": "sample-skill",
  "prompts": [
    {
      "id": "direct",
      "task": "Inspect ./service and report gaps."
    }
  ],
  "deterministic_checks": [],
  "qualitative_checks": []
}
```

The plugin infers `id`, `language`, and `service` from the file path. The
`skill` value is matched to the directory name passed with `--skill`.

## Commands

Validate evals without running Codex:

```bash
uv run pytest evals --skill skills/<skill-dir>
```

List cases:

```bash
uv run pytest evals --collect-only -q --skill skills/<skill-dir>
```

Select fixtures and prompts with normal pytest selection:

```bash
uv run pytest evals/go/kvstore -k runtime-preserving --skill skills/<skill-dir>
```

Run live Codex A/B only when explicitly configured:

```bash
uv run pytest evals --skill skills/<skill-dir> --codex-eval-config codex-evals.ab.toml
```

## Config

Default validation config:

```toml
[run]
live_ab = false
```

Live A/B config:

```toml
[run]
live_ab = true

[qualitative]
enabled = true

[models]
agent = "gpt-5.2"
judge = "gpt-5.2"
```

`[models].agent` configures the task run, `--model` overrides it, and
`[models].judge` configures the qualitative grading pass.

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
