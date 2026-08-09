# Skill Source Instructions

This file adds skill-maintenance guidance to the repository-root `AGENTS.md`.

- `skills/` is canonical. Update `.agents/skills/` only as relative discovery
  links, and keep shared behavior in `skills/references/` when it genuinely
  applies to more than one skill.
- Load and edit only the language or signal reference needed for the task.
- Every addition or modification to shipped skill content must add or
  semantically update at least one matching rubric eval under
  `evals/*/*/eval/qual/` (or `evals/*/*/eval/rubric/`) whose `skill` field names
  the changed skill. Do not use existing coverage as an exception and do not
  weaken a check merely to accept an incorrect output. Effective-equivalent
  formatting, key ordering, same-case relocation, prompt ordering,
  identity-only IDs, language/service-only metadata changes, or empty input
  defaults do not count as a semantic coverage update.
- Run and report both
  `make eval-validation SKILL=skills/<name>` and a representative
  `make eval-rubric SKILL=skills/<name> CASE=<language>/<service>` command.
  Validation proves collection and schema shape; it does not replace semantic
  rubric grading. For shared-reference changes, keep
  `references/consumers.json` aligned and repeat this for every retained
  declared affected skill. A consumer retired in the same diff follows the
  complete-retirement cleanup exception.
- A complete skill retirement must remove all tracked and non-ignored content
  under the canonical directory, the discovery link, Available Skills row,
  matching eval definitions, tracked `eval-reports/<skill>/` artifacts, the
  retired skill from each shared-reference consumer list, and related aliases or
  documentation. Ignored local caches are outside the repository contract and
  need not be deleted. Delete a consumer-map key only when its shared reference
  is also removed. Run
  `make agent-policy-check` and `make test-eval-harness`; a local rubric run is
  not required for a skill that no longer exists. Deleting shipped content from
  a retained skill remains a modification and follows the normal eval and run
  requirements.

For script changes, run the owning unit suite, for example
`python3 -m unittest discover -s skills/otel-audit/tests -p 'test_*.py'`.
Validate the changed skill with
`make eval-validation SKILL=skills/otel-audit`, substituting the changed skill
path, then run a representative local rubric such as
`make eval-rubric SKILL=skills/otel-instrument CASE=go/kvstore`. Run
`make test-interactive-otel-scripts` when shared guidance or scripts change.
Use sanity or runtime evals when their documented proof is also needed.
