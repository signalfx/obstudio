# Codex Skill Eval Framework

## What It Is

The skill eval system tests `$otel-audit` and `$otel-instrument` with Codex. It
follows the OpenAI eval pattern: run the agent, capture `codex exec --json`
traces, grade sanity behavior, and use schema-constrained rubric
grading where rules alone are too weak.

Each eval is:

```text
prompt + fixture service -> pytest validation
prompt + fixture service -> live Codex trace + artifacts -> sanity + rubric + optional runtime checks -> report
```

## Layout

Fixture apps and eval definitions live together:

```text
evals/
  go/chi-basic/
    eval/
      qual/
        audit.json
        instrument.json
    ...
  node/express-basic/
    eval/qual/
      audit.json
      instrument.json
  python/flask-basic/
    eval/qual/
      audit.json
      instrument.json

pytest-codex-evals/
  src/pytest_codex_evals/
    schemas/
  tests/
```

The eval definitions use JSON instead of CSV because these cases need more than
prompt text: fixture metadata, prompt variants, sanity checks, artifact
paths, rubric checks, and optional runtime check config. CSV is fine for a
small prompt list, but JSON keeps each service eval self-contained and
machine-validated.

Each eval has a `prompts[]` array of task variants. The pytest plugin collects
JSON files under `eval/qual/`, `eval/runtime/`, and `eval/sanity/`, then expands
every variant into its own pytest item. Live runs are selected by eval kind:

- `sanity`: quick skill-loading and final-output guards.
- `rubric`: schema-constrained judge checks.
- `runtime`: Docker/Observer trace and metric checks.

Sanity evals use the dummy `evals/sanity/skill-smoke/eval/sanity/` fixture by
default so they do not spend time analyzing or modifying a real service.

For each live case, the harness always runs `with_skill`. Passing `AB=1` adds
the `baseline` side with no skill name and no repo skills visible.

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

Sanity grading uses Python over files, JSONL traces, and command output:

- final response text checks
- expected file creation and manifest edits
- command execution evidence from `codex exec --json`
- command count and token usage from trace events
- baseline contamination checks for accidental skill visibility

Checks default to `with_skill`, keeping the A/B baseline simple. Baseline runs
only need to prove run health and skill isolation unless a check explicitly sets
`applies_to` to `baseline` or `both`.

Runtime checks run through `eval-runtime`. The eval JSON only points at an
eval-owned Compose file and declares telemetry
expectations. Compose owns service topology, Observer startup, app startup, and
a profiled `traffic` service that generates requests with tools such as `siege`.
The harness runs Compose, invokes `traffic`, queries the managed Observer API
for trace and metric evidence, then tears the stack down.

The harness also adds setup guards to every run:

- `skills-loaded`: the `with_skill` side exposes repo skills under `.agents/skills/`.
- `skills-not-loaded`: the `baseline` side does not expose repo skills or reference them in traces.

Rubric grading runs a second read-only Codex pass with the schema packaged
by `pytest-codex-evals`. It uses the eval JSON's `rubric` entries and the judge
model configured in `codex-evals*.toml`; the task-run model is configured as
`[models].agent`.
Rubric evals can also set `judge_inputs` or a custom `judge_prompt`, so the
judge prompt is not tied to service-file based skills.

## Commands

```bash
make test-eval-harness
make test-pytest-plugin
make skill-eval-list
make eval-validation SKILL=skills/otel-audit
make eval-sanity SKILL=skills/otel-audit
make eval-sanity-ab SKILL=skills/otel-audit
make eval-rubric SKILL=skills/otel-instrument CASE=go/kvstore
make eval-rubric-ab SKILL=skills/otel-instrument CASE=go/kvstore
make eval-runtime SKILL=skills/otel-instrument
make eval-runtime-ab SKILL=skills/otel-instrument
make eval-all SKILL=skills/otel-instrument
make eval-all-ab SKILL=skills/otel-instrument
```

`eval-validation` validates JSON and fixture shape only. `eval-sanity`,
`eval-rubric`, and `eval-runtime` run the loaded-skill side. Add baseline
with `AB=1`, `WITH=ab`, or the `*-ab` targets. The direct pytest form is:

```bash
cd evals && uv run pytest '<language>/<service>/eval/qual' -k "<prompt-id>" --skill "../skills/<skill-dir>" --codex-eval-kind rubric --ab
```

The reusable pytest plugin lives in `pytest-codex-evals/`. It owns the generic
Codex controls (`--skill`, `--codex-eval-config`, `--model`,
`--codex-eval-kind`, `--ab`, `--no-rubric`, `--codex-runtime`), JSON eval
collection, validation, side execution, and A/B execution. Service
selection is plain pytest path selection, prompt selection is plain `-k`
filtering, and `--skill` points to a skill directory containing `SKILL.md`.
Markdown reports are rendered as a separate step from the raw JSON written by
pytest:

```bash
cd evals
uv run pytest go/kvstore/eval/qual --skill ../skills/otel-instrument --codex-eval-kind rubric
uv run codex-eval-harness report --repo-root .. --skill ../skills/otel-instrument --kind rubric
```

Build and publish it with:

```bash
make build-pytest-plugin
make publish-pytest-plugin
```

## Outputs

Full artifacts are ignored by git:

```text
.workspace/codex-evals/<skill>/<run-id>/
  run.json
  runs/
    validation.json
    sanity-with_skill.json
    rubric-ab.json
    runtime-with_skill.json
  cases/<language>/<service>/<prompt-id>/
    with_skill/
      service/
      trace.jsonl
      last_message.md
      grade.json
      rubric_grade.json
      summary.json
    baseline/
      service/
      trace.jsonl
      last_message.md
      grade.json
      rubric_grade.json
      summary.json
  results/<language>/<service>/<eval>/
    eval.json
    with_skill.json
    with_baseline.json
  <kind>/
    benchmark.json
    report.md
```

Pytest creates `run.json`, `runs/*.json`, `cases/`, and `results/`. The
`codex-eval-harness report` step creates `<kind>/benchmark.json`,
`<kind>/report.md`, and the latest summary copies:

```text
eval-reports/<skill>/validation/report.md
eval-reports/<skill>/sanity/report.md
eval-reports/<skill>/rubric/report.md
eval-reports/<skill>/runtime/report.md
```

`benchmark.json` is role-specific: sanity reports contain only sanity check
data, rubric reports contain only rubric judge data, and runtime reports contain
only runtime check data. Baseline columns are `-` when the run mode did not
execute a baseline side.

## Maintenance Rules

- Add an eval when a skill behavior changes or a real failure is found.
- Keep sanity checks focused on behavior that can be proven from files,
  traces, commands, and final output.
- Use runtime checks only for end-to-end telemetry proof that needs Docker and a
  managed Observer.
- Use rubric checks for style, semantic convention quality, and workflow
  correctness.
- Keep full traces out of git; commit only durable eval definitions, harness
  code, and intentionally reviewed summary reports.
