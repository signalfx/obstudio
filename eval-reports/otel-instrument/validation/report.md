# otel-instrument Codex Eval Validation Report

This report validates eval JSON, eval directory availability, and skill source availability. It does not run Codex execution.

## Environment

| Field | Value |
|---|---|
| Mode | validation |
| Eval kind | validation |
| Skill | otel-instrument |
| Run ID | 20260702T062929008621Z |
| Workers | 1 |
| Config | evals/codex-evals.validation.toml |

## Eval Summary

| Eval | Service | Prompts | Eval File | Sanity Checks | Rubric Checks | Runtime Checks |
|---|---|---:|---|---:|---:|---:|
| go/chi-basic/qual/instrument | go/chi-basic | 2 | evals/go/chi-basic/eval/qual/instrument.json | 0 | 6 | 0 |
| go/chi-basic/runtime/instrument | go/chi-basic | 1 | evals/go/chi-basic/eval/runtime/instrument.json | 0 | 0 | 1 |
| go/chi-partial/qual/instrument | go/chi-partial | 2 | evals/go/chi-partial/eval/qual/instrument.json | 0 | 5 | 0 |
| go/chi-partial/runtime/instrument | go/chi-partial | 1 | evals/go/chi-partial/eval/runtime/instrument.json | 0 | 0 | 1 |
| go/kvstore/qual/incident-readiness | go/kvstore | 1 | evals/go/kvstore/eval/qual/incident-readiness.json | 0 | 6 | 0 |
| go/kvstore/qual/instrument | go/kvstore | 2 | evals/go/kvstore/eval/qual/instrument.json | 0 | 5 | 0 |
| go/kvstore/runtime/instrument | go/kvstore | 1 | evals/go/kvstore/eval/runtime/instrument.json | 0 | 0 | 1 |
| java/kafka-batch-consumer/qual/instrument | java/kafka-batch-consumer | 2 | evals/java/kafka-batch-consumer/eval/qual/instrument.json | 0 | 5 | 0 |
| java/kafka-listener-container/qual/instrument | java/kafka-listener-container | 2 | evals/java/kafka-listener-container/eval/qual/instrument.json | 0 | 5 | 0 |
| java/kafka-producer-consumer/qual/instrument | java/kafka-producer-consumer | 2 | evals/java/kafka-producer-consumer/eval/qual/instrument.json | 0 | 5 | 0 |
| java/kafka-streams/qual/incident-readiness | java/kafka-streams | 1 | evals/java/kafka-streams/eval/qual/incident-readiness.json | 0 | 6 | 0 |
| java/kafka-streams/qual/instrument | java/kafka-streams | 2 | evals/java/kafka-streams/eval/qual/instrument.json | 0 | 6 | 0 |
| java/springboot-basic/qual/instrument | java/springboot-basic | 2 | evals/java/springboot-basic/eval/qual/instrument.json | 0 | 5 | 0 |
| node/express-basic/qual/instrument | node/express-basic | 2 | evals/node/express-basic/eval/qual/instrument.json | 0 | 5 | 0 |
| node/express-basic/runtime/instrument | node/express-basic | 1 | evals/node/express-basic/eval/runtime/instrument.json | 0 | 0 | 1 |
| python/ai-assistant-demo/qual/instrument | python/ai-assistant-demo | 1 | evals/python/ai-assistant-demo/eval/qual/instrument.json | 0 | 7 | 0 |
| python/assistant-v3-framework-bridge-demo/qual/instrument | python/assistant-v3-framework-bridge-demo | 1 | evals/python/assistant-v3-framework-bridge-demo/eval/qual/instrument.json | 0 | 7 | 0 |
| python/fastapi-celery/qual/incident-readiness | python/fastapi-celery | 1 | evals/python/fastapi-celery/eval/qual/incident-readiness.json | 0 | 7 | 0 |
| python/fastapi-celery/qual/instrument | python/fastapi-celery | 2 | evals/python/fastapi-celery/eval/qual/instrument.json | 0 | 5 | 0 |
| python/fastapi-celery/runtime/instrument | python/fastapi-celery | 1 | evals/python/fastapi-celery/eval/runtime/instrument.json | 0 | 0 | 1 |
| python/flask-basic/qual/instrument | python/flask-basic | 2 | evals/python/flask-basic/eval/qual/instrument.json | 0 | 5 | 0 |
| python/flask-basic/runtime/instrument | python/flask-basic | 1 | evals/python/flask-basic/eval/runtime/instrument.json | 0 | 0 | 1 |
| python/mcp-ai-tool-demo/qual/instrument | python/mcp-ai-tool-demo | 1 | evals/python/mcp-ai-tool-demo/eval/qual/instrument.json | 0 | 7 | 0 |
| sanity/skill-smoke/sanity/instrument | sanity/skill-smoke | 2 | evals/sanity/skill-smoke/eval/sanity/instrument.json | 0 | 0 | 0 |
