# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261112T015447024501Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | 1 | 43% (6/14), avg score 76 | 4.7M | 19.9m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 4614019 | 4468736 | 0 | 38191 | 9597 | unknown | 4652210 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2876385 | 2722688 | 0 | 12366 | 6763 | unknown | 2888751 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-2 FAIL | service/.observe/otel-instrumentation.md:75; service/tests/test_telemetry.py:58; service/tests/runtime_check.py:88. All four final host profiles supply identity, and no absent-identity launch is allocated in the saved handoff. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-8 FAIL | service/tests/test_telemetry.py:130; service/tests/runtime_check.py:116-121,196; service/otel_setup.py:49. The retained investigation covers Werkzeug's logging bootstrap, without a matching Flask.log_exception/access-renderer trail and parameterized privacy witnesses. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-9 FAIL | service/otel_setup.py:68-71; service/.observe/otel-instrumentation.md:114; service/tests/test_telemetry.py:137-140. No retained test asserts downstream dropped_attributes or droppedAttributesCount preservation. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-10 FAIL | service/tests/shutdown_check.py:75-101; service/.observe/stop-xm2296d5/result.json. The host checker explicitly records shutdown_drain_proven=false. Expected explorer eviction is not treated as a wiring failure. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-11 FAIL | service/tests/test_telemetry.py:226-263 records request data and returns a synthetic HTTP 400, but does not capture LogRecordExportResult.FAILURE or the terminal client outcome. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-12 FAIL | trace.jsonl item_6 shows original make dev with explicit --reload. The final Makefile sets RELOAD ?= 0 and emits --no-reload. Final source hashes and all four final host receipts match current source. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-13 FAIL | Final host profiles run-5fyeij5r, run-y0ujagxz, and run-4_5awap6; service/tests/test_telemetry.py:58; service/Makefile. Every retained normal launch supplies OTEL_SERVICE_NAME or resource service.name. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-14 FAIL | service/.observe/otel-instrumentation.md:101-117; service/otel_setup.py:64-71,115-116. The matrix discusses ReadWriteLogRecord mutation but does not allocate these selected processor obligations. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
