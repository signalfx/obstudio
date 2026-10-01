# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20261001T073458817071Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | 1 | 60% (3/5), avg score 82 | 2.5M | 10.8m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2446117 | 2330240 | 0 | 20799 | 6294 | unknown | 2466916 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 940740 | 848896 | 0 | 9709 | 5098 | unknown | 950449 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | canonical-proof-packet | rubric:rubric-2 FAIL | service/.observe/otel-verify.md states the audit has no explicit finding group and renders ordinary `Findings · 4`; jq checks in trace.jsonl returned false for finding_group/group fields. Searches of trace/report artifacts did not show an explicit opentelemetry-group rejection check. |
| with_skill | go/chi-basic | with_skill | canonical-proof-packet | rubric:rubric-5 FAIL | trace.jsonl shows render-html commands writing service/.observe/otel.html, including a later render with --selection-json. service/.observe/otel.html now contains DATA.selection with requested_ids/approved_ids and selection tray state. render-instrumentation-html produced service/.observe/otel-instrumentation.html, ... |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
