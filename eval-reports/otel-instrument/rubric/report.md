# otel-instrument Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-instrument |
| Run ID | 20261014T125557782207Z-selected-aggregate |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | not applicable (aggregation only) |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/dependency-log-compatibility | go/kvstore | 1 | 100% (6/6), avg score 98 | 1.3M | 7.5m | - | - | - |
| with_skill | java/springboot-basic/qual/logging-compatible-plan | java/springboot-basic | 1 | 100% (6/6), avg score 98 | 1.4M | 8.0m | - | - | - |
| with_skill | node/express-basic/qual/dependency-log-compatibility | node/express-basic | 1 | 100% (6/6), avg score 98 | 816.2K | 9.3m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-decorator-profile | python/ai-assistant-demo | 1 | 100% (6/6), avg score 97 | 4.7M | 14.3m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-operation-contract | python/ai-assistant-demo | 1 | 100% (4/4), avg score 97 | 2.7M | 9.4m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | 1 | 100% (8/8), avg score 95 | 2.2M | 10.9m | - | - | - |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | 1 | 100% (12/12), avg score 94 | 9.4M | 22.2m | - | - | - |
| with_skill | python/flask-basic/qual/local-log-launcher-policy | python/flask-basic | 1 | 100% (6/6), avg score 96 | 2.4M | 11.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/dependency-log-compatibility | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 1258111 | 1159552 | 0 | 16543 | 6673 | unknown | 1274654 |
| with_skill | java/springboot-basic/qual/logging-compatible-plan | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1396652 | 1262848 | 0 | 16445 | 4557 | unknown | 1413097 |
| with_skill | node/express-basic/qual/dependency-log-compatibility | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 794551 | 690944 | 0 | 21653 | 7400 | unknown | 816204 |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-decorator-profile | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 4709314 | 4500736 | 0 | 32750 | 12489 | unknown | 4742064 |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-operation-contract | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2680503 | 2491264 | 0 | 23071 | 6219 | unknown | 2703574 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 2136884 | 1987072 | 0 | 22400 | 5271 | unknown | 2159284 |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 9315043 | 9061760 | 0 | 45638 | 16783 | unknown | 9360681 |
| with_skill | python/flask-basic/qual/local-log-launcher-policy | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2398227 | 2270848 | 0 | 18986 | 6014 | unknown | 2417213 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/kvstore/qual/dependency-log-compatibility | go/kvstore | with_skill | codex | cumulative | measured | 1/1 recognized | 145245 | 121088 | 0 | 5639 | 2914 | unknown | 150884 |
| with_skill | java/springboot-basic/qual/logging-compatible-plan | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 742474 | 665216 | 0 | 7081 | 2582 | unknown | 749555 |
| with_skill | node/express-basic/qual/dependency-log-compatibility | node/express-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 373230 | 312064 | 0 | 6998 | 4005 | unknown | 380228 |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-decorator-profile | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 454643 | 399872 | 0 | 9669 | 4509 | unknown | 464312 |
| with_skill | python/ai-assistant-demo/qual/genai-instrument-operation-contract | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 193751 | 166912 | 0 | 5121 | 2117 | unknown | 198872 |
| with_skill | python/ai-assistant-demo/qual/genai-sdk-default-instrument | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 479822 | 400512 | 0 | 10317 | 6481 | unknown | 490139 |
| with_skill | python/flask-basic/qual/instrument | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1342240 | 1190912 | 0 | 17357 | 10487 | unknown | 1359597 |
| with_skill | python/flask-basic/qual/local-log-launcher-policy | python/flask-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 1859551 | 1753216 | 0 | 14237 | 6900 | unknown | 1873788 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
