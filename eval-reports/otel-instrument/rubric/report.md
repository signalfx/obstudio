# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261110T184739892225Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | 1 | 64% (9/14), avg score 79 | 6.4M | 19.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 6363538 | 6186752 | 0 | 41119 | 9061 | unknown | 6404657 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1108193 | 979968 | 0 | 6264 | 1563 | unknown | 1114457 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-2 FAIL | service/.observe/otel-instrumentation.md:158-187 groups exporter timeout/compression/headers/TLS/proxy and several numeric settings; installed config.go exposes additional resolvable branches. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-9 FAIL | Instrumentation report lines 149 and 183; installed sdk/log v0.22.0 record.go defines logAttrDropped with sync.OnceFunc, while attrnorm/truncate.go emits no diagnostic. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-10 FAIL | otel-verify.md response ledger records full 3/0, partial 2/1 and warning 3/0. Installed client.go assigns timeout to http.Client; retry.go checks elapsed+throttle but waits max(throttle, backoff). The batch timeout wrapper supplies a separate enclosing deadline. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-13 FAIL | TestResourcePreservesOperator covers resource-only identity through telemetryResource. runtime_probe.py always assigns OTEL_SERVICE_NAME; the host checker also uses an explicit service name. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-14 FAIL | otel-instrumentation.md LOG-SPEC-CLOSURE and remaining controls; retained otlp.md:464-500 distinguishes these transport clauses. The installed record.go, config.go and retry.go resolve facts omitted from the report. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
