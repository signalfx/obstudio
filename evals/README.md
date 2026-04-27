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
| Deterministic Checks | Python checks over final text, files, and traces | Concrete pass/fail behavior | `deterministic_grade.json` |
| Qualitative Checks | Schema-constrained judge pass | Semantic quality and workflow fit | `qualitative_grade.json` |

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
agent = "gpt-5.2"
judge = "gpt-5.2"
```

## Reports

Run artifacts are written under `.workspace/codex-evals/<skill>/<run-id>/`.
Latest summaries are copied to `eval-reports/<skill>/`.

| Mode | Run artifacts | Latest summary |
|---|---|---|
| Validation | `validation-report.md`, `validation-benchmark.json` | `VALIDATION_REPORT.md`, `validation-benchmark.json` |
| With Skill | `with_skill-report.md`, `with_skill-benchmark.json` | `WITH_SKILL_REPORT.md`, `with_skill-benchmark.json` |
| With Baseline | `with_baseline-report.md`, `with_baseline-benchmark.json` | `WITH_BASELINE_REPORT.md`, `with_baseline-benchmark.json` |
| Live A/B | `ab-report.md`, `ab-benchmark.json` | `AB_REPORT.md`, `ab-benchmark.json` |

Each live run also writes file-level JSON under:

```text
.workspace/codex-evals/<skill>/<run-id>/results/<language>/<service>/<eval>/
  eval.json
  with_skill.json
  with_baseline.json
```

The Markdown report has one row per eval file, aggregates all prompt variants,
and only tabulates failure cases. Baseline columns are `-` when the run mode did
not execute a baseline side.

For compatibility, live runs also write `report.md`, `benchmark.json`,
`REPORT.md`, and `benchmark.json`.

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
