# create-splunk-free-account Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | create-splunk-free-account |
| Run ID | 20260909T024400470300Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.token-benchmark.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | 1 | 100% (11/11), avg score 100 | 34.2K | 1.2m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | 1 | 100% (7/7), avg score 100 | 35.1K | 1.3m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | 1 | 100% (10/10), avg score 100 | 35.6K | 1.2m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | 1 | 100% (8/8), avg score 100 | 35.3K | 1.1m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 34.8K | 1.2m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 35.0K | 57.9s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 35.2K | 56.6s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 34.5K | 45.0s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 33634 | 13056 | unknown | 586 | 395 | unknown | 34220 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 34418 | 25344 | unknown | 649 | 342 | unknown | 35067 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 34407 | 25344 | unknown | 1215 | 516 | unknown | 35622 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 34457 | 21248 | unknown | 888 | 516 | unknown | 35345 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 34369 | 17152 | unknown | 453 | 200 | unknown | 34822 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 34390 | 21248 | unknown | 611 | 402 | unknown | 35001 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 34512 | 20224 | unknown | 659 | 354 | unknown | 35171 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 34227 | 13056 | unknown | 277 | 115 | unknown | 34504 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31928 | 21248 | unknown | 1882 | 563 | unknown | 33810 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 36140 | 27392 | unknown | 997 | 302 | unknown | 37137 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31665 | 25344 | unknown | 1288 | 346 | unknown | 32953 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31049 | 25344 | unknown | 1587 | 844 | unknown | 32636 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 71289 | 46592 | unknown | 1578 | 673 | unknown | 72867 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 30942 | 25344 | unknown | 1159 | 555 | unknown | 32101 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31572 | 25344 | unknown | 1008 | 349 | unknown | 32580 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 30496 | 25344 | unknown | 913 | 393 | unknown | 31409 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
