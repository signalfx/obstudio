# otel-verify Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | otel-verify |
| Run ID | 20261020T034421183362Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-basic/qual/verify | go/chi-basic | 1 | evals/go/chi-basic/eval/qual/verify.json | 0 | 5 | 0 |
| go/native-genai-demo/qual/verify | go/native-genai-demo | 1 | evals/go/native-genai-demo/eval/qual/verify.json | 0 | 7 | 0 |
| python/ai-assistant-demo/qual/ao-target-handoff-verify | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/ao-target-handoff-verify.json | 0 | 4 | 0 |
| python/ai-assistant-demo/qual/gateway-env-verification | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/gateway-env-verification.json | 0 | 4 | 0 |
| python/ai-assistant-demo/qual/genai-sdk-required-verify | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/genai-sdk-required-verify.json | 0 | 14 | 0 |
| python/ai-assistant-demo/qual/per-function-decorator-verify | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/per-function-decorator-verify.json | 0 | 6 | 0 |
| python/ai-assistant-demo/qual/resource-selector-failures | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/resource-selector-failures.json | 0 | 4 | 0 |
| python/ai-assistant-demo/qual/resource-selector-length-verify | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/resource-selector-length-verify.json | 0 | 4 | 0 |
| python/ai-assistant-demo/qual/reuse-env-policy-verification | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/reuse-env-policy-verification.json | 0 | 4 | 0 |
| python/ai-assistant-demo/qual/tool-message-mapping-verify | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/tool-message-mapping-verify.json | 0 | 4 | 0 |
| python/ai-assistant-demo/qual/verify | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/verify.json | 0 | 6 | 0 |
| python/existing-otel-agent-demo/qual/route-recovery-verify | python/existing-otel-agent-demo | 1 | evals/python/existing-otel-agent-demo/eval/qual/route-recovery-verify.json | 0 | 5 | 0 |
| python/existing-otel-agent-demo/qual/verify | python/existing-otel-agent-demo | 1 | evals/python/existing-otel-agent-demo/eval/qual/verify.json | 0 | 7 | 0 |
| python/model-directed-agent/qual/connection-modes-verify | python/model-directed-agent | 1 | evals/python/model-directed-agent/eval/qual/connection-modes-verify.json | 0 | 5 | 0 |
| python/model-directed-agent/qual/resource-table-verify | python/model-directed-agent | 1 | evals/python/model-directed-agent/eval/qual/resource-table-verify.json | 0 | 6 | 0 |
| python/model-directed-agent/qual/verify | python/model-directed-agent | 1 | evals/python/model-directed-agent/eval/qual/verify.json | 0 | 4 | 0 |
