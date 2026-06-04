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
discovers the Observer host port with `docker compose port observer 3000`,
invokes `traffic`, queries that isolated Observer instance, then tears the stack
down. Compose can use `${CODEX_EVAL_SERVICE_DIR}` when it must build the
instrumented temp service workspace rather than the source fixture. Shared
runtime image definitions live in `evals/runtime/`; service-specific runtime
files stay beside each eval under `eval/runtime/`.

## Commands

| Target | Purpose |
|---|---|
| `make test-eval-harness` | Validate every eval JSON and fixture |
| `make skill-eval-list SKILL=skills/otel-audit` | List collected eval items for a skill path |
| `make eval-validation SKILL=skills/otel-audit` | Validate eval JSONs without running Codex |
| `make eval-validation-test SKILL=skills/otel-audit` | Validate evals and write raw JSON only |
| `make eval-validation-report SKILL=skills/otel-audit` | Render the latest validation Markdown and benchmark |
| `make eval-sanity SKILL=skills/otel-audit` | Run quick loaded-skill sanity checks |
| `make eval-sanity-test SKILL=skills/otel-audit` | Run sanity checks and write raw JSON only |
| `make eval-sanity-report SKILL=skills/otel-audit` | Render the latest sanity Markdown and benchmark |
| `make eval-sanity-ab SKILL=skills/otel-audit` | Run sanity checks with baseline |
| `make eval-rubric SKILL=skills/otel-instrument CASE=go/kvstore` | Run rubric judge checks |
| `make eval-rubric-test SKILL=skills/otel-instrument CASE=go/kvstore` | Run rubric checks and write raw JSON only |
| `make eval-rubric-report SKILL=skills/otel-instrument` | Render the latest rubric Markdown and benchmark |
| `make eval-rubric-ab SKILL=skills/otel-instrument CASE=go/kvstore` | Run rubric judge checks with baseline |
| `make eval-runtime SKILL=skills/otel-instrument` | Run Docker/Observer runtime checks |
| `make eval-runtime-test SKILL=skills/otel-instrument` | Run runtime checks and write raw JSON only |
| `make eval-runtime-report SKILL=skills/otel-instrument` | Render the latest runtime Markdown and benchmark |
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
the controller merges those into raw run JSON. Report targets then render
Markdown and benchmark files from the merged JSON.

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
Pytest writes raw JSON; report targets parse that JSON and create Markdown plus
role-specific benchmarks.

```text
.workspace/codex-evals/<skill>/<run-id>/
  run.json
  runs/
    validation.json
    sanity-with_skill.json
    sanity-ab.json
    rubric-with_skill.json
    runtime-with_skill.json
  results/<language>/<service>/<eval>/
    eval.json
    with_skill.json
    with_baseline.json
  <kind>/
    report.md
    benchmark.json
```

Latest summaries are copied by eval kind:

```text
eval-reports/<skill>/validation/report.md
eval-reports/<skill>/validation/benchmark.json
eval-reports/<skill>/sanity/report.md
eval-reports/<skill>/sanity/benchmark.json
eval-reports/<skill>/rubric/report.md
eval-reports/<skill>/rubric/benchmark.json
eval-reports/<skill>/runtime/report.md
eval-reports/<skill>/runtime/benchmark.json
```

Each `benchmark.json` is kind-specific. Sanity contains sanity checks only,
rubric contains judge/rubric fields only, and runtime contains runtime check
fields only. Baseline columns are `-` when the run mode did not execute a
baseline side.

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
| `evals/java/kafka-producer-consumer/` | Plain Kafka producer + consumer | `mvn test` |
| `evals/java/kafka-batch-consumer/` | Plain Kafka batch consumer | `mvn test` |
| `evals/java/kafka-listener-container/` | Kafka listener container | `mvn test` |
| `evals/java/kafka-streams/` | Kafka Streams with Guice wiring | `mvn test` |

The Java Kafka fixtures use broker-free unit or topology tests as eval commands.
Running the services with `mvn exec:java` or `mvn spring-boot:run` requires a
Kafka broker and is documented in each fixture README. See those fixture READMEs
for eval intent, required environment variables, and the Java-agent versus
manual-SDK boundary.

Kafka coverage is organized by processing pattern rather than by every
framework combination: direct producer/consumer, batch consumer, listener
container, and Kafka Streams.
