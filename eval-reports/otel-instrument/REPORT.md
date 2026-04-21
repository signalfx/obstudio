# otel-instrument Benchmark -- Iteration 1

## Summary Table

| Eval | App | With Skill | Baseline | Delta | Time (ws) | Tokens (ws) |
|------|-----|-----------|----------|-------|-----------|-------------|
| 1 | flask-basic | 95% (19/20) | 65% (13/20) | **+30%** | 167s | 33.4K |
| 2 | chi-basic | 81% (17/21) | 90% (19/21) | **-9%** | 141s | 34.5K |
| 3 | express-basic | 91% (20/22) | 86% (19/22) | **+5%** | 111s | 24.1K |
| 4 | kvstore | 96% (24/25) | 76% (19/25) | **+20%** | 228s | 46.8K |
| **Avg** | | **91%** | **79%** | **+12%** | **162s** | **34.7K** |

Stddev: pass_rate +/-0.07 (ws), +/-0.11 (bl) | time +/-49s | tokens +/-9.4K

## Key Findings

### Where the skill excels
- **Flask (+30%)**: Skill creates separate init file, uses env vars for config, configures metrics properly
- **kvstore (+20%)**: Skill preserves multi-package layout, places SDK init in correct cmd/ directory, minimal modifications to library code
- **Express (+5%)**: Skill uses individual instrumentation packages per reference guidance, properly structured

### Where the skill underperforms
- **chi-basic (-9%)**: Skill chose `otelchi` over `otelhttp` per Go reference guidance. While `otelchi` gives better route-aware span names, it doesn't produce HTTP server metrics (duration histogram, active_requests gauge). The eval assertions have an internal contradiction: assertion 11 allows otelchi, but assertions 4/16/17 require otelhttp-specific behavior.

### Cross-cutting patterns
- **RecordError/recordException**: Fails in ALL runs (both with_skill and without_skill). Neither the skill nor baseline consistently adds explicit error recording on exception paths. This is a universal gap.
- **http.server.active_requests**: Fails for with_skill in Express (experimental feature) and chi (otelchi limitation). Only otelhttp in Go produces this metric.
- **TextMapPropagator**: Failed for with_skill in Flask (relies on distro auto-config) but would have passed with explicit setup.

## Assertion-Level Breakdown

### Eval 1: flask-basic (Python/Flask)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | deps | opentelemetry-api in pyproject.toml | PASS | PASS |
| 2 | deps | opentelemetry-sdk in pyproject.toml | PASS | PASS |
| 3 | deps | opentelemetry-exporter-otlp added | PASS | PASS |
| 4 | deps | opentelemetry-instrumentation-flask added | PASS | PASS |
| 5 | sdk_init | Separate OTel init file | PASS | **FAIL** |
| 6 | sdk_init | TracerProvider with Resource/service.name | PASS | PASS |
| 7 | sdk_init | OTLPSpanExporter configured | PASS | PASS |
| 8 | sdk_init | SDK initialized once | PASS | PASS |
| 9 | sdk_init | TextMapPropagator set | **FAIL** | **FAIL** |
| 10 | auto | FlaskInstrumentor wired | PASS | PASS |
| 11 | spans | HTTP spans for all routes | PASS | PASS |
| 12 | spans | Low-cardinality span names | PASS | PASS |
| 13 | spans | HTTP semconv attributes | PASS | PASS |
| 14 | spans | ERROR on 5xx | PASS | PASS |
| 15 | metrics | http.server.request.duration | PASS | **FAIL** |
| 16 | metrics | http.server.active_requests | PASS | **FAIL** |
| 17 | config | OTEL_SERVICE_NAME env var | PASS | **FAIL** |
| 18 | config | OTEL_EXPORTER_OTLP_ENDPOINT | PASS | PASS |
| 19 | config | No hardcoded endpoints | PASS | PASS |
| 20 | errors | recordException on exceptions | PASS | **FAIL** |

### Eval 2: chi-basic (Go/chi)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | deps | go.opentelemetry.io/otel | PASS | PASS |
| 2 | deps | otel/sdk | PASS | PASS |
| 3 | deps | otlptrace exporter | PASS | PASS |
| 4 | deps | otelhttp in go.mod | **FAIL** | PASS |
| 5 | sdk_init | Separate OTel init file | PASS | **FAIL** |
| 6 | sdk_init | TracerProvider with service.name | PASS | PASS |
| 7 | sdk_init | OTLPTraceExporter | PASS | PASS |
| 8 | sdk_init | SetTracerProvider() | PASS | PASS |
| 9 | sdk_init | SetTextMapPropagator() | PASS | PASS |
| 10 | sdk_init | Graceful shutdown | PASS | PASS |
| 11 | auto | otelhttp or otelchi middleware | PASS | PASS |
| 12 | spans | HTTP spans for all routes | PASS | PASS |
| 13 | spans | Low-cardinality span names | PASS | PASS |
| 14 | spans | HTTP semconv attributes | PASS | PASS |
| 15 | spans | ERROR on 5xx | PASS | PASS |
| 16 | metrics | http.server.request.duration | **FAIL** | PASS |
| 17 | metrics | http.server.active_requests | **FAIL** | PASS |
| 18 | config | OTEL_SERVICE_NAME | PASS | PASS |
| 19 | config | OTEL_EXPORTER_OTLP_ENDPOINT | PASS | PASS |
| 20 | config | No hardcoded endpoints | PASS | PASS |
| 21 | errors | RecordError on panics/errors | **FAIL** | **FAIL** |

### Eval 3: express-basic (Node.js/Express)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | deps | @opentelemetry/sdk-node | PASS | PASS |
| 2 | deps | exporter-trace-otlp-http | PASS | PASS |
| 3 | deps | instrumentation-http | PASS | **FAIL** |
| 4 | deps | instrumentation-express | PASS | **FAIL** |
| 5 | sdk_init | Separate instrumentation file | PASS | PASS |
| 6 | sdk_init | NodeSDK with service.name | PASS | PASS |
| 7 | sdk_init | OTLPTraceExporter | PASS | PASS |
| 8 | sdk_init | --import preload | PASS | PASS |
| 9 | sdk_init | Graceful shutdown SIGTERM | PASS | PASS |
| 10 | auto | HttpInstrumentation | PASS | PASS |
| 11 | auto | ExpressInstrumentation | PASS | PASS |
| 12 | spans | HTTP spans for all routes | PASS | PASS |
| 13 | spans | Low-cardinality span names | PASS | PASS |
| 14 | spans | HTTP semconv attributes | PASS | PASS |
| 15 | spans | ERROR on 5xx | PASS | PASS |
| 16 | metrics | http.server.request.duration | PASS | PASS |
| 17 | metrics | http.server.active_requests | **FAIL** | PASS |
| 18 | config | OTEL_SERVICE_NAME | PASS | PASS |
| 19 | config | OTEL_EXPORTER_OTLP_ENDPOINT | PASS | PASS |
| 20 | config | dev script --import | PASS | PASS |
| 21 | config | No hardcoded endpoints | PASS | PASS |
| 22 | errors | recordException on errors | **FAIL** | **FAIL** |

### Eval 4: kvstore (Go/stdlib)

| # | Category | Assertion | With Skill | Baseline |
|---|----------|-----------|-----------|----------|
| 1 | deps | go.opentelemetry.io/otel | PASS | PASS |
| 2 | deps | otel/sdk | PASS | PASS |
| 3 | deps | otlptrace exporter | PASS | PASS |
| 4 | deps | otelhttp in go.mod | PASS | PASS |
| 5 | sdk_init | Separate init file/function | PASS | PASS |
| 6 | sdk_init | TracerProvider with service.name | PASS | PASS |
| 7 | sdk_init | OTLPTraceExporter | PASS | PASS |
| 8 | sdk_init | SetTracerProvider() | PASS | PASS |
| 9 | sdk_init | SetTextMapPropagator() | PASS | PASS |
| 10 | sdk_init | Graceful shutdown | PASS | PASS |
| 11 | auto | otelhttp.NewHandler wraps ServeMux | PASS | PASS |
| 12 | spans | HTTP spans for all routes | PASS | PASS |
| 13 | spans | Low-cardinality span names | PASS | PASS |
| 14 | spans | HTTP semconv attributes | PASS | **FAIL** |
| 15 | spans | ERROR on 5xx | PASS | **FAIL** |
| 16 | metrics | http.server.request.duration | PASS | PASS |
| 17 | metrics | http.server.active_requests | PASS | PASS |
| 18 | config | OTEL_SERVICE_NAME | PASS | PASS |
| 19 | config | OTEL_EXPORTER_OTLP_ENDPOINT | PASS | PASS |
| 20 | config | No hardcoded endpoints | PASS | PASS |
| 21 | errors | RecordError on store 5xx errors | **FAIL** | **FAIL** |
| 22 | structure | 404 does not set ERROR | PASS | **FAIL** |
| 23 | structure | Multi-package layout preserved | PASS | PASS |
| 24 | structure | store.go/http.go minimally modified | PASS | **FAIL** |
| 25 | structure | SDK init in cmd/kvstore-server/ | PASS | **FAIL** |

## Session & reasoning logs

- `.workspace/otel-instrument/iteration-1/eval-1-flask-basic/with_skill/outputs/session.md`
- `.workspace/otel-instrument/iteration-1/eval-1-flask-basic/with_skill/outputs/reasoning.md`
- `.workspace/otel-instrument/iteration-1/eval-1-flask-basic/without_skill/outputs/session.md`
- `.workspace/otel-instrument/iteration-1/eval-1-flask-basic/without_skill/outputs/reasoning.md`
- `.workspace/otel-instrument/iteration-1/eval-2-chi-basic/with_skill/outputs/session.md`
- `.workspace/otel-instrument/iteration-1/eval-2-chi-basic/with_skill/outputs/reasoning.md`
- `.workspace/otel-instrument/iteration-1/eval-2-chi-basic/without_skill/outputs/session.md`
- `.workspace/otel-instrument/iteration-1/eval-2-chi-basic/without_skill/outputs/reasoning.md`
- `.workspace/otel-instrument/iteration-1/eval-3-express-basic/with_skill/outputs/session.md`
- `.workspace/otel-instrument/iteration-1/eval-3-express-basic/with_skill/outputs/reasoning.md`
- `.workspace/otel-instrument/iteration-1/eval-3-express-basic/without_skill/outputs/session.md`
- `.workspace/otel-instrument/iteration-1/eval-3-express-basic/without_skill/outputs/reasoning.md`
- `.workspace/otel-instrument/iteration-1/eval-4-kvstore/with_skill/outputs/session.md`
- `.workspace/otel-instrument/iteration-1/eval-4-kvstore/with_skill/outputs/reasoning.md`
- `.workspace/otel-instrument/iteration-1/eval-4-kvstore/without_skill/outputs/session.md`
- `.workspace/otel-instrument/iteration-1/eval-4-kvstore/without_skill/outputs/reasoning.md`
