# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260722T152331088618Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |
| Report scope | scoped |
| Selected prompts | 1 |
| Expected prompts | 31 |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 1 | 50% (4/8), avg score 78 | 6.4M | 22.6m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | decision-gated | rubric:rubric-2 FAIL | service/otel.go calls otel.SetMeterProvider(mp); rg found no SetTracerProvider, TextMapPropagator, propagation, or TracerProvider in service code. |
| with_skill | go/chi-basic | with_skill | decision-gated | rubric:rubric-3 FAIL | service/main.go keeps chi routes and adds recordTaskCreated only in POST /tasks; rg found no otelhttp or http.route in application code. |
| with_skill | go/chi-basic | with_skill | decision-gated | rubric:rubric-5 FAIL | service/.observe/otel-selection.json has requested_ids=[OTEL-002] and approved_ids=[OTEL-002]; service/otel.go defines metric task.created; service/main.go calls recordTaskCreated. |
| with_skill | go/chi-basic | with_skill | decision-gated | rubric:rubric-6 FAIL | service/.observe/otel-instrumentation.json findings contains only OTEL-002 with status working, telemetry_changes for task.created, tests, evidence, and follow-up actions. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
