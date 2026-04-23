# otel-instrument Benchmark -- Iteration 4

## Summary

| Eval | App | With Skill | Baseline | Delta | Time (skill) | Time (base) | Tokens (skill) | Tokens (base) |
|------|-----|-----------|----------|-------|------|------|--------|--------|
| 1 | flask-basic (Python) | 90% (18/20) | 65% (13/20) | +25% | 169s | 93s | 35.3K | 20.6K |
| 2 | chi-basic (Go) | 81% (17/21) | 71% (15/21) | +10% | 310s | 212s | 48.9K | 44.1K |
| 3 | express-basic (Node) | 95% (21/22) | 77% (17/22) | +18% | 141s | 129s | 26.7K | 20.7K |
| 4 | kvstore (Go) | **96%** (25/26) | 81% (21/26) | +15% | 269s | 324s | 50.3K | 55.0K |
| 5 | chi-partial (Go) | 77% (10/13) | 69% (9/13) | +8% | 306s | 222s | 49.0K | 32.0K |
| 6 | springboot (Java) | **100%** (16/16) | 31% (5/16) | **+69%** | 172s | 137s | 29.9K | 23.0K |
| **Avg** | | **90%** | **66%** | **+24%** | **228s** | **186s** | **40.0K** | **32.6K** |

## Key Findings

1. **Springboot-basic remains the most discriminating eval (+69%)**: The baseline chose spring-boot-starter instead of javaagent, causing 11/16 assertion failures. The skill's reference docs guide it to the correct javaagent approach. This is a structural gap -- the baseline cannot pass javaagent-specific assertions without the skill's domain knowledge.

2. **chi-partial shows lowest delta (+8%)**: The baseline catches most anti-patterns in this iteration but still misses MeterProvider configuration and hardcoded endpoint replacement. The skill correctly adds metrics export and removes `collector.example.com`.

3. **recordException continues to fail in both configs**: Flask and express test apps have no try/catch blocks with caught exceptions, making this assertion structurally unsatisfiable. This is a known eval design gap, not a skill weakness.

4. **kvstore skill run is notably minimal**: The skill produced 0 changes to library code (`store.go` and `http.go` are byte-for-byte identical), placing all OTel code in `cmd/kvstore-server/otel.go`. The baseline made extensive modifications to `store.go` (+170 lines), adding context parameters and spans throughout the library package.

5. **Iteration-4 vs iteration-3 comparison**: Overall delta improved from +20% to +24%. Skill avg dipped slightly from 93% to 90% (chi-basic and chi-partial skill runs slightly weaker). Baseline dropped from 72% to 66%, driven by springboot baseline declining from 44% to 31% and flask baseline from 80% to 65%.

## Assertion-Level Breakdown

### Eval 1: flask-basic (Python/Flask)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | opentelemetry-api in pyproject.toml | PASS | PASS |
| 2 | dependencies | opentelemetry-sdk in pyproject.toml | PASS | PASS |
| 3 | dependencies | opentelemetry-exporter-otlp added | PASS | PASS |
| 4 | dependencies | opentelemetry-instrumentation-flask added | PASS | PASS |
| 5 | sdk_init | Separate OTel init file created | PASS | **FAIL** |
| 6 | sdk_init | TracerProvider with service.name Resource | PASS | PASS |
| 7 | sdk_init | OTLPSpanExporter configured | PASS | PASS |
| 8 | sdk_init | SDK initialized once per process | PASS | PASS |
| 9 | sdk_init | TextMapPropagator set | **FAIL** | **FAIL** |
| 10 | auto | FlaskInstrumentor().instrument_app(app) called | PASS | PASS |
| 11 | spans | HTTP spans for all routes | PASS | PASS |
| 12 | spans | Low-cardinality span names | PASS | PASS |
| 13 | spans | HTTP semconv attributes present | PASS | PASS |
| 14 | spans | ERROR on 5xx responses | PASS | **FAIL** |
| 15 | metrics | http.server.request.duration histogram | PASS | PASS |
| 16 | config | OTEL_SERVICE_NAME env-driven | PASS | **FAIL** |
| 17 | config | OTEL_EXPORTER_OTLP_ENDPOINT env-driven | PASS | PASS |
| 18 | config | No hardcoded endpoints/tokens | PASS | PASS |
| 19 | error | ERROR on unhandled exceptions | PASS | **FAIL** |
| 20 | error | recordException on caught exceptions | **FAIL** | **FAIL** |

### Eval 2: chi-basic (Go/Chi)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | go.opentelemetry.io/otel in go.mod | PASS | PASS |
| 2 | dependencies | otel/sdk in go.mod | PASS | PASS |
| 3 | dependencies | otlptrace exporter added | PASS | PASS |
| 4 | dependencies | otelhttp in go.mod | PASS | **FAIL** |
| 5 | sdk_init | Separate otel.go file | PASS | PASS |
| 6 | sdk_init | TracerProvider with service.name | PASS | PASS |
| 7 | sdk_init | OTLPTraceExporter configured | PASS | PASS |
| 8 | sdk_init | otel.SetTracerProvider() called | PASS | PASS |
| 9 | sdk_init | otel.SetTextMapPropagator() called | PASS | PASS |
| 10 | sdk_init | Graceful shutdown wired | PASS | PASS |
| 11 | auto | otelhttp.NewHandler wraps chi router | PASS | **FAIL** |
| 12 | spans | HTTP spans for all routes | PASS | PASS |
| 13 | spans | Low-cardinality span names | **FAIL** | PASS |
| 14 | spans | HTTP semconv attributes present | **FAIL** | PASS |
| 15 | spans | ERROR on 5xx | PASS | PASS |
| 16 | metrics | http.server.request.duration histogram | PASS | **FAIL** |
| 17 | config | OTEL_SERVICE_NAME env-driven | PASS | PASS |
| 18 | config | OTLP endpoint env-driven | PASS | PASS |
| 19 | config | No hardcoded endpoints | PASS | PASS |
| 20 | error | ERROR on failures/panics | **FAIL** | **FAIL** |
| 21 | error | span.RecordError called | **FAIL** | **FAIL** |

### Eval 3: express-basic (Node.js/Express)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | @opentelemetry/sdk-node added | PASS | PASS |
| 2 | dependencies | exporter-trace-otlp added | PASS | PASS |
| 3 | dependencies | instrumentation-http added | PASS | **FAIL** |
| 4 | dependencies | instrumentation-express added | PASS | **FAIL** |
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
| 15 | spans | ERROR on 5xx | PASS | **FAIL** |
| 16 | metrics | http.server.request.duration histogram | PASS | PASS |
| 17 | config | OTEL_SERVICE_NAME env-driven | PASS | PASS |
| 18 | config | OTLP endpoint env-driven | PASS | PASS |
| 19 | config | dev script loads instrumentation first | PASS | PASS |
| 20 | config | No hardcoded endpoints | PASS | PASS |
| 21 | error | ERROR on unhandled errors | PASS | **FAIL** |
| 22 | error | span.recordException called | **FAIL** | **FAIL** |

### Eval 4: kvstore (Go/net-http)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | go.opentelemetry.io/otel in go.mod | PASS | PASS |
| 2 | dependencies | otel/sdk in go.mod | PASS | PASS |
| 3 | dependencies | otlptrace exporter added | PASS | PASS |
| 4 | dependencies | otelhttp in go.mod | PASS | PASS |
| 5 | sdk_init | Separate init file/function | PASS | PASS |
| 6 | sdk_init | TracerProvider with service.name | PASS | PASS |
| 7 | sdk_init | OTLPTraceExporter configured | PASS | PASS |
| 8 | sdk_init | otel.SetTracerProvider() called | PASS | PASS |
| 9 | sdk_init | otel.SetTextMapPropagator() called | PASS | **FAIL** |
| 10 | sdk_init | Graceful shutdown wired | PASS | PASS |
| 11 | auto | otelhttp.NewHandler wraps ServeMux | PASS | PASS |
| 12 | spans | HTTP spans for all routes | PASS | PASS |
| 13 | spans | Low-cardinality span names | PASS | PASS |
| 14 | spans | HTTP semconv attributes present | PASS | **FAIL** |
| 15 | spans | ERROR on 5xx | PASS | PASS |
| 16 | metrics | http.server.request.duration histogram | PASS | PASS |
| 17 | metrics | http.server.active_requests gauge | PASS | PASS |
| 18 | config | OTEL_SERVICE_NAME with "kvstore" value | PASS | PASS |
| 19 | config | OTLP endpoint env-driven | PASS | PASS |
| 20 | config | No hardcoded endpoints | PASS | PASS |
| 21 | error | ERROR on store errors causing 5xx | PASS | PASS |
| 22 | error | span.RecordError on store errors | **FAIL** | PASS |
| 23 | error | 404s don't set ERROR | PASS | **FAIL** |
| 24 | structure | Multi-package layout preserved | PASS | PASS |
| 25 | structure | store.go/http.go minimally modified | PASS | **FAIL** |
| 26 | structure | SDK init in cmd/kvstore-server/ | PASS | **FAIL** |

### Eval 5: chi-partial (Go/Chi partial instrumentation)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | dependencies | sdk/metric added | PASS | **FAIL** |
| 2 | dependencies | otlpmetric exporter added | PASS | **FAIL** |
| 3 | sdk_init | MeterProvider configured | PASS | **FAIL** |
| 4 | sdk_init | TextMapPropagator set | PASS | PASS |
| 5 | config | Hardcoded endpoint replaced | PASS | **FAIL** |
| 6 | sdk_init | Resource includes service.name | PASS | PASS |
| 7 | sdk_init | Graceful shutdown wired | PASS | PASS |
| 8 | auto | otelhttp.NewHandler preserved | PASS | PASS |
| 9 | spans | High-cardinality span fixed | PASS | PASS |
| 10 | spans | Tracer moved from hot path | **FAIL** | PASS |
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
| 7 | auto | Servlet container auto-instrumented | PASS | **FAIL** |
| 8 | spans | HTTP spans for all routes | PASS | PASS |
| 9 | spans | Low-cardinality span names | PASS | **FAIL** |
| 10 | spans | ERROR on 5xx | PASS | **FAIL** |
| 11 | metrics | http.server.request.duration histogram | PASS | **FAIL** |
| 12 | config | OTEL_SERVICE_NAME configurable | PASS | PASS |
| 13 | config | OTLP endpoint env-driven | PASS | PASS |
| 14 | config | No hardcoded endpoints | PASS | PASS |
| 15 | error | ERROR on unhandled exceptions | PASS | **FAIL** |
| 16 | error | recordException on unhandled exceptions | PASS | **FAIL** |

## Analyst Notes

### Most discriminating assertions (fail baseline, pass skill)
- springboot: javaagent approach -- 11 assertions fail in baseline due to choosing spring-boot-starter SDK instead of javaagent. Baseline structurally cannot pass these assertions without the skill's reference guide directing it to the correct approach.
- kvstore structure: multi-package layout, minimal modifications, SDK init location -- skill preserves architecture with 0 library code changes while baseline rewrites store.go (+170 lines)
- chi-partial: MeterProvider, otlpmetric exporter, hardcoded endpoint replacement -- baseline misses all three, skill fixes all three

### Non-discriminating assertions (pass in both configs)
- Most dependency assertions for Python/Node (baseline Claude knows these packages)
- OTLP endpoint env-driven (both configs use env vars or SDK defaults)
- Graceful shutdown (both configs implement it)
- Low-cardinality span names on greenfield apps

### Always-failing assertions
- `recordException on caught exceptions` fails in both configs for flask/express (no caught exceptions in test apps)
- `ERROR on panics` and `RecordError on panics` fail in both configs for chi-basic (no panic recovery middleware)

### Iteration-over-iteration trends (iterations 3 -> 4)
- Skill avg: 93% -> 90% (slight decline; chi-basic dropped from 90% to 81% due to otelhttp span name issue, chi-partial dropped from 85% to 77% due to tracer removal vs move)
- Baseline avg: 72% -> 66% (decline; springboot baseline dropped from 44% to 31%, flask baseline dropped from 80% to 65%)
- Delta: +20% -> +24% (widened, driven more by baseline decline than skill improvement)

### Token/Time tradeoffs
- With-skill runs use ~23% more tokens (40.0K vs 32.6K avg) and ~23% more time (228s vs 186s)
- kvstore is the only eval where baseline uses MORE tokens and time than skill (55.0K/324s vs 50.3K/269s), due to baseline making extensive library modifications
- For complex evals (kvstore, springboot), the skill's token overhead pays for itself in much higher correctness

## Session & Reasoning Logs

```
.workspace/otel-instrument/iteration-4/eval-1-flask-basic/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-4/eval-2-chi-basic/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-4/eval-3-express-basic/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-4/eval-4-kvstore/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-4/eval-5-chi-partial/{with,without}_skill/outputs/{session,reasoning}.md
.workspace/otel-instrument/iteration-4/eval-6-springboot-basic/{with,without}_skill/outputs/{session,reasoning}.md
```
