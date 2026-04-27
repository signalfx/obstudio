# pytest-codex-evals

Pytest plugin for running Codex evals with JSONL traces, isolated workspaces,
A/B sides, deterministic artifact checks, optional schema-constrained
qualitative grading, optional Docker runtime checks, and aggregate reports.

## What It Provides

- Pytest collection for `*_eval.json` files.
- One pytest item per `prompts[]` entry.
- Fast validation by default: schema, eval directory, and skill path.
- Optional live Codex A/B runs through TOML config.
- Deterministic checks from final text, files, JSONL traces, and command output.
- Schema-constrained qualitative grading with a configurable judge model.
- Optional Docker-backed runtime checks that can exercise a service and verify
  traces or metrics in an Observer-compatible API.
- A single aggregate report with validation, deterministic, qualitative, and
  runtime sections.

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

Deterministic checks can assert final text, files, trace command evidence, or
run local commands in the produced `service/` workspace. Command checks use an
argv list, not a shell string, so they work well with ecosystem tools:

```json
{
  "id": "go-module-has-otelhttp",
  "description": "Go module graph includes otelhttp.",
  "kind": "command_stdout_contains_all",
  "command": ["go", "list", "-mod=readonly", "-m", "all"],
  "values": ["go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"]
}
```

Other command-backed kinds are `command_succeeds`,
`command_stdout_contains_any`, and `command_stdout_contains_none`.

Runtime checks are optional because they need Docker plus a running telemetry
backend. The built-in `observer_docker_runtime` check uses the Docker Python SDK
to start containers or a small Compose file, sends traffic, then queries an
Observer-compatible API for traces and metrics:

```json
{
  "id": "observer-runtime",
  "description": "Service emits traces and metrics to Observer.",
  "kind": "observer_docker_runtime",
  "timeout_seconds": 120,
  "runtime": {
    "observer": { "base_url": "http://127.0.0.1:3000", "clear": true },
    "compose_file": "docker-compose.yml",
    "services": ["app"],
    "environment": {
      "OTEL_EXPORTER_OTLP_ENDPOINT": "http://host.docker.internal:4318",
      "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf"
    },
    "health": { "url": "http://127.0.0.1:8080/health", "expect_status": 200 },
    "traffic": [{ "method": "GET", "url": "http://127.0.0.1:8080/health", "expect_status": 200 }],
    "expect": {
      "traces": { "contains_any": ["GET /health", "http"] },
      "metrics": { "contains_any": ["http", "duration"] }
    }
  }
}
```

Runtime checks are skipped unless `[runtime].enabled = true` is set in the
TOML config or `--codex-runtime` is passed.

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

Parallelize cases with pytest-xdist:

```bash
uv run pytest -n 4 evals --skill skills/<skill-dir> --codex-eval-config codex-evals.ab.toml
```

The plugin writes per-worker result payloads and merges them into the same
aggregate reports at session finish.

Print per-item progress with:

```bash
uv run pytest -n 4 evals --codex-eval-progress --skill skills/<skill-dir> --codex-eval-config codex-evals.ab.toml
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

[runtime]
enabled = false

[models]
agent = "gpt-5.5"
judge = "gpt-5.5"
```

`[models].agent` configures the task run, `--model` overrides it, and
`[models].judge` configures the qualitative grading pass.
`[runtime].enabled` controls Docker/Observer runtime checks; the command-line
`--codex-runtime` flag can enable them for a single run.

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
.workspace/codex-evals/<skill>/<run-id>/results/<group>/<item>/<eval>/
  eval.json
  with_skill.json
  with_baseline.json
eval-reports/<skill>/AB_REPORT.md
eval-reports/<skill>/ab-benchmark.json
```

With-skill and with-baseline runs write analogous `with_skill-*` and
`with_baseline-*` artifacts.

The canonical Markdown report includes environment metadata plus separate
tables for validation, deterministic checks, qualitative checks, and runtime
checks. Live tables aggregate prompts by eval file and show with-skill and
baseline token usage and elapsed time. Baseline columns are `-` when the
selected run mode did not execute the baseline side.

For compatibility, live runs also write `.workspace/.../report.md`,
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
