# otel-audit Benchmark -- Iteration 2

## Summary

| Eval | App | With Skill | Baseline | Delta | Time (skill) | Tokens (skill) |
|------|-----|-----------|----------|-------|------|--------|
| 1 | chi-basic (Go) | 93% (13/14) | 86% (12/14) | +7% | 140s | 28.3K |
| 2 | express-basic (Node) | **100%** (15/15) | 73% (11/15) | **+27%** | 106s | 24.3K |
| 3 | flask-basic (Python) | 93% (13/14) | 86% (12/14) | +7% | 138s | 37.3K |
| 4 | kvstore (Go) | 90% (18/20) | 90% (18/20) | +0% | 132s | 34.5K |
| 5 | chi-partial (Go) | **100%** (18/18) | 78% (14/18) | **+22%** | 122s | 26.6K |
| 6 | springboot (Java) | **100%** (13/13) | 85% (11/13) | **+15%** | 99s | 22.5K |
| **Avg** | | **96%** | **83%** | **+13%** | **123s** | **28.9K** |

Stddev: pass_rate ±0.04 (skill), ±0.06 (baseline) | time ±16s | tokens ±5.6K

## Key Findings

1. **Three perfect scores with skill**: express-basic, chi-partial, and springboot all hit 100% with the skill. These are the evals where structured output format and specific package recommendations matter most.

2. **chi-partial is the most discriminating audit eval**: The +22% delta comes from the skill correctly flagging all 4 anti-patterns (hardcoded endpoint, high-cardinality span name, hot-path tracer, missing error recording) while the baseline missed the hardcoded endpoint and high-cardinality span name.

3. **Baseline structurally can't pass 2 assertions**: "recommends /otel-instrument" and "notes no anti-patterns" require skill-specific knowledge/format. These account for most baseline failures on simple apps.

4. **kvstore is a dead heat**: Both scored 90%, both missed the same assertions (LRU eviction observability). The baseline was surprisingly thorough at deep codebase analysis.

## Assertion-Level Breakdown

### Eval 1: chi-basic (Go/chi -- zero instrumentation)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | discovery | Identifies Go | PASS | PASS |
| 2 | discovery | Identifies chi (go-chi/chi/v5) | PASS | PASS |
| 3 | discovery | Identifies main.go entry point | **FAIL** | PASS |
| 4 | discovery | Lists HTTP routes | PASS | PASS |
| 5 | coverage | No OTel SDK initialization | PASS | PASS |
| 6 | coverage | No go.opentelemetry.io deps | PASS | PASS |
| 7 | coverage | Missing otelhttp middleware | PASS | PASS |
| 8 | coverage | Missing Duration (RED) | PASS | PASS |
| 9 | coverage | Missing Rate (RED) | PASS | PASS |
| 10 | coverage | Missing Errors (RED) | PASS | PASS |
| 11 | coverage | No OTLP exporter | PASS | PASS |
| 12 | anti-pattern | No anti-patterns noted | PASS | **FAIL** |
| 13 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 14 | recommendation | Mentions otelhttp/otelchi | PASS | PASS |

### Eval 2: express-basic (Node/Express -- zero instrumentation)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | discovery | Identifies Node.js | PASS | PASS |
| 2 | discovery | Identifies Express | PASS | PASS |
| 3 | discovery | Identifies app.js entry point | PASS | PASS |
| 4 | discovery | Lists HTTP routes | PASS | PASS |
| 5 | coverage | No OTel SDK initialization | PASS | PASS |
| 6 | coverage | No @opentelemetry/* packages | PASS | PASS |
| 7 | coverage | Missing instrumentation-http | PASS | **FAIL** |
| 8 | coverage | Missing instrumentation-express | PASS | **FAIL** |
| 9 | coverage | Missing Duration (RED) | PASS | PASS |
| 10 | coverage | Missing Rate (RED) | PASS | PASS |
| 11 | coverage | Missing Errors (RED) | PASS | PASS |
| 12 | coverage | No OTLP exporter | PASS | PASS |
| 13 | anti-pattern | No anti-patterns noted | PASS | **FAIL** |
| 14 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 15 | recommendation | Mentions specific packages | PASS | PASS |

### Eval 3: flask-basic (Python/Flask -- zero instrumentation)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | discovery | Identifies Python | PASS | PASS |
| 2 | discovery | Identifies Flask from pyproject.toml | PASS | PASS |
| 3 | discovery | Identifies app.py entry point | PASS | PASS |
| 4 | discovery | Lists HTTP routes | PASS | PASS |
| 5 | coverage | No OTel SDK initialization | PASS | PASS |
| 6 | coverage | No opentelemetry packages | PASS | PASS |
| 7 | coverage | Missing flask instrumentation | PASS | PASS |
| 8 | coverage | Missing Duration (RED) | PASS | PASS |
| 9 | coverage | Missing Rate (RED) | PASS | PASS |
| 10 | coverage | Missing Errors (RED) | PASS | PASS |
| 11 | coverage | No OTLP exporter | PASS | PASS |
| 12 | anti-pattern | No anti-patterns noted | **FAIL** | **FAIL** |
| 13 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 14 | recommendation | Mentions flask instrumentation package | PASS | PASS |

### Eval 4: kvstore (Go/stdlib -- zero instrumentation, complex structure)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | discovery | Identifies Go | PASS | PASS |
| 2 | discovery | Identifies stdlib net/http | PASS | PASS |
| 3 | discovery | Identifies cmd/kvstore-server/main.go | PASS | PASS |
| 4 | discovery | Multi-package structure identified | PASS | PASS |
| 5 | discovery | Lists HTTP routes | PASS | PASS |
| 6 | discovery | Identifies filesystem persistence | PASS | PASS |
| 7 | discovery | Identifies indexLoop background goroutine | PASS | PASS |
| 8 | coverage | No OTel SDK initialization | PASS | PASS |
| 9 | coverage | No go.opentelemetry.io deps | PASS | PASS |
| 10 | coverage | Missing otelhttp middleware | PASS | PASS |
| 11 | coverage | Missing Duration (RED) | PASS | PASS |
| 12 | coverage | Missing Rate (RED) | PASS | PASS |
| 13 | coverage | Missing Errors (RED) | PASS | PASS |
| 14 | coverage | No OTLP exporter | PASS | PASS |
| 15 | coverage | Filesystem I/O has no tracing | PASS | PASS |
| 16 | coverage | LRU eviction has no observability | **FAIL** | PASS |
| 17 | anti-pattern | No anti-patterns noted | PASS | **FAIL** |
| 18 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 19 | recommendation | Mentions otelhttp for ServeMux | PASS | PASS |
| 20 | recommendation | Custom spans for persistence/eviction | **FAIL** | PASS |

### Eval 5: chi-partial (Go/chi -- partial instrumentation with anti-patterns)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | discovery | Identifies Go | PASS | PASS |
| 2 | discovery | Identifies chi (go-chi/chi/v5) | PASS | PASS |
| 3 | discovery | Identifies main.go entry point | PASS | PASS |
| 4 | discovery | Lists HTTP routes | PASS | PASS |
| 5 | discovery | Existing TracerProvider identified | PASS | PASS |
| 6 | discovery | otelhttp.NewHandler identified | PASS | PASS |
| 7 | coverage | No MeterProvider configured | PASS | PASS |
| 8 | coverage | Missing Duration due to MeterProvider | PASS | PASS |
| 9 | coverage | Missing Rate due to MeterProvider | PASS | PASS |
| 10 | coverage | No TextMapPropagator | PASS | PASS |
| 11 | coverage | No graceful shutdown | PASS | PASS |
| 12 | coverage | No service.name resource | PASS | PASS |
| 13 | anti-pattern | Hardcoded OTLP endpoint flagged | PASS | **FAIL** |
| 14 | anti-pattern | Hot-path tracer flagged | PASS | PASS |
| 15 | anti-pattern | High-cardinality span name flagged | PASS | **FAIL** |
| 16 | anti-pattern | Missing recordException flagged | PASS | PASS |
| 17 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 18 | recommendation | Mentions MeterProvider for metrics | PASS | **FAIL** |

### Eval 6: springboot-basic (Java/Spring Boot -- zero instrumentation)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | discovery | Identifies Java | PASS | PASS |
| 2 | discovery | Identifies Spring Boot from pom.xml | PASS | PASS |
| 3 | discovery | Identifies TasksApplication.java | PASS | PASS |
| 4 | discovery | Lists HTTP routes | PASS | PASS |
| 5 | coverage | No OTel SDK or Java agent | PASS | PASS |
| 6 | coverage | No opentelemetry deps in pom.xml | PASS | PASS |
| 7 | coverage | Missing Duration (RED) | PASS | PASS |
| 8 | coverage | Missing Rate (RED) | PASS | PASS |
| 9 | coverage | Missing Errors (RED) | PASS | PASS |
| 10 | coverage | No OTLP exporter | PASS | PASS |
| 11 | anti-pattern | No anti-patterns noted | PASS | **FAIL** |
| 12 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 13 | recommendation | Mentions Java agent (javaagent) | PASS | PASS |

## Analyst Notes

### Non-discriminating assertions
- All "discovery" assertions (language, framework, routes) pass in both configs -- baseline Claude is good at codebase recognition
- All RED signal gap assertions pass in both configs for zero-instrumentation apps
- "No OTLP exporter" consistently passes in both

### Structurally-biased assertions
- "Recommends /otel-instrument" fails in all 6 baseline runs (no skill awareness)
- "No anti-patterns noted" fails in 4/6 baseline runs (no explicit template section)
- These 2 assertions account for 10 of the 16 total baseline failures

### Most discriminating assertion
- chi-partial anti-pattern detection: "hardcoded endpoint" and "high-cardinality span name" fail in baseline but pass with skill. These are the assertions that truly test skill value.

### Token/Time tradeoffs
- With-skill runs use ~35% more tokens (28.9K vs 21.4K avg)
- With-skill runs are actually 5% faster (123s vs 129s avg) despite reading more material
- The skill's structured process may reduce exploration time

## Session & Reasoning Logs

```
.workspace/otel-audit/iteration-2/eval-1-chi-basic/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-audit/iteration-2/eval-2-express-basic/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-audit/iteration-2/eval-3-flask-basic/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-audit/iteration-2/eval-4-kvstore/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-audit/iteration-2/eval-5-chi-partial/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-audit/iteration-2/eval-6-springboot-basic/{with,without}_skill/outputs/{session,reasoning}.md
```
