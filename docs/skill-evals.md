# Skill Eval Framework

## What It Is

An automated benchmarking system that measures whether our skills (otel-audit, otel-instrument, otel-verify, otel-observe) actually improve Claude's output compared to Claude without any skill guidance.

## How It Works

For each test case, the runner executes two passes:

1. **With skill** — runs `claude -p` with the skill's SKILL.md + references loaded
2. **Baseline (without skill)** — runs the same prompt with no skill context

Both runs execute against real example apps (flask-basic, chi-basic, kvstore, express-basic, fastapi-celery) in isolated workspaces.

## How Pass Rates Are Calculated

Each eval has a list of **assertions** — concrete checks against the output. For example, a otel-audit eval might assert:

- `.observe/inventory.md` file is created
- Inventory contains a Spans table
- Inventory contains a Metrics table
- At least 5 span signals are defined
- Fault domains are identified

**Pass rate = assertions passed / total assertions**

If an eval has 10 assertions and the skill run passes 9, that's 90%. The benchmark averages across all evals for a skill and reports the standard deviation.

## What the Results Mean

| Metric | Description |
|--------|-------------|
| **Pass rate** | % of assertions satisfied (higher = better) |
| **Delta** | Skill pass rate minus baseline pass rate (positive = skill helps) |
| **Time** | Wall-clock seconds per eval run |
| **Tokens** | Total tokens consumed per run |

**Interpreting delta:**
- **Positive delta** — the skill is adding value over vanilla Claude
- **Zero delta** — skill doesn't change the outcome (Claude already knows how)
- **Negative delta** — skill is actually hurting (over-constraining or misdirecting)

## First Run Results (2026-04-20)

| Skill | With Skill | Baseline | Delta | Avg Time | Avg Tokens |
|-------|-----------|----------|-------|----------|------------|
| otel-audit | 97% | 100% | -3% | 159s | 14,793 |
| otel-instrument | 71% | 71% | 0% | 365s | 28,848 |
| otel-observe | 60% | 60% | 0% | 546s | 52,945 |
| otel-verify | 45% | 45% | 0% | 254s | 17,584 |

## Analysis

1. **otel-audit** is the most mature — 97% pass rate, only missed 1 assertion on one eval.

2. **No skill outperforms baseline yet.** This doesn't mean skills are useless — it means our assertions test for things Claude can already do without guidance (create OTel files, add packages). The skills' real value (correct inventory format, SLI definitions, fault domain taxonomy, semconv compliance) needs more targeted assertions.

3. **otel-verify** scores lowest (45%) because it requires a running collector and service — assertions like "trace data is queried" and "metrics are checked" can't fully pass in a sandbox without infrastructure.

4. **Token cost correlates with skill complexity** — otel-observe (chains all sub-skills) uses 53K tokens vs otel-audit at 15K.

## Next Steps

- Add assertions that test skill-specific output quality (inventory format compliance, semconv naming, fault domain coverage)
- Fix otel-verify evals to mock or stub the collector dependency
- Re-run after skill improvements to track progress over time

## Running Evals

```bash
make skill-eval SKILL=otel-audit       # one skill
make skill-eval-all                      # all skills
```

Results land in `skill-eval-workspace/<skill>/latest/`.
