# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260722T192657125215Z |
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
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | 1 | 83% (5/6), avg score 88 | 8.4M | 21.9m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | benchmark | rubric:rubric-5 FAIL | service/.observe/otel-selection.json preserves requested_ids separately from approved_ids. service/.observe/otel-instrumentation.json includes finding status, telemetry_changes, tests, evidence, and next_steps, but no remaining_gaps or verification_handoff structure; service/.observe/otel-verify.json exists with Par... |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
