# otel-verify Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | otel-verify |
| Run ID | 20260722T175436568932Z |
| Agent model | gpt-5.5 |
| Judge model | gpt-5.5 |
| Rubric enabled | True |
| Workers | 1 |
| Config | evals/codex-evals.toml |
| Report scope | full |
| Selected prompts | 3 |
| Expected prompts | 3 |

## Rubric Summary

| Mode | Eval | Service | Prompts | With Skill | With Skill Tokens | With Skill Time | Baseline | Baseline Tokens | Baseline Time |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| with_skill | go/chi-basic/qual/verify | go/chi-basic | 1 | 100% (6/6), avg score 100 | 1.7M | 8.2m | - | - | - |
| with_skill | go/chi-partial/qual/benchmark-verify | go/chi-partial | 1 | 75% (3/4), avg score 86 | 2.3M | 13.2m | - | - | - |
| with_skill | java/springboot-basic/qual/verify | java/springboot-basic | 1 | 50% (3/6), avg score 55 | 1.4M | 7.1m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | go/chi-partial | with_skill | benchmark | rubric:rubric-4 FAIL | otel-verify.md mentions collector.example.com:4318, metrics/logs not configured, and Resource identity not proven. Searches for cardinal/high-cardinality and shutdown/provider Shutdown in the report found no corresponding diagnosis. |
| with_skill | java/springboot-basic | with_skill | local-java-agent-resolution | rubric:rubric-1 FAIL | trace item_46 ran .agents/skills/otel-verify/scripts/resolve_java_agent.py with all four --candidate JARs. service/.observe/java-agent-resolution.json selected splunk-otel-javaagent-8.0.0.jar instead of opentelemetry-javaagent-2.1.0+build.7.jar. |
| with_skill | java/springboot-basic | with_skill | local-java-agent-resolution | rubric:rubric-2 FAIL | selected.artifact_version is 8.0.0 and selected.sha256 is 8f604eb4b37f1912fcf623c6163a93b09fb69132ce126528a8302a413f8c751c. The expected fixture manifest has Implementation-Version 2.1.0+build.7 and SHA-256 7848a920c8104008d499c1bd3879fb5e07aeef7af30823042a710e07d0e6d00c. |
| with_skill | java/springboot-basic | with_skill | local-java-agent-resolution | rubric:rubric-3 FAIL | rejected contains opentelemetry-javaagent-9.0.0.jar with reason unrecognized-Premain-Class. selected.path is .../splunk-otel-javaagent-8.0.0.jar. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
