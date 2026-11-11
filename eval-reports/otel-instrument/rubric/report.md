# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261111T215146697393Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | 1 | 64% (9/14), avg score 76 | 4.2M | 18.8m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 4199262 | 4054656 | 0 | 39753 | 10364 | unknown | 4239015 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/logging-instrument-contract | go/chi-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2140122 | 1978880 | 0 | 9331 | 4153 | unknown | 2149453 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-2 FAIL | otel-instrumentation.md lists four host profiles, all with supplied identity. TestResourcePrecedence/default exercises only the resource helper. TestLogPolicyAndActivation's disabled cases check logger preservation and shutdown, while TestPropagationPeerFlagsAndBaggage constructs its own propagator. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-10 FAIL | Every final host result explicitly reports shutdown_drain_proven=false. otel-instrumentation.md:165–171 defers the queued-record trial; no retained trial contains a pending-record witness and its shutdown receipt/client outcome. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-11 FAIL | verify_log_modes.py tests none, nonlocal endpoint, unsupported protocol, generic headers and SDK-disabled modes. These suppress pipeline construction; the reports explicitly retain transport-fault and diagnostic-volume behavior as unproven. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-13 FAIL | Host resource-only, explicit-override and whitespace profiles preserve service.name, service.version and obstudio.eval.preserved. TestRuntimeHTTP explicitly supplies runtime-http-test, and all policy launches supply identities. Only TestResourcePrecedence/default checks go-chi-basic. |
| with_skill | go/chi-basic | with_skill | logging-trial-1 | rubric:rubric-14 FAIL | telemetry.go:60 uses raw EqualFold comparison. Disabled-case tests cover only true and TrUe; the report explicitly says other spellings are untested. No retained assertions cover 1, t, T or padded true, or disposition the recommended invalid-value diagnostic. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
