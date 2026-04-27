# otel-audit Codex A/B Eval Report

| Case | Prompt | With Skill Checks | Baseline Guards | Commands (ws/base) | Tokens (ws/base) |
|---|---|---:|---:|---:|---:|
| go/chi-basic | direct | 71% (5/7) | 100% (3/3) | 10/10 | 79003/86721 |
| go/chi-basic | readiness-review | 86% (6/7) | 100% (3/3) | 16/16 | 130670/218812 |
| go/kvstore | direct | 67% (4/6) | 100% (3/3) | 38/44 | 489466/188245 |
| go/kvstore | readiness-review | 83% (5/6) | 100% (3/3) | 54/42 | 429618/406098 |
| node/express-basic | direct | 67% (4/6) | 100% (3/3) | 20/12 | 146798/67231 |
| node/express-basic | readiness-review | 83% (5/6) | 100% (3/3) | 30/16 | 254170/125405 |
| python/fastapi-celery | direct | 67% (4/6) | 100% (3/3) | 28/32 | 212199/251361 |
| python/fastapi-celery | readiness-review | 83% (5/6) | 100% (3/3) | 50/28 | 444873/215639 |
| python/flask-basic | direct | 67% (4/6) | 100% (3/3) | 26/18 | 282150/133372 |
| python/flask-basic | readiness-review | 100% (6/6) | 100% (3/3) | 26/20 | 214494/153719 |

## Deterministic Checks

### go/chi-basic (direct)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-audit |
| with_skill | final-identifies-go | PASS | All values present |
| with_skill | final-identifies-chi | PASS | All values present |
| with_skill | final-notes-no-otel | FAIL | Missing: missing |
| with_skill | final-recommends-instrument | FAIL | Missing: $otel-instrument |
| with_skill | audit-read-only | PASS | /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-audit-go-chi-basic-direct-3y_6n58a/with_skill/service/otel.go |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### go/chi-basic (readiness-review)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-audit |
| with_skill | final-identifies-go | PASS | All values present |
| with_skill | final-identifies-chi | PASS | All values present |
| with_skill | final-notes-no-otel | PASS | All values present |
| with_skill | final-recommends-instrument | FAIL | Missing: $otel-instrument |
| with_skill | audit-read-only | PASS | /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-audit-go-chi-basic-readiness-review-8bsnbp_l/with_skill/service/otel.go |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### go/kvstore (direct)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-audit |
| with_skill | final-identifies-go | PASS | All values present |
| with_skill | final-identifies-servemux | FAIL | None present: ServeMux, net/http, stdlib |
| with_skill | final-notes-persistence | PASS | At least one value present |
| with_skill | final-recommends-instrument | FAIL | Missing: $otel-instrument |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### go/kvstore (readiness-review)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-audit |
| with_skill | final-identifies-go | PASS | All values present |
| with_skill | final-identifies-servemux | PASS | At least one value present |
| with_skill | final-notes-persistence | PASS | At least one value present |
| with_skill | final-recommends-instrument | FAIL | Missing: $otel-instrument |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### node/express-basic (direct)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-audit |
| with_skill | final-identifies-node | FAIL | None present: Node.js, Node |
| with_skill | final-identifies-express | PASS | All values present |
| with_skill | final-notes-no-otel | PASS | All values present |
| with_skill | final-recommends-instrument | FAIL | Missing: $otel-instrument |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### node/express-basic (readiness-review)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-audit |
| with_skill | final-identifies-node | PASS | At least one value present |
| with_skill | final-identifies-express | PASS | All values present |
| with_skill | final-notes-no-otel | PASS | All values present |
| with_skill | final-recommends-instrument | FAIL | Missing: $otel-instrument |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### python/fastapi-celery (direct)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-audit |
| with_skill | final-identifies-python | FAIL | Missing: Python |
| with_skill | final-identifies-fastapi | PASS | All values present |
| with_skill | final-identifies-celery | PASS | At least one value present |
| with_skill | final-recommends-instrument | FAIL | Missing: $otel-instrument |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### python/fastapi-celery (readiness-review)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-audit |
| with_skill | final-identifies-python | PASS | All values present |
| with_skill | final-identifies-fastapi | PASS | All values present |
| with_skill | final-identifies-celery | PASS | At least one value present |
| with_skill | final-recommends-instrument | FAIL | Missing: $otel-instrument |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### python/flask-basic (direct)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-audit |
| with_skill | final-identifies-python | FAIL | Missing: Python |
| with_skill | final-identifies-flask | PASS | All values present |
| with_skill | final-notes-no-otel | FAIL | Missing: missing |
| with_skill | audit-read-only | PASS | /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-audit-python-flask-basic-direct-d9z9ar_i/with_skill/service/otel_setup.py |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

### python/flask-basic (readiness-review)

| Side | Check | Result | Evidence |
|---|---|---|---|
| with_skill | final-message-present | PASS | Final message present |
| with_skill | skills-loaded | PASS | Loaded skills: otel-audit |
| with_skill | final-identifies-python | PASS | All values present |
| with_skill | final-identifies-flask | PASS | All values present |
| with_skill | final-notes-no-otel | PASS | All values present |
| with_skill | audit-read-only | PASS | /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-audit-python-flask-basic-readiness-review-v8obyuuy/with_skill/service/otel_setup.py |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

