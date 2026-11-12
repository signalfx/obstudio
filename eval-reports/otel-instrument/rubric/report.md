# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261112T062944153723Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | java/springboot-basic/qual/logging-instrument-contract | java/springboot-basic | 1 | 71% (10/14), avg score 80 | 8.6M | 22.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | java/springboot-basic/qual/logging-instrument-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 8548805 | 8379520 | 0 | 40209 | 12750 | unknown | 8589014 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | java/springboot-basic/qual/logging-instrument-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1752610 | 1586432 | 0 | 9565 | 4673 | unknown | 1762175 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | java/springboot-basic | with_skill | logging-trial-1 | rubric:rubric-2 FAIL | service/scripts/otel-entrypoint.sh; service/.observe/otel-instrumentation.md; service/.observe/verify-runtime.py covers healthy, default identity, SDK-disabled, none and one JVM endpoint conflict. |
| with_skill | java/springboot-basic | with_skill | logging-trial-1 | rubric:rubric-10 FAIL | verify-delivery.py Receiver.do_POST and drain assertions; delivery-proof-0894ff51b4b0 requests.json files and result claims. |
| with_skill | java/springboot-basic | with_skill | logging-trial-1 | rubric:rubric-11 FAIL | verify-delivery.py checks only 'Failed to export' in received bodies; retry/native.log contains no corresponding exporter diagnostic; terminal diagnostic cadence remains unproven. |
| with_skill | java/springboot-basic | with_skill | logging-trial-1 | rubric:rubric-13 FAIL | Passing host identity receipts; otel-entrypoint.sh header/endpoint gates; final runtime matrix tests only none and one conflicting JVM log endpoint. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
