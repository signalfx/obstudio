# Direct Verification Scope

Load this reference only when no canonical `.observe/otel-audit.json` exists.
It owns the direct-user and Markdown-fallback verification scope. Never combine
this path with canonical audit, selection, instrumentation, or verification
JSON overlays.

## Scope Sources

Use a direct concrete user request as scope. Otherwise read
`.observe/otel-instrumentation.md` when present. Extract changed signals, prior
gates, and every signal-affecting path. Reconcile every command, runtime,
source path, and expected signal with current source before execution. Never
read `.observe/otel.md`; it is not part of the current workflow.

Do not fabricate audit IDs, selection state, instrumentation JSON, or verify
JSON. If a canonical audit exists but its bound instrumentation JSON is absent,
use the canonical selection only for a clearly incomplete read-only check and
route the missing machine handoff to `$otel-instrument`; do not fall back here.

## Conservative Closure

Close every source-detected provider, exporter, custom span, metric, log path,
and runtime/config capability in direct scope. Include:

- endpoint configurability and an effective stable `service.name`;
- bounded span names and dimensions, including cardinality/privacy defects;
- provider and exporter reachability from the target process;
- force-flush and shutdown paths; and
- every route, workflow, job, stream, tool, and error outcome whose telemetry
  differs.

Give each source-proven absent capability its own inventory and reader row with
`Not configured`. A name or dimension that embeds request, user, tenant,
session, or identifier data is a cardinality defect even when emission remains
`Not proven`. Source presence alone is never runtime proof.

Write each row's exact `OTel item` label to
`.observe/tmp/otel-verify-expected-items.txt`. A grouped provider or signal row
must not absorb a distinct capability, signal, or call site. Use that file only
with the reader validator's `--expected-items-file` option.

## Direct Result

Use the same viability, scenario, item-proof, and result semantics as the main
skill. Generated SDK contracts remain contract-only. Mark a declared but
unresolved dependency `Blocked`, not `Source only`. Mark an absent requested
bridge/exporter `Not configured`, not `Not proven`.

At the artifact boundary load `verification-report.md`. It owns the Markdown
shape, validation, and standalone response. Run no canonical flow validator or
HTML renderer on this path.
