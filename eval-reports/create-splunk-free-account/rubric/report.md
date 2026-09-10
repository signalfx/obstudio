# create-splunk-free-account Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | create-splunk-free-account |
| Run ID | 20260910T183817322766Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | 1 | 100% (10/10), avg score 100 | 42.1K | 1.3m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | 1 | 100% (7/7), avg score 100 | 42.2K | 1.0m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | 1 | 100% (10/10), avg score 100 | 42.6K | 1.3m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | 1 | 100% (8/8), avg score 100 | 42.6K | 1.3m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 42.0K | 1.1m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 42.5K | 1.3m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 42.4K | 1.0m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 42.6K | 1.0m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 41.5K | 50.5s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41360 | 28416 | unknown | 776 | 516 | unknown | 42136 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41376 | 20224 | unknown | 821 | 516 | unknown | 42197 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41385 | 28416 | unknown | 1208 | 516 | unknown | 42593 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41294 | 22272 | unknown | 1340 | 1034 | unknown | 42634 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41229 | 28416 | unknown | 721 | 516 | unknown | 41950 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41538 | 20224 | unknown | 931 | 723 | unknown | 42469 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41520 | 28416 | unknown | 879 | 516 | unknown | 42399 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41624 | 13056 | unknown | 973 | 819 | unknown | 42597 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41108 | 28416 | unknown | 421 | 304 | unknown | 41529 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38336 | 28416 | unknown | 2104 | 1217 | unknown | 40440 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38204 | 28416 | unknown | 1302 | 663 | unknown | 39506 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38497 | 20224 | unknown | 1872 | 945 | unknown | 40369 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37920 | 20224 | unknown | 1473 | 710 | unknown | 39393 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37619 | 20224 | unknown | 1354 | 766 | unknown | 38973 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37708 | 28416 | unknown | 1484 | 951 | unknown | 39192 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38265 | 28416 | unknown | 1295 | 694 | unknown | 39560 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37637 | 20224 | unknown | 1240 | 652 | unknown | 38877 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37361 | 20224 | unknown | 1091 | 574 | unknown | 38452 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
