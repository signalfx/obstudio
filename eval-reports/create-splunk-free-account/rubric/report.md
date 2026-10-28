# create-splunk-free-account Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | create-splunk-free-account |
| Run ID | 20261027T234525831334Z |
| Agent model | gpt-6-luna |
| Judge model | gpt-6-luna |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | 1 | 90% (9/10), avg score 90 | 43.5K | 1.1m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | 1 | 100% (7/7), avg score 100 | 43.5K | 40.7s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | 1 | 91% (10/11), avg score 91 | 42.5K | 1.0m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | 1 | 100% (8/8), avg score 100 | 42.4K | 47.4s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 43.5K | 36.2s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 43.5K | 39.1s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 42.5K | 39.8s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 42.0K | 34.5s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-submit-after-consent | plugins/obstudio | 1 | 100% (2/2), avg score 100 | 41.8K | 35.3s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 41.6K | 32.1s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 42947 | 27392 | 0 | 573 | 376 | unknown | 43520 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 42960 | 19200 | 0 | 547 | 230 | unknown | 43507 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41452 | 18432 | 0 | 1087 | 460 | unknown | 42539 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41420 | 30080 | 0 | 964 | 690 | unknown | 42384 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 42888 | 19200 | 0 | 602 | 415 | unknown | 43490 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 42959 | 30848 | 0 | 590 | 375 | unknown | 43549 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41685 | 18560 | 0 | 817 | 490 | unknown | 42502 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41489 | 18432 | 0 | 520 | 348 | unknown | 42009 |
| with_skill | plugins/obstudio/qual/free-account-submit-after-consent | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41329 | 18432 | 0 | 442 | 135 | unknown | 41771 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41250 | 18432 | 0 | 384 | 279 | unknown | 41634 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 30991 | 15104 | 0 | 2158 | 1461 | unknown | 33149 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 30900 | 14976 | 0 | 950 | 510 | unknown | 31850 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31339 | 26752 | 0 | 1486 | 600 | unknown | 32825 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 30525 | 14848 | 0 | 972 | 391 | unknown | 31497 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 28740 | 13952 | 0 | 792 | 319 | unknown | 29532 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 28823 | 13952 | 0 | 824 | 453 | unknown | 29647 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 29474 | 14208 | 0 | 701 | 272 | unknown | 30175 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 28848 | 25856 | 0 | 736 | 347 | unknown | 29584 |
| with_skill | plugins/obstudio/qual/free-account-submit-after-consent | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 28452 | 25600 | 0 | 811 | 580 | unknown | 29263 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 29995 | 14592 | 0 | 701 | 329 | unknown | 30696 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | consent-gate | rubric:rubric-1 FAIL | “I would call `observer_splunk_free_account_region_detect` with no arguments.” |
| with_skill | plugins/obstudio | with_skill | location-privacy | rubric:rubric-8 FAIL | Says “The detector returns a public tool value” and “The label can be replaced with another supported choice,” without specifying the exact three values or replacement formats. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
