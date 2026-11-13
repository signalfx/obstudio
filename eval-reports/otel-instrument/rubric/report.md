# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | grade-only-ccff3b7-to-d507eb43 |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | 1 | 75% (46/61), avg score 76 | 7.5M | 29.2m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 7423369 | 7256192 | 0 | 47046 | 10203 | unknown | 7470415 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-instrument-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 3735343 | 3550208 | 0 | 27076 | 16659 | unknown | 3762419 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-5 FAIL | trace.jsonl items 89 and 95 change implementation/report artifacts; item 97 uses rg against the final reports rather than reading their complete saved expectations. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-7 FAIL | baked-controls.md assigns both f00576e63b14d3879b3b977e9df6bbe6 and ff025e6a3bbd9cd9c702aebcc1f647cc to each request.0 control; the two profiles' requests.json files identify different owning requests. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-9 FAIL | otel-instrumentation.md configuration section; dependency-evidence.json records signatures/current versions; installed PeriodicExportingMetricReader constructor contains additional float conversions and fallback handling. Makefile uses RELOAD=--no-reload effectively. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-11 FAIL | otel_setup.py:141–186 introduces signal selectors; test_telemetry.py:156–171 exercises logs branches only; installed instrumentation/logging/__init__.py:208–240 has separate legacy/new bridge flags. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-13 FAIL | test_telemetry.py:52–60; verify_runtime.py:47–48; verify_stop.py:60; host profile result.json files cover Resource-only, explicit override and whitespace identities on logs/spans. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-17 FAIL | expected-controls.json reuses runtime-d9d87d4da2/request.0/asserted across profiles; build_evidence.py:67–85; baked-controls.md:368–381 and 593–606 show duplicate witnesses. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-18 FAIL | trace.jsonl item 96 retains successful evidence-bake and validate-evidence-receipt output; service/.observe/otel-evidence-receipt.json exists; filesystem inspection found no evidence-receipt-check.json. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-19 FAIL | app.py:79 and 105; expected-controls.json lists four workflow log controls but no startup or runtime request completed control; otel-direct-evidence-index.json repeats that declared scope. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-26 FAIL | otel_setup.py:51–60; runtime-d9d87d4da2/normal/logs.json contains HTTP server activity and application error without HTTP method/route/status, while native.log retains the actual access/error details. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-28 FAIL | test_telemetry.py:230–244 emits three events with OTEL_SPAN_EVENT_COUNT_LIMIT=2; the first, overflowing event is removed before the before/after event comparison. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-41 FAIL | test_telemetry.py:35–38 and 312–314; make-test-final.log retains only the test's ok result, without the final SDK diagnostic lines or counts. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-44 FAIL | test_telemetry.py:287–308 replaces trace export and PeriodicExportingMetricReader; runtime-d9d87d4da2 receiver captures do not exercise that fault. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-46 FAIL | otel-instrumentation.md LOG-SPEC-CLOSURE; dependency-evidence.json sources are PyPI URLs; trace web entries retain page metadata without an addressable revision/clause receipt. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-56 FAIL | otel_setup.py:141–165 introduces application-owned destination resolution; Makefile and host captures use 127.0.0.1:55718; focused conflict checks substitute exporters. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-57 FAIL | test_telemetry.py:159–170 and BOOT exporter substitutions; otel_setup.py:162 checks shared headers; no retained received-header assertions cover valid logs headers or conflicting generic headers. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.

## Execution provenance

This is a grader-only reassessment of the retained actor from `ccff3b7`, judged against the actual corrected definition at `d507eb43`. No actor, application, test or workflow was rerun. Actor token usage and time are retained actual execution facts; judge usage and time come from the corrected executed judge. Canonical skills, bare task, approved eval inputs, fixture actor sources and applicable harness inputs were proved unchanged; only the recorded judge definition inputs differ. This report covers only `python/flask-basic`, `logging-trial-1`, with 61 criteria. It supplies zero fresh actor/workflow/cohort credit. Audit is plan-only and standalone verification is prerequisite-only. Detailed stage source hashes and actual model metadata are in benchmark.json execution_provenance.

The separate trusted canonical receipt check is valid with direct result Partial. It ran after the model and does not settle semantic capture/import truth. The raw rubric-18 missing-gate-file note and 46/61 grade remain unchanged; mechanical acceptance is recorded independently.
