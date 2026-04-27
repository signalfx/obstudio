# otel-audit Codex Eval Report

| Case | Prompt | With Skill Checks | Baseline Guards | Commands (ws/base) | Tokens (ws/base) |
|---|---|---:|---:|---:|---:|
| go/chi-basic | direct | 71% (5/7) | 100% (3/3) | 20/16 | 162614/131249 |

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
| with_skill | audit-read-only | PASS | /var/folders/j0/q4s1xtqn6kx48fbgtb30qhw00000gn/T/codex-eval-otel-audit-go-chi-basic-direct-a_lqf1nd/with_skill/service/otel.go |
| baseline | final-message-present | PASS | Final message present |
| baseline | skills-not-loaded | PASS | No repo skill files present |
| baseline | baseline-skill-isolation | PASS | No repo skill references found |

