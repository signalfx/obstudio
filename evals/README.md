# Skill Evals

Skill evals are pytest-collected JSON files. Each fixture keeps its eval
definitions under a service-local `eval/` folder:

```text
evals/<language>/<service>/eval/qual/audit.json
evals/<language>/<service>/eval/qual/instrument.json
evals/<language>/<service>/eval/runtime/instrument.json
evals/<language>/<service>/eval/sanity/audit.json
```

Only create the kind folders a service actually needs. The make targets select
these directories with global-style path patterns such as `*/*/eval/qual`,
`*/*/eval/runtime`, and `*/*/eval/sanity`.

Each eval defines `prompts[]` task variants. The harness separates the eval
kind from the baseline decision:

- `validation` validates JSON and skill source availability without Codex.
- `sanity` runs quick loaded-skill guards such as final output and skill
  visibility.
- `rubric` runs the task and a schema-constrained judge pass.
- `runtime` runs Docker/Observer telemetry checks.
- `AB=1` adds the no-skill baseline side to any live eval kind.

| Eval Type | What Runs | What It Proves | Output |
|---|---|---|---|
| Validation | Pytest collection only | JSON shape, eval directory, skill source | Validation report |
| Sanity | Codex with `.agents/skills/<skill>` visible | Skill loads and the task completes | Sanity report |
| Rubric | Codex task plus schema-constrained judge | Semantic quality and workflow fit | Rubric report |
| Runtime Checks | Docker Compose plus Observer API queries | Live spans/metrics are emitted after traffic | Runtime report |
| A/B | Adds the no-skill baseline side to sanity, rubric, or runtime | Skill lift over baseline | Same report shape with baseline columns populated |

Validation is the fast gate for CI: it proves the eval JSONs are collectable and
the referenced skill source exists. Live evals run the loaded-skill side by
default. Pass `AB=1`, `WITH=ab`, or use the `*-ab` target to add the baseline.

Each eval JSON keeps the human-facing tasks at the top, then only the checks for
that eval kind:

```json
{
  "skill": "otel-audit",
  "prompts": [
    {
      "id": "direct",
      "task": "Scan the service in ./service for observability gaps."
    }
  ],
  "rubric": [
    "Identifies the relevant entrypoint and current telemetry state."
  ]
}
```

Mode-specific JSON files are grouped by role:

```text
eval/sanity/*.json     # quick skill-loading checks
eval/runtime/*.json    # Docker/Observer runtime checks
eval/qual/*.json       # schema-constrained rubric checks
```

The default sanity pattern picks `evals/sanity/skill-smoke/eval/sanity/`, a
dummy fixture used only to prove that the selected skill loads and the prompt
returns quickly.

Rubric evals may set `judge_inputs` or `judge_prompt` when the judge should
inspect artifacts other than a service directory.

## A/B Sides

| Side | Skill visibility |
|---|---|
| `with_skill` | Copied fixture plus temporary `.agents/skills` entries |
| `with_baseline` | Same copied fixture with no repo skills visible |

Baseline checks stay intentionally simple: final output, `skills-not-loaded`,
and baseline contamination checks.
Detailed sanity artifact checks default to the `with_skill` side, which
also gets a `skills-loaded` guard.

Use command-backed checks when an ecosystem tool can prove behavior more
reliably than text search. Examples in this repo use `go list -mod=readonly -m
all`, `npm pkg get`, `node -e`, and Python `tomllib` against the generated
service workspace.

Runtime checks are top-level `checks[]` entries in `eval/runtime/*.json`.
`eval-runtime` enables them automatically. The eval JSON points at a Compose
file and declares trace/metric expectations. The Compose file owns service
topology, Observer startup, app startup, and a profiled `traffic` service that
generates requests with tools such as `siege`. The harness runs Compose,
invokes `traffic`, queries Observer at `http://127.0.0.1:3000`, then tears the
stack down. Compose can use `${CODEX_EVAL_SERVICE_DIR}` when it must build the
instrumented temp service workspace rather than the source fixture.

## Commands

| Target | Purpose |
|---|---|
| `make test-eval-harness` | Validate every eval JSON and fixture |
| `make skill-eval-list SKILL=skills/otel-audit` | List collected eval items for a skill path |
| `make eval-validation SKILL=skills/otel-audit` | Validate eval JSONs without running Codex |
| `make eval-sanity SKILL=skills/otel-audit` | Run quick loaded-skill sanity checks |
| `make eval-sanity-ab SKILL=skills/otel-audit` | Run sanity checks with baseline |
| `make eval-rubric SKILL=skills/otel-instrument CASE=go/kvstore` | Run rubric judge checks |
| `make eval-rubric-ab SKILL=skills/otel-instrument CASE=go/kvstore` | Run rubric judge checks with baseline |
| `make eval-runtime SKILL=skills/otel-instrument` | Run Docker/Observer runtime checks |
| `make eval-runtime-ab SKILL=skills/otel-instrument` | Run Docker/Observer runtime checks with baseline |
| `make eval-all SKILL=skills/otel-audit` | Run validation, sanity, rubric, and runtime |
| `make eval-all-ab SKILL=skills/otel-audit` | Run validation plus A/B sanity, rubric, and runtime |
| `make eval-with-skill SKILL=skills/otel-instrument CASE=go/kvstore` | Run only the loaded-skill side |
| `make eval-with-baseline SKILL=skills/otel-instrument CASE=go/kvstore` | Run only the no-skill baseline side |
| `make eval-ab SKILL=skills/otel-audit CASE=go/chi-basic PROMPT=direct` | Run both sides in one A/B comparison |
| `make skill-eval` / `make skill-eval-ab` | Compatibility aliases for `eval-with-skill` / `eval-ab` |

Parallelize pytest items with `EVAL_WORKERS`:

```bash
make eval-all SKILL=skills/otel-audit EVAL_WORKERS=4
make eval-all-ab SKILL=skills/otel-audit EVAL_WORKERS=4
make eval-sanity SKILL=skills/otel-instrument WITH=ab
make eval-runtime SKILL=skills/otel-instrument CASE=python/fastapi-celery
make eval-rubric SKILL=skills/otel-audit EVAL_PATTERN='go/*/eval/qual'
```

Each worker writes per-item result JSON under `.workspace/codex-evals/_worker-results/`;
the controller merges those into the normal latest reports.

Progress logging is enabled by default for Make targets and prints item start
and completion lines:

```text
[codex-eval] START rubric:ab go/chi-basic/eval/qual/audit.json::otel-audit::go/chi-basic::direct
[codex-eval] PASSED rubric:ab go/chi-basic/eval/qual/audit.json::otel-audit::go/chi-basic::direct (142.3s)
```

Disable it with `EVAL_PROGRESS=0`.

## Config

| File | Purpose |
|---|---|
| `evals/codex-evals.validation.toml` | Validation-only config |
| `evals/codex-evals.toml` | Default live config and model settings |
| `evals/codex-evals.baseline.toml` | Compatibility with-baseline config |
| `evals/codex-evals.ab.toml` | Compatibility A/B config |

Set the judge model with:

```toml
[models]
agent = "gpt-5.5"
judge = "gpt-5.5"

[runtime]
enabled = false
```

## Reports

Run artifacts are written under `.workspace/codex-evals/<skill>/<run-id>/`.
Latest summaries are copied by eval kind.

| Mode | Run artifacts | Latest summary |
|---|---|---|
| Validation | `validation-report.md`, `validation-benchmark.json` | `<skill>/validation/report.md`, `<skill>/validation/benchmark.json` |
| Sanity | `with_skill-report.md`, `with_skill-benchmark.json` | `<skill>/sanity/report.md`, `<skill>/sanity/benchmark.json` |
| Sanity A/B | `ab-report.md`, `ab-benchmark.json` | `<skill>/sanity/report.md`, `<skill>/sanity/benchmark.json` |
| Rubric | `with_skill-report.md`, `with_skill-benchmark.json` | `<skill>/rubric/report.md`, `<skill>/rubric/benchmark.json` |
| Rubric A/B | `ab-report.md`, `ab-benchmark.json` | `<skill>/rubric/report.md`, `<skill>/rubric/benchmark.json` |
| Runtime | `with_skill-report.md`, `with_skill-benchmark.json` | `<skill>/runtime/report.md`, `<skill>/runtime/benchmark.json` |
| Runtime A/B | `ab-report.md`, `ab-benchmark.json` | `<skill>/runtime/report.md`, `<skill>/runtime/benchmark.json` |

Each live run also writes file-level JSON under:

```text
.workspace/codex-evals/<skill>/<run-id>/results/<language>/<service>/<eval>/
  eval.json
  with_skill.json
  with_baseline.json
```

The canonical Markdown report has validation plus the section for the selected
eval type: Sanity Summary, Rubric Summary, or Runtime Summary. Live tables
aggregate all prompt variants and include token usage plus elapsed time for
with-skill and baseline sides. Baseline columns are `-` when the run mode did
not execute a baseline side.

Each kind has its own latest `report.md` and `benchmark.json` under
`eval-reports/<skill>/<kind>/`; mode-specific artifacts stay in the timestamped
run directory.

## Fixture Apps

| App | Stack | Run |
|---|---|---|
| `evals/python/flask-basic/` | Flask | `make dev` |
| `evals/python/fastapi-celery/` | FastAPI + Celery | `make dev` |
| `evals/node/express-basic/` | Express | `npm run dev` |
| `evals/go/chi-basic/` | Chi | `go run .` |
| `evals/go/chi-partial/` | Chi with partial OTel | `go run .` |
| `evals/go/kvstore/` | Chi + package tests | `make test` |
| `evals/java/springboot-basic/` | Spring Boot | `mvn spring-boot:run` |
