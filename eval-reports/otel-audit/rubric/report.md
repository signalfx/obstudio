# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261116T060932547215Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.logging.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | 1 | 44/63 criteria passed; strict: 4 fail, 3 not proven, 12 N/A, 0 ungraded; 0/1 strict runs incomplete, 0 all-N/A, avg score 86 | 4.8M | 35.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 4747295 | 4499072 | 0 | 34046 | 9069 | unknown | 4781341 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/flask-basic/qual/logging-audit-contract | python/flask-basic | with_skill | codex | cumulative | measured | 8/8 recognized | 6408811 | 5566336 | 0 | 47252 | 16919 | unknown | 6456063 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-7 NOT_PROVEN | trace.jsonl item 51 changes runtime.http.config after item 49's HTTP readback; item 52 changes environment prerequisites. Item 54 exposes shutdown/accounting controls and telemetry names, but not those changed requirements. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-11 FAIL | service/.observe/otel-audit.json:116 prescribes defaults underneath Resource.create(); retained dependency-source/opentelemetry-sdk/opentelemetry/sdk/resources/__init__.py:193-205 supplies the SDK fallback. trace.jsonl item_33 confirms this source was read. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-19 FAIL | otel-audit.json:996 http.workflow.success specifies both GET inputs but only says to assert the response/status field, without expecting 200. http.framework.methods at line 1018 likewise omits explicit outcomes for several generated method cases. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-30 NOT_PROVEN | otel-audit.json:1194-1200 limits the planned value cases to ASCII strings. Retained API attributes/__init__.py:41-85 distinguishes unchanged bytes from truncated strings and recursive sequence/map cleaning; these distinctions lack planned checks or explicit capability dispositions. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-51 FAIL | otel-audit.json:116 prescribes adding defaults only for missing fields beneath Resource.create(), while runtime.identity:1080 promises python-flask-basic when operator identity is absent. evidence/dependency-source/opentelemetry-sdk/opentelemetry/sdk/resources/__init__.py:199-208 already inserts unknown_service[:exe... |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-58 NOT_PROVEN | service/.observe/otel-audit.json Receiver resolution and Configuration value cases: signals/endpoint rows; logs.config:1210 accepts local signal endpoints but omits an independently checked host/port/path approval boundary and alias-negative control. |
| with_skill | python/flask-basic | with_skill | logging-trial-1 | rubric:rubric-62 FAIL | service/.observe/otel-audit.json:660-667 lists both fields. Retained instrumentation/_semconv.py:169-173 permits only http.request.method and url.scheme; WSGI _parse_active_request_count_attrs:477-483 applies that list to the Flask metric. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
