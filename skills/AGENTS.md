# Skill Source Instructions

This file adds skill-maintenance guidance to the repository-root `AGENTS.md`.

- `skills/` is canonical. Update `.agents/skills/` only as relative discovery
  links, and keep shared behavior in `skills/references/` when it genuinely
  applies to more than one skill.
- Load and edit only the language or signal reference needed for the task.
- Pair instruction behavior changes with the smallest observable eval. Do not
  weaken a check merely to accept an incorrect output.

For script changes, run the owning unit suite, for example
`python3 -m unittest discover -s skills/otel-audit/tests -p 'test_*.py'`.
Validate the changed skill with
`make eval-validation SKILL=skills/otel-audit`, substituting the changed skill
path. Run `make test-interactive-otel-scripts` when shared guidance or scripts
change. Use sanity, rubric, or runtime evals only when their documented proof is
needed.
