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
with a changed rubric JSON whose top-level `skill` matches and whose parsed
effective definition differs from every rubric in the same fixture case at the
merge base. Effective comparison ignores top-level and prompt IDs, uses the
physical path to decide whether language/service-only metadata adds coverage,
normalizes omitted and empty input defaults, and ignores prompt and eval-input
ordering. The eval loader still preserves explicit language/service values for
case identity and reporting; the policy check only determines whether an edit
adds behavior coverage. A shared
`skills/references/` change is mapped through
`skills/references/consumers.json` and requires a changed matching rubric for
every retained current or prior declared consumer; a concurrently retired
consumer follows the complete-retirement cleanup exception. A complete skill
retirement instead requires removal or migration of its tracked and non-ignored
canonical content, eval definitions, and tracked latest eval reports; ignored
local caches are outside the repository contract. Consumer mappings must remove
only the retired skill's memberships unless the shared reference itself is also
removed. The checker does not require a rubric run for a skill that no longer
exists.
This proves repository pairing and schema alignment, not that the rubric change
exercises the right behavior or that the local model-backed rubric command
actually ran.
Until a credentials-backed live rubric CI job is enabled, the exact command and
result recorded in the pull request remain an explicit author attestation
reviewed under `OBS-SKILL`.
