# splunk-configure Rubric Codex Eval Report

Evaluated source: `7db9a57ada23292c0047e9d5cac24fbf0208847b`. Case outcomes: 1 failed, 2 passed. These are the saved run's results; no actor or judge was rerun for this publication.

Rubric grades are available for **3 of 3 prompts**. Case outcomes also include execution and workflow checks; they are not a count of checklist items.

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-configure |
| Run ID | 20261116T170554Z-consolidated-report |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 8 |
| Config | evals/codex-evals.logging.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | Case outcomes | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | 1 | 1 failed | 36% (4/11), avg score 40 | 553.9K | 3.7m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | 1 | 1 passed | 100% (4/4), avg score 100 | 662.9K | 7.9m | - | - | - |
| with_skill | python/ai-assistant-demo/qual/finding-group-configure | python/ai-assistant-demo | 1 | 1 passed | 100% (7/7), avg score 100 | 483.8K | 7.5m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | with_skill | codex | cumulative | measured | 1/1 recognized | 547501 | 485760 | 0 | 6393 | 1247 | unknown | 553894 |
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 645346 | 509952 | 0 | 17569 | 1346 | unknown | 662915 |
| with_skill | python/ai-assistant-demo/qual/finding-group-configure | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 466153 | 410624 | 0 | 17629 | 1854 | unknown | 483782 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | with_skill | codex | cumulative | measured | 1/1 recognized | 167334 | 139008 | 0 | 2330 | 269 | unknown | 169664 |
| with_skill | python/ai-assistant-demo/qual/ao-target-handoff-configure | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 648447 | 578048 | 0 | 3107 | 321 | unknown | 651554 |
| with_skill | python/ai-assistant-demo/qual/finding-group-configure | python/ai-assistant-demo | with_skill | codex | cumulative | measured | 1/1 recognized | 376531 | 325632 | 0 | 2690 | 188 | unknown | 379221 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | dashboards/checkout-configure | with_skill | generate | rubric:rubric-1 FAIL | detectors.md reports zero generated detectors in every category; no P99 threshold was generated. |
| with_skill | dashboards/checkout-configure | with_skill | generate | rubric:rubric-2 FAIL | detectors.md merges checkout.payment.errors into the /payment duration group; detectors.tf contains no detector resources. |
| with_skill | dashboards/checkout-configure | with_skill | generate | rubric:rubric-3 FAIL | detectors.tf contains only comments, required_providers, and provider configuration. |
| with_skill | dashboards/checkout-configure | with_skill | generate | rubric:rubric-4 FAIL | detectors.tf contains no program_text, data(), detect(), or baseline alerting expressions. |
| with_skill | dashboards/checkout-configure | with_skill | generate | rubric:rubric-5 FAIL | variables.tf declares realm, sensitive api_token, service_name, and notification_channel, followed by 'No threshold variables'; terraform.tfvars.example contains empty credentials. |
| with_skill | dashboards/checkout-configure | with_skill | generate | rubric:rubric-6 FAIL | detectors.md declares Result: Blocked and asks for verification or source-only acceptance before generation. |
| with_skill | dashboards/checkout-configure | with_skill | generate | rubric:rubric-7 FAIL | Its resource table lists 'No detector resources', metric 'None accepted', and severity 'N/A'. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
