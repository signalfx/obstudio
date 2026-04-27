# Skill Evals

Skill evals are pytest-collected JSON files. Each fixture keeps its eval
definitions next to the service code:

```text
evals/<language>/<service>/audit_eval.json
evals/<language>/<service>/instrument_eval.json
```

Each eval defines `prompts[]` task variants. The harness has three primitive
modes: `eval-validation`, `eval-with-skill`, and `eval-with-baseline`.

| Eval Type | What Runs | What It Proves | Output |
|---|---|---|---|
| Validation | Pytest collection only | JSON shape, eval directory, skill source | Validation report |
| With Skill | Codex with `.agents/skills/<skill>` visible | Skill-guided task behavior | With-skill report |
| With Baseline | Codex with no repo skill visible | No-skill baseline behavior | With-baseline report |
| A/B | Codex with both sides in one run | Skill lift over no-skill baseline | A/B report |
| Deterministic Checks | Python checks over final text, files, traces, and command output | Concrete pass/fail behavior | `deterministic_grade.json` |
| Qualitative Checks | Schema-constrained judge pass | Semantic quality and workflow fit | `qualitative_grade.json` |
| Runtime Checks | Docker Python SDK plus Observer API queries | Live spans/metrics are emitted after traffic | Runtime section in `deterministic_grade.json` |

Validation is the fast gate for CI: it proves the eval JSONs are collectable and
the referenced skill source exists. `eval-with-skill` and `eval-with-baseline`
each run one Codex side and write deterministic plus qualitative grades. `eval-ab`
runs both sides in one comparison.

Each eval JSON keeps the human-facing tasks at the top, then deterministic and
qualitative checks:

```json
{
  "skill": "otel-audit",
  "prompts": [
    {
      "id": "direct",
      "task": "Scan the service in ./service for observability gaps."
    }
  ],
  "deterministic_checks": [],
  "qualitative_checks": []
}
```

## A/B Sides

| Side | Skill visibility |
|---|---|
| `with_skill` | Copied fixture plus temporary `.agents/skills` entries |
| `with_baseline` | Same copied fixture with no repo skills visible |

Baseline checks stay intentionally simple: run health plus `skills-not-loaded`.
Detailed deterministic artifact checks default to the `with_skill` side, which
also gets a `skills-loaded` guard.

Use command-backed checks when an ecosystem tool can prove behavior more
reliably than text search. Examples in this repo use `go list -mod=readonly -m
all`, `npm pkg get`, `node -e`, and Python `tomllib` against the generated
service workspace.

Runtime checks use the `observer_docker_runtime` check kind. They are skipped by
default and run only when `[runtime].enabled = true` is set in the selected TOML
config or `EVAL_RUNTIME=1` is passed to Make. These checks use the Docker Python
SDK to start containers or a Compose file, send HTTP traffic, then query a
running Observer at `http://127.0.0.1:3000` for trace and metric evidence.

## Commands

| Target | Purpose |
|---|---|
| `make test-eval-harness` | Validate every eval JSON and fixture |
| `make skill-eval-list SKILL=skills/otel-audit` | List collected eval items for a skill path |
| `make eval-validation SKILL=skills/otel-audit` | Validate eval JSONs without running Codex |
| `make eval-with-skill SKILL=skills/otel-instrument CASE=go/kvstore` | Run only the loaded-skill side |
| `make eval-with-baseline SKILL=skills/otel-instrument CASE=go/kvstore` | Run only the no-skill baseline side |
| `make eval-ab SKILL=skills/otel-audit CASE=go/chi-basic PROMPT=direct` | Run both sides in one A/B comparison |
| `make eval-all SKILL=skills/otel-audit CASE=go/chi-basic PROMPT=direct` | Run validation and A/B |
| `make skill-eval` / `make skill-eval-ab` | Compatibility aliases for `eval-with-skill` / `eval-ab` |

Parallelize pytest items with `EVAL_WORKERS`:

```bash
make eval-all SKILL=skills/otel-audit EVAL_WORKERS=4
make eval-ab SKILL=skills/otel-instrument CASE=go/kvstore EVAL_WORKERS=2
make eval-with-skill SKILL=skills/otel-instrument CASE=python/fastapi-celery EVAL_RUNTIME=1
```

Each worker writes per-item result JSON under `.workspace/codex-evals/_worker-results/`;
the controller merges those into the normal latest reports.

Progress logging is enabled by default for Make targets and prints item start
and completion lines:

```text
[codex-eval] START ab go/chi-basic/audit_eval.json::otel-audit::go/chi-basic::direct
[codex-eval] PASSED ab go/chi-basic/audit_eval.json::otel-audit::go/chi-basic::direct (142.3s)
```

Disable it with `EVAL_PROGRESS=0`.

## Config

| File | Purpose |
|---|---|
| `evals/codex-evals.validation.toml` | Validation-only config |
| `evals/codex-evals.toml` | With-skill config |
| `evals/codex-evals.baseline.toml` | With-baseline config |
| `evals/codex-evals.ab.toml` | Live A/B config, including qualitative judge model |

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
Latest summaries are copied to `eval-reports/<skill>/`.

| Mode | Run artifacts | Latest summary |
|---|---|---|
| Validation | `validation-report.md`, `validation-benchmark.json` | `REPORT.md`, `benchmark.json` |
| With Skill | `with_skill-report.md`, `with_skill-benchmark.json` | `REPORT.md`, `benchmark.json` |
| With Baseline | `with_baseline-report.md`, `with_baseline-benchmark.json` | `REPORT.md`, `benchmark.json` |
| Live A/B | `ab-report.md`, `ab-benchmark.json` | `REPORT.md`, `benchmark.json` |

Each live run also writes file-level JSON under:

```text
.workspace/codex-evals/<skill>/<run-id>/results/<language>/<service>/<eval>/
  eval.json
  with_skill.json
  with_baseline.json
```

The canonical Markdown report has one row per eval file in separate validation,
deterministic, qualitative, and runtime tables. Live tables aggregate all prompt
variants and include token usage plus elapsed time for with-skill and baseline
sides. Baseline columns are `-` when the run mode did not execute a baseline
side.

Only the canonical latest `REPORT.md` and `benchmark.json` are copied under
`eval-reports/<skill>/`; mode-specific artifacts stay in the timestamped run
directory.

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
