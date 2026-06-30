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
# Or: --target=claude-code / --target=cursor
```

Restart the agent after installation, then invoke the skill using that agent's
syntax:

| Agent | Invocation |
|---|---|
| Codex | `$otel-verify` |
| Claude Code | `/otel-verify` |
| Cursor | `/otel-verify` |

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

When present, verification reads:

- `.observe/otel.md` for the audit baseline and acceptance scenarios.
- `.observe/otel-instrumentation.md` for added or modified signals and prior
  validation results.

It writes `.observe/otel-verify.md`. The canonical ownership and schema for all
`.observe` reports remain in the
[report flow contract](../skills/references/report-flow-contract.md#verification-report-contract);
this guide does not repeat that full contract.

After an automatic verification run, `.observe/otel-instrumentation.md` records
the verification result and report path. `$splunk-configure` can then use the
`Working` metric rows in `.observe/otel-verify.md` as detector-generation
evidence instead of treating source presence as runtime proof.

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

Start with `Result` and `Bottom line`, then read these sections in order:

1. `What Changed` summarizes the telemetry or runtime behavior under test.
2. `Tested And Working` contains one row per exact added or modified OTel item,
   how it was tested, and the direct evidence.
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
| `Not run` | Verification was explicitly skipped. |

Within `Tested And Working`, `Working` requires direct evidence. `Not working`
means an executed check failed; `Not proven` means the scenario could not run;
`Not configured` means the requested signal or exporter does not exist.

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
[`skills/otel-verify/SKILL.md`](../skills/otel-verify/SKILL.md).
