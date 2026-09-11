# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20260911T040856779669Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/instrument | go/kvstore | 1 | 60% (6/10), avg score 68 | 11.5M | 33.7m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 11421223 | 11185664 | unknown | 65598 | 25238 | unknown | 11486821 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/instrument | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 171704 | 115584 | unknown | 9322 | 6289 | unknown | 181026 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-5 FAIL | service/cmd/kvstore-server/otel.go:94-100 creates sdklog LoggerProvider and otelslog handler; service/kvstore/store.go:227,314,322 and service/cmd/kvstore-server/main.go:42,66 still use standard log.Printf paths that are not sent through otelslog. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-6 FAIL | service/kvstore/http.go:61-65 emits slog.WarnContext with r.Context(); service/cmd/kvstore-server/otel.go:29-31 sets defaultServiceName = 'kvstore'; service/cmd/kvstore-server/otel_test.go:69 asserts 'kvstore'. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-7 FAIL | service/cmd/kvstore-server/otel.go:149-159 returns an error for non-local OTEL_EXPORTER_OTLP_LOGS_ENDPOINT when OTEL_LOGS_EXPORTER is otlp; main.go:31-32 fatal-exits on initOTel error. |
| with_skill | go/kvstore | with_skill | direct | rubric:rubric-8 FAIL | service/cmd/kvstore-server/otel.go:167-169 rejects OTEL_EXPORTER_OTLP_HEADERS entirely; :176-178 allows OTEL_EXPORTER_OTLP_LOGS_HEADERS to flow through when set. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
