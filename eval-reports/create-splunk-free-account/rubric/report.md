# create-splunk-free-account Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | create-splunk-free-account |
| Run ID | 20260902T151235604085Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | 1 | 100% (10/10), avg score 96 | 41.6K | 45.3s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | 1 | 100% (7/7), avg score 100 | 41.7K | 48.3s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | 1 | 100% (10/10), avg score 100 | 42.0K | 51.4s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | 1 | 100% (8/8), avg score 100 | 41.7K | 42.4s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | 1 | 100% (6/6), avg score 95 | 41.3K | 38.5s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 41.5K | 38.7s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | 1 | 100% (6/6), avg score 100 | 41.8K | 41.3s | - | - | - |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | 1 | 100% (5/5), avg score 100 | 41.3K | 32.4s | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41305 | 20224 | unknown | 337 | 74 | unknown | 41642 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41335 | 20224 | unknown | 355 | 48 | unknown | 41690 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41270 | 28416 | unknown | 695 | 12 | unknown | 41965 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41213 | 20224 | unknown | 479 | 193 | unknown | 41692 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41156 | 20224 | unknown | 184 | 0 | unknown | 41340 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41291 | 4864 | unknown | 256 | 52 | unknown | 41547 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41392 | 28416 | unknown | 362 | 57 | unknown | 41754 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 41105 | 20224 | unknown | 206 | 37 | unknown | 41311 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | plugins/obstudio/qual/free-account | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38394 | 28416 | unknown | 1083 | 177 | unknown | 39477 |
| with_skill | plugins/obstudio/qual/free-account-accepted | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 62976 | 39040 | unknown | 1111 | 257 | unknown | 64087 |
| with_skill | plugins/obstudio/qual/free-account-location-privacy | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38694 | 28416 | unknown | 1107 | 84 | unknown | 39801 |
| with_skill | plugins/obstudio/qual/free-account-native-form | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37929 | 20224 | unknown | 829 | 66 | unknown | 38758 |
| with_skill | plugins/obstudio/qual/free-account-outcome-unknown | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37863 | 28416 | unknown | 932 | 22 | unknown | 38795 |
| with_skill | plugins/obstudio/qual/free-account-region-review-gate | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37759 | 20224 | unknown | 843 | 223 | unknown | 38602 |
| with_skill | plugins/obstudio/qual/free-account-resubmit-same-email | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 38462 | 4864 | unknown | 909 | 27 | unknown | 39371 |
| with_skill | plugins/obstudio/qual/free-account-tool-unavailable | plugins/obstudio | with_skill | codex | cumulative | measured | 1/1 recognized | 37398 | 28416 | unknown | 549 | 49 | unknown | 37947 |

## Rubric Failures

No rubric failures.

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
