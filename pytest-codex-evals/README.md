# pytest-codex-evals

Pytest plugin for running Codex evals with JSONL traces, isolated workspaces,
A/B sides, sanity artifact checks, optional schema-constrained
rubric grading, optional Docker runtime checks, and aggregate reports.

## What It Provides

- Pytest collection for eval JSON files.
- One pytest item per `prompts[]` entry.
- Fast validation by default: schema, eval directory, and skill path.
- Live Codex runs by eval kind: sanity, rubric, runtime, or combined standard checks.
- Optional A/B baseline side with `--ab`.
- Sanity checks from final text, files, and command output.
- Schema-constrained rubric grading with a configurable judge model.
- Optional Docker-backed runtime checks that can exercise a service and verify
  traces or metrics in an Observer-compatible API.
- A kind-aware aggregate report with validation plus the relevant live section.

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
evals/<suite>/<case>/eval/qual/<name>.json
evals/<suite>/<case>/eval/runtime/<name>.json
evals/<suite>/<case>/eval/sanity/<name>.json
```

The `eval/<kind>/` layout lets jobs select a global-style path pattern such as
`*/*/eval/qual` or `services/*/eval/runtime`.

If a case needs local source files or other fixtures, place them in the case
directory above `eval/`. If it does not, the case directory can contain only the
`eval/` folder.

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
  "rubric": [
    "The answer cites concrete evidence."
  ]
}
```

The plugin infers `id` and display labels from the file path when they are not
provided. The `skill` value is matched to the directory name passed with
`--skill`.

Role-specific schemas are strict:

- `eval/sanity/*.json`: `skill`, `prompts`, optional `checks`.
- `eval/qual/*.json`: `skill`, `prompts`, required `rubric`, optional `judge_prompt` and `judge_inputs`.
- `eval/runtime/*.json`: `skill`, `prompts`, required runtime `checks`.

`judge_prompt` lets a suite replace the built-in rubric judge prompt. It can
use `{case_id}`, `{prompt_id}`, `{task}`, `{rubric}`, and `{inputs}` template
fields. Use `judge_inputs` to tell the judge what artifacts matter for that
skill; the default prompt does not assume every eval has service files.

Sanity checks can assert final text, files, trace command evidence, or
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

Runtime checks are optional because they need Docker and a telemetry backend.
Each runtime check runs an eval-owned Docker Compose file, then queries an
Observer-compatible API for traces and metrics. Keep service topology, build
instructions, startup, and traffic generation in Compose. The eval JSON only
points at the Compose file and declares telemetry expectations. Compose can use
`${CODEX_EVAL_SERVICE_DIR}` when it must build the instrumented temp service
workspace instead of the source fixture.

```json
{
  "id": "observer-runtime",
  "description": "Service emits traces and metrics to Observer.",
  "compose_file": "docker-compose.yml",
  "timeout_seconds": 120,
  "expect": {
    "traces": { "span_names": ["GET /health"] },
    "metrics": { "metric_names": ["http.server.request.duration"] }
  }
}
```

The referenced Compose file should expose an `observer` service on
`127.0.0.1:3000` and a profiled one-shot `traffic` service. The harness runs:
`docker compose up -d --build`, `docker compose --profile traffic run --rm
traffic`, then `docker compose down -v --remove-orphans`.

Runtime checks run when `--codex-eval-kind runtime`, `[runtime].enabled = true`,
or `--codex-runtime` is passed.

## Commands

Validate evals without running Codex:

```bash
uv run pytest evals --skill skills/<skill-dir> --codex-eval-kind validation
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
uv run pytest evals --skill skills/<skill-dir> --codex-eval-kind sanity
uv run pytest evals --skill skills/<skill-dir> --codex-eval-kind rubric
uv run pytest evals --skill skills/<skill-dir> --codex-eval-kind runtime
```

Add the no-skill baseline side:

```bash
uv run pytest evals --skill skills/<skill-dir> --codex-eval-kind rubric --ab
```

Parallelize cases with pytest-xdist:

```bash
uv run pytest -n 4 evals --skill skills/<skill-dir> --codex-eval-kind rubric --ab
```

The plugin writes per-worker result payloads and merges them into the same
aggregate reports at session finish.

Print per-item progress with:

```bash
uv run pytest -n 4 evals --codex-eval-progress --skill skills/<skill-dir> --codex-eval-kind rubric --ab
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

Live config:

```toml
[run]
mode = "with_skill"
eval_kind = "rubric"

[rubric]
enabled = true

[runtime]
enabled = false

[models]
agent = "gpt-5.5"
judge = "gpt-5.5"
```

`[models].agent` configures the task run, `--model` overrides it, and
`[models].judge` configures the rubric grading pass.
`[runtime].enabled` controls Docker/Observer runtime checks. CLI flags override
the TOML mode for a single run:

```bash
uv run pytest evals --skill skills/<skill-dir> --codex-eval-kind runtime --ab
```

## Outputs

Validation-only runs write:

```text
.workspace/codex-evals/<skill>/<run-id>/validation-report.md
.workspace/codex-evals/<skill>/<run-id>/validation-benchmark.json
eval-reports/<skill>/validation/report.md
eval-reports/<skill>/validation/benchmark.json
```

Live A/B runs write:

```text
.workspace/codex-evals/<skill>/<run-id>/ab-report.md
.workspace/codex-evals/<skill>/<run-id>/ab-benchmark.json
.workspace/codex-evals/<skill>/<run-id>/results/<group>/<item>/<eval>/
  eval.json
  with_skill.json
  with_baseline.json
eval-reports/<skill>/<kind>/report.md
eval-reports/<skill>/<kind>/benchmark.json
```

With-skill and with-baseline runs write analogous `with_skill-*` and
`with_baseline-*` artifacts in the timestamped run directory.

The canonical Markdown report includes environment metadata plus validation and
the selected eval type's predefined template: Sanity Summary, Rubric Summary,
or Runtime Summary. Live tables aggregate prompts by eval file and show
with-skill and baseline token usage and elapsed time. Baseline columns are `-`
when the selected run mode did not execute the baseline side.

Each eval kind has its own latest `report.md` and `benchmark.json` under
`eval-reports/<skill>/<kind>/`; mode-specific summaries remain in `.workspace`.

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
