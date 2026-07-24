# Incident and GenAI Detector Defaults

Read only after an incident or GenAI classification route is active. Use the
same provider/resource/HCL safety contract as `terraform-templates.md`.

## Incident defaults

| Category | Detection | Initial severity |
|---|---|---|
| freshness | source-backed age/lag static threshold | Critical |
| backpressure | capacity/SLO threshold, normalized percentage, or proven baseline; sudden change for rebalance count | Major |
| dependency | p99 duration threshold or error/timeout/retry increase | Major |
| customer-impact | workflow latency or bounded error/degraded/timeout increase | Critical |
| impact-classification | unavailable static condition or degraded baseline grouped by workflow/region | Critical |
| auth-edge | login/edge latency, error/timeout/expiry baseline, or certificate/TLS expiry threshold | Critical |
| capacity-saturation | normalized utilization/quota threshold or throttle/restart increase | Major |

There is no universal queue-depth, lag, or active-work count threshold. Use 85%
only for normalized saturation. Only source-backed CPU utilization supports a
CPU saturation detector; cumulative CPU time supports only a diagnostic
`rollup='rate'` view and does not prove normalized CPU utilization.

## GenAI defaults

| Category | Detection | Initial severity |
|---|---|---|
| genai-latency | p99 workflow/provider/first-chunk duration or baseline | Major |
| genai-token-pressure | p95/p99 bounded token volume or service token limit | Major |
| genai-provider | timeout/rate-limit/unavailable/retry/fallback/deployment failure | Critical |
| genai-tool | tool error/timeout, p99 duration, or fanout increase | Major |
| genai-model-config | readiness/resolution/model mismatch/config-canary failure | Critical |
| genai-workflow-fanout | LLM/tool/nested-agent fanout increase or workflow timeout | Major |
| genai-retrieval | retrieval latency/error/no-result/stale-result/freshness | Major |
| genai-memory-context | memory/context latency, stale/missing/auth outcome | Major |
| genai-evaluation-quality | score drop, violation, evaluator failure, or no-data | Major |
| genai-content-governance | bounded unsafe-capture/redaction/policy failure | Critical |
| genai-cost | accurate app-computed cost spike or budget threshold | Major |

Use `against_recent.detector_mean_std` only for a suitable bounded stream; use
static thresholds for hard failure, expiry, quota, and SLO conditions. Never
alert on raw content or approximate provider cost.

For either family, missing or unverified signals remain prerequisites. Do not
generate placeholder detectors merely to fill a coverage matrix.
