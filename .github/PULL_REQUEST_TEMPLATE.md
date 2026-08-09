## Summary

- What changed:
- Why:

## Scope

- In scope:
- Explicitly out of scope:
- Relevant `OBS-*` rules:

## Validation evidence

- Exact commands and results:
- Agent-policy check (when applicable):
- Regression test added or updated:
- Skill eval file(s), when shipped skill content changed:
- Local rubric command and result for each added or modified skill; for a
  complete retirement, record agent-policy and eval-harness cleanup results:
- Affected UI interaction/accessibility evidence; normal+narrow/theme visual
  evidence for material visual changes:
- Plugin/integration compatibility evidence; isolated-failure evidence when
  discovery, shared state, lifecycle, execution, or orchestration changed:
- Checks skipped and why:
- Coverage or other evidence for changed behavior:

## Risk and review

- Compatibility, migration, or rollback considerations:
- Residual risks or unverified assumptions:
- [ ] The diff contains no unrelated changes.
- [ ] No shipped skill content changed; every added or modified skill has a
      semantic (not effective-equivalent identity/default/order-only) matching
      rubric update and exact local rubric result; or every retired skill has
      complete source, discovery, table, eval, tracked-report, consumer-list
      membership, and compatibility cleanup evidence above.
- [ ] No UI changed, or every affected field, option, action, accessibility
      path, state, and material visual change has proportionate evidence above.
- [ ] No plugin/integration changed, or an existing path has compatibility
      evidence and affected failure-isolation behavior is proven above.
