# otel-audit Codex A/B Eval Report

| Case | Prompt | With Skill Checks | Baseline Guards | Commands (ws/base) | Tokens (ws/base) |
|---|---|---:|---:|---:|---:|
| go/chi-basic | direct | 71% (5/7) | 100% (3/3) | 22/10 | 169816/80321 |
| go/chi-basic | readiness-review | 86% (6/7) | 100% (3/3) | 20/14 | 162069/210920 |

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
| with_skill | audit-read-only | PASS | /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-audit-go-chi-basic-direct-fc_j0kef/with_skill/service/otel.go |
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
| with_skill | audit-read-only | PASS | /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-audit-go-chi-basic-readiness-review-naeyh22y/with_skill/service/otel.go |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

