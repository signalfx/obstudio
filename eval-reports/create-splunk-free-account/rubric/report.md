# create-splunk-free-account Rubric Codex Eval Report

Evaluated source: `7db9a57ada23292c0047e9d5cac24fbf0208847b`. Case outcomes: 2 failed, 8 passed. These are the saved run's results; no actor or judge was rerun for this publication.

Rubric grades are available for **10 of 10 prompts**. Case outcomes also include execution and workflow checks; they are not a count of checklist items.

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | create-splunk-free-account |
| Run ID | 20261116T170554Z-consolidated-report |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 8 |
| Config | evals/codex-evals.logging.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | Case outcomes | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | 1 | 1 passed | 100% (10/10), avg score 100 | 45.1K | 47.0s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | 1 | 1 passed | 100% (7/7), avg score 100 | 38.6K | 39.4s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | 1 | 1 passed | 100% (11/11), avg score 100 | 45.8K | 1.0m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | 1 | 1 passed | 100% (8/8), avg score 100 | 38.7K | 44.4s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | 1 | 1 passed | 100% (6/6), avg score 100 | 38.4K | 43.2s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | 1 | 1 passed | 100% (5/5), avg score 100 | 38.3K | 35.4s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | 1 | 1 passed | 100% (6/6), avg score 100 | 38.8K | 39.6s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | 1 | 1 passed | 100% (5/5), avg score 100 | 38.2K | 33.2s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-submit-after-consent | plugins/obstudio | 1 | 1 failed | 0% (0/2), avg score 50 | 38.2K | 37.3s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | 1 | 1 failed | 100% (5/5), avg score 100 | 16.9K | 29.8s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 44677 | 29824 | 0 | 402 | 181 | unknown | 45079 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38179 | 16768 | 0 | 398 | 74 | unknown | 38577 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 44854 | 20096 | 0 | 978 | 147 | unknown | 45832 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38079 | 16640 | 0 | 654 | 283 | unknown | 38733 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38011 | 16640 | 0 | 388 | 126 | unknown | 38399 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37957 | 16768 | 0 | 370 | 164 | unknown | 38327 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38239 | 9728 | 0 | 576 | 237 | unknown | 38815 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37873 | 16640 | 0 | 322 | 143 | unknown | 38195 |
| with_skill | plugins/obstudio/qual/free-account-submit-after-consent | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37809 | 26368 | 0 | 412 | 83 | unknown | 38221 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 16730 | 0 | 0 | 185 | 141 | unknown | 16915 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 43801 | 25856 | 0 | 982 | 116 | unknown | 44783 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 25885 | 12544 | 0 | 682 | 53 | unknown | 26567 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 26456 | 12544 | 0 | 1093 | 155 | unknown | 27549 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 32321 | 15744 | 0 | 763 | 67 | unknown | 33084 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 25225 | 22016 | 0 | 546 | 0 | unknown | 25771 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 32057 | 15616 | 0 | 570 | 44 | unknown | 32627 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 32658 | 15872 | 0 | 589 | 0 | unknown | 33247 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 25302 | 12288 | 0 | 581 | 64 | unknown | 25883 |
| with_skill | plugins/obstudio/qual/free-account-submit-after-consent | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 36406 | 15616 | 0 | 586 | 243 | unknown | 36992 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31716 | 15488 | 0 | 595 | 146 | unknown | 32311 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | submit-after-consent | rubric:rubric-1 FAIL | last_message.md contains only the confirmation template; no observer_splunk_free_account_create call or argument object appears. All grade.json guard checks passed. |
| with_skill | plugins/obstudio | with_skill | submit-after-consent | rubric:rubric-2 FAIL | SKILL.md grants only mcp__plugin_obstudio_obstudio__observer_splunk_free_account_region_detect and mcp__plugin_obstudio_obstudio__observer_splunk_free_account_create, with no unscoped names. last_message.md contains no modeled tool call. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
