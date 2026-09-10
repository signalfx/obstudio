# splunk-detector-publish Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-detector-publish |
| Run ID | 20260910T193044836994Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | 1 | 43% (3/7), avg score 48 | 416.4K | 4.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | with_skill | codex | cumulative | measured | 1/1 recognized | 409151 | 374656 | unknown | 7212 | 4310 | unknown | 416363 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-detectors/qual/detector-publish | dashboards/checkout-detectors | with_skill | codex | cumulative | measured | 1/1 recognized | 122462 | 82432 | unknown | 5306 | 3420 | unknown | 127768 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | dashboards/checkout-detectors | with_skill | offline-plan | rubric:rubric-3 FAIL | Final says "GAP (0)" and "UNCERTAIN (3)" with rows for all three detectors. |
| with_skill | dashboards/checkout-detectors | with_skill | offline-plan | rubric:rubric-4 FAIL | Final: "none can be classified as GAP; all are UNCERTAIN" and POST order lists only `high_latency`, `high_error_rate`, `low_throughput` names. |
| with_skill | dashboards/checkout-detectors | with_skill | offline-plan | rubric:rubric-6 FAIL | Final AutoDetect section says built-in detectors would not count as COVERED, but no planned API body or `program_text -> programText` mapping is shown. |
| with_skill | dashboards/checkout-detectors | with_skill | offline-plan | rubric:rubric-7 FAIL | No occurrence of `tags` or `["obstudio"]` appears in last_message.md. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
