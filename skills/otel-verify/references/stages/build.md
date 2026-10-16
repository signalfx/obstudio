### 4. Run The Build/Import Viability Gate

Before creating telemetry harnesses or starting services, prove that the
changed instrumentation can load under the selected project runtime.

Build an impact table:

```markdown
| Affected module/surface | Changed files | Gate command | Result | Failure ownership | Impacted scenarios |
|---|---|---|---|---|---|
```

Rules:

- Run static integrity checks for changed scripts/config and
  `git diff --check` when Git is available.
- Compile, typecheck, syntax-check, or import every module containing changed
  instrumentation. Use the narrowest project-native command that still loads
  the changed code and its generated sources/annotation processors.
- Use the selected runtime from Step 3 for every gate. A failure under a
  rejected global runtime is not an application failure.
- If `.observe/otel-instrumentation.md` records a passing gate, rerun it when
  practical; otherwise treat it as prior evidence, not current proof.
- Classify a failure on a changed line or changed API contract as
  `instrumentation-introduced` unless evidence proves otherwise. Classify
  missing configured runtimes, declared dependencies, private registries, or
  credentials as `environment`. Use `pre-existing` or `unknown` only with
  concrete evidence.
- Verification remains read-only for application code. For an
  instrumentation-introduced failure, mark affected signal/path rows
  `Blocked`, set the overall result to `Fail`, name `$otel-instrument` as the
  repair path, and do not attempt expensive runtime/OTLP harnesses that depend
  on the broken module.
- An unavailable prerequisite produces `Blocked` rows and an overall `Partial`
  when meaningful proof passed. Use an overall `Blocked` result when no
  meaningful proof can run. Use `Fail` only when a scenario ran and its
  expected telemetry was absent or invalid.
- Continue with unaffected modules and scenarios when their runtime surface is
  independent.

