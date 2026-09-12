# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260911T185941635354Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | 1 | 33% (1/3), avg score 72 | 5.4M | 16.1m | - | - | - |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | 2 | 79% (11/14), avg score 82 | 13.1M | 35.7m | - | - | - |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | 1 | 100% (4/4), avg score 95 | 7.8M | 17.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 5374161 | 5205632 | unknown | 35356 | 15613 | unknown | 5409517 |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 13006263 | 12614400 | unknown | 75186 | 26331 | unknown | 13081449 |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 7750838 | 7579008 | unknown | 33523 | 14881 | unknown | 7784361 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/benchmark-instrument | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 570974 | 494080 | unknown | 9327 | 4479 | unknown | 580301 |
| with_skill | go/chi-basic/qual/instrument | go/chi-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 729707 | 537472 | unknown | 17251 | 10318 | unknown | 746958 |
| with_skill | go/chi-basic/qual/instrument-decision-gated | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 527853 | 473984 | unknown | 9522 | 4093 | unknown | 537375 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | benchmark | rubric:rubric-2 FAIL | observe_report.py validate-flow passed for audit -> selection -> instrumentation. service/.observe/otel-instrumentation.json includes OTEL-001 status, telemetry_changes, tests/evidence, scenario ids, and next_steps. service/.observe/otel-verify.json is absent; instrumentation.md records go test and go mod tidy as bl... |
| with_skill | go/chi-basic | with_skill | benchmark | rubric:rubric-3 FAIL | service/.observe/otel-instrumentation.html starts with a concise verification-not-run status and lists OTEL-001, but only shows generic 'Internal verification has not completed' proof. service/.observe/otel.html remains audit-oriented and contains the 'Copy this prompt and paste into AI chat' tray label without inst... |
| with_skill | go/chi-basic | with_skill | direct | rubric:rubric-7 FAIL | service/.observe/otel-instrumentation.md records the exact blockers: missing go.sum entries and DNS failure resolving proxy.golang.org. service/.observe/otel-instrumentation.html starts with one concise partial status and lists OTEL-001 changes, but says internal verification has not completed. `go test ./...` and `... |
| with_skill | go/chi-basic | with_skill | runtime-preserving | rubric:rubric-1 FAIL | Trace preflight states service/main.go on :8000, native Go, service.name go-chi-basic with OTEL env overrides, no environment dimension. Initial go.mod was go 1.23 with chi v5.2.4; final go.mod is go 1.25.0 with chi v5.2.2. |
| with_skill | go/chi-basic | with_skill | runtime-preserving | rubric:rubric-7 FAIL | otel-instrumentation.md records PermissionError for loopback receiver and compatibility details. otel-instrumentation.html says verification not run and lists OTEL-001 changes, but its proof section says internal verification has not completed. No service/.observe/otel-verify.json is present. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
