# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261111T182845083749Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | 1 | 50% (7/14), avg score 74 | 4.5M | 18.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 4458127 | 4315776 | 0 | 36582 | 9951 | unknown | 4494709 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1684039 | 1530880 | 0 | 10538 | 5051 | unknown | 1694577 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-2 FAIL | service/.observe/otel-instrumentation.md:144; service/.observe/otel-verify.md; test_telemetry.py checks native application markers but omits native access-record preservation. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-3 FAIL | otel_setup.py:167; installed werkzeug/_internal.py::_log and logging/handler.py::_setup_logging_handler. A read-only probe produced native stderr without the bridge and none with it. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-6 FAIL | test_telemetry_unit.py:62-68; instrumentation report claims executor reuse coverage. Host concurrency uses separate per-request executors. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-8 FAIL | normal-hse4l4r5/native.log lacks access categories present in its OTLP receipts; none-a8laoiv5/native.log contains sanitized HTTP status categories. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-10 FAIL | normal-hse4l4r5/result.json retains receipt/liveness/second-stop ordering. Refusal and stall receipts each contain one 21-record log batch but no response or client-outcome receipt. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-11 FAIL | test_telemetry.py sets OTEL_BLRP_SCHEDULE_DELAY=60000. Refusal trace receipt is at 16913.769335; first log receipt follows stop at 16914.143535. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-13 FAIL | Final identity-profile raw Resources and clean-copy assertions pass. Normal native output lacks framework records retained by the explicit-none profile. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
