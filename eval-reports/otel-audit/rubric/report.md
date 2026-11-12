# otel-audit Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-audit |
| Run ID | 20261112T061304851814Z |
| Agent model | gpt-6.1-sol |
| Judge model | gpt-6.1-sol |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | java/springboot-basic/qual/logging-audit-contract | java/springboot-basic | 1 | 79% (11/14), avg score 85 | 4.0M | 16.6m | - | - | - |

## Agent Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | java/springboot-basic/qual/logging-audit-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 3929316 | 3773568 | 0 | 26183 | 5020 | unknown | 3955499 |

## Judge Token Usage

| Mode | Eval | Service | Side | Provider | Source | Status | Coverage | Input | Cached Input | Cache Creation Input | Output | Reasoning Output | Provider Total | Derived Total |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | java/springboot-basic/qual/logging-audit-contract | java/springboot-basic | with_skill | codex | cumulative | measured | 1/1 recognized | 2368841 | 2229760 | 0 | 11789 | 6441 | unknown | 2380630 |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | java/springboot-basic | with_skill | logging-trial-1 | rubric:rubric-2 FAIL | saved-contracts.json matches the final findings, scenarios and shared evidence; OTEL-001 constraints promise artifact-derived version, while runtime.identity leaves default identity to future documentation. |
| with_skill | java/springboot-basic | with_skill | logging-trial-1 | rubric:rubric-10 FAIL | logging.shutdown; runtime.shutdown; DELIVERY evidence; sdk-auto-builder.java:644-656 stops at sdk.close(). |
| with_skill | java/springboot-basic | with_skill | logging-trial-1 | rubric:rubric-13 FAIL | runtime.identity says to document the actual detector; logging.identity inherits that profile; OTEL-001 promises artifact-derived service.version, while pom.xml supplies 0.0.1-SNAPSHOT. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
