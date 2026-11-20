# Promptfoo changed-file pilot

This additive pilot runs one existing Flask audit task through Promptfoo 0.126.0.
It keeps the existing suites, runner, skill-loading proof and canonical audit validator.
It does not replace the pytest harness or measure the entire audit skill.

| Changed file | Participating suite selected |
| --- | --- |
| `skills/otel-audit/**`, its discovery link, audit eval JSON | `otel-audit` |
| `skills/otel-instrument/**`, instrumentation eval JSON | None; ownership is reported outside this pilot |
| Unrelated application/documentation | None |
| Shared guide/script | Intersection of base/head `skills/references/consumers.json` owners with participating suites |
| Consumer metadata, new unmapped shared guide | All participating suites (currently audit) |
| Flask source, harness, eval model/config/lock, pilot provider/grader/config/lock, CI workflow | Audit |

The selector compares **merge base to HEAD**, including deleted paths and both sides of
renames. Invalid refs, invalid metadata and incomplete diffs fail rather than skip.
It reads both revisions' eval `skill` fields and shared consumer metadata; Promptfoo
does not discover these relationships automatically. Only audit participates. The
second-participant test is a deterministic routing control, not an instrumentation eval.
Changing an audit eval selects this representative pilot, not that file's full suite.
This bare case declares no seed inputs; unused `eval/inputs` and runtime assets do not select it.

## Run locally

Use Node >=22.22.0, npm, uv, Git and the existing authenticated Codex CLI.
The isolated eval home must contain existing authorized credentials and the minimal
`evals/codex-eval-home.config.toml`; see the parent eval README for authentication.
Do not use a personal home with unrelated plugins or MCP servers.
The adapter enforces the minimal template and records its non-secret configuration hash.

```sh
npm ci --prefix evals/promptfoo --ignore-scripts
npm test --prefix evals/promptfoo
python3 evals/promptfoo/routing.py --base origin/main
CODEX_EVAL_HOME="$PWD/.workspace/codex-evals/codex-home" npm run eval --prefix evals/promptfoo -- --base origin/main
# Use the fresh directory printed by the command, even if the model eval failed:
npm run report --prefix evals/promptfoo -- /absolute/path/to/.workspace/promptfoo/RUN-ID
```

Commit source changes before selecting them (the adapter refuses dirty input files): Git comparison excludes uncommitted
changes. For example, a commit changing `skills/otel-audit/SKILL.md` selects audit;
an instrumentation-only commit exits with `skipped: not affected`, without model calls.
The package and Python locks are enforced. A private local registry returning 403 can
be replaced for this command only with the public registry/index; no user settings
need to change.

The original task is just `$otel-audit`. The existing harness adds an explicit initial
skill-read instruction; both prompts are preserved. The pilot creates the case in
memory from `python/flask-basic/eval/qual/audit.json` and overrides only task/identity.
It executes only the with-skill side through the existing `run_side` function.
Raw files stay under `.workspace/promptfoo/<fresh UUID>/`; no cached result is reused.

## Find the evidence

Start at [the latest compact proof](../../eval-reports/promptfoo-pilot/report.md) and
[its machine-readable attestation](../../eval-reports/promptfoo-pilot/benchmark.json).
They show the prompt, verbatim rules, actual audit excerpt, each automated status,
source/artifact SHA-256 values, judge evidence/reason, guards, model requests and timing.
The corresponding `npm run report` target is the only publisher of these latest files.
Keep human review notes separate; never replace the raw automated grade.

Each local run also contains:

- `promptfoo.json`: original native export with assertion reason and unchanged provider output.
- `selection.json`: paths, merge base, selection reasons and nonparticipating owners.
- `evidence/prompt.txt`, `judge-prompt.txt`, `judge-schema.json`, `result.json`, `validation.txt`.
- `evidence/agent/`: original task transcript, final response, guard grade, staged skill,
  service source and actual canonical `.observe/otel-audit.json`/`otel.html` artifacts.
- `evidence/judge/`: raw read-only judge transcript, stderr and structured grade.

For native Promptfoo inspection, set `PROMPTFOO_CONFIG_DIR` to that run's `viewer`
directory and run the pinned `promptfoo view` command locally. No hosted report,
account, sharing command, or browser is required by automated runs. Viewer ratings
cannot change the stored attestation; the raw export and judge grade remain authoritative.
Bulk transcripts and viewer databases are ignored, not committed or uploaded.

## What fails the gate

The judge runs against a separate temporary evidence copy, outside the repository's
instruction ancestry. Its schema retains `pass`, `fail`, `not-proven`,
`not-applicable`, and `ungraded`. Rule/Example/Evidence/Insufficient evidence guidance
is in the exact judge prompt; examples are pilot-authored, canonical rules are imported.
Rule 6 remains a compound criterion and requires evidence for each clause.

All six IDs must appear exactly once, with explicit `pass`, a reason and evidence.
N/A is never converted into a pass or excluded from the required denominator.
Agent/judge errors, missing grading, changed source/evidence, failed full skill-read
guards, changed service files outside `.observe`, or an invalid canonical audit fail.
Promptfoo's Boolean/0–1 score is only this conservative gate; the five states remain
in its raw output and assertion reason. A deterministic test runs the actual pinned
CLI with all five statuses and proves that only explicit pass succeeds.
The wrapper checks exported success/failure/error counts after the CLI exits.

## CI and limits

`CI` always starts the pilot job and includes it in `Required CI`; there is no outer
path filter that can leave a required status pending. The job has read-only contents
access, does not persist checkout credentials, and receives no model secrets. It runs
unit/CLI contract tests, selects suites, and **when audit is selected** requires a
fresh passing local attestation bound to all current pilot/runner/config/skill/fixture
inputs. Changing the grader/config/runner invalidates old proof. The attestation is
an author-supplied local claim verified for completeness and freshness, not an
independent CI model execution or a cryptographic signature from a trusted evaluator.

This repository currently has no model secret in Actions, so paid/model execution
remains local with an existing login. No new secret, environment, permission or
privileged workflow is introduced. A future trusted credential-backed runner would
be separate work. Repository maintainers should continue requiring `Required CI`
in branch rules; this pilot does not change repository settings.

The live run proves the custom-provider → Python adapter → existing Codex CLI →
read-only judge → Promptfoo assertion path. It does not test Promptfoo's Codex SDK
provider or built-in heuristic `skill-used` assertion, broad model quality, runtime
telemetry, manual rating behavior, or other skills/fixtures. Requested model names are
recorded; resolved server model identity and billing cost may be absent from CLI output.
A forcibly interrupted or outer-timeout run can leave child processes; its partial directory
must not be treated as stable proof. The completeness gate rejects such runs.

Design references: [custom providers](https://www.promptfoo.dev/docs/providers/custom-api/),
[JavaScript assertion results](https://www.promptfoo.dev/docs/configuration/expected-outputs/javascript/),
[GitHub integration](https://www.promptfoo.dev/docs/integrations/github-action/).
