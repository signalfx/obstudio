# create-splunk-free-account Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | create-splunk-free-account |
| Run ID | 20261105T171048975112Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | 1 | 100% (10/10), avg score 100 | 43.1K | 43.1s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | 1 | 100% (7/7), avg score 100 | 45.0K | 38.0s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | 1 | 100% (11/11), avg score 100 | 45.5K | 54.5s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | 1 | 100% (8/8), avg score 100 | 45.2K | 47.1s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 43.0K | 32.8s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 43.4K | 34.8s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 45.0K | 38.3s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 44.6K | 38.2s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-submit-after-consent | plugins/obstudio | 1 | 0% (0/2), avg score 50 | 44.7K | 36.8s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 43.0K | 30.0s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 42765 | 31360 | 0 | 351 | 132 | unknown | 43116 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 44581 | 32256 | 0 | 465 | 143 | unknown | 45046 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 44544 | 19968 | 0 | 927 | 92 | unknown | 45471 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 44543 | 24576 | 0 | 657 | 275 | unknown | 45200 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 42673 | 31360 | 0 | 358 | 109 | unknown | 43031 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 43004 | 31488 | 0 | 353 | 136 | unknown | 43357 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 44459 | 32256 | 0 | 502 | 158 | unknown | 44961 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 44315 | 19840 | 0 | 325 | 147 | unknown | 44640 |
| with_skill | plugins/obstudio/qual/free-account-submit-after-consent | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 44251 | 32128 | 0 | 422 | 93 | unknown | 44673 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 42626 | 31360 | 0 | 330 | 211 | unknown | 42956 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 51234 | 30848 | 0 | 1050 | 180 | unknown | 52284 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 30797 | 27264 | 0 | 610 | 0 | unknown | 31407 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31378 | 14976 | 0 | 1041 | 136 | unknown | 32419 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 32096 | 15616 | 0 | 765 | 51 | unknown | 32861 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31675 | 27776 | 0 | 574 | 0 | unknown | 32249 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31787 | 27776 | 0 | 614 | 52 | unknown | 32401 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 32403 | 15744 | 0 | 588 | 0 | unknown | 32991 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 69937 | 44160 | 0 | 574 | 47 | unknown | 70511 |
| with_skill | plugins/obstudio/qual/free-account-submit-after-consent | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 36164 | 15488 | 0 | 614 | 233 | unknown | 36778 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 31459 | 27648 | 0 | 455 | 0 | unknown | 31914 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | submit-after-consent | rubric:rubric-1 FAIL | last_message.md contains only the approved confirmation, beginning with “**Thank you for registering. Your free edition account is on its way!**”. All grade.json guard checks passed. |
| with_skill | plugins/obstudio | with_skill | submit-after-consent | rubric:rubric-2 FAIL | allowed-tools: mcp__plugin_obstudio_obstudio__observer_splunk_free_account_region_detect, mcp__plugin_obstudio_obstudio__observer_splunk_free_account_create |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
