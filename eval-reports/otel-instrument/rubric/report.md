# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261109T182011554577Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | 1 | 71% (10/14), avg score 76 | 6.3M | 19.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 6225932 | 6093312 | 0 | 42629 | 11370 | unknown | 6268561 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 757647 | 634496 | 0 | 6867 | 2162 | unknown | 764514 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-1 FAIL | trace.jsonl records skill loading, implementation, builds and tests. Both service/.observe/logging-workflow-proof/*/result.json files report failed with PermissionError invoking ps; final make test exited 2. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-9 FAIL | The reports document bounded bodies and batch settings but omit log attribute count/value defaults. Installed sdk/log v0.22.0 provider.go supplies a default count of 128 and unlimited value length; neither is reconciled in the normal report. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-11 FAIL | TestStalledLogTransportKeepsNativeSink exercises logs and native output without observing other signals. TestLogBoundaryPreservesHTTPExport covers disabled/conflicting log branches, not an active failing log exporter. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-14 FAIL | service/.observe/otel-instrumentation.md includes package metadata and scenario tables, but no official logging source-to-evidence closure covering normative requirements, recommendations, optional/Development capabilities and local policy. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
