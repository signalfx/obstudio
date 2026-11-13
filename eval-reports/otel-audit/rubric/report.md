# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | grade-only-ccff3b7-to-d507eb43 |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | 1 | 92% (56/61), avg score 88 | 5.3M | 20.1m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 5249443 | 5065344 | 0 | 32685 | 7508 | unknown | 5282128 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2872014 | 2720896 | 0 | 19170 | 9205 | unknown | 2891184 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-9 FAIL | service/.observe/otel-audit.json Selected configuration reader inventory and runtime.receiver; retained candidate-source/opentelemetry-sdk/opentelemetry/sdk/metrics/_internal/export/__init__.py:488-557 under service/.observe/evidence contains the unresolved reader chain; trace.jsonl source-inspection commands do not... |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-10 FAIL | service/.observe/otel-audit.json runtime.receiver acceptance; service/.observe/evidence/candidate-source/opentelemetry-sdk/opentelemetry/sdk/metrics/_internal/export/__init__.py:506-518 parses floats and handles invalid or empty inputs. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-13 FAIL | service/.observe/otel-audit.json Resource and activation authority evidence; Shared process Resource telemetry; runtime.identity and logs.identity. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-41 FAIL | service/.observe/otel-audit.json logs.fault acceptance; retained candidate OTLP common/http.py:211-239 and SDK _shared_internal/__init__.py:33-53 show emitting and suppression paths that are not reconciled into a saved bound. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-57 FAIL | service/.observe/otel-audit.json logs.configuration trigger and acceptance; runtime.selectors and logs.fault allocate other scenarios but do not bind the selected header conflicts. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.

## Execution provenance

This is a grader-only reassessment of the retained actor from `ccff3b7`, judged against the actual corrected definition at `d507eb43`. No actor, application, test or workflow was rerun. Actor token usage and time are retained actual execution facts; judge usage and time come from the corrected executed judge. Canonical skills, bare task, approved eval inputs, fixture actor sources and applicable harness inputs were proved unchanged; only the recorded judge definition inputs differ. This report covers only `python/flask-basic`, `logging-trial-1`, with 61 criteria. It supplies zero fresh actor/workflow/cohort credit. Audit is plan-only and standalone verification is prerequisite-only. Detailed stage source hashes and actual model metadata are in benchmark.json execution_provenance.
