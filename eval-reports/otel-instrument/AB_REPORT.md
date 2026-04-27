# otel-instrument Codex A/B Eval Report

| Case | Prompt | With Skill Checks | Baseline Guards | Commands (ws/base) | Tokens (ws/base) |
|---|---|---:|---:|---:|---:|
| node/express-basic | direct | 83% (5/6) | 100% (3/3) | 32/28 | 406258/576348 |
| node/express-basic | runtime-preserving | 100% (6/6) | 100% (3/3) | 68/40 | 1049010/733960 |
| python/fastapi-celery | direct | 67% (4/6) | 100% (3/3) | 114/38 | 2112327/750818 |
| python/fastapi-celery | runtime-preserving | 50% (3/6) | 100% (3/3) | 36/32 | 576932/744019 |
| python/flask-basic | direct | 50% (3/6) | 100% (3/3) | 56/20 | 1130606/419010 |
| python/flask-basic | runtime-preserving | 50% (3/6) | 100% (3/3) | 38/56 | 412180/1147299 |

## Deterministic Checks

### node/express-basic (direct)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-instrument |
| with_skill | package-sdk-node | PASS | All values present in /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-node-express-basic-direct-w38bxgiv/with_skill/service/package.json |
| with_skill | package-http-express-instrumentation | FAIL | Missing: @opentelemetry/instrumentation-http, @opentelemetry/instrumentation-express |
| with_skill | instrumentation-file | PASS | Existing: /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-node-express-basic-direct-w38bxgiv/with_skill/service/otel.js |
| with_skill | startup-preload | PASS | At least one value present in /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-node-express-basic-direct-w38bxgiv/with_skill/service/package.json |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### node/express-basic (runtime-preserving)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-instrument |
| with_skill | package-sdk-node | PASS | All values present in /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-node-express-basic-runtime-preserving-aqp76zk_/with_skill/service/package.json |
| with_skill | package-http-express-instrumentation | PASS | All values present in /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-node-express-basic-runtime-preserving-aqp76zk_/with_skill/service/package.json |
| with_skill | instrumentation-file | PASS | Existing: /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-node-express-basic-runtime-preserving-aqp76zk_/with_skill/service/instrumentation.js |
| with_skill | startup-preload | PASS | At least one value present in /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-node-express-basic-runtime-preserving-aqp76zk_/with_skill/service/package.json |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### python/fastapi-celery (direct)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-instrument |
| with_skill | pyproject-otel-sdk | FAIL | Missing: opentelemetry-api, opentelemetry-sdk |
| with_skill | pyproject-fastapi-instrumentation | PASS | At least one value present in /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-python-fastapi-celery-direct-ae_ssu1l/with_skill/service/pyproject.toml |
| with_skill | otel-setup-file | FAIL | No candidate files found |
| with_skill | compose-env-wired | PASS | At least one value present in /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-python-fastapi-celery-direct-ae_ssu1l/with_skill/service/docker-compose.yml |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### python/fastapi-celery (runtime-preserving)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-instrument |
| with_skill | pyproject-otel-sdk | FAIL | Missing: opentelemetry-api, opentelemetry-sdk |
| with_skill | pyproject-fastapi-instrumentation | PASS | At least one value present in /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-python-fastapi-celery-runtime-preserving-dlecco1d/with_skill/service/pyproject.toml |
| with_skill | otel-setup-file | FAIL | No candidate files found |
| with_skill | compose-env-wired | FAIL | None present: OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### python/flask-basic (direct)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-instrument |
| with_skill | pyproject-otel-sdk | FAIL | Missing: opentelemetry-api |
| with_skill | pyproject-flask-instrumentation | PASS | All values present in /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-python-flask-basic-direct-lnhzgv6d/with_skill/service/pyproject.toml |
| with_skill | otel-setup-file | FAIL | No candidate files found |
| with_skill | app-wires-instrumentation | FAIL | None present: otel_setup, setup_otel, FlaskInstrumentor, instrument_app |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### python/flask-basic (runtime-preserving)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-instrument |
| with_skill | pyproject-otel-sdk | FAIL | Missing: opentelemetry-api, opentelemetry-sdk |
| with_skill | pyproject-flask-instrumentation | PASS | All values present in /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-instrument-python-flask-basic-runtime-preserving-1v0yz4n4/with_skill/service/pyproject.toml |
| with_skill | otel-setup-file | FAIL | No candidate files found |
| with_skill | app-wires-instrumentation | FAIL | None present: otel_setup, setup_otel, FlaskInstrumentor, instrument_app |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

