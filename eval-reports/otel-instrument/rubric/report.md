# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260910T194617117847Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/instrument | go/kvstore | 1 | 90% (9/10), avg score 76 | 9.2M | 23.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 9176946 | 8938240 | unknown | 50052 | 12083 | unknown | 9226998 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 680101 | 610816 | unknown | 8109 | 4175 | unknown | 688210 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-6 FAIL | service/cmd/kvstore-server/otel.go:30 sets defaultServiceName = "kvstore"; service/kvstore/http.go:59-63 emits the request warning; service/.observe/otel-verify.md reports log OTLP delivery as Not proven. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
