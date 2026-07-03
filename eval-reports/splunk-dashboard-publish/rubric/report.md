# splunk-dashboard-publish Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-dashboard-publish |
| Run ID | 20260703T005240819871Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-sync/qual/dashboard-publish | dashboards/checkout-sync | 1 | 67% (4/6), avg score 82 | 234.8K | 2.7m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | dashboards/checkout-sync | with_skill | offline-plan | rubric:rubric-1 FAIL | Final diff includes checkout Overview, checkout RED, and charts kpi_p99_latency, p99_latency, error_rate. Creation order says: "referencing the returned chartId values with the Terraform grid placements" but omits column/row/width/height values. |
| with_skill | dashboards/checkout-sync | with_skill | offline-plan | rubric:rubric-5 FAIL | Final says no network calls, no credential reads, no create/update/delete, and no ledger. It does not include a "Confirm? (yes/no)" or equivalent explicit confirmation prompt. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
