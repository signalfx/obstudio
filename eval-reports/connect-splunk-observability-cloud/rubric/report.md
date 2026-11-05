# connect-splunk-observability-cloud Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | connect-splunk-observability-cloud |
| Run ID | 20261105T170736837341Z |
| Agent model | - |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.model-override.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | 4 | 95% (42/44), avg score 95 | 138.7K | 3.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | with_skill | codex | cumulative | measured | 4/4 recognized | 137082 | 115072 | 0 | 1661 | 624 | unknown | 138743 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/connect-splunk-observability-cloud | plugins/obstudio | with_skill | codex | cumulative | measured | 4/4 recognized | 173281 | 99712 | 0 | 4493 | 762 | unknown | 177774 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | newly-ready-organization-browser | rubric:rubric-1 FAIL | Assumed endpoints.rest is "http://127.0.0.1:17900"; no wildcard normalization is modeled. |
| with_skill | plugins/obstudio | with_skill | terminal-clickable-fallback | rubric:rubric-1 FAIL | Assumed result: {"endpoints":{"rest":"http://127.0.0.1:17900"}}; modeled call: observer_status(). |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
