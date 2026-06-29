# OTel Report Flow Contract

Use this reference whenever `$otel-audit`, `$otel-instrument`, `$otel-verify`,
or `$splunk-configure` writes files under `.observe/`.

## Document Ownership

Each document has one job. Do not mix these responsibilities.

| Document | Owner skill | Purpose | Must not contain |
|---|---|---|---|
| `.observe/otel.md` | `$otel-audit` | Source-derived audit, current instrumentation inventory, gaps, GenAI readiness, and verification plan | Implementation changelog or executed verification proof |
| `.observe/otel-instrumentation.md` | `$otel-instrument` | Implementation ledger: code changes, added/modified/removed signals, validation gates, verification and detector handoff | Baseline audit rewrite, source-only route inventory unless needed for changed paths |
| `.observe/otel-verify.md` | `$otel-verify` | Runtime/app-code proof: compile/import viability, tests/harnesses, OTLP/Explorer visibility, path coverage, verified/unverified signals | Unproven implementation claims |
| `.observe/detectors.md` | `$splunk-configure` | Human-readable detector plan: generated detectors, covered metrics, skipped metrics, prerequisites | Secrets, unverified detector claims |
| `.observe/splunk-configure-verify.md` | `$splunk-configure` | Detector output validation: Terraform syntax, SignalFlow shape, coverage, safety checks | Live apply results unless explicitly requested |

## Reader-First Report Order

Users read these reports to understand status and next action quickly. Put the
most important information first.

Unless a document-specific contract below defines a stricter reader order,
every `.observe/` report should start with:

1. Title with service name.
2. `**Result:**` or `**Status:**` using `Pass`, `Partial`, `Fail`, `Blocked`,
   or `Not run`.
3. `## Executive Summary` with 3-7 bullets:
   - what was found or changed
   - what is proven
   - what remains unproven or blocked
   - the next action
4. `## Flow` when more than one skill/document is involved:
   `audit -> instrument -> verify -> configure -> configure-verify`
5. `## Audit Evidence` for audits, or `## Commands Run` for execution reports.
6. The shortest user-facing view of the system or change.
7. For audits, the current instrumentation baseline followed by actionable
   gaps; for execution reports, unproven work before diagnostics.

The verification report uses the question-led section order in
`## Verification Report Contract` instead of a separate executive-summary
section.

Keep detailed tables, source paths, command logs, and raw evidence after the
summary so readers can follow the flow without hunting through long matrices.

## Status Rules

- Use `Pass` only when every in-scope row has proof.
- Use `Partial` when meaningful work passed but any in-scope signal/path is
  unverified, source-only, not run, or blocked.
- Use `Fail` when an executed scenario violates expected telemetry or an
  instrumentation-introduced compile/import/test failure remains.
- Use `Blocked` when no meaningful proof can run because a concrete prerequisite
  is missing.
- Never call source definitions "verified" without command output, test
  assertion, harness evidence, collector evidence, or static proof explicitly
  allowed by the skill.

## Audit Contract

Audit is read-only and baseline-oriented:

- Write `.observe/otel.md`.
- Declare `**GenAI ownership detected:** Yes` or `No` from source evidence and
  include a matching `GenAI ownership` row in `## Audit Evidence`.
- Include `Current Instrumentation`, `GenAI Readiness` when relevant, `Gaps`,
  and `Verification Plan`.
- Use only the top-level sections in the reader order below.
- Do not run verification harnesses or claim runtime proof.

Use this reader order after the common title, status, summary, and flow:

1. `## Audit Evidence`
2. `## Routes` when routes exist
3. `## Signal Flow`
4. `## Current Instrumentation`
5. `## GenAI Readiness` when relevant
6. `## Gaps`
7. `## Verification Plan`
8. `## Anti-Patterns`
9. `## Recommendation`

`## Audit Evidence` is a compact source ledger, not a prose list:

```markdown
| Check | Finding | Source |
|---|---|---|
| Manifest | <language/framework/dependency finding> | <path> |
| Entry point | <process finding> | <path> |
| Route source | <route finding> | <path(s)> |
| Runtime/startup | <runtime finding> | <path(s) or none detected> |
| GenAI ownership | <Yes or No, matching the report declaration> | <owned source paths or repository scan evidence> |
```

`GenAI ownership detected: Yes` requires `## GenAI Readiness` after
`## Current Instrumentation`. `No` forbids that section. This explicit decision
keeps report validation deterministic; do not infer the section from loose
keywords in prose.

`## Signal Flow` contains one compact `### Component Flow Map`. Show only
major components and telemetry-distinct edges; do not duplicate every route or
scenario. Separate independent process roots. Use these exact evidence markers:

- `[SOURCE-COVERED]`: source or configuration supports the edge; runtime
  emission is not proven.
- `[GAP: <human-readable area>]`: the edge has an instrumentation, safety, or
  proof gap described in `## Gaps`.

Use only `[SOURCE-COVERED]` and `[GAP: <area>]` in the component map. The map is
the compact reader view and `Verification Plan` is the detailed downstream
handoff.

Put `## Current Instrumentation` immediately after the flow map so readers see
what exists before they evaluate deficiencies. When present, put
`## GenAI Readiness` next because it is specialized current-state context. Put
the prioritized `## Gaps` table after that baseline and before
`## Verification Plan`. The executive summary remains responsible for keeping
the most important gaps visible on the first screen.

`## Verification Plan` has two non-overlapping parts:

1. `### Test Environments` defines reusable runtime, toolchain, scope, and
   prerequisite profiles. Each row has a stable `Environment ID`.
2. `### Acceptance Scenarios` defines the exact action, expected telemetry,
   proof level, and acceptance criteria. Its `Environment` cell contains only
   one or more IDs from `Test Environments`.

Do not repeat fixture or prerequisite prose in every scenario. Add or refine a
test-environment row and reference its ID instead. Use these headings for every
audit report and downstream handoff.

Keep exactly one top-level `## Gaps` section and use this prioritized table:

```markdown
| Priority | Area | Gap | Why it matters | Required fix | Instrument mode | Verification scenarios |
|---|---|---|---|---|---|---|
| required | <human-readable area> | <source-derived gap> | <user/operator impact> | <specific result> | default | <scenario IDs or N/A> |
```

Allowed priority values are `required`, `recommended`, and `deferred`:

- `required`: baseline correctness, trace continuity, error attribution,
  exporter/resource identity, cardinality safety, or duplicate-signal issues.
- `recommended`: deeper diagnostics, business metrics, or opt-in OTLP logs
  whose cost/privacy tradeoff is not already approved.
- `deferred`: work requiring a user/product decision, external owner,
  credentials, infrastructure, or an unsafe/oversized change.

Allowed instrument modes are `default`, `fix all`, and `manual decision`.
Use `default` for safe app-owned required work and required verification,
`fix all` for safe recommended work, and `manual decision` for deferred or
externally owned work. A required gap may use `manual decision` when it cannot
be repaired safely without an explicit choice. If no gaps exist, keep the table
header and write `No gaps found.` below it. Group rows by remediation theme;
do not repeat every route or flow edge.

## Instrumentation Contract

Instrumentation is a goal workflow, not just a code edit:

1. Read `.observe/otel.md` when present.
2. Parse its prioritized `## Gaps` table and reconcile it with current source.
3. Implement scoped instrumentation.
4. Run project-runtime compile/import and focused tests.
5. Write `.observe/otel-instrumentation.md`.
6. Invoke or apply the `$otel-verify` workflow unless the user explicitly opts
   out or a concrete prerequisite blocks it.
7. If verified metric evidence exists and the user requested alerting/detectors,
   invoke or apply `$splunk-configure`.

For a normal instrumentation run, address every safe app-owned `required` row
whose instrument mode is `default`. When the user asks to fix all gaps, also
address safe `recommended` rows whose mode is `fix all`. Never silently
implement `manual decision` rows; record the owner, prerequisite, or decision
needed. An explicit narrower user scope takes precedence, but untouched audit
rows must remain visible.

The instrumentation report must reconcile every consumed audit row under
`## Audit Gap Closure`:

```markdown
| Priority | Gap | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|---|
```

Use `Working`, `Not working`, `Not proven`, `Not configured`, or `Deferred` for
the final result. `Working` requires the source change or proven existing
implementation, the applicable local validation gate, and `$otel-verify` proof
at the audit row's required proof level. A shared helper test does not close
untested named call sites or routes.

The instrumentation report must include:

```markdown
# OTel Instrumentation Report: <service>

**Result:** Pass | Partial | Fail | Blocked
**Source audit:** `.observe/otel.md` | not found
**Verification report:** `.observe/otel-verify.md` | not run
**Detector report:** `.observe/detectors.md` | not requested | blocked

## Executive Summary
## Flow
## Files Changed
## Signals Changed
## Audit Gap Closure
<!-- Include the next section only when GenAI ownership is Yes. -->
## GenAI Readiness Closure
## Validation Gates
## Verification Handoff / Results
## Detector Handoff / Results
## Remaining Gaps
## Next Steps
```

`Signals Changed` is the instrumentation report's implementation-change
inventory and belongs only in `.observe/otel-instrumentation.md`.

Include `## GenAI Readiness Closure` only when the source audit declares
`GenAI ownership detected: Yes`. Put it after `## Audit Gap Closure` and use
one row for every source-audit readiness surface:

```markdown
| Surface | Required signals | Implemented / proven | Tests | Remaining signals | Result |
|---|---|---|---|---|---|
```

Use `Working`, `Partial`, `Not working`, `Not proven`, `Not configured`,
`Deferred`, or `Owner-mapped`. `Working` requires `Remaining signals` to be
`None`; every other result must name what remains or the exact owner/blocker.
The report-level `Result` cannot be `Pass` while any audit-gap closure is
`Not working`, `Not proven`, or `Not configured`, or while any GenAI readiness
surface is `Partial`, `Not working`, `Not proven`, or `Not configured`.
`Deferred` and `Owner-mapped` are allowed in a Pass only when their external
owner or explicit scope decision is fully recorded.

## Verification Report Contract

Verification reads both audit and instrumentation reports:

- Audit source: `.observe/otel.md`
- Implementation source: `.observe/otel-instrumentation.md`
- Output: `.observe/otel-verify.md`

Write verification reports for a reader deciding whether the instrumentation
works. The first screen must answer, in this order:

1. What was added or modified?
2. Was each change tested?
3. Is it working?
4. What is the proof?
5. If anything is not working or not proven, why and what is needed next?

Use these sections before any diagnostic detail:

```markdown
## What Changed
## Tested And Working
## Not Working Or Not Proven
## Proof
```

Under `## Tested And Working`, include one authoritative table that lets the
reader evaluate every individual added or modified OTel item without joining
information from other sections:

```markdown
**Individual result:** <working>/<total> working: <counts by signal type>.

| OTel item | Type | Added or modified | Working status | How it was tested | Evidence |
|---|---|---|---|---|---|
```

Use one row per exact route/server span, custom span call site, metric, log
pipeline/category, and runtime/exporter behavior. If multiple modified call
sites emit the same span name, keep separate rows and identify the call site.
Use only `Working`, `Not working`, `Not proven`, or `Not configured` for status.
Do not group rows merely to make the report or final command response shorter.
Every `Working` row must name the test mode and direct evidence.

Keep `Not working` distinct from `Not proven`: use `Not working` only when an
executed check failed or expected telemetry was absent. Use `Not proven` when
the necessary scenario was not run or a prerequisite was unavailable.
Use `Not configured` when a requested signal has no implementation or runtime
configuration. In particular, MDC or trace-context fields in stdout do not
mean OTLP log export is configured.

Do not put command inventories, runtime resolution, build-gate matrices, path
coverage matrices, signal inventories, or trace IDs before these sections.
Consolidate repeated evidence. Put commands and per-path diagnostics in
`## Technical Details` only when they help reproduce a result or explain a
gap.

## Splunk Configure Contract

Detector generation should be proof-aware:

- Read `.observe/otel.md` for service metadata, gaps, GenAI readiness, and
  candidate metrics.
- Read `.observe/otel-instrumentation.md` for implemented signal changes.
- Read `.observe/otel-verify.md` for verified emitted metrics and OTLP proof.
- Generate Terraform only for metrics that are present in source and either
  verified or explicitly accepted as source-only by the user.
- Put missing or unverified detector inputs in
  `GenAI Instrumentation Prerequisites`, `Instrumentation Prerequisites`, or
  `Skipped Metrics`; do not invent detectors for absent metrics.
- Always write `.observe/splunk-configure-verify.md`.

## Splunk Configure Verification

After generating Terraform, run local validation when tools are available:

1. Confirm generated files exist:
   - `.observe/terraform/detectors.tf`
   - `.observe/terraform/variables.tf`
   - `.observe/terraform/terraform.tfvars.example`
   - `.observe/terraform/.gitignore`
   - `.observe/detectors.md`
2. Run `terraform fmt -check -recursive .observe/terraform` when Terraform is
   installed.
3. Run `terraform -chdir=.observe/terraform init -backend=false -input=false`
   and `terraform -chdir=.observe/terraform validate -json` when Terraform is
   installed; retain `.terraform.lock.hcl` and record warnings separately.
4. Validate SignalFlow shape without contacting Splunk:
   - generated metric names exist in audit/instrumentation/verify evidence
   - every detector filters by `service.name`
   - threshold variables are declared
   - rule `detect_label` values match published detect labels
   - no user/session/request/trace IDs, raw prompts, raw content, or secrets
     appear in filters, group-bys, or example variables
5. When approved detector-capable credentials are already available, run
   `terraform -chdir=.observe/terraform plan -refresh=false -input=false` to
   compile every detector through Splunk `/v2/detector/validate`. Do not apply.
6. `Pass` requires local validation plus the authenticated plan. If local
   checks pass but credentials are unavailable, use `Partial` and identify
   remote SignalFlow compilation as unproven.
7. `.observe/detectors.md` must inherit the exact result from
   `.observe/splunk-configure-verify.md` so the plan and proof reports cannot
   disagree.

The verification report shape:

```markdown
# Splunk Configure Verification: <service>

**Result:** Pass | Partial | Fail | Blocked
**Source:** `.observe/detectors.md`
**Terraform:** `.observe/terraform/`

## Executive Summary
## What Was Added
## Tested And Working
## Not Yet Proven
## Validation Notes
## Next Steps
```
