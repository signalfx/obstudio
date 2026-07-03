# splunk-detector-publish Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-detector-publish |
| Run ID | 20260703T005240819871Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | 1 | 50% (3/6), avg score 48 | 227.2K | 2.4m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | dashboards/checkout-detectors | with_skill | offline-plan | rubric:rubric-3 FAIL | Final says 'UNCERTAIN (3)' and 'GAP (0)'; Reason text is 'Sandbox has no network access, so absence or presence of a matching live detector cannot be proven.' |
| with_skill | dashboards/checkout-detectors | with_skill | offline-plan | rubric:rubric-4 FAIL | Final: 'No POST /v2/detector would run from this offline plan because there are zero confirmed GAP specs.' |
| with_skill | dashboards/checkout-detectors | with_skill | offline-plan | rubric:rubric-6 FAIL | Final includes an AutoDetect Advisory section, but the POST section lacks payload bodies and does not show programText or detectLabel fields. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
