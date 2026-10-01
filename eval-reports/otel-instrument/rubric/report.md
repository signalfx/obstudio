# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261001T171120090826Z |
| Agent model | - |
| Judge model | - |
| Rubric enabled | True |
| Workers | 1 |
| Config | - |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/instrument | python/splunk-ao-integration-demo | 1 | 67% (4/6), avg score 76 | 5.2M | 9.7m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/instrument | python/splunk-ao-integration-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 5138629 | 5027200 | 0 | 20255 | 4828 | unknown | 5158884 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | python/splunk-ao-integration-demo/qual/instrument | python/splunk-ao-integration-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 174283 | 125824 | 0 | 1863 | 499 | unknown | 176146 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | python/splunk-ao-integration-demo | with_skill | integration-paths | rubric:rubric-4 FAIL | service/decorator_app.py:80-89; service/tests/test_integration_paths.py:22-63 |
| with_skill | python/splunk-ao-integration-demo | with_skill | integration-paths | rubric:rubric-5 FAIL | service/tests/test_integration_paths.py:54-57,119-126; .observe/otel-verify.json |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
