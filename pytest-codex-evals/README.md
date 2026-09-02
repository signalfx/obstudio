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
  traces, metrics, logs, and preserved service output through an
  Observer-compatible API and Docker Compose.
- Separate raw JSON execution output and kind-specific Markdown/benchmark reports.

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

### 0.2 runtime-expectation migration

Version 0.2 makes the public runtime `expect` object strict so misspelled
assertions cannot be silently ignored. Remove unknown keys before upgrading and
use `service_logs` for preserved stdout/stderr assertions. A runtime check must
declare at least one non-empty `endpoints` or `service_logs` list; an explicitly
empty `endpoints` list remains valid when `service_logs` is non-empty.

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
Observer-compatible API for telemetry and can inspect preserved service output.
Keep service topology, build instructions, startup, and traffic generation in
Compose. The eval JSON only points at the Compose file and declares telemetry
expectations. Compose can use `${CODEX_EVAL_SERVICE_DIR}` when it must build the
instrumented temp service workspace instead of the source fixture.

```json
{
  "id": "observer-runtime",
  "description": "Service emits a correlated log and preserves console output.",
  "compose_file": "docker-compose.yml",
  "timeout_seconds": 120,
  "environment": {
    "CODEX_EVAL_OTEL_LOGS_EXPORTER": ""
  },
  "stop_services_before_validation": ["app"],
  "expect": {
    "endpoints": [
      {
        "id": "logs",
        "url": "/api/query/logs",
        "record_checks": [
          {
            "id": "request-log",
            "match": { "body": "request completed" },
            "field_equals": {
              "resource.serviceName": "sample-service"
            },
            "non_empty": ["traceId", "spanId"],
            "exact_count": 1,
            "unique_by": ["traceId", "spanId"],
            "correlates_with_trace": true
          }
        ]
      }
    ],
    "service_logs": [
      {
        "id": "preserved-console-sink",
        "service_name": "app",
        "occurrences": { "request completed": 1 }
      }
    ]
  }
}
```

Use `endpoints` for Observer API responses and `record_checks` when all asserted
fields must belong to the same JSON record. `service_logs` verifies retained
stdout or stderr output. Per-check `environment` values select isolated runtime
scenarios, while `stop_services_before_validation` can stop only `app` so its
shutdown-flushed telemetry is available before Observer assertions run.

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

Pytest runs write raw JSON only:

```text
.workspace/codex-evals/<skill>/<run-id>/
  run.json
  runs/
    validation.json
    sanity-with_skill.json
    sanity-ab.json
    rubric-with_skill.json
    runtime-with_skill.json
  results/<group>/<item>/<eval>/
    eval.json
    with_skill.json
    with_baseline.json
```

Reports are rendered separately from those raw files:

```bash
uv run codex-eval-harness report --repo-root . --skill <skill-id> --kind sanity
```

The report step writes `<kind>/report.md` and `<kind>/benchmark.json` in the
timestamped run directory and copies the latest summary to
`eval-reports/<skill>/<kind>/`.

Report benchmarks include a SHA-256 manifest of the canonical skill tree, the
collected eval definitions, their staged fixtures and prompt-selected inputs,
eval configuration, harness package code and schemas, and locked harness
dependencies. Filtered runs remain scoped to their collected cases; full
validation also detects newly added matching definitions. Verify tracked
manifests without invoking an agent or judge with:

```bash
uv run codex-eval-harness verify-reports --repo-root .
```

Each `benchmark.json` is kind-specific. Sanity reports contain only sanity
check fields, rubric reports contain only rubric judge fields, and runtime
reports contain only runtime check fields. Baseline columns are empty when a
baseline side was not run.

### Token usage

Live run artifacts retain the backward-compatible `tokens`, `agent_tokens`,
and `rubric_tokens` fields and also include optional `agent_usage` and
`rubric_usage` objects. The normalized objects report input, cached input,
cache-creation input, output, reasoning output, the provider-reported total,
and an independently derived input-plus-output total.

Codex input and output counts remain provider-inclusive totals; cached input,
cache creation, and reasoning output are breakdowns and are not subtracted.
Claude input is normalized from uncached input plus cache-read and
cache-creation input, while output remains the provider's inclusive output
count. A cumulative provider record takes precedence over per-turn records so
the same work is not counted twice. If no cumulative record is recognized,
complete incremental records are summed.

Markdown and benchmark reports include measurement coverage. `unknown` means a
field was absent or could not be recognized and is distinct from an explicitly
reported `0`; partial aggregates include the number of prompts that measured
each field. A row is measured only when every prompt has a provider-reported
total or a complete independently derived total; recognized fragments without
a preferred total remain partial and the aggregate total remains unknown.
Agent/task usage and rubric/judge usage remain separate, and judge usage is
rendered only in rubric reports. Codex and Claude judge subprocesses disable
OTel export, so globally configured provider telemetry cannot put grading usage
into Observer's agent/task ring; judge usage is still parsed from the subprocess
trace for the rubric report.

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
