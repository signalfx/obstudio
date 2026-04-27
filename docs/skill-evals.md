# Codex Skill Eval Framework

## What It Is

The skill eval system tests `$otel-audit` and `$otel-instrument` with Codex. It
follows the OpenAI eval pattern: run the agent, capture `codex exec --json`
traces, grade deterministic behavior, and use schema-constrained qualitative
grading where rules alone are too weak.

Each eval is:

```text
prompt + fixture service -> pytest validation
prompt + fixture service -> live Codex trace + artifacts -> deterministic + qualitative + optional runtime checks -> report
```

## Layout

Fixture apps and eval definitions live together:

```text
evals/
  go/chi-basic/
    audit_eval.json
    instrument_eval.json
    ...
  node/express-basic/
    audit_eval.json
    instrument_eval.json
  python/flask-basic/
    audit_eval.json
    instrument_eval.json

pytest-codex-evals/
  src/pytest_codex_evals/
    schemas/
  tests/
```

The eval definitions use JSON instead of CSV because these cases need more than
prompt text: fixture metadata, prompt variants, deterministic checks, artifact
paths, qualitative checks, and optional runtime check config. CSV is fine for a
small prompt list, but JSON keeps each service eval self-contained and
machine-validated.

Each eval has a `prompts[]` array of task variants. The pytest plugin collects
each `*_eval.json` file directly and expands every variant into its own pytest
item. For each live case, the harness runs two sides:

- `with_skill`: prefixes the task with `Use the $<skill> skill.`
- `baseline`: runs the task as written, with no skill name and no repo skills visible

## A/B Runs

Each case runs twice with the same model and same copied fixture:

| Side | Skill visibility | Prompt |
|---|---|---|
| `with_skill` | Temporary `.agents/skills` links are present | Explicitly invokes `$otel-audit` or `$otel-instrument` |
| `baseline` | No repo skills are present | Same task intent without naming the skill |

The execution workspaces are created outside the repository so the baseline
cannot discover repo-scoped skills by walking up to the repo root. After each
run, artifacts are copied back under `.workspace/codex-evals/`.

## Grading

Deterministic grading uses Python over files, JSONL traces, and command output:

- final response text checks
- expected file creation and manifest edits
- command execution evidence from `codex exec --json`
- command count and token usage from trace events
- baseline contamination checks for accidental skill visibility

Checks default to `with_skill`, keeping the A/B baseline simple. Baseline runs
only need to prove run health and skill isolation unless a check explicitly sets
`applies_to` to `baseline` or `both`.

Runtime checks use `observer_docker_runtime`. They are skipped by default and
only run when `[runtime].enabled = true` or `--codex-runtime` is set. The check
uses the Docker Python SDK to start containers or a Compose file, sends traffic,
then queries a running Observer API for trace and metric evidence.

The harness also adds setup guards to every run:

- `skills-loaded`: the `with_skill` side exposes repo skills under `.agents/skills/`.
- `skills-not-loaded`: the `baseline` side does not expose repo skills or reference them in traces.

Qualitative grading runs a second read-only Codex pass with the schema packaged
by `pytest-codex-evals`. It uses the eval JSON's `qualitative_checks` and the
judge model configured in `codex-evals*.toml`; the task-run model is configured
as `[models].agent`.

## Commands

```bash
make test-eval-harness
make test-pytest-plugin
make skill-eval-list
make eval-validation SKILL=skills/otel-audit
make eval-with-skill SKILL=skills/otel-instrument CASE=go/kvstore
make eval-with-baseline SKILL=skills/otel-instrument CASE=go/kvstore
make eval-ab SKILL=skills/otel-audit MODEL=gpt-5.5 NO_QUALITATIVE=1
make eval-with-skill SKILL=skills/otel-instrument CASE=python/fastapi-celery EVAL_RUNTIME=1
make eval-all SKILL=skills/otel-audit CASE=go/chi-basic PROMPT=direct
```

`eval-validation` validates JSON and fixture shape only. `eval-with-skill` and
`eval-with-baseline` each run one Codex side and grade deterministic plus
qualitative checks. The live A/B command is:

```bash
cd evals && uv run pytest <language>/<service> -k "<prompt-id>" --skill "../skills/<skill-dir>" --codex-eval-config codex-evals.ab.toml
```

The reusable pytest plugin lives in `pytest-codex-evals/`. It owns the generic
Codex controls (`--skill`, `--codex-eval-config`, `--model`,
`--no-qualitative`, `--codex-runtime`), JSON eval collection, validation, side
execution, A/B execution, and reporting. Service selection is plain pytest path
selection, prompt selection is plain `-k` filtering, and `--skill` points to a
skill directory containing `SKILL.md`.

Build and publish it with:

```bash
make build-pytest-plugin
make publish-pytest-plugin
```

## Outputs

Full artifacts are ignored by git:

```text
.workspace/codex-evals/<skill>/<run-id>/
  benchmark.json
  report.md
  validation-benchmark.json
  validation-report.md
  with_skill-benchmark.json
  with_skill-report.md
  with_baseline-benchmark.json
  with_baseline-report.md
```

Live A/B runs also include:

```text
.workspace/codex-evals/<skill>/<run-id>/
  ab-benchmark.json
  ab-report.md
  cases/<language>/<service>/<prompt-id>/
    with_skill/
      service/
      trace.jsonl
      last_message.md
      deterministic_grade.json
      qualitative_grade.json
      summary.json
    baseline/
      service/
      trace.jsonl
      last_message.md
      deterministic_grade.json
      qualitative_grade.json
      summary.json
```

The canonical latest summary is copied to:

```text
eval-reports/<skill>/REPORT.md
eval-reports/<skill>/benchmark.json
```

Mode-specific summaries stay in the timestamped `.workspace` run directory.
The canonical latest report has separate tables for validation, deterministic,
qualitative, and runtime results; live tables include with-skill, baseline,
token, and elapsed-time columns.

## Maintenance Rules

- Add an eval when a skill behavior changes or a real failure is found.
- Keep deterministic checks focused on behavior that can be proven from files,
  traces, commands, and final output.
- Use runtime checks only for end-to-end telemetry proof that needs Docker and a
  running Observer.
- Use qualitative checks for style, semantic convention quality, and workflow
  correctness.
- Keep full traces out of git; commit only durable eval definitions, harness
  code, and intentionally reviewed summary reports.
