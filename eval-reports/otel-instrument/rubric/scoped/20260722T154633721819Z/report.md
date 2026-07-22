# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260722T154633721819Z |
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
| with_skill | go/chi-partial/qual/instrument | go/chi-partial | 1 | 67% (4/6), avg score 70 | 5.9M | 17.6m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-5 FAIL | service/main.go:50 uses static server span naming and no GetTask-<id> span remains. However bad body/not found/conflict paths at service/main.go:84-85, 120, 129-135, and 142 only write responses; there are no RecordError or SetStatus calls. |
| with_skill | go/chi-partial | with_skill | direct | rubric:rubric-6 FAIL | service/main.go:129-135 returns identical 409 statuses for already done and already reserved without adding a label. service/main.go:166-167 only adds http.route to the Labeler. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
