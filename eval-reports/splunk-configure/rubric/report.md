# splunk-configure Rubric Codex Eval Report

## Environment

| Field | Value |
|---|---|
| Mode | with_skill |
| Eval kind | rubric |
| Skill | splunk-configure |
| Run ID | 20260722T175512164773Z |
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
| with_skill | dashboards/checkout-configure/qual/configure | dashboards/checkout-configure | 1 | 86% (6/7), avg score 86 | 3.1M | 12.3m | - | - | - |
| with_skill | dashboards/checkout-configure/qual/configure-audit-only-source | dashboards/checkout-configure | 1 | 100% (5/5), avg score 100 | 1.7M | 7.9m | - | - | - |
| with_skill | dashboards/checkout-configure/qual/configure-partial-overlay | dashboards/checkout-configure | 1 | 100% (4/4), avg score 100 | 691.0K | 4.6m | - | - | - |

## Rubric Failures

| Mode | Service | Side | Prompt | Result | Evidence |
|---|---|---|---|---|---|
| with_skill | dashboards/checkout-configure | with_skill | generate | rubric:rubric-1 FAIL | `service/.observe/otel.md` matches `service/otel-report.md`; `detectors.tf` has `latency_http_server_request_duration` using `http.server.request.duration`. `service/.observe/detectors.md` summary lists `Throughput \| 0` and `Saturation \| 0`. |

## Result JSON

File-level JSON results are stored under `results/<language>/<service>/<eval>/` in this run directory.
