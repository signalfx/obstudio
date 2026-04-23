# otel-audit Benchmark -- Iteration 4

## Summary

| Eval | App | With Skill | Baseline | Delta | Time (skill) | Time (base) | Tokens (skill) | Tokens (base) |
|------|-----|-----------|----------|-------|------|------|--------|--------|
| 1 | chi-basic (Go) | 93% (13/14) | 86% (12/14) | +7% | 109s | 88s | 24.4K | 18.3K |
| 2 | express-basic (Node) | **100%** (15/15) | 60% (9/15) | **+40%** | 111s | 97s | 23.7K | 18.2K |
| 3 | flask-basic (Python) | **100%** (14/14) | 86% (12/14) | **+14%** | 122s | 99s | 26.9K | 19.6K |
| 4 | kvstore (Go) | 85% (17/20) | 70% (14/20) | **+15%** | 134s | 107s | 34.7K | 26.6K |
| 5 | chi-partial (Go) | **100%** (18/18) | 89% (16/18) | **+11%** | 112s | 101s | 27.5K | 23.2K |
| 6 | springboot (Java) | **100%** (13/13) | 54% (7/13) | **+46%** | 127s | 87s | 22.5K | 17.5K |
| **Avg** | | **96.3%** | **74.2%** | **+22.2%** | **119s** | **97s** | **26.6K** | **20.6K** |

## Key Findings

1. **Four perfect scores with skill**: express-basic, flask-basic, chi-partial, and springboot all hit 100%. The skill's structured output format, RED methodology framing, and specific package recommendations drive these results.

2. **Springboot-basic shows the largest delta (+46%)**: The baseline missed RED methodology framing entirely (Duration, Rate, Errors all failed), did not address anti-patterns, did not recommend /otel-instrument, and did not identify TasksApplication.java as the entry point. This is the most discriminating eval in the suite.

3. **Express-basic remains highly discriminating (+40%)**: The baseline missed specific package names (@opentelemetry/instrumentation-http and @opentelemetry/instrumentation-express), used the umbrella package instead, failed to address anti-patterns, missed request rate gap, and did not recommend /otel-instrument.

4. **chi-partial achieves perfect 100%**: All 18 assertions pass including all 4 anti-pattern detections (hardcoded OTLP endpoint, high-cardinality span name, hot-path tracer creation, missing error recording). Baseline improved to 89% (from 78% in iteration 3) but still missed /otel-instrument and recordException.

5. **chi-basic shows lowest delta (+7%)**: Baseline Go/chi audits are strong -- both configs pass all discovery and most coverage assertions. Only the anti-patterns framing and /otel-instrument recommendation separate them.

6. **Baseline structurally cannot pass 2 assertion types**: "/otel-instrument recommendation" fails in all 6 baseline runs (no skill awareness). "No anti-patterns noted" fails in 4/6 baseline runs (no template section).

## Assertion-Level Breakdown

### Eval 1: chi-basic (Go/chi -- zero instrumentation)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | discovery | Identifies Go | PASS | PASS |
| 2 | discovery | Identifies chi (go-chi/chi/v5) | PASS | PASS |
| 3 | discovery | Identifies main.go entry point | PASS | PASS |
| 4 | discovery | Lists HTTP routes | PASS | PASS |
| 5 | coverage | No OTel SDK initialization | PASS | PASS |
| 6 | coverage | No go.opentelemetry.io deps | PASS | PASS |
| 7 | coverage | Missing otelhttp middleware | PASS | PASS |
| 8 | coverage | Missing Duration (RED) | PASS | PASS |
| 9 | coverage | Missing Rate (RED) | PASS | PASS |
| 10 | coverage | Missing Errors (RED) | PASS | PASS |
| 11 | coverage | No OTLP exporter | PASS | PASS |
| 12 | anti-pattern | No anti-patterns noted | **FAIL** | **FAIL** |
| 13 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 14 | recommendation | Mentions otelhttp/otelchi | PASS | PASS |

**Skill failure**: Listed code-quality issues (ignored strconv.Atoi errors) under Anti-Patterns heading instead of noting no OTel anti-patterns exist.
**Baseline failures**: No /otel-instrument recommendation (no skill awareness); no anti-pattern section.

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
| 10 | coverage | Missing Rate (RED) | PASS | **FAIL** |
| 11 | coverage | Missing Errors (RED) | PASS | PASS |
| 12 | coverage | No OTLP exporter | PASS | PASS |
| 13 | anti-pattern | No anti-patterns noted | PASS | **FAIL** |
| 14 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 15 | recommendation | Mentions specific packages | PASS | **FAIL** |

**Baseline failures**: Recommended @opentelemetry/auto-instrumentations-node (umbrella) instead of naming individual packages; no explicit request rate gap; no anti-pattern section; no /otel-instrument; no specific package mentions.

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
| 12 | anti-pattern | No anti-patterns noted | PASS | **FAIL** |
| 13 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 14 | recommendation | Mentions flask instrumentation package | PASS | PASS |

**Baseline failures**: No anti-pattern section (never mentions anti-patterns); no /otel-instrument recommendation.

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
| 10 | coverage | Missing otelhttp middleware | PASS | **FAIL** |
| 11 | coverage | Missing Duration (RED) | PASS | PASS |
| 12 | coverage | Missing Rate (RED) | PASS | PASS |
| 13 | coverage | Missing Errors (RED) | PASS | PASS |
| 14 | coverage | No OTLP exporter | PASS | **FAIL** |
| 15 | coverage | Filesystem I/O has no tracing | PASS | PASS |
| 16 | coverage | LRU eviction has no observability | **FAIL** | PASS |
| 17 | anti-pattern | No anti-patterns noted | **FAIL** | **FAIL** |
| 18 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 19 | recommendation | Mentions otelhttp for ServeMux | PASS | **FAIL** |
| 20 | recommendation | Custom spans for persistence/eviction | **FAIL** | **FAIL** |

**Skill failures**: Did not explicitly call out LRU eviction as a separate observability gap (mentioned only as side effect of persistence failure); listed structural anti-patterns (missing context.Context, goroutines without context) instead of noting no OTel anti-patterns; did not frame custom spans for persistence/eviction as optional enhancements.
**Baseline failures**: Did not name otelhttp specifically; did not mention OTLP exporter; no anti-pattern section; no /otel-instrument; no otelhttp for ServeMux; no custom spans suggestion.

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
| 13 | anti-pattern | Hardcoded OTLP endpoint flagged | PASS | PASS |
| 14 | anti-pattern | Hot-path tracer flagged | PASS | PASS |
| 15 | anti-pattern | High-cardinality span name flagged | PASS | PASS |
| 16 | anti-pattern | Missing recordException flagged | PASS | **FAIL** |
| 17 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 18 | recommendation | Mentions MeterProvider for metrics | PASS | PASS |

**Baseline failures**: Did not mention recordException (only covered error status, not the span event); no /otel-instrument recommendation.

### Eval 6: springboot-basic (Java/Spring Boot -- zero instrumentation)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | discovery | Identifies Java | PASS | PASS |
| 2 | discovery | Identifies Spring Boot from pom.xml | PASS | PASS |
| 3 | discovery | Identifies TasksApplication.java | PASS | **FAIL** |
| 4 | discovery | Lists HTTP routes | PASS | PASS |
| 5 | coverage | No OTel SDK or Java agent | PASS | PASS |
| 6 | coverage | No opentelemetry deps in pom.xml | PASS | PASS |
| 7 | coverage | Missing Duration (RED) | PASS | **FAIL** |
| 8 | coverage | Missing Rate (RED) | PASS | **FAIL** |
| 9 | coverage | Missing Errors (RED) | PASS | **FAIL** |
| 10 | coverage | No OTLP exporter | PASS | PASS |
| 11 | anti-pattern | No anti-patterns noted | PASS | **FAIL** |
| 12 | recommendation | Recommends /otel-instrument | PASS | **FAIL** |
| 13 | recommendation | Mentions Java agent (javaagent) | PASS | PASS |

**Baseline failures**: Did not explicitly identify TasksApplication.java as "entry point"; missed all three RED methodology assertions (Duration, Rate, Errors) -- report described gaps in general terms without RED framing; no anti-pattern section; no /otel-instrument recommendation.

## Analyst Notes

### Most discriminating evals
- **Springboot-basic (+46%)**: Largest delta in the suite. Baseline completely missed RED methodology framing and scored only 54%. The Java ecosystem has fewer recognizable OTel package names (Java agent vs explicit npm/pip packages), so the baseline has less to latch onto.
- **Express-basic (+40%)**: Baseline recommends the umbrella auto-instrumentations-node package instead of naming instrumentation-http and instrumentation-express individually. Also misses Rate gap and anti-pattern section.

### Lowest delta eval
- **chi-basic (+7%)**: Baseline Go/chi audits are strong. Simple Go services with chi are well-understood by the base model. Only anti-patterns framing and /otel-instrument recommendation differentiate the two configs.

### Structurally-biased assertions
- "Recommends /otel-instrument" fails in all 6 baseline runs (no skill awareness) -- accounts for 6 baseline failures
- "No anti-patterns noted" fails in 4/6 baseline runs (no explicit template section) -- accounts for 4 baseline failures
- These 2 assertion types account for 10 of the 24 total baseline failures

### Non-discriminating assertions
- All "discovery" assertions (language, framework, routes) pass in both configs except springboot entry point
- All RED signal gap assertions pass in both configs for simple zero-instrumentation Go/Python apps
- "No OTLP exporter" passes in both configs for 5 of 6 evals

### Iteration-over-iteration trends (iterations 3 -> 4)
- Skill avg: 97% -> 96.3% (slight softening; kvstore dropped from 90% to 85%)
- Baseline avg: 77% -> 74.2% (continued decline; springboot baseline dropped from 77% to 54%)
- Delta: +20% -> +22.2% (widened, driven by springboot baseline decline)
- chi-partial baseline improved: 78% -> 89% (better anti-pattern detection without skill)
- 4 of 6 skill runs at 100% (same as iteration 3)

### Token/Time tradeoffs
- With-skill runs use ~29% more tokens (26.6K vs 20.6K avg)
- With-skill runs take ~23% more time (119s vs 97s avg)
- Both configs are faster than iteration 3 (skill: 119s vs 136s, baseline: 97s vs 107s)

## Session & Reasoning Logs

```
.workspace/otel-audit/iteration-4/eval-1-chi-basic/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-audit/iteration-4/eval-2-express-basic/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-audit/iteration-4/eval-3-flask-basic/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-audit/iteration-4/eval-4-kvstore/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-audit/iteration-4/eval-5-chi-partial/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-audit/iteration-4/eval-6-springboot-basic/{with,without}_skill/outputs/{session,reasoning}.md
```
