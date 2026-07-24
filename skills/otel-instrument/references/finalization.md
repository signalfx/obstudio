# Instrumentation Finalization

Load this reference exactly once after implementation, child verification,
requested downstream work, final review, and applicable full-runtime work are
complete. It owns VS Code support, credential safety, final reporting, and the
terminal command boundary.

## Contents

- VS Code debugging
- Final report and response
- Credential safety
- Terminal sequence

## VS Code Debugging

This step is required whenever `.vscode/launch.json` exists.

1. Check whether `.vscode/launch.json` exists.
2. If it exists, update at least one service debug configuration with:
   - `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`
   - `OTEL_METRIC_EXPORT_INTERVAL=1000`
   - `OTEL_BSP_SCHEDULE_DELAY=100`
3. Report the configuration, path, and whether values were added or present.
4. If the file exists but no configuration can be updated, stop and explain.
5. If absent, report `No .vscode/launch.json found; debugging setup skipped.`

## Final Report And Response

- Separate file changes from verified outcomes.
- Explain the operator/product result of each signal change and its next product
  action, not only files, packages, or signal names.
- State the selected project runtime, affected-module compile/type/import
  result, focused tests that ran, and verification result or exact blocker.
- Write `.observe/otel-instrumentation.md` using
  `instrumentation-report.md`. Include added, modified, and removed
  traces/spans, metrics, logs/events, runtime/config, and dependencies. With no
  prior audit, state that this establishes the implementation baseline.
- In canonical flow, write instrumentation JSON with exactly dependency-closed
  `approved_ids` in audit order, validate the complete available flow, and
  render instrumentation HTML using `json-approval-handoff.md`. Refresh it with
  verification proof when available. Leave `.observe/otel.html` as audit scope.
- State audit ID, selected IDs, machine-report path, and HTML path. Never call
  unselected findings implemented.
- Include `Audit Gap Closure` counts for `Working`, `Not
  working`, `Not proven`, `Not configured`, and `Deferred`; keep every source
  audit gap visible even when selected scope is narrower.
- For incident readiness, summarize each in-scope workflow, dependency, input
  complexity, freshness, backpressure, synthetic/canary, auth/edge, capacity,
  health/readiness, and release/config surface as `MTTD-improving`,
  `localization-only`, `provider/platform-owned`, or `uncovered`. Name each
  remaining detector prerequisite and owner. Do not call the pass complete
  while app-owned required telemetry is only a follow-up unless scope was
  explicitly narrowed.
- For GenAI, follow `genai-instrumentation.md` finalization and remaining-signal
  rules.
- Include `$otel-verify` results and `.observe/otel-verify.md` when run. If
  detector/configuration work was requested, include its outputs and
  `.observe/splunk-configure-verify.md` status.
- If verification is partial, say exactly what works and what is missing.
- Never say `complete`, `working`, or `verified` when the mandatory
  compile/type/import gate failed, was blocked, or was not run. Say
  `implemented; verification blocked/not run` and name the prerequisite.
- Always include service-name configuration, OTLP endpoint configuration,
  expected automatic spans/metrics, selected log scope, and applicable
  full-runtime result.

New applications may receive a full scaffold matching their existing runtime
shape. Existing applications receive incremental work only: preserve current
ownership and add what selected scope lacks.

## Credential Safety

Enter this section only when the repository already has an env-file workflow or
the user explicitly requests one. Standard application OTel environment
variables do not authorize creating `.env.example`, `.env`, or `.gitignore`;
document them in the report or existing launcher.

When the condition applies:

1. Ensure `.env` is gitignored before writing secrets.
2. Create or update `.env.example` only with safe placeholders.
3. Search tracked configuration and confirm no real token appears in a file to
   be committed.

## Terminal Sequence

After every report/artifact requirement, requested detector/configure workflow,
conditional full-runtime gate, applicable credential work, final code review,
and validation, choose exactly one terminal branch.

### Final Child Without Executed Failure

When final child `.observe/otel-verify.json` has no executed failure and is
`lifecycle: final`, run:

```bash
python3 -I "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" finalize-instrumentation \
  .observe/otel-audit.json \
  --selection-json .observe/otel-selection.json \
  --instrumentation-json .observe/otel-instrumentation.json \
  --verify-json .observe/otel-verify.json \
  -o .observe/otel-instrumentation.html
```

This validates canonical bindings, verify reader projection, and gap closure;
rejects stale instructions to run an already-present child; renders HTML once;
and applies the final child gate last. It must pass. `Partial` proof may pass
with no executed failure; an intermediate or `not_working` child cannot. Invoke
only the loaded skill wrapper. Never import helper internals, calculate
`instrumentation_sha256` manually, edit a child digest, or rerun unchanged
constituent validators. Rerun child verification against the current overlay
instead.

### Stopped Executed Failure

When safe in-scope repairs are exhausted at an evidenced boundary, do not run
the final gate or relabel the child final. Preserve `lifecycle: intermediate`,
the executed failure, repair-only finding `remaining` and run `next_steps`, and
the structured `stop_boundaries[]` record. Keep instrumentation
`meta.result: Fail` and the finding `not_working`. Run canonical `validate-flow`
and `render-instrumentation-html` with `--verify-json`. Their success validates
a stopped-failure handoff, not completed instrumentation.

### Explicit No-Child Branch

When the user opted out or a concrete prerequisite prevented a child overlay,
do not fabricate one or run a gate that requires it. If compile/focused proof
passed, preserve instrumentation `meta.result: Partial` and selected findings
`not_proven`; absence of child verification alone is not overall `Blocked` or
`Not run`. Record `Verification: Not run` or `Verification: Blocked` plus the
reason in finding evidence, `next_steps`, and technical Markdown. Rerun the
canonical `validate-flow` and `render-instrumentation-html` commands from
`json-approval-handoff.md` without `--verify-json`. That is terminal validation.

### Direct No-Audit Branch

Do not seek or invoke a canonical gate. Finish technical reports and run
the last applicable project tests, child verification/report validator or exact
skip/blocker, and direct report validation. The last successful applicable
validation is terminal. Never fabricate audit, selection, instrumentation, or
verification JSON.

### Terminal Boundary

A passing `finalize-instrumentation` command (which includes
`instrumentation-final-gate`), successful stopped-failure validation,
successful explicit no-child validation, or successful direct validation starts
the terminal boundary. On fixed Go, run runner `--action cleanup` exactly once
after that check. After cleanup—or immediately after the terminal check when it
does not apply—emit the final response without another command.

Do not run `git status`, `git diff`, inspect `go.sum`, inspect/remove caches,
list files/artifacts, repeat a validator/test, or perform duplicate final review
after this boundary. After fixed-Go cleanup, never rerun the resolver, edit the
project, run Go, or attempt manual `GOCACHE`, `GOMODCACHE`, `go`, `rm`, or
`find` recovery. If cleanup fails, report that exact failure immediately.
