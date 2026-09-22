# create-splunk-free-account Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | create-splunk-free-account |
| Run ID | 20260921T234133309675Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | 1 | 100% (10/10), avg score 100 | 40.6K | 1.1m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | 1 | 100% (7/7), avg score 100 | 40.5K | 1.0m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | 1 | 91% (10/11), avg score 91 | 40.7K | 1.5m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | 1 | 100% (8/8), avg score 100 | 41.7K | 1.4m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 41.0K | 1.0m | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 40.6K | 58.2s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 40.3K | 51.3s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 40.0K | 53.1s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | 1 | 60% (3/5), avg score 75 | 39.6K | 50.4s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 39611 | 26368 | 0 | 1000 | 808 | unknown | 40611 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 39512 | 26368 | 0 | 1016 | 707 | unknown | 40528 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 39468 | 26368 | 0 | 1239 | 605 | unknown | 40707 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 39831 | 18176 | 0 | 1864 | 1550 | unknown | 41695 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 39706 | 26368 | 0 | 1249 | 1032 | unknown | 40955 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 39613 | 26368 | 0 | 989 | 720 | unknown | 40602 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 39448 | 18176 | 0 | 822 | 516 | unknown | 40270 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 39308 | 26368 | 0 | 663 | 516 | unknown | 39971 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 39104 | 26368 | 0 | 525 | 418 | unknown | 39629 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 27906 | 22272 | 0 | 1938 | 1087 | unknown | 29844 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 27704 | 22272 | 0 | 1555 | 887 | unknown | 29259 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 27985 | 22272 | 0 | 2696 | 1681 | unknown | 30681 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 27526 | 22272 | 0 | 1799 | 1092 | unknown | 29325 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 27036 | 22272 | 0 | 1262 | 684 | unknown | 28298 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 27201 | 22272 | 0 | 1453 | 903 | unknown | 28654 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 27741 | 22272 | 0 | 1264 | 657 | unknown | 29005 |
| with_skill | plugins/obstudio/qual/free-account-setup-pending | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 27167 | 12672 | 0 | 1309 | 697 | unknown | 28476 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 26821 | 22272 | 0 | 1207 | 668 | unknown | 28028 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | plugins/obstudio | with_skill | location-privacy | rubric:rubric-4 FAIL | Includes `data.countryName -> country`, `data.region -> state`, `data.city -> city`, `data.postalCode -> postalCode`, and lists `latitude`, `longitude`, `metroCode`, `regionCode`, `salesRegion`, `countryCode`, and root `region` as not submitted. |
| with_skill | plugins/obstudio | with_skill | observer-required | rubric:rubric-2 FAIL | "the compatible Splunk Observability Studio backend tool... is unavailable" |
| with_skill | plugins/obstudio | with_skill | observer-required | rubric:rubric-5 FAIL | The final message contains no instruction such as starting or making available a compatible backend exposing `observer_splunk_free_account_create`. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
