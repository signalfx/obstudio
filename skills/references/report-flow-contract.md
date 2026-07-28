# OTel Report Flow Contract

Use this reference whenever `$otel-audit`, `$otel-instrument`, `$otel-verify`,
or `$splunk-configure` writes files under `.observe/`.

## Canonical Artifact Chain

Use one canonical audit plus small, validated overlays:

`$otel-audit` -> `.observe/otel-audit.json` -> human scope planning in
`.observe/otel.html` -> optional `.observe/otel-audit.selected.json` ->
`.observe/otel-selection.json` ->
`.observe/otel-instrumentation.json` -> `.observe/otel-instrumentation.html` ->
`.observe/otel-verify.json` -> refreshed `.observe/otel-instrumentation.html`

Apply these precedence and identity rules throughout the chain:

- `.observe/otel-audit.json` is the canonical audit. Its normalized audit digest
  excludes top-level `review_selection`, so a separately saved selected-audit
  copy can carry reviewer scope without changing source-derived audit identity.
  Do not mutate the canonical audit to record selection, implementation, or
  verification state.
- `.observe/otel-selection.json`, `.observe/otel-instrumentation.json`, and
  `.observe/otel-verify.json` are the authoritative overlays for their stages.
  Each overlay must match the canonical audit's `meta.audit_id` through
  `audit_id` and the validator-computed SHA-256 digest of the canonical field
  representation through `audit_sha256`.
- `.observe/otel-instrumentation.json` must also match the validator-computed
  digest of the exact normalized selection through `selection_sha256`. That
  digest includes `requested_ids`, dependency-closed `approved_ids`, stable
  `decision_answers`, and approval metadata. Changing an answer invalidates
  older instrumentation even when the executable finding IDs do not change.
  Verification remains transitively bound to that exact selection because its
  `instrumentation_sha256` covers the complete normalized instrumentation
  overlay, including `selection_sha256`.
- `.observe/otel.html` is the self-contained human review and plan-building surface.
  It renders the canonical audit and generates the exact `$otel-instrument`
  command for the reviewer-selected scope; it is not a second source of
  source-derived audit truth. It must not render instrumentation or
  verification overlays.
- `.observe/otel-instrumentation.html` is the generated human change, impact,
  and proof surface. `$otel-instrument` creates it from the bound audit,
  selection, and instrumentation overlay; `$otel-verify` refreshes it with the
  verification overlay. It never replaces or rewrites the audit view.
- Instrumentation and verification Markdown reports are generated, readable
  technical outputs. They never override JSON. If JSON and Markdown disagree,
  fail or regenerate the Markdown; never merge the conflicting state.
- Only executable `default`/`fix all` finding IDs in the dependency-closed
  `approved_ids` of `.observe/otel-selection.json` may flow into instrumentation
  and verification. `manual decision` and `external follow-up` findings remain
  audit state and are never selection IDs. A manual answer is stored separately
  in `decision_answers`; it can unlock only the executable IDs listed by that
  authored option and never selects them automatically. Preserve canonical
  audit order and
  require instrumentation and verification overlays to reconcile exactly that
  executable set.

## Document Ownership

Each document has one job. Do not mix these responsibilities.

| Document | Owner skill | Purpose | Must not contain |
|---|---|---|---|
| `.observe/otel-audit.json` | `$otel-audit` | Canonical source-derived audit with stable finding/scenario IDs and dependency edges | Reviewer selection, implementation state, or verification state |
| `.observe/otel-audit.selected.json` | Human scope-planning flow | Optional saved copy of the canonical audit carrying top-level `review_selection`; the selection is excluded from the normalized audit digest | A different audit baseline, implementation state, or verification state |
| `.observe/otel.html` | `$otel-audit` renderer + human reviewer | Interactive review of the canonical audit and saved `review_selection` export | Instrumentation or verification overlays |
| `.observe/otel-instrumentation.html` | `$otel-instrument` renderer, refreshed by `$otel-verify` | Concise verification status followed by every selected finding's change, observability impact, item proof, and coverage | Aggregate technical ledgers, audit selection controls, unbound overlays, or an independently rewritten baseline |
| `.observe/otel-selection.json` | Human scope-planning flow | Authoritative manual `decision_answers` plus requested and dependency-closed executable finding IDs (stored in the compatibility field `approved_ids`) | Manual/external finding IDs in `requested_ids` or `approved_ids`, executable work not unlocked by its recorded answer, findings absent from the audit, or silently inferred selection |
| `.observe/otel-instrumentation.json` | `$otel-instrument` | Authoritative implementation result for every dependency-closed selected finding ID (`approved_ids`), bound to the exact normalized selection by `selection_sha256` | Unselected findings, stale decision answers, or a rewritten audit baseline |
| `.observe/otel-verify.json` | `$otel-verify` | Authoritative scenario proof for every dependency-closed selected finding ID (`approved_ids`), bound to the exact normalized instrumentation overlay by `instrumentation_sha256` | Unselected findings, stale/unbound instrumentation proof, or unsupported `working` claims |
| `.observe/otel-instrumentation.md` | `$otel-instrument` | Generated readable compatibility view of the instrumentation overlay | State that differs from `.observe/otel-instrumentation.json` |
| `.observe/otel-verify.md` | `$otel-verify` | Generated readable compatibility view of the verification overlay | State that differs from `.observe/otel-verify.json` |
| `.observe/detectors.md` | `$splunk-configure` | Human-readable detector plan: generated detectors, covered metrics, skipped metrics, prerequisites | Secrets, unverified detector claims |
| `.observe/splunk-configure-verify.md` | `$splunk-configure` | Detector output validation: Terraform syntax, SignalFlow shape, coverage, safety checks | Live apply results unless explicitly requested |

## Human HTML Usage Flow

Use the two HTML reports for different moments in the workflow:

1. Open `.observe/otel.html` after `$otel-audit` to understand the source-derived
   findings, answer any manual decision controls, select executable findings,
   and copy the exact `$otel-instrument` command. Treat this HTML as the
   audit and scope-planning surface. It is not proof that code changed, telemetry
   emitted, or Splunk Observability Cloud saw data.
2. Run `$otel-instrument` with the copied command. When the user asks for
   instrumentation without a saved selection, `$otel-instrument` may select all
   executable findings only after validating the canonical audit and prompting
   for unresolved manual decisions.
3. Open `.observe/otel-instrumentation.html` after `$otel-instrument` to review
   what selected issues changed, how each change improves observability, what
   telemetry proof exists, and what remains incomplete or blocked. Treat this
   HTML as the change-impact and verification-status surface, not as a place to
   change audit scope.
4. If scope is wrong, return to `.observe/otel.html`, change the selection, save
   or copy a new command, and rerun `$otel-instrument`. If proof is incomplete,
   fix the named runtime/code/product prerequisite and rerun instrumentation or
   verification through the bound JSON overlays; do not edit generated HTML.

Serve both generated HTML reports from the same restricted loopback report
server through an unguessable tokenized URL path and return their
`http://127.0.0.1:<port>/<token>/...` links after instrumentation and
verification.
Version the reusable server state so a prior bundle without the required
report allowlist cannot be reused. Do not open the links automatically. Keep
Markdown and JSON artifacts as absolute local-file links; only generated HTML
uses browser-safe loopback links. Keep the server allowlist limited to
`otel.html`, `otel-instrumentation.html`, and `otel-audit.json`; do not expose
instrumentation, verification, or repository source JSON/files. Transfer the
unguessable token through user-private state rather than process arguments,
serialize concurrent server launches, and expire an idle detached server.
When HTTP cannot open repository-relative source citations safely, render them
as copyable path text instead of dead browser links.

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
   `audit -> select -> instrument -> verify`
5. `## Audit Evidence` for audits, or `## Commands Run` for execution reports.
6. The shortest user-facing view of the system or change.
7. For audits, the current instrumentation baseline followed by actionable
   gaps; for execution reports, unproven work before diagnostics.

The verification report uses the question-led section order in
`## Verification Report Contract` instead of a separate executive-summary
section.

Keep detailed tables, source paths, command logs, and raw evidence after the
summary so readers can follow the flow without hunting through long matrices.

For an audit, the HTML first screen is a decision view. Show one concise
current-baseline sentence, then exactly one findings list ordered by
machine-readable priority: `required`, `recommended`, and `deferred`, preserving
canonical order within a priority. Priority defines ordering only. Render
manual decisions and external requirements only inside the relevant finding.
Keep quick-win, effort, severity, priority, and execution-state information
machine-readable in canonical JSON. Do
not surface
canonical `meta.status` as a human outcome; it classifies the machine report and
does not claim runtime proof. Keep finding-specific missing proof in that
finding's nested `Technical details`; reserve the report-level `Technical
appendix` for cross-finding current-state evidence, the shared verification
plan, and audit notes. Do not repeat the same runtime disclaimer in every
decision summary. Lead each finding card with its human title or area and one
concise expected monitoring outcome, with the stable `OTEL-###` ID shown only
as a secondary cross-report reference. Do not replace stable IDs with
display-order aliases such as `gap-1`.
Treat `default` as safe required/default work and `fix all` as safe broader
opt-in work, but use the same neutral `Select` checkbox for both without an
`optional` tag. Manual decision and external follow-up findings remain
non-executable when they gate concrete service-owned OTel work. Do not create
manual or external findings just to record product/runtime choices, billing,
cost, safety policy, content-governance, or external business context; keep that
material in readiness/context rows unless it blocks an in-scope service-owned
OTel finding. A manual finding has no selection checkbox
and can never enter either selection ID list; instead, render its two or three
authored `decision_options` as an accessible one-of answer control. External
findings remain non-interactive and cannot enter selection JSON. An unanswered
manual dependency is blocked. Once answered, only executable findings listed
in that option's `unlocks` become selectable; nonmatching branches remain
blocked, and the answer does not auto-select matching work.
A manual decision has no checkbox and its finding ID cannot enter
`requested_ids` or `approved_ids`; `decision_answers` separately persists the
stable `finding_id`/`option_id` pair.
For mutually exclusive choices, keep product/runtime branch decisions in
readiness context unless that domain is explicitly in scope. When multiple
options each produce real service-owned OTel work, create one option-locked
executable finding per real branch and put each finding ID only in the matching
option's `unlocks`. Do not use one shared executable finding for multiple
exclusive options, and do not make two branch implementations appear as
simultaneous independent audit gaps before the user answers.

Keep each primary finding disclosure button separate from its selection checkbox. Give
every checkbox a unique accessible name, bind that disclosure to its body with
`aria-controls`, and hide decorative carets from assistive technology. Put the
cards under a compact `Findings · N` heading immediately after the decision
view, except that a schema-v2 `Blocked` audit must first show its structured
scan-incomplete panel. Each card has one title, one expected monitoring
outcome, the relevant decision/select control, and the stable `OTEL-###` ID as
a secondary cross-report reference. Priority is expressed only by list order,
and lifecycle is reflected by the checkbox, next-step copy, saved selection
state, and machine overlays. Keep severity in canonical JSON for machine
compatibility.

Do not render the canonical component flow as a service map, connection list,
component-coverage groups, linked-area counts, or raw flow text in audit HTML.
Those views repeat findings without adding a scope decision or runtime
proof. Keep the canonical flow in JSON for tooling. Do not render a duplicate
all-findings decision table. Each
finding card must show one `product_outcome` sentence answering what the owner
should see or gain after implementation and verification. After the card
header and selection or decision control, keep the expanded narrative
decision-sized. Its four first-level fields are `Gap`, `Why it
matters`, a mode-aware required action, and `Next step`: label the action
`Instrumentation change` for executable work, `Decision needed` for a manual
prerequisite, and `External requirement` for an external prerequisite. For a
currently selectable, unselected executable finding, the next step is `Select`
-> copy the generated command -> `$otel-instrument`. Keep the copy synchronized
with selection state: explicitly selected work proceeds to the command, an auto-added
dependency explains why it is included, and blocked executable work names its blocking `OTEL-###`
IDs and directs the reviewer to resolve them first. Do not label verification,
explorer, dashboard, or detector follow-up as the immediate next step.

Show a compact telemetry shape on the card from exact
`expected_telemetry[*].type` counts, including configuration and resource
items. When a finding has dependencies, show their stable IDs as a selection
effect; `Next step` distinguishes blocked work from executable dependency
closure. Do not infer a material-safety badge from free-text
constraints, severity, or priority. The current schema does not classify that
judgment, and a badge on every constrained finding would add noise.

Put exact expected telemetry, evidence, acceptance criteria, and authored
constraints behind one collapsed `Technical details`
disclosure. Label the constraints `Implementation guardrails`. Its summary
reports acceptance-check, guardrail, and source-reference counts. Do not render
raw verification-scenario IDs, repeated full scope
classification, canonical `follow_up_actions`, resolution metadata, or a
second dependency list in the finding HTML. Those fields remain in canonical
JSON for downstream instrumentation and verification. Post-instrumentation
product actions belong in
`.observe/otel-instrumentation.html`. Keep a manual decision's question and
owner in its decision control and `Next step`; keep an external prerequisite's
owner and required telemetry in its primary action and `Next step`.

HTML remains a complete review and selection surface; links to canonical JSON
are optional alternate formats, not required reading. After a finding jump, open the target's primary disclosure,
leave its nested `Technical details` closed, and move keyboard focus to the
primary disclosure button; apply the same behavior to direct report hashes.
Reserve one collapsed report-level `Technical appendix` for
cross-finding source-visible instrumentation evidence, the shared verification
plan, authored notes, audit evidence, and recommendations. Do not render a
separate Anti-Patterns subsection in decision-focused HTML. An actionable
anti-pattern belongs in its finding card; distinct provenance notes remain in
canonical JSON without
creating a second human action ledger.

For instrumentation, `.observe/otel-instrumentation.html` is a post-change
decision view. Start with exactly one human verification-state heading and one
proof-and-delivery sentence, then enumerate every dependency-closed selected
finding exactly once in canonical audit order. For a `Partial` result with no
`not_working` finding, use **Verification incomplete — no observed failures**.
State the proven telemetry count as **X of Y telemetry changes are proven** and
state separately whether local OTLP delivery and Splunk Observability Cloud
were checked. Do not label the instrumentation stage as failed merely because
scenario coverage is incomplete, and do not infer merge readiness when the
artifacts contain no merge policy. Render zero product-visible items as **not
checked** only when no saved target-product query ran; reserve **not visible**
for an executed product check that failed to find expected telemetry. Preserve
canonical `Partial` and `not_proven` values in JSON and generated Markdown while
translating `not_proven` to **verification incomplete** in the human HTML.

Render instrumentation HTML as selected issue cards with concise sections for
what changed, how observability improves, telemetry proof, scenario coverage,
and remaining uncertainty. Preserve the complete code/config mapping, closure
rows, scenario evidence, stable IDs, commands, exact counts, and item proof in
`.observe/otel-instrumentation.json`, `.observe/otel-instrumentation.md`,
`.observe/otel-verify.json`, and `.observe/otel-verify.md`. These canonical and
technical artifacts, not the HTML, are the downstream handoff.

Do not truncate, group, or replace the selected-issue list with a thematic
executive summary. Each entry must show the human issue title with its stable
ID, whether the reviewer selected it or it was added as a dependency, every
finding-level `changes` sentence, the audit `product_outcome` under **How it
improves observability**, its telemetry shape, its current verification state,
and one concise verification summary built from the audit scenarios' human
`trigger` text. Render a **Telemetry change / What was observed / Status**
table and use **Not proven** when the bound proof overlay does not support a
working claim. State local delivery and target-product check scope once in the
report-level status sentence; do not repeat it on every finding. Do not render
generic per-finding lines such as **Target product: Not checked** or **Executed
checks: No executed check failed**. Use **Verification incomplete** on an
incomplete finding and reserve **no observed failures** for the report-level
heading. Keep named checks in one collapsed
**Coverage details** disclosure, grouped neutrally as confirmed in a running
service, passed focused checks, focused evidence obtained for an incomplete
scenario, not exercised, blocked, failed, or not configured. Only a `working`
scenario may appear as confirmed or passed; a `not_proven` scenario with useful
executed evidence must remain explicitly incomplete. Do not render a
stronger-proof group or per-finding completion checklist. Never put unexplained
`x/y` scenario, exercised-check, item-proof, delivery, or product-visibility
ratios on a finding card; keep exact counts and stable IDs in the canonical JSON
and generated Markdown proof ledgers. Show separate **Implementation** and
**Proof** badges so a recorded change is not presented as proof.

After the concise status, show the complete selected-issue list described above
without repeating component/provider candidates or appending another technical
ledger. When the selection is narrower than the audit, an optional final
unselected-scope note may point back to `.observe/otel.html`; it must not repeat
the audit findings as another instrumentation work queue.

When a selected finding is proof-first and records no telemetry item, show it
in the same selected-issue list as verification scope rather than counting it
as an application signal change; retain its audit `product_outcome` instead of
showing an empty or missing improvement.
Do not render a component/service-map-style instrumentation summary when it
duplicates the same finding across provider, exporter, registry, or runtime
candidates.

Do not expose raw trace IDs or span IDs in human-facing HTML. Reader prose says
**the generated trace** and names the relevant span or signal without its
opaque correlation identifier. Preserve exact trace IDs in canonical
verification `trace_ids`, durable evidence, and Markdown `Technical Details`
when they are needed for reproducibility; HTML may state that generated-trace
evidence was recorded without printing the identifier.

A generated HTML explanation is not runtime proof. Use product-visible wording
only when verification records `explorer_visible` with direct evidence.

The HTML selection state must preserve reviewer intent. `requested_ids` contains
only the executable IDs the reviewer explicitly selected; `approved_ids`
contains that set plus executable dependency closure in canonical audit order.
`decision_answers` is a separate canonical-audit-order list of
`{"finding_id":"OTEL-###","option_id":"stable-option-id"}` entries. It maps
each answered manual finding to one authored option. It is decision state, not executable scope: manual
IDs never enter either ID list, and choosing an answer never checks or adds the
work it unlocks. If an answer changes, remove requested and dependency-closed
IDs that the new option does not unlock before export. Preserve an authored
answer whose option unlocks no work without inventing executable IDs.
Never export the closed set
as though every dependency had been explicitly requested. Preserve
`approved_ids` as a compatibility field, but label its value in the human UI
as dependency-closed executable selection, not approval. A finding checkbox
reflects explicit intent; auto-added dependencies appear as `included` without
looking explicitly checked.

Keep the empty handoff tray both `hidden` and `inert`. When selection exists,
show only the plain selectable terminal command section. Do not render a
selection-count summary, save guidance, or a `Save selection` button. Generate the command
from current explicit `requested_ids` plus canonical `decision_answers`, for
example
`$otel-instrument --ids OTEL-001,OTEL-002 --decision OTEL-003=option-id <absolute-service-root>`.
Embed the validated absolute service root supplied during audit finalization in
the HTML payload and use it in this command when the report is served over
loopback HTTP. Keep `file://` path inference only as a compatibility fallback;
a normally finalized report must never show the literal `<service-root>`
placeholder.
Use explicit requested IDs rather than dependency-closed `approved_ids`,
because `$otel-instrument` recomputes and validates the dependency closure. If
only decision answers are recorded, state that an executable finding must be
selected before an instrumentation command exists. The cards, terminal
command, and live-region feedback must make each explicit selection,
decision answer, and auto-added dependency understandable before execution.
The terminal command is the only visible selection handoff. Keep compatibility
for trusted selected-audit copies and `.observe/otel-selection.json`, but do not
expose browser save or download controls. State that
manual/external finding IDs remain in the audit and are never exported through
`requested_ids` or `approved_ids`; `decision_answers` separately carries stable
`finding_id`/`option_id` pairs for answered manual findings. Announce answer,
dependency, and command guidance through an `aria-live="polite"`,
`aria-atomic="true"` status region. Keep the command tray usable on narrow
screens.

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

- Write and validate `.observe/otel-audit.json` first. Treat it as the immutable
  source of truth for the audit.
- Render `.observe/otel.html` from the validated JSON for human review and
  scope planning.
- Give every actionable finding and acceptance scenario a stable ID. Record
  finding dependencies so selection export can compute dependency closure.
- Give every finding one concise `product_outcome` sentence stating what the
  owner should see or gain after implementation and verification. Do not claim
  the source audit has already proven that outcome.
- Declare `**GenAI ownership detected:** Yes` or `No` from source evidence and
  include a matching `GenAI ownership` row in `## Audit Evidence`.
- Preserve `Current Instrumentation`, incident readiness, GenAI readiness, gaps,
  and verification plan in canonical JSON. The human HTML decision view renders
  actionable findings only, with readiness ledgers reserved for downstream
  tooling instead of visible peer sections.
- Use only the top-level sections in the reader order below.
- Do not run verification harnesses or claim runtime proof.

Use this reader order after the common title, status, summary, and flow:

1. `## Audit Evidence`
2. `## Routes` when routes exist
3. `## Signal Flow`
4. `## Current Instrumentation`
5. `## Gaps`
6. `## Verification Plan`
7. `## Anti-Patterns`
8. `## Recommendation`

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

`GenAI ownership detected: Yes` requires canonical `genai_readiness[]` rows.
`No` forbids those rows. This explicit decision keeps validation deterministic;
do not infer GenAI ownership from loose keywords in prose.

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

Keep current instrumentation and readiness ledgers in canonical JSON so
downstream tools can reason from the source baseline. In human HTML, put the
priority-ordered findings before technical context, and do not render readiness
ledgers as separate visible sections. The executive summary and finding cards
remain responsible for keeping the most important gaps visible on the first
screen.

When source evidence shows incident-readiness ownership, `## Current
Instrumentation` may contain one `### Incident Readiness` subsection with this
table:

```markdown
| Area | Status | Evidence | Required Signals / Gap | Detection / Localization Impact |
|---|---|---|---|---|
```

Every telemetry-scoped `partial` or `missing` row must have a prioritized
`## Gaps` row whose `Area` cell is identical and whose verification-scenario IDs
define the proof handoff. A row is telemetry-scoped only when it names concrete
service-owned OTel telemetry or configuration to add or repair; product
contracts, cost ownership, safety policy, content-governance policy, and
external business prerequisites remain readiness context unless they block an
in-scope service-owned OTel finding. This is a nested current-state view, not a
second top-level gap ledger.

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

Allowed instrument modes are `default`, `fix all`, `manual decision`, and
`external follow-up`. Use `default` for safe app-owned required work and
required verification, `fix all` for safe recommended work, and `manual
decision` for deferred or externally owned work. Use `external follow-up` for
work owned outside the service that must remain visible but cannot enter
instrumentation selection. A required gap may use `manual decision` when it
cannot be repaired safely without an explicit choice. If no gaps exist, keep
the table header and write `No gaps found.` below it. Group rows by remediation
theme; do not repeat every route or flow edge.

Canonical manual-decision findings must carry `decision_owner`,
`decision_question`, and two or three explicit selectable
`decision_options`. Each option carries a unique stable `id`, a concise
`label`, a concrete `outcome`, and an `unlocks` list of executable findings
that depend on the manual finding. An empty `unlocks` list records an answer
that intentionally produces no instrumentation work. Because the options are
mutually exclusive, their executable `unlocks` sets must be pairwise disjoint;
one executable finding cannot safely represent two different answers.
Canonical external-follow-up findings carry `external_owner` and
`external_requirement`; these fields are invalid on executable findings.

## Instrumentation Contract

Instrumentation is a goal workflow, not just a code edit:

1. Validate `.observe/otel-audit.json` together with
   `.observe/otel-selection.json` or a selected-audit copy carrying
   `review_selection`; do not infer selected scope from Markdown or prose.
   `$otel-instrument` must first run the shared `adopt-selection` helper to
   materialize trusted repository state, an explicit candidate, or—only when no
   repository selection exists—a matching saved audit into
   `.observe/otel-selection.json`, after validating the canonical audit ID and
   SHA-256 digest.
2. Reconcile only the selection overlay's dependency-closed `approved_ids` with
   current source. If no valid selection overlay exists, return to human review
   in `.observe/otel.html` instead of silently selecting work.
3. Implement the dependency-closed selected scope.
4. Run project-runtime compile/import and focused tests.
5. Write and validate `.observe/otel-instrumentation.json`, with one row per
   dependency-closed selected finding in canonical audit order and
   `selection_sha256` for the exact normalized selection, then generate
   `.observe/otel-instrumentation.md` as its readable compatibility view and
   `.observe/otel-instrumentation.html` as the human change and impact view.
6. When a bound `.observe/otel-verify.json` exists, refresh
   `.observe/otel-instrumentation.html` with its proof. Do not regenerate
   `.observe/otel.html` with downstream state.
7. If verified metric evidence exists and the user requested alerting/detectors,
   invoke or apply `$splunk-configure`.

The audit HTML may offer every executable `default` and `fix all` finding; its
machine-readable priority controls display order, not eligibility. Explicit
reviewer selection is the instrumentation scope. On a bare or broad
instrumentation request with no saved selection, deterministically select all
eligible executable findings. Never select or silently implement `manual
decision` or `external follow-up` rows. A validated `decision_answers` entry resolves only its authored
manual choice: executable rows in that option's `unlocks` may then be selected,
while every other branch stays blocked. Reject unanswered manual dependencies,
external dependencies, and executable IDs that do not match the recorded
answer rather than auto-adding a non-executable prerequisite. The exported
selection overlay, including executable dependency closure, is the final scope authority;
untouched executable audit rows and their validated prerequisites remain
visible in the immutable audit and HTML review.

When the source audit includes telemetry-scoped Incident Readiness rows,
reconcile those rows through the matching prioritized gaps and
`## Audit Gap Closure`. Preserve non-telemetry readiness context without
creating instrumentation work. Do not create a parallel incident closure section
or claim a telemetry-scoped readiness surface is working while one of its
required signals remains missing or unproven.

Telemetry Consumer Compatibility Contract:

- Before instrumentation edits, inventory existing emitted telemetry contracts
  that downstream users may consume: metric names and dimensions, span names
  and attributes, resource attributes, log fields, exporter settings, checked-in
  dashboards/detectors, entity mappings, query fixtures, and telemetry tests.
- Adding OTel semantic-convention fields is additive. Removing, renaming, or
  changing the meaning/cardinality of a consumer-visible existing field is a
  breaking telemetry consumer change unless the old field is unsafe
  high-cardinality data that must be replaced by a bounded equivalent.
- Preserve safe existing aliases by default while adding semantic fields. For
  example, emit `deployment.environment.name` without silently dropping a safe
  existing realm/resource alias that dashboards or entity mappings may use.
- Intentional removal of unsafe fields, such as raw URL `path` dimensions,
  remains a breaking consumer migration. Name the replacement, such as
  `http.route`, and the required dashboard/detector query update.
- Every affected instrumentation item must carry
  `telemetry_changes[].consumer_compatibility` with status `compatible`,
  `breaking`, or `requires_review`, the exact existing contract, the action,
  user impact, and migration steps for breaking items. The human
  instrumentation HTML must summarize the breaking count and show the
  issue-local compatibility table.

The instrumentation overlay and its Markdown compatibility report must
reconcile every dependency-closed selected audit row under
`## Audit Gap Closure`:

```markdown
| Finding | What changed | Tested | Result | Evidence / reason |
|---|---|---|---|---|
| OTEL-### — exact audit title | concrete code/config change or `No code change` | scenario IDs and test mode | Working / Not working / Not proven / Not configured | direct evidence or exact blocker |
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
**Source audit:** `.observe/otel-audit.json` | not found
**Selection:** `.observe/otel-selection.json` | not found
**Verification report:** `.observe/otel-verify.json` | not run
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
When any selected item affects an existing consumer-visible telemetry contract,
include a concise `Consumer compatibility` subsection listing the existing
contract, status (`compatible`, `breaking`, or `requires_review`), action, user
impact, and migration for breaking items.

When incident readiness applies because the user requested faster detection or
localization, incident evidence was supplied, or the source audit contains
Incident Readiness, add this nested inventory inside `## Signals Changed`:

```markdown
### Incident Readiness Signal Roles

| Surface | Exact signal | Role | Detector use / reason | Proof | Remaining owner / prerequisite |
|---|---|---|---|---|---|
```

Use exactly `MTTD-improving`, `localization-only`,
`provider/platform-owned`, or `uncovered` in `Role`. Write one row per exact
added or proven signal; do not group several metric names into one row. Use
`None` for `Exact signal` only for an owner-mapped or uncovered prerequisite.
This is the signal-role inventory, not another gap ledger or a second closure
section: every row must still reconcile through `## Audit Gap Closure` when a
source audit exists.

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

Verification reads the canonical audit and authoritative overlays:

- Audit source: `.observe/otel-audit.json`
- Selected scope: `.observe/otel-selection.json`
- Implementation source: `.observe/otel-instrumentation.json`
- Authoritative output: `.observe/otel-verify.json`
- Generated readable output: `.observe/otel-verify.md`

Validate `audit_id` and `audit_sha256` before using either input overlay, then
require instrumentation's `selection_sha256` to match the exact normalized
selection and bind verification to the exact normalized instrumentation overlay
with `instrumentation_sha256`. Because that instrumentation digest includes
`selection_sha256`, verification is transitively bound to reviewer intent. A
matching executable or item inventory is not enough: a changed decision answer
or any material instrumentation change invalidates older proof. Write
one verification finding for every dependency-closed selected ID
(`approved_ids`) in canonical audit order.

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

```markdown
**Individual result:** <working>/<total> working: <counts by signal type>.

| Item ID | OTel item | Type | Added or modified | Working status | How it was tested | Product result / visibility | Evidence |
|---|---|---|---|---|---|---|---|
```

Use one row per exact route/server span, custom span call site, metric, log
pipeline/category, and runtime/exporter behavior. If multiple modified call
sites emit the same span name, keep separate rows and identify the call site.
Use only `Working`, `Not working`, `Not proven`, or `Not configured` for status.
Do not group rows merely to make the report or final command response shorter.
`Item ID` must match the canonical telemetry-change or item-result ID, and
`Product result / visibility` must state the local OTLP or product visibility
state used by the bound verification overlay.
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

- Read `.observe/otel-audit.json` for service metadata, gaps, GenAI readiness,
  and candidate metrics.
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
