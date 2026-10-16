# Observe the skill workflow

This records ordinary skill use in any host that can run Python. It does not
require an eval runner, SEP-2640, or native Codex/Claude telemetry. SEP-2640
delivers these instructions; fetching a reference is not executing its stage.

Respect the user's file-write constraints first. If metadata files are forbidden,
Python is unavailable, or recording fails, continue the authorized primary work
without recording. Never change provider settings to enable this helper.

Resolve `RECORDER` to this reference directory's `scripts/skill_workflow.py`.
At the beginning, run:

```sh
python3 "$RECORDER" start --skill otel-audit --repo-root /absolute/service/root
```

Use the invoked skill name (`otel-audit`, `otel-instrument`, or `otel-verify`).
Retain the returned absolute `run` path for this invocation only. Do not reuse a
previous invocation's journal. Stages and allowed branches are declared in
`workflows.json` and routed from each skill's SKILL.md.
Each journal captures bundle and stage-contract digests at start for comparing
versions. These identify the available instructions, not proof that every file
entered model context. Local and remotely projected bundles can have different
digests because their reference paths differ.

Use only these branch values; omit `--branch` for every stage not listed:

| Skill | Stage | Branches |
|---|---|---|
| audit | discover | go, python, node, java, other |
| audit | assess | fresh, incremental, mixed |
| instrument | scope | explicit, saved, all, blocked |
| instrument | plan | fresh, incremental, targeted |
| instrument | verify | focused, full_runtime, blocked |
| verify | inputs | canonical, missing, stale |
| verify | build | passed, blocked |
| verify | signals | focused, full_runtime, contract_only, blocked |

For example, instrumentation's `preflight` has no language branch. If a recorder
call rejects a stage or branch, correct that metadata from this table and retry
once before continuing. A rejected call did not record the stage; do not assume
it succeeded. If recording still fails, continue the primary task.

After completing a reasoning stage, record an honest checkpoint, for example:

```sh
python3 "$RECORDER" checkpoint --run "$RUN" --stage discover --branch go --status passed
```

Checkpoints are agent-reported. They have no measured stage latency or token
count. Do not treat loading instructions as completing the stage. Evidence may
be attached with repeated `--evidence .observe/otel-audit.json` options; paths
must be repository-relative and existing files. Only path and SHA-256 are saved
locally. File contents are never exported.

When an existing workflow command corresponds to a declared stage, measure that
actual command instead of adding a checkpoint for the same operation:

```sh
python3 "$RECORDER" execute --run "$RUN" --stage build -- go test ./...
```

In particular, wrap existing build/import commands as `build`, signal-check
commands as `signals` (verification) or `verify` (instrumentation), and the final
report validator/renderer as `report`. Use the current skill's declared stage
IDs. Do not run these commands directly and then substitute a checkpoint for
their measured execution. If no command applies to a stage, use a checkpoint
with the actual result or an explicit skipped/blocked reason.

The command retains its output and exit status. The journal stores measured
elapsed time and exit code, never command arguments, output, prompts, or
environment values. This measures only that command, not unobserved reasoning.
Use the original required command; do not add work just to produce telemetry.
Retries become separate attempts. A successful retry resolves that stage's
failure, while preserving the earlier attempt. For blocked or intentionally
skipped stages, use `checkpoint --status blocked|skipped --reason <short-code>`.
Do not mark an unreached stage skipped or passed to make coverage look complete.

Before the skill's final response, finish explicitly:

```sh
python3 "$RECORDER" finish --run "$RUN" --status passed
python3 "$RECORDER" inspect --run "$RUN"
```

Use `partial`, `failed`, or `cancelled` when appropriate. Requested success is
downgraded to partial when required stages are missing, out of order, or still
blocked/failed. A run without a finish remains incomplete. Preserve the skill's
normal final response format; do not add recorder narration to strict responses.

Journals live in `.observe/skill-runs/`. Export is best effort to the local Studio
MCP endpoint (`http://127.0.0.1:3000/mcp` by default). Set
`OBSTUDIO_SKILL_MCP_ENDPOINT=http://127.0.0.1:<port>/mcp` for another local
instance, or `none` for offline-only recording. `sync --run "$RUN"` replays a
journal after Studio starts or clears its bounded memory. Replaying retained
events is idempotent. Studio exposes the path through its existing trace explorer
and `observer_skill_workflows` MCP tool, with measured commands and checkpoints
labeled separately. Tokens remain unknown without independent provider evidence.

Missing stages, failed checks, repeated retries, and branch mismatches are
improvement candidates. They are not proof that skill prose caused a problem.
Compare the recorded path with actual commands, artifacts, and rubric judgments
before changing the skill. `otel-verify` proves application telemetry; it does
not independently grade the audit or instrumentation skill's reasoning.
