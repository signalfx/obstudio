# Agent Guideline Eval Specifications

These standalone specifications describe future live evaluations of the
repository-level coding and review rules in `AGENTS.md`. They do not currently
execute a coding or review agent and are not evidence of behavioral compliance.
Each role includes a seeded violation, a safe counterexample, and an unrelated
clean change so a future grader must detect real violations without
manufacturing findings. The matrix covers focused diffs and tests, mandatory
skill rubric pairing and local-run evidence, functional/accessibility/visual UI
proof, reusable-plugin compatibility and isolation, and per-target agent
integration failure containment.

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

Separately, `scripts/check_agent_policy.py --base-ref <ref>` performs a
deterministic diff check: changed content under a named skill must be paired
with a changed rubric JSON whose top-level `skill` matches. A shared
`skills/references/` change is mapped through
`skills/references/consumers.json` and requires a changed matching rubric for
every current or prior declared consumer. This proves repository pairing and
schema alignment, not that the local model-backed rubric command actually ran.
Until a credentials-backed live rubric CI job is enabled, the exact command and
result recorded in the pull request remain an explicit author attestation
reviewed under `OBS-SKILL`.
