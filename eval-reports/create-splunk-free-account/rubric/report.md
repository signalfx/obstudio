# create-splunk-free-account Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | create-splunk-free-account |
| Run ID | 20260911T202316422103Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.token-benchmark.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | 1 | 100% (11/11), avg score 100 | 36.2K | 57.8s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | 1 | 100% (7/7), avg score 100 | 40.7K | 54.5s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | 1 | 100% (10/10), avg score 100 | 36.8K | 1.1m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | 1 | 100% (8/8), avg score 100 | 41.2K | 57.9s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 36.1K | 39.2s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 36.2K | 50.1s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-resubmit-live-warning | plugins/obstudio | 1 | 100% (4/4), avg score 100 | 40.6K | 33.0s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 36.5K | 43.7s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 36.3K | 52.6s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 40.3K | 35.9s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 35658 | 17152 | unknown | 527 | 332 | unknown | 36185 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 40343 | 20224 | unknown | 391 | 84 | unknown | 40734 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 35626 | 17152 | unknown | 1185 | 474 | unknown | 36811 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 40379 | 13056 | unknown | 870 | 516 | unknown | 41249 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 35544 | 25344 | unknown | 531 | 319 | unknown | 36075 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 35663 | 17152 | unknown | 508 | 302 | unknown | 36171 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-live-warning | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 40223 | 20224 | unknown | 411 | 278 | unknown | 40634 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 35853 | 26368 | unknown | 630 | 326 | unknown | 36483 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 35668 | 17152 | unknown | 654 | 443 | unknown | 36322 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 40094 | 20224 | unknown | 236 | 132 | unknown | 40330 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 32697 | 26368 | unknown | 1784 | 766 | unknown | 34481 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 32524 | 26368 | unknown | 1011 | 335 | unknown | 33535 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 32935 | 26368 | unknown | 1733 | 728 | unknown | 34668 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 32053 | 17152 | unknown | 1135 | 379 | unknown | 33188 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31844 | 25344 | unknown | 800 | 207 | unknown | 32644 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31971 | 17152 | unknown | 966 | 376 | unknown | 32937 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-live-warning | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31755 | 17152 | unknown | 607 | 86 | unknown | 32362 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 32721 | 26368 | unknown | 887 | 225 | unknown | 33608 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31930 | 25344 | unknown | 1283 | 601 | unknown | 33213 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31620 | 25344 | unknown | 824 | 254 | unknown | 32444 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
