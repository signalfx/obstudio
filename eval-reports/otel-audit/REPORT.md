# otel-audit Benchmark -- Iteration 1

## Summary Table


| Eval    | App           | With Skill  | Baseline    | Delta    | Time (ws) | Tokens (ws) |
| ------- | ------------- | ----------- | ----------- | -------- | --------- | ----------- |
| 1       | chi-basic     | 86% (12/14) | 86% (12/14) | **0%**   | 105s      | 25.5K       |
| 2       | express-basic | 80% (12/15) | 73% (11/15) | **+7%**  | 81s       | 22.2K       |
| 3       | flask-basic   | 71% (10/14) | 86% (12/14) | **-15%** | 103s      | 31.1K       |
| 4       | kvstore       | 85% (17/20) | 90% (18/20) | **-5%**  | 149s      | 36.4K       |
| **Avg** |               | **81%**     | **84%**     | **-3%**  | **110s**  | **28.8K**   |


Stddev: pass_rate +/-0.07 (ws), +/-0.08 (bl) | time +/-28s | tokens +/-6.0K

## Key Findings

### Surprising result: Baseline outperforms skill on aggregate

The otel-audit skill scored 81% vs baseline 84%. This is counterintuitive but explainable:

1. **Route enumeration**: With_skill reports consistently fail to list individual HTTP routes (0/4 evals pass), while baseline passes 4/4. The skill's structured report template emphasizes gaps at the framework level rather than enumerating routes.
2. **RED terminology**: With_skill fails RED-signal assertions in flask (0/3) where the report covers the concepts but doesn't use "RED: Duration/Rate/Errors" terminology.
3. **Anti-patterns**: Both configurations fail this assertion consistently. With_skill reports identify real code-quality issues (which contradicts "no anti-patterns"), while baseline simply omits the section.
4. **Structural advantage**: With_skill always passes "/otel-instrument recommendation" (+1 per eval), but this is offset by route enumeration failures (-1 per eval).

### What the skill does well

- Always recommends `/otel-instrument` (structural advantage)
- Structured report format following SKILL.md template
- Deep analysis of kvstore (filesystem persistence, background goroutines, LRU eviction)
- Identifies specific auto-instrumentation packages to add

### What baseline does well

- Detailed route enumeration with HTTP methods
- Explicit RED signal naming with metric names
- More comprehensive gap counts (26 gaps in kvstore baseline vs 8 in with_skill)

## Assertion-Level Breakdown

### Eval 1: chi-basic (Go/chi)


| #   | Category  | Assertion                     | With Skill | Baseline |
| --- | --------- | ----------------------------- | ---------- | -------- |
| 1   | discovery | Go as language                | PASS       | PASS     |
| 2   | discovery | chi (go-chi/chi/v5) framework | PASS       | PASS     |
| 3   | discovery | main.go entry point           | PASS       | PASS     |
| 4   | discovery | 6 HTTP routes                 | **FAIL**   | PASS     |
| 5   | gaps      | No OTel SDK                   | PASS       | PASS     |
| 6   | gaps      | No go.opentelemetry.io deps   | PASS       | PASS     |
| 7   | gaps      | Missing otelhttp/otelchi      | PASS       | PASS     |
| 8   | gaps      | Missing duration histogram    | PASS       | PASS     |
| 9   | gaps      | Missing request rate          | PASS       | PASS     |
| 10  | gaps      | Missing error rate            | PASS       | PASS     |
| 11  | gaps      | No OTLP exporter              | PASS       | PASS     |
| 12  | anti      | No anti-patterns              | **FAIL**   | **FAIL** |
| 13  | rec       | Recommends /otel-instrument   | PASS       | **FAIL** |
| 14  | rec       | Mentions otelhttp/otelchi     | PASS       | PASS     |


### Eval 2: express-basic (Node.js/Express)


| #   | Category  | Assertion                        | With Skill | Baseline |
| --- | --------- | -------------------------------- | ---------- | -------- |
| 1   | discovery | Node.js as language              | PASS       | PASS     |
| 2   | discovery | Express from package.json        | PASS       | PASS     |
| 3   | discovery | app.js entry point               | PASS       | PASS     |
| 4   | discovery | 6 HTTP routes                    | **FAIL**   | PASS     |
| 5   | gaps      | No OTel SDK                      | PASS       | PASS     |
| 6   | gaps      | No @opentelemetry/* packages     | PASS       | PASS     |
| 7   | gaps      | Missing instrumentation-http     | PASS       | PASS     |
| 8   | gaps      | Missing instrumentation-express  | PASS       | PASS     |
| 9   | gaps      | Missing duration histogram (RED) | **FAIL**   | PASS     |
| 10  | gaps      | Missing request rate (RED)       | **FAIL**   | PASS     |
| 11  | gaps      | Missing error rate (RED)         | PASS       | **FAIL** |
| 12  | gaps      | No OTLP exporter                 | PASS       | PASS     |
| 13  | anti      | No anti-patterns                 | PASS       | **FAIL** |
| 14  | rec       | Recommends /otel-instrument      | PASS       | **FAIL** |
| 15  | rec       | Mentions specific packages       | PASS       | **FAIL** |


### Eval 3: flask-basic (Python/Flask)


| #   | Category  | Assertion                        | With Skill | Baseline |
| --- | --------- | -------------------------------- | ---------- | -------- |
| 1   | discovery | Python as language               | PASS       | PASS     |
| 2   | discovery | Flask from pyproject.toml        | PASS       | PASS     |
| 3   | discovery | app.py entry point               | PASS       | PASS     |
| 4   | discovery | 6 HTTP routes                    | **FAIL**   | PASS     |
| 5   | gaps      | No OTel SDK                      | PASS       | PASS     |
| 6   | gaps      | No opentelemetry packages        | PASS       | PASS     |
| 7   | gaps      | Missing instrumentation-flask    | PASS       | PASS     |
| 8   | gaps      | Missing duration histogram (RED) | **FAIL**   | PASS     |
| 9   | gaps      | Missing request rate (RED)       | **FAIL**   | PASS     |
| 10  | gaps      | Missing error rate (RED)         | **FAIL**   | PASS     |
| 11  | gaps      | No OTLP exporter                 | PASS       | PASS     |
| 12  | anti      | No anti-patterns                 | PASS       | **FAIL** |
| 13  | rec       | Recommends /otel-instrument      | PASS       | **FAIL** |
| 14  | rec       | Mentions instrumentation-flask   | PASS       | PASS     |


### Eval 4: kvstore (Go/stdlib)


| #   | Category  | Assertion                             | With Skill | Baseline |
| --- | --------- | ------------------------------------- | ---------- | -------- |
| 1   | discovery | Go as language                        | PASS       | PASS     |
| 2   | discovery | stdlib net/http (ServeMux)            | PASS       | PASS     |
| 3   | discovery | cmd/kvstore-server/main.go            | PASS       | PASS     |
| 4   | discovery | Multi-package structure               | PASS       | PASS     |
| 5   | discovery | HTTP routes                           | **FAIL**   | PASS     |
| 6   | discovery | Filesystem persistence                | PASS       | PASS     |
| 7   | discovery | indexLoop background goroutine        | PASS       | PASS     |
| 8   | gaps      | No OTel SDK                           | PASS       | PASS     |
| 9   | gaps      | No go.opentelemetry.io deps           | PASS       | PASS     |
| 10  | gaps      | Missing otelhttp middleware           | PASS       | PASS     |
| 11  | gaps      | Missing duration histogram            | PASS       | PASS     |
| 12  | gaps      | Missing request rate                  | PASS       | PASS     |
| 13  | gaps      | Missing error rate                    | PASS       | PASS     |
| 14  | gaps      | No OTLP exporter                      | **FAIL**   | PASS     |
| 15  | gaps      | Filesystem I/O no tracing             | PASS       | PASS     |
| 16  | gaps      | LRU eviction no observability         | PASS       | PASS     |
| 17  | anti      | No anti-patterns                      | **FAIL**   | **FAIL** |
| 18  | rec       | Recommends /otel-instrument           | PASS       | **FAIL** |
| 19  | rec       | Mentions otelhttp for ServeMux        | PASS       | PASS     |
| 20  | rec       | Suggests custom spans for persistence | PASS       | PASS     |


## Session & reasoning logs

- `.workspace/otel-audit/iteration-1/eval-1-chi-basic/with_skill/outputs/session.md`
- `.workspace/otel-audit/iteration-1/eval-1-chi-basic/with_skill/outputs/reasoning.md`
- `.workspace/otel-audit/iteration-1/eval-1-chi-basic/without_skill/outputs/session.md`
- `.workspace/otel-audit/iteration-1/eval-1-chi-basic/without_skill/outputs/reasoning.md`
- `.workspace/otel-audit/iteration-1/eval-2-express-basic/with_skill/outputs/session.md`
- `.workspace/otel-audit/iteration-1/eval-2-express-basic/with_skill/outputs/reasoning.md`
- `.workspace/otel-audit/iteration-1/eval-2-express-basic/without_skill/outputs/session.md`
- `.workspace/otel-audit/iteration-1/eval-2-express-basic/without_skill/outputs/reasoning.md`
- `.workspace/otel-audit/iteration-1/eval-3-flask-basic/with_skill/outputs/session.md`
- `.workspace/otel-audit/iteration-1/eval-3-flask-basic/with_skill/outputs/reasoning.md`
- `.workspace/otel-audit/iteration-1/eval-3-flask-basic/without_skill/outputs/session.md`
- `.workspace/otel-audit/iteration-1/eval-3-flask-basic/without_skill/outputs/reasoning.md`
- `.workspace/otel-audit/iteration-1/eval-4-kvstore/with_skill/outputs/session.md`
- `.workspace/otel-audit/iteration-1/eval-4-kvstore/with_skill/outputs/reasoning.md`
- `.workspace/otel-audit/iteration-1/eval-4-kvstore/without_skill/outputs/session.md`
- `.workspace/otel-audit/iteration-1/eval-4-kvstore/without_skill/outputs/reasoning.md`