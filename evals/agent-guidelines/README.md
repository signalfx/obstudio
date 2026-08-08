# Agent Guideline Eval Specifications

These standalone specifications describe future live evaluations of the
repository-level coding and review rules in `AGENTS.md`. They do not currently
execute a coding or review agent and are not evidence of behavioral compliance.
Each role includes a seeded violation, a safe counterexample, and an unrelated
clean change so a future grader must detect real violations without
manufacturing findings.

`test_agent_guideline_contracts.py` deterministically verifies the policy
headings, stable rule IDs, case balance, rubric coverage, and judge output
schemas. It runs as part of the existing eval-harness test suite.

These files deliberately do not live under an `eval/qual` directory. The
current live eval collector evaluates a named skill by loading it through
`.agents/skills`; repository-level `AGENTS.md` behavior is a different subject.
Registering these cases there would claim skill-backed execution that does not
exist. Until a repository-policy runner is added, only their schema, balance,
and alignment with the tracked policy are automated; behavioral grading remains
a follow-up.
