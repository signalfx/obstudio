# Eval Instructions

This file adds eval-harness and fixture guidance to the repository-root
`AGENTS.md`.

- Preserve fixture realism and the distinction between validation, sanity,
  rubric, runtime, and A/B checks described in `evals/README.md`.
- Keep deterministic artifact and loading checks in sanity/validation; use
  rubric checks for semantic judgment and runtime checks only for live
  telemetry proof.
- Keep baseline checks intentionally simple and do not weaken expected behavior
  to make an implementation pass.
- Treat `.workspace/codex-evals/` as generated run output. Update tracked latest
  reports only through the corresponding report target.

For a narrow deterministic check, run
`make eval-validation SKILL=skills/otel-audit`, substituting the affected skill.
Run `make test-eval-harness` for the complete harness validation suite. When a
live check is warranted, use the narrowest case, for example
`make eval-rubric SKILL=skills/otel-instrument CASE=go/kvstore`; add `AB=1` only
when baseline comparison is intentional.
