# GenAI Detector Classification

Read only when routed by `detector-classification.md`. Classify GenAI metrics
before generic latency/error/throughput/saturation and incident categories.

## Explicit context gate

GenAI context requires `meta.genai_ownership_detected`, a GenAI Readiness row,
or explicit metric/dimension evidence such as `gen_ai`, `llm`, inference,
embedding, model provider/deployment, agent, function/tool call, retrieval/RAG,
hallucination, toxicity, or factuality. Do not classify generic `model`,
`workflow`, `tool`, `config`, `canary`, `token`, `session`, `chat`, `memory`,
`context`, `evaluation`, `evaluator`, `quality`, `cost`, or `billing` by name
alone. Those generic words require audit evidence that the owning workflow is a
GenAI/LLM path.

## Categories

| Category | Evidence |
|---|---|
| `genai-latency` | `gen_ai.client.operation.duration` or explicit GenAI model/provider/workflow, first-token/chunk, stream, embedding, or end-to-end duration |
| `genai-token-pressure` | `gen_ai.client.token.usage` or explicit GenAI input/output/total/cached/prompt/completion/context token volume |
| `genai-provider` | provider/model timeout, rate-limit, throttle, retry, fallback, unavailable, 5xx, region/deployment failure |
| `genai-tool` | tool/function-call duration, count, error, timeout, success, or bounded failure class |
| `genai-model-config` | deployment/readiness, model resolution, requested-vs-response mismatch, config/feature/canary state |
| `genai-workflow-fanout` | LLM/tool/nested-agent call count, workflow fanout, outcome, or timeout |
| `genai-retrieval` | retrieval/RAG/vector/embedding/rerank latency, error, no-result, stale-result, freshness, or dependency health |
| `genai-memory-context` | memory/context/session-state/chat-history operations, hit/miss, stale/missing context, source/version, auth/permission outcome |
| `genai-evaluation-quality` | `gen_ai.evaluation.*`, score/result distribution, violations, evaluator error/timeout, sample/no-data/freshness |
| `genai-content-governance` | capture mode, redaction/truncation, unsafe capture, policy rejection, privacy/PII/access/retention evidence; never raw content |
| `genai-cost` | app-computed cost, budget/quota, billing-export freshness, or calculation failure backed by an accurate pricing map |

Provider billing data without app-owned accurate cost calculation is an
owner-mapped prerequisite, not an approximate detector. Content governance is
usually a prerequisite unless a bounded policy outcome metric exists.

## Defaults and missing surfaces

Use p99/static SLOs for duration, `against_recent` for bounded volume/quality/
fanout changes, critical severity for provider unavailability, unsafe capture,
or model-readiness failure, and major for degradation/pressure. Thresholds
remain service/SLO owned.

Consume every independently actionable GenAI Readiness surface row:
provider/model, workflow/agent, tool/function, token/context, stream/session,
retrieval, memory/context, evaluation/data export, content governance, cost
ownership, and privacy/cardinality. Do not merge distinct readiness surfaces.
Missing or partial GenAI areas become instrumentation prerequisites; never emit
placeholder Terraform.
