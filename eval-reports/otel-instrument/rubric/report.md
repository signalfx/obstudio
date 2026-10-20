# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261019T181503344566Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.model-override.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | 2 | 82% (18/22), avg score 76 | 2.0M | 13.6m | - | - | - |
| with_skill | java/springboot-basic/qual/logging-compatible-plan | java/springboot-basic | 1 | 100% (6/6), avg score 100 | 667.0K | 7.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 1922618 | 1743744 | 0 | 29028 | 4883 | unknown | 1951646 |
| with_skill | java/springboot-basic/qual/logging-compatible-plan | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 650344 | 576384 | 0 | 16663 | 1736 | unknown | 667007 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | java/springboot-basic/qual/instrument | java/springboot-basic | with_skill | codex | cumulative | measured | 2/2 recognized | 354211 | 304256 | 0 | 6000 | 1330 | unknown | 360211 |
| with_skill | java/springboot-basic/qual/logging-compatible-plan | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 512130 | 447360 | 0 | 2286 | 103 | unknown | 514416 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | java/springboot-basic | with_skill | direct | rubric:rubric-5 FAIL | run-otel.sh and .env.example use springboot-basic. .observe/otel-verify.md explicitly reports no captured LogRecords or runtime proof of severity, correlation, duplication, or sink preservation. |
| with_skill | java/springboot-basic | with_skill | direct | rubric:rubric-7 FAIL | Lines 147-148 accept arbitrary signal-specific logs endpoints; lines 153-154 accept any generic HTTP host. An in-memory guard probe reached the Java launch boundary for https://remote.invalid/v1/logs, http://remote.invalid:4318, and a remote generic HTTPS endpoint paired with explicit local logs. Generic headers wer... |
| with_skill | java/springboot-basic | with_skill | runtime-preserving | rubric:rubric-5 FAIL | The launcher defaults service.name to springboot-basic rather than java-springboot-basic. TaskController.create retains WARN body 'runtime request completed', but .observe/otel-verify.md reports no received LogRecord or trace/span correlation evidence. |
| with_skill | java/springboot-basic | with_skill | runtime-preserving | rubric:rubric-7 FAIL | service/run-otel.sh accepts explicit logs endpoints without locality validation and accepts any http:// generic hostname. In-memory invocation probes reached the Java execution boundary with https://remote.example/v1/logs, http://remote.example:4318, and a remote HTTPS generic endpoint paired with local logs. Generi... |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
