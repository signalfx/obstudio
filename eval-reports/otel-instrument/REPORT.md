# otel-instrument Benchmark -- Iteration 2

## Summary

| Eval | App | With Skill | Baseline | Delta | Time (skill) | Tokens (skill) |
|------|-----|-----------|----------|-------|------|--------|
| 1 | flask-basic (Python) | 90% (18/20) | 90% (18/20) | +0% | 182s | 35.6K |
| 2 | chi-basic (Go) | 90% (19/21) | 86% (18/21) | +4% | 218s | 48.9K |
| 3 | express-basic (Node) | 95% (21/22) | 95% (21/22) | +0% | 125s | 25.4K |
| 4 | kvstore (Go) | **96%** (25/26) | 73% (19/26) | **+23%** | 271s | 51.2K |
| 5 | chi-partial (Go) | 85% (11/13) | 54% (7/13) | **+31%** | 294s | 50.5K |
| 6 | springboot (Java) | **100%** (16/16) | 44% (7/16) | **+56%** | 153s | 28.5K |
| **Avg** | | **93%** | **74%** | **+19%** | **207s** | **40.0K** |

Stddev: pass_rate ±0.05 (skill), ±0.21 (baseline) | time ±67s | tokens ±11.6K

## Key Findings

1. **Skill excels on complex/non-standard apps**: The largest deltas are on springboot (+56%), chi-partial (+31%), and kvstore (+23%). These require domain-specific decisions (Java agent vs SDK, fixing anti-patterns, respecting multi-package layout) where the skill's reference docs provide critical guidance.

2. **Baseline already strong on simple greenfield apps**: Flask and Express show 0% delta -- baseline Claude knows standard Python/Node OTel patterns well enough to match the skill on straightforward scaffolding tasks.

3. **chi-partial is the most discriminating eval**: It tests whether the agent can detect and fix anti-patterns in *existing* code rather than just adding new instrumentation. The skill achieved 85% vs baseline's 54%.

4. **springboot shows the highest delta**: The baseline chose Spring Boot Starter (a legitimate approach) but the assertions expect the Java agent approach. The skill correctly followed the reference guide's recommendation for the Java agent.

## Assertion-Level Breakdown

### Eval 1: flask-basic (Python/Flask)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | opentelemetry-api in pyproject.toml | PASS | PASS |
| 2 | dependencies | opentelemetry-sdk in pyproject.toml | PASS | PASS |
| 3 | dependencies | opentelemetry-exporter-otlp added | PASS | PASS |
| 4 | dependencies | opentelemetry-instrumentation-flask added | PASS | PASS |
| 5 | sdk_init | Separate OTel init file created | PASS | PASS |
| 6 | sdk_init | TracerProvider with service.name Resource | PASS | PASS |
| 7 | sdk_init | OTLPSpanExporter configured | PASS | PASS |
| 8 | sdk_init | SDK initialized once per process | PASS | PASS |
| 9 | sdk_init | TextMapPropagator set | **FAIL** | **FAIL** |
| 10 | auto | FlaskInstrumentor().instrument_app(app) called | PASS | PASS |
| 11 | spans | HTTP spans for all routes | PASS | PASS |
| 12 | spans | Low-cardinality span names | PASS | PASS |
| 13 | spans | HTTP semconv attributes present | PASS | PASS |
| 14 | spans | ERROR on 5xx responses | PASS | PASS |
| 15 | metrics | http.server.request.duration histogram | PASS | PASS |
| 16 | config | OTEL_SERVICE_NAME env-driven | PASS | PASS |
| 17 | config | OTEL_EXPORTER_OTLP_ENDPOINT env-driven | PASS | PASS |
| 18 | config | No hardcoded endpoints/tokens | PASS | PASS |
| 19 | error | ERROR on unhandled exceptions | PASS | PASS |
| 20 | error | recordException on caught exceptions | **FAIL** | **FAIL** |

### Eval 2: chi-basic (Go/chi)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | go.opentelemetry.io/otel in go.mod | PASS | PASS |
| 2 | dependencies | otel/sdk in go.mod | PASS | PASS |
| 3 | dependencies | otlptrace exporter added | PASS | PASS |
| 4 | dependencies | otelhttp in go.mod | PASS | PASS |
| 5 | sdk_init | Separate otel.go file | PASS | **FAIL** |
| 6 | sdk_init | TracerProvider with service.name | PASS | PASS |
| 7 | sdk_init | OTLPTraceExporter configured | PASS | PASS |
| 8 | sdk_init | otel.SetTracerProvider() called | PASS | PASS |
| 9 | sdk_init | otel.SetTextMapPropagator() called | PASS | PASS |
| 10 | sdk_init | Graceful shutdown wired | PASS | PASS |
| 11 | auto | otelhttp.NewHandler wraps chi router | PASS | PASS |
| 12 | spans | HTTP spans for all routes | PASS | PASS |
| 13 | spans | Low-cardinality span names | PASS | PASS |
| 14 | spans | HTTP semconv attributes present | **FAIL** | PASS |
| 15 | spans | ERROR on 5xx | PASS | PASS |
| 16 | metrics | http.server.request.duration histogram | PASS | PASS |
| 17 | config | OTEL_SERVICE_NAME env-driven | PASS | PASS |
| 18 | config | OTLP endpoint env-driven | PASS | PASS |
| 19 | config | No hardcoded endpoints | PASS | PASS |
| 20 | error | ERROR on failures/panics | PASS | **FAIL** |
| 21 | error | span.RecordError called | **FAIL** | **FAIL** |

### Eval 3: express-basic (Node/Express)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | @opentelemetry/sdk-node added | PASS | PASS |
| 2 | dependencies | exporter-trace-otlp added | PASS | PASS |
| 3 | dependencies | instrumentation-http added | PASS | PASS |
| 4 | dependencies | instrumentation-express added | PASS | PASS |
| 5 | sdk_init | Separate instrumentation file | PASS | PASS |
| 6 | sdk_init | NodeSDK with service.name Resource | PASS | PASS |
| 7 | sdk_init | OTLPTraceExporter configured | PASS | PASS |
| 8 | sdk_init | Loaded via --require/--import | PASS | PASS |
| 9 | sdk_init | Graceful shutdown on SIGTERM | PASS | PASS |
| 10 | auto | HttpInstrumentation registered | PASS | PASS |
| 11 | auto | ExpressInstrumentation registered | PASS | PASS |
| 12 | spans | HTTP spans for all routes | PASS | PASS |
| 13 | spans | Low-cardinality span names | PASS | PASS |
| 14 | spans | HTTP semconv attributes present | PASS | PASS |
| 15 | spans | ERROR on 5xx | PASS | PASS |
| 16 | metrics | http.server.request.duration histogram | PASS | PASS |
| 17 | config | OTEL_SERVICE_NAME env-driven | PASS | PASS |
| 18 | config | OTLP endpoint env-driven | PASS | PASS |
| 19 | config | dev script loads instrumentation first | PASS | PASS |
| 20 | config | No hardcoded endpoints | PASS | PASS |
| 21 | error | ERROR on unhandled errors | PASS | PASS |
| 22 | error | span.recordException called | **FAIL** | **FAIL** |

### Eval 4: kvstore (Go/stdlib)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | go.opentelemetry.io/otel in go.mod | PASS | PASS |
| 2 | dependencies | otel/sdk in go.mod | PASS | PASS |
| 3 | dependencies | otlptrace exporter added | PASS | PASS |
| 4 | dependencies | otelhttp in go.mod | PASS | **FAIL** |
| 5 | sdk_init | Separate init file/function | PASS | PASS |
| 6 | sdk_init | TracerProvider with service.name | PASS | PASS |
| 7 | sdk_init | OTLPTraceExporter configured | PASS | PASS |
| 8 | sdk_init | otel.SetTracerProvider() called | PASS | PASS |
| 9 | sdk_init | otel.SetTextMapPropagator() called | PASS | PASS |
| 10 | sdk_init | Graceful shutdown wired | PASS | PASS |
| 11 | auto | otelhttp.NewHandler wraps ServeMux | PASS | **FAIL** |
| 12 | spans | HTTP spans for all routes | PASS | PASS |
| 13 | spans | Low-cardinality span names | PASS | PASS |
| 14 | spans | HTTP semconv attributes present | PASS | PASS |
| 15 | spans | ERROR on 5xx | PASS | PASS |
| 16 | metrics | http.server.request.duration histogram | PASS | **FAIL** |
| 17 | metrics | http.server.active_requests gauge | PASS | **FAIL** |
| 18 | config | OTEL_SERVICE_NAME with "kvstore" value | PASS | PASS |
| 19 | config | OTLP endpoint env-driven | PASS | PASS |
| 20 | config | No hardcoded endpoints | PASS | PASS |
| 21 | error | ERROR on store errors causing 5xx | PASS | PASS |
| 22 | error | span.RecordError on store errors | **FAIL** | PASS |
| 23 | error | 404s don't set ERROR | PASS | **FAIL** |
| 24 | structure | Multi-package layout preserved | PASS | PASS |
| 25 | structure | store.go/http.go minimally modified | PASS | **FAIL** |
| 26 | structure | SDK init in cmd/kvstore-server/ | PASS | **FAIL** |

### Eval 5: chi-partial (Go/chi -- partial instrumentation)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | sdk/metric added | PASS | **FAIL** |
| 2 | dependencies | otlpmetric exporter added | PASS | **FAIL** |
| 3 | sdk_init | MeterProvider configured | PASS | **FAIL** |
| 4 | sdk_init | TextMapPropagator set | PASS | PASS |
| 5 | sdk_init | Hardcoded endpoint replaced | PASS | **FAIL** |
| 6 | sdk_init | Resource includes service.name | PASS | PASS |
| 7 | sdk_init | Graceful shutdown wired | PASS | PASS |
| 8 | auto | otelhttp.NewHandler preserved | PASS | PASS |
| 9 | spans | High-cardinality span fixed | PASS | PASS |
| 10 | spans | Tracer moved from hot path | PASS | **FAIL** |
| 11 | metrics | http.server.request.duration produced | PASS | **FAIL** |
| 12 | error | Span status ERROR on failures | **FAIL** | PASS |
| 13 | error | span.RecordError called | **FAIL** | PASS |

### Eval 6: springboot-basic (Java/Spring Boot)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | javaagent.jar referenced | PASS | **FAIL** |
| 2 | dependencies | No SDK deps in pom.xml | PASS | **FAIL** |
| 3 | sdk_init | -javaagent JVM argument | PASS | **FAIL** |
| 4 | sdk_init | JAVA_TOOL_OPTIONS or startup script | PASS | **FAIL** |
| 5 | sdk_init | No programmatic SDK init | PASS | PASS |
| 6 | auto | Spring MVC auto-instrumented | PASS | **FAIL** |
| 7 | auto | Servlet container auto-instrumented | PASS | PASS |
| 8 | spans | HTTP spans for all routes | PASS | PASS |
| 9 | spans | Low-cardinality span names | PASS | PASS |
| 10 | spans | ERROR on 5xx | PASS | **FAIL** |
| 11 | metrics | http.server.request.duration histogram | PASS | **FAIL** |
| 12 | config | OTEL_SERVICE_NAME configurable | PASS | PASS |
| 13 | config | OTLP endpoint env-driven | PASS | PASS |
| 14 | config | No hardcoded endpoints | PASS | PASS |
| 15 | error | ERROR on unhandled exceptions | PASS | **FAIL** |
| 16 | error | recordException on unhandled exceptions | PASS | **FAIL** |

## Analyst Notes

### Non-discriminating assertions (pass in both configs)
- Most dependency assertions for Python/Node (baseline Claude knows these packages)
- OTLP endpoint env-driven (both configs use env vars or SDK defaults)
- Graceful shutdown (both configs implement it)

### Always-failing assertions
- `recordException on caught exceptions` fails in both configs for flask/express when Step 4 is skipped (no custom spans = nowhere to call recordException). Consider scoping this to "if custom spans exist."
- `TextMapPropagator explicitly set` fails in Python because the SDK default handles it. Consider accepting SDK defaults.

### High-variance patterns
- springboot eval has largest delta (56%) but this is driven by approach choice (agent vs starter), not quality
- chi-partial is the truest skill-vs-baseline test since it requires fixing broken existing code

### Token/Time tradeoffs
- With-skill runs use ~27% more tokens (40K vs 32K avg) and ~12% more time (207s vs 185s)
- The token overhead comes from reading SKILL.md + language reference files
- For complex evals (kvstore, chi-partial, springboot), the skill actually saves time relative to baseline on kvstore (271s vs 328s)

## Session & Reasoning Logs

```
.workspace/otel-instrument/iteration-2/eval-1-flask-basic/with_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-1-flask-basic/without_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-2-chi-basic/with_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-2-chi-basic/without_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-3-express-basic/with_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-3-express-basic/without_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-4-kvstore/with_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-4-kvstore/without_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-5-chi-partial/with_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-5-chi-partial/without_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-6-springboot-basic/with_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-2/eval-6-springboot-basic/without_skill/outputs/{session,reasoning}.md
```
