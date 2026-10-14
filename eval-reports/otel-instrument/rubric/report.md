# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261014T112937676348Z-aggregate |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/dependency-log-compatibility | go/kvstore | 1 | 100% (6/6), avg score 96 | 1.5M | 8.5m | - | - | - |
| with_skill | java/springboot-basic/qual/logging-compatible-plan | java/springboot-basic | 1 | 100% (6/6), avg score 96 | 1.3M | 8.8m | - | - | - |
| with_skill | node/express-basic/qual/dependency-log-compatibility | node/express-basic | 1 | 100% (6/6), avg score 98 | 825.2K | 8.5m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-decorator-profile | python/ai-assistant-demo | 1 | 100% (6/6), avg score 95 | 3.7M | 11.8m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-operation-contract | python/ai-assistant-demo | 1 | 100% (4/4), avg score 96 | 4.7M | 11.3m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | 1 | 100% (8/8), avg score 96 | 3.5M | 11.0m | - | - | - |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | 1 | 100% (12/12), avg score 94 | 10.1M | 21.0m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/dependency-log-compatibility | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 1502862 | 1358080 | 0 | 19911 | 8855 | unknown | 1522773 |
| with_skill | java/springboot-basic/qual/logging-compatible-plan | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1305394 | 1180928 | 0 | 18267 | 5384 | unknown | 1323661 |
| with_skill | node/express-basic/qual/dependency-log-compatibility | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 803920 | 705280 | 0 | 21250 | 8078 | unknown | 825170 |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-decorator-profile | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3722587 | 3507840 | 0 | 26504 | 8010 | unknown | 3749091 |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-operation-contract | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 4631444 | 4445312 | 0 | 23703 | 6983 | unknown | 4655147 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 3468841 | 3274880 | 0 | 25300 | 7589 | unknown | 3494141 |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 10029476 | 9630464 | 0 | 48949 | 16999 | unknown | 10078425 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/dependency-log-compatibility | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 418284 | 365056 | 0 | 5863 | 2498 | unknown | 424147 |
| with_skill | java/springboot-basic/qual/logging-compatible-plan | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 786320 | 713728 | 0 | 7658 | 3990 | unknown | 793978 |
| with_skill | node/express-basic/qual/dependency-log-compatibility | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 173811 | 107776 | 0 | 5199 | 2204 | unknown | 179010 |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-decorator-profile | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 324420 | 269696 | 0 | 8810 | 4200 | unknown | 333230 |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-operation-contract | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 377735 | 312448 | 0 | 9436 | 4622 | unknown | 387171 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 466476 | 421760 | 0 | 7007 | 3109 | unknown | 473483 |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 917696 | 805248 | 0 | 11609 | 5581 | unknown | 929305 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
