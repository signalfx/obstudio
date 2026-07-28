# OTel Verify

`otel-verify` proves whether existing OpenTelemetry instrumentation works. It
uses the project's configured runtime, executes application code where
possible, checks each declared signal and path, and can capture local OTLP or
Obstudio evidence. It does not add instrumentation or silently repair
application code.

## Install And Invoke

The Obstudio installer includes `otel-verify` for every supported agent:

```bash
./obstudio install --target=codex
# Or: --target=claude-code / --target=cursor / --target=kiro
```

After installation, restart the agent if it does not discover the new skill.
Then invoke it using that agent's syntax:

| Agent | Invocation |
|---|---|
| Codex | `$otel-verify` |
| Claude Code | `/otel-verify` |
| Cursor | `/otel-verify` |
| Kiro | `/otel-verify` |

Natural-language requests also select the skill, for example:

```text
verify this service's OpenTelemetry instrumentation
```

`otel-instrument` invokes the verification workflow by default after its
implementation gate. It may omit verification only when the user explicitly
opts out or a concrete prerequisite blocks execution. In the blocked case, the
instrumentation report must name the exact unavailable runtime, listener,
dependency, credential, or fixture.

Run `otel-verify` directly when you want to recheck existing instrumentation,
refresh verification after runtime or dependency changes, or prove telemetry
without making application-code changes.

## Inputs And Output

Verification reads:

- `.observe/otel-audit.json` for the canonical audit baseline and acceptance
  scenarios.
- `.observe/otel-selection.json` for explicitly requested finding IDs and dependency-
  complete verification scope.
- `.observe/otel-instrumentation.json` for canonical added, modified, or removed
  signals, finding closure, and prior validation results.

With a validated canonical audit and selection, it writes `.observe/otel-verify.json`
and retains `.observe/otel-verify.md` as the human-readable report. The canonical
ownership and schema for all `.observe` reports remain in the
[report flow contract](https://github.com/signalfx/obstudio/blob/main/skills/references/report-flow-contract.md#verification-report-contract);
this guide does not repeat that full contract.

When canonical audit JSON is not present, run `$otel-audit` first. Verification
does not infer scope or identity from generated Markdown reports.

After an automatic verification run, `.observe/otel-verify.json` owns the
canonical verification result and is cryptographically bound to the exact
normalized instrumentation overlay. `.observe/otel.html` remains the audit and
approval surface. The workflow refreshes `.observe/otel-instrumentation.html`
with implementation impact and verification proof instead of mixing downstream
state into the audit. Until `$splunk-configure` moves to canonical verification
JSON in the follow-up workflow, it continues to use `Working` metric rows in
`.observe/otel-verify.md` as detector-generation evidence.

## What Verification Proves

Verification starts with the repository's configured runtime rather than a
convenient global toolchain. It then gathers the strongest safe evidence
available:

1. Build, type, syntax, or import viability for changed instrumentation.
2. Application-code tests or focused harnesses for each span, metric, log, and
   telemetry-distinct path.
3. Span attributes, error behavior, parentage, metric units and dimensions,
   log correlation and redaction, and exporter/resource configuration.
4. A real local runtime when a claim depends on automatic startup, route
   resolution, request-duration metrics, duplicate server-span prevention, or
   runtime-installed log export.
5. OTLP and Telemetry Explorer visibility when a local receiver is available.

Source code alone is not proof that a signal works. Generated SDK-only
telemetry may prove an export contract, but it does not prove that application
code emits the signal.

## Read The Report

Open the returned loopback `otel-instrumentation.html` link for the combined
change, impact, and proof view, the returned loopback `otel.html` link for the
original audit and approval context, or the local-file
`.observe/otel-verify.md` link for verification detail. The workflow starts or
reuses a restricted `127.0.0.1` report server but does not open either HTML
page automatically. Start with `Result` and `Bottom line`, then read these
sections in order:

1. `What Changed` summarizes the telemetry or runtime behavior under test.
2. `Tested And Working` contains one row per exact added, modified, or removed
   OTel item, how it was tested, and the direct evidence.
3. `Not Working Or Not Proven` names failed, blocked, or unconfigured items and
   the next action required.
4. `Proof` explains the strength of the evidence, such as an application test,
   focused harness, actual runtime, or OTLP query.
5. `Technical Details` records commands and diagnostics needed to reproduce a
   result or investigate a gap.

Interpret the report-level result as follows:

| Result | Meaning |
|---|---|
| `Pass` | Every in-scope signal and path has direct evidence. |
| `Partial` | Some evidence passed, but at least one item is blocked, unconfigured, or not proven. |
| `Fail` | An executed check failed, expected telemetry was absent or invalid, or instrumentation changes broke source viability. |
| `Blocked` | No meaningful proof could run because a concrete prerequisite is unavailable. |
| `Not run` | Verification was explicitly skipped. |

Within `Tested And Working`, `Working` requires direct evidence. `Not working`
means an executed check failed; `Not proven` means the scenario was not run or
a prerequisite was unavailable; `Not configured` means the requested signal
or exporter does not exist.

## Boundaries

- Verification is read-only for application code unless the user explicitly
  asks to add or repair tests.
- Instrumentation-introduced failures return to `otel-instrument` for repair.
- Live provider credentials are not required when deterministic fakes can
  prove the same behavior.
- Explorer visibility is claimed only when the source process stays alive
  through the OTLP queries and direct evidence is captured.
- A representative happy path does not prove error, timeout, streaming,
  startup, shutdown, or other telemetry-distinct paths.

For the complete agent workflow, see
[`skills/otel-verify/SKILL.md`](https://github.com/signalfx/obstudio/blob/main/skills/otel-verify/SKILL.md).
