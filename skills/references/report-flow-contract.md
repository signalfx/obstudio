# OTel Report Flow Contract

Use this reference whenever `$otel-audit`, `$otel-instrument`, `$otel-verify`,
`$splunk-configure`, or `$splunk-dashboard` reads or writes files under
`.observe/`.

## Canonical Artifact Chain

Use one immutable audit plus small, validated overlays:

`$otel-audit` -> `.observe/otel-audit.json` -> human scope planning in
`.observe/otel.html` -> `.observe/otel-selection.json` ->
`.observe/otel-instrumentation.json` -> `.observe/otel-instrumentation.html` ->
`.observe/otel-verify.json` -> refreshed `.observe/otel-instrumentation.html` ->
`$splunk-configure` / `$splunk-dashboard` -> reviewed Terraform ->
`$splunk-detector-publish` / `$splunk-dashboard-publish`

Apply these precedence and identity rules throughout the chain:

- `.observe/otel-audit.json` is the canonical audit. Do not mutate it to record
  selection, implementation, or verification state.
- `.observe/otel-selection.json`, `.observe/otel-instrumentation.json`, and
  `.observe/otel-verify.json` are the authoritative overlays for their stages.
  Each overlay must match the canonical audit's `meta.audit_id` through
  `audit_id` and the validator-computed SHA-256 digest of the canonical field
  representation through `audit_sha256`.
- `.observe/otel.html` is the self-contained human review and plan-building surface.
  It renders the canonical audit and exports the selection overlay; it is not a
  second source of truth. It must not render instrumentation or verification
  overlays.
- `.observe/otel-instrumentation.html` is the generated human change, impact,
  and proof surface. `$otel-instrument` creates it from the bound audit,
  selection, and instrumentation overlay; `$otel-verify` refreshes it with the
  verification overlay. It never replaces or rewrites the audit view.
- Markdown reports are generated, readable compatibility outputs. They never
  override JSON. If JSON and Markdown disagree, fail or regenerate the Markdown;
  never merge the conflicting state.
- Fall back to the legacy Markdown chain only when
  `.observe/otel-audit.json` is absent. If the canonical JSON exists but is
  invalid, or an overlay has a stale audit identity/digest, stop and repair the
  JSON instead of falling back. Do not mix JSON overlays with a legacy Markdown
  audit run.
- Only executable `default`/`fix all` finding IDs in the dependency-closed
  `approved_ids` of `.observe/otel-selection.json` may flow into instrumentation
  and verification. `manual decision` and `external follow-up` findings remain
  audit state and are never selection IDs. A manual answer is stored separately
  in `decision_answers`; it can unlock only the executable IDs listed by that
  authored option and never selects them automatically. In schema v2 manual
  and external findings are valid only
  when transitively required by at least one executable finding. Preserve
  canonical audit order and
  require instrumentation and verification overlays to reconcile exactly that
  executable set. Passing this mode gate does not establish finding eligibility;
  `$otel-audit` must apply the OTel finding boundary before assigning any ID.

## Document Ownership

Each document has one job. Do not mix these responsibilities.

| Document | Owner skill | Purpose | Must not contain |
|---|---|---|---|
| `.observe/otel-audit.json` | `$otel-audit` | Canonical source-derived audit with stable finding/scenario IDs and dependency edges | Selection, implementation, or verification state |
| `.observe/otel.html` | `$otel-audit` renderer + human reviewer | Interactive review of the canonical audit and selection export | Independent audit state or hidden selection state |
| `.observe/otel-instrumentation.html` | `$otel-instrument` renderer, refreshed by `$otel-verify` | Concise verification status followed by every selected finding's change, observability impact, item proof, and coverage | Aggregate technical ledgers, audit selection controls, unbound overlays, or an independently rewritten baseline |
| `.observe/otel-selection.json` | Human scope-planning flow | Authoritative manual `decision_answers` plus requested and dependency-closed executable finding IDs (stored in the compatibility field `approved_ids`) | Manual/external finding IDs, executable work not unlocked by its recorded answer, findings absent from the audit, or silently inferred selection |
| `.observe/otel-instrumentation.json` | `$otel-instrument` | Authoritative implementation result for every dependency-closed selected finding ID (`approved_ids`) | Unselected findings or a rewritten audit baseline |
| `.observe/otel-verify.json` | `$otel-verify` | Authoritative scenario proof for every dependency-closed selected finding ID (`approved_ids`), bound to the exact normalized instrumentation overlay by `instrumentation_sha256` | Unselected findings, stale/unbound instrumentation proof, or unsupported `working` claims |
| `.observe/otel.md` | `$otel-audit` | Generated readable compatibility view of the canonical audit | State that differs from `.observe/otel-audit.json` |
| `.observe/otel-instrumentation.md` | `$otel-instrument` | Generated readable compatibility view of the instrumentation overlay | State that differs from `.observe/otel-instrumentation.json` |
| `.observe/otel-verify.md` | `$otel-verify` | Generated readable compatibility view of the verification overlay | State that differs from `.observe/otel-verify.json` |
| `.observe/detectors.md` | `$splunk-configure` | Human-readable detector plan: generated detectors, covered metrics, skipped metrics, prerequisites | Secrets, unverified detector claims |
| `.observe/splunk-configure-verify.md` | `$splunk-configure` | Detector output validation: Terraform syntax, SignalFlow shape, coverage, safety checks | Live apply results unless explicitly requested |
| `.observe/dashboards.md` | `$splunk-dashboard` or `$splunk-configure` | Human-readable panel, product-action, preview, and validation inventory | Claims that a generated preview rendered or returned live values without evidence |
| `.observe/dashboards.preview.json` | `$splunk-dashboard` or `$splunk-configure` | Fully resolved local Observer preview kept in lockstep with dashboard Terraform | Credentials, unresolved Terraform expressions, or publish/apply state |

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
   `audit -> select -> instrument -> verify -> configure/dashboard -> publish`
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
current-baseline sentence, then group actions by priority in this order:
**Required**, **Recommended**, and **Deferred**. Do not render standalone
priority or quick-win summary cards. Within each priority group, render only
the applicable action tag -- **Fix now**, **Decide now**, **Consider next**,
**Decide first**, **Resolve prerequisite first**, **Consider later**, or **Track
external follow-up** -- with its count and findings. Show executable progress
separately from open decisions, blocked work, and external follow-ups in the
priority heading. **Fix now** covers safe required work, while **Decide now**
identifies required decisions outside the instrumentation selection.
Render **Decide now**, **Decide first**, or **Track external follow-up** only
for a validated prerequisite of executable instrumentation; orphan
non-executable findings are invalid canonical input.
Keep quick-win information as an effort tag on findings; it
overlaps priority and is not an additive executive total. Do not surface
canonical `meta.status` as a human outcome; it classifies the machine report and
does not claim runtime proof. Keep finding-specific missing proof in that
finding's nested `Technical details`; reserve the report-level `Technical
appendix` for cross-finding current-state evidence, the shared verification
plan, and audit notes. Do not repeat the same runtime disclaimer in every
decision summary. Lead each
queue item with its human title or area and one concise expected monitoring
outcome, with the stable `OTEL-###` ID shown only as a secondary cross-report
reference. Do not replace stable IDs with display-order aliases such as `gap-1`.
Translate `default`, `fix all`, `manual decision`, and `external follow-up`
into the classifications `ready to implement`, `optional`, `decision needed`,
and `external follow-up`. Use the neutral `Select` checkbox only for executable
`default`/`fix all` findings. A manual finding has no selection checkbox
and can never enter either selection ID list; instead, render its two or three
authored `decision_options` as an accessible one-of answer control. External
findings remain non-interactive and cannot enter selection JSON. An unanswered
manual dependency is blocked. Once answered, only executable findings listed
in that option's `unlocks` become selectable; nonmatching branches remain
blocked, and the answer does not auto-select matching work.
A manual decision has no checkbox and cannot enter selection JSON; only its
stable answer ID is persisted separately.

Keep each primary finding disclosure button separate from its selection checkbox. Give
every checkbox a unique accessible name, bind that disclosure to its body with
`aria-controls`, and hide decorative carets from assistive technology. Put the
cards under a compact `Findings · N` heading immediately after the decision
view, except that a schema-v2 `Blocked` audit must first show its structured
scan-incomplete panel. Do not render Priority, Effort, or Status filter facets; they duplicate
the priority-first action view and finding tags while delaying the findings.
On each finding card, render exactly one highlighted applicable action tag:
`Fix now`, `Decide now`, `Consider next`, `Decide first`, `Resolve prerequisite
first`, `Consider later`, or `Track external follow-up`. Do not repeat
priority or instrument mode as separate tags. Render concrete effort only as
`small effort`, `medium effort`, or `large effort`; omit `decision` because the
action tag already communicates it. Omit the baseline `proposed` lifecycle tag
and show lifecycle only after it changes, such as `selected`, `included`,
`working`, or `done`.
Keep severity in canonical JSON for machine compatibility but
do not render a severity bar, badge, or filter as a competing human ranking.
Priority-tag text must meet at least 4.5:1 contrast on every report surface.

Do not render the canonical component flow as a service map, connection list,
component-coverage groups, linked-area counts, or raw flow text in audit HTML.
Those views repeat findings without adding a scope decision or runtime
proof. Keep the canonical flow in JSON and generated Markdown for tooling and
compatibility. Do not render a duplicate all-findings decision table. Each
finding card must show one `product_outcome` sentence answering what the owner
should see or gain after implementation and verification. After the card
header and selection or decision control, keep the expanded narrative
decision-sized. Its four first-level fields are `Gap`, `Why it
matters`, a mode-aware required action, and `Next step`: label the action
`Instrumentation change` for executable work, `Decision needed` for a manual
prerequisite, and `External requirement` for an external prerequisite. For a
currently selectable, unselected executable finding, the next step is `Select`
-> `Save selection` -> `$otel-instrument`. Keep the copy synchronized with
selection state: explicitly selected work proceeds to saving, an auto-added
dependency explains why it is included, and blocked executable work names its blocking `OTEL-###`
IDs and directs the reviewer to resolve them first. Do not label verification,
explorer, dashboard, or detector follow-up as the immediate next step.

Show a compact telemetry shape on the card from exact
`expected_telemetry[*].type` counts, including configuration and resource
items. When a finding has dependencies, show their stable IDs as a selection effect;
the action tag and `Next step` still distinguish blocked work from executable
dependency closure. Do not infer a material-safety badge from free-text
constraints, severity, or priority. The current schema does not classify that
judgment, and a badge on every constrained finding would add noise.

Put exact expected telemetry with configuration scope, evidence, acceptance
criteria, and authored constraints behind one collapsed `Technical details`
disclosure. Label the constraints `Implementation guardrails`. Its summary
reports acceptance-check, guardrail, and source-reference counts. Do not render
raw verification-scenario IDs, OTel concern taxonomy, repeated full scope
classification, canonical `follow_up_actions`, resolution metadata, or a
second dependency list in the finding HTML. Those fields remain in canonical
JSON for downstream instrumentation and verification; Markdown remains the
complete compatibility view. Post-instrumentation product actions belong in
`.observe/otel-instrumentation.html`. Keep a manual decision's question and
owner in its decision control and `Next step`; keep an external prerequisite's
owner and required telemetry in its primary action and `Next step`.

HTML remains a complete review and selection surface; links to
`.observe/otel.md` and canonical JSON are optional alternate formats, not
required reading. The Markdown fallback exposes the enforcement fields in
`### OTel Closure Details`; render frozen schema-v1 findings there as
`Legacy v1 — unclassified` without mutating normalized JSON. After a finding
jump, open the target's primary disclosure,
leave its nested `Technical details` closed, and move keyboard focus to the
primary disclosure button; apply the same behavior to direct report hashes.
Render authored Incident and GenAI telemetry-readiness tables as visible panels
after findings rather than hiding them in embedded JSON or the technical
appendix. Reserve one collapsed report-level `Technical appendix` for
cross-finding source-visible instrumentation evidence, the shared verification
plan, authored notes, audit evidence, and recommendations. Do not render a
separate Anti-Patterns subsection in decision-focused HTML. An actionable
anti-pattern belongs in its finding card; distinct compatibility or provenance
notes remain in canonical JSON and the complete Markdown fallback without
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

Do not render aggregate statistic cards or the global **Code → telemetry →
product result**, telemetry-item mapping, **Technical closure ledger**,
**Verification proof**, **Scenario proof**, or **Item-level proof** sections in
instrumentation HTML. Their units overlap and the selected cards already carry
the human decision context. Preserve the complete code/config mapping, closure
rows, scenario evidence, stable IDs, commands, exact counts, and item proof in
`.observe/otel-instrumentation.json`, `.observe/otel-instrumentation.md`,
`.observe/otel-verify.json`, and `.observe/otel-verify.md`. These canonical and
compatibility artifacts, not the HTML, are the downstream handoff.

Do not truncate, group, or replace the selected-issue list with a thematic
executive summary. Each entry must show the human issue title with its stable
ID, whether the reviewer selected it or it was added as a dependency, every
finding-level `changes` sentence, the audit `product_outcome` under **How it
improves observability**, its telemetry shape, its current verification state,
and one concise verification summary built from the audit scenarios' human
`trigger` text. A direct successful
unit, application, or runtime observation proves the specific telemetry item it
exercised; mark that `item_results` row `working` even when unrelated scenario
coverage remains incomplete. Source/config presence and an unbounded or
ambiguous absence do not qualify. A bounded expected-absence assertion for a
removed item is governed by the direct-assertion rule below. Evidence must directly name or assert the exact
telemetry item and call site. Aggregate receiver counts, a differently named
signal, or a shared helper that never invokes that item are context only and
must leave it `not_proven`. Render those rows as **Not proven**, never
**Observed**, and state that the exact item was not directly observed. Render a
**Telemetry change / What was observed /
Status** table. State local delivery and target-product check scope once in the
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
stronger-proof group or per-finding completion
checklist. Never put unexplained
`x/y` scenario, exercised-check, item-proof, delivery, or product-visibility
ratios on a finding card; keep exact counts and stable IDs in the canonical JSON
and generated Markdown proof ledgers.
For each blocked canonical scenario, require a reader-facing
`blocking_reason` naming the exact unavailable prerequisite and an
`unobserved_outcome` naming the exact runtime, OTLP-delivery, or product proof
that could not be captured. The reason must be supported by that scenario's
command/evidence and must not be an imperative user instruction. Replace the
generic blocked count in instrumentation HTML with **Runtime verification
unavailable** before **Coverage details**, followed by **Why runtime
verification is unavailable**, **Already proven** from mapped working item
evidence, and **Still unobserved** from the structured scenario outcome. Keep
affected audit triggers neutral in the collapsed disclosure; do not make them
look like the user's next steps.
Canonical verification records the item-local judgment in the required boolean
`item_results[].direct_assertion_passed` before any scenario/finding rollup.
It is `true` exactly when a saved assertion directly exercises the exact item
or call site and passes; item status is then `working`. Contextual, aggregate,
ambiguous, not-run, and failed evidence set it `false`. For a removed item, a
bounded executed capture must prove both absence of the removed signal and
presence of the intended replacement owner. The validator rejects item status
that contradicts this boolean, so incomplete route or lifecycle coverage cannot
downgrade item-local proof.
Show separate
**Implementation** and **Proof** badges; a recorded change is not proof, and a
proof-only selected row is not a failed implementation. Do not say required
proof is pending when the finding or item already meets its authored proof
level. Keep consolidated run-level proof plans in the canonical overlays and
generated Markdown rather than adding another HTML action list.

Never use **pending** as an umbrella for a failed verification. For overall
`Fail`, label the first-screen detail **Verification failures**, label each `not_working` card with **What verification found** and
**Code repair required**, followed by **How the repair is confirmed**, and
label a standalone primary action **Next repair steps**. In an active
instrumentation child, label it **Active repair loop** and do not hand the user
another workflow invocation. For `not_proven`, do not render the finding's
`remaining` list as a user checklist. Use named scenario triggers only in the
neutral coverage disclosure. Keep
acceptance criteria, commands, scenario IDs, and raw evidence in canonical JSON
and generated Markdown. Explain workflow ownership once: `$otel-verify` never changes
application code, `$otel-instrument` repairs in-scope code/config, and the
instrumentation workflow automatically invokes verification afterward only to
confirm whether the repair worked. Do not render that automatic recheck as a
second repair bullet or user action. A failed finding's `remaining` list and
the run-level `next_steps` expose the concrete repair that must happen now;
scenario mappings retain the affected confirmation scope. Exact scenario IDs
and counts belong in canonical proof artifacts, not as manual user instructions. Once a
verification overlay exists, never fall back to stale instrumentation-phase
next steps when its `next_steps` list is empty.

When current verification exists, label instrumentation-overlay test text as an
**instrumentation-phase snapshot** so an earlier "not run" statement cannot be
mistaken for current proof. Current verification status and evidence take
precedence. A successful full-runtime `-javaagent` attachment suppresses prior
fixed-path agent-unavailable evidence and forbids current next steps that ask
the user to provide, locate, install, download, or supply that agent. Future
work must say to reuse the resolved version/path. Unknown production-version
parity is a separate limitation, not agent unavailability.

Every final overlay is a current-state projection. A successful repair and
confirmation supersede earlier `not_working` statuses, observations, repair
actions, trace IDs, and run-level next steps. Keep optional attempt history only
as explicitly superseded technical evidence; never mix it into current status,
remaining work, first-screen text, or the user's next action.

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
show a compact `N in selection · R of T required fixes` summary, adding `P
auto-added dependencies` only when nonzero, and one primary `Save selection`
action. Do not require an intermediate review panel and do not expose `Copy
command` or `Copy selection JSON` controls. The cards and live-region feedback
must make each explicit selection and auto-added dependency understandable
before saving.

`Save selection` serializes `requested_ids`, dependency-closed `approved_ids`,
and stable `decision_answers`, then requests a browser download named
`otel-selection.json`. A self-contained `file://` report cannot silently write
or overwrite `.observe/otel-selection.json` or confirm the browser's download
destination. Tell the reviewer to place the downloaded file at that exact path
before running `$otel-instrument`. State that manual/external finding IDs remain
in the audit and are never exported to instrumentation scope; only stable manual
answer IDs are carried separately in `decision_answers`. Announce answer,
dependency, and save/download guidance through an `aria-live="polite"`,
`aria-atomic="true"` status region. Keep the tray and action usable as a
single-column layout on narrow screens.

## Status Rules

- For a schema-v2 audit's canonical `meta.status`, use `Pass` only when the source scan
  completed and produced zero findings, `Partial` when the completed scan
  produced one or more findings, and `Blocked` when one or more structured
  `scan_blockers` prevented a complete source scan. Audit `Pass` also requires
  no unresolved `partial` or `missing` readiness rows. Audit `Pass` means no
  source-visible gaps; it is not a runtime-verification claim. Audits never use
  `Fail`.
- Frozen schema-v1 inputs may carry legacy `Blocked` status without structured
  blockers because that field did not exist in the original contract. Preserve
  that normalized input and digest; regenerate the audit as schema v2 before
  relying on blocker structure or a headless gate.
- For execution-report `Result`, use `Pass` only when every in-scope row has
  proof. Use `Partial` when meaningful work passed but any in-scope signal/path
  is unverified, source-only, not run, or blocked.
- Use execution `Fail` when an executed scenario violates expected telemetry or
  an instrumentation-introduced compile/import/test failure remains.
- Use execution `Blocked` when no meaningful proof can run because a concrete
  prerequisite is missing.
- Never call source definitions "verified" without command output, test
  assertion, harness evidence, collector evidence, or static proof explicitly
  allowed by the skill.

## Audit Contract

Audit is read-only and baseline-oriented:

An OTel finding ID is not a general operational task container. A finding is
eligible only when closing it necessarily changes or proves span, metric, or log
emission; telemetry correlation or propagation; semantic attributes or
cardinality; OTel SDK, auto-instrumentation, provider, exporter, resource,
propagation, or OTLP log-pipeline configuration; or telemetry-specific proof.
The finding's title, area, gap, product outcome, required fix, acceptance
criteria, expected telemetry, scenarios, and follow-up actions must describe
one coherent OTel deficiency, change, product use, and proof path. Remove
behavior, policy, documentation, API/OpenAPI contract, ownership-link,
deployment, and general test work from those fields. If no independently useful
OTel closure remains, omit the finding. Keep an applicable non-telemetry fact
only in evidence, constraints, or operator-impact prose under the mixed-concern
rule below. Do not relabel general operational output as `configuration`
telemetry.

Canonical JSON must scope every `type: configuration` expected-telemetry item
with `configuration_scope` equal to `otel-sdk`, `otel-resource`,
`otel-exporter`, `otel-sampling`, `otel-propagation`,
`otel-instrumentation`, or `otel-collector`. A configuration item never closes
a finding alone; the same finding must name a span, metric, log, or resource
outcome that proves the configured behavior.

New canonical audits use schema v2. Every finding must also declare one or more
structured `otel_concerns` from
`signal-emission`, `context-propagation`, `trace-log-correlation`,
`semantic-attributes`, `cardinality-safety`, `otel-configuration`, or
`telemetry-proof`. The validator cross-checks this declaration against its
configuration items, signal outcomes, attributes, and verification-scenario
shape and canonicalizes their order. These values classify a coherent OTel
closure; they cannot make general operational work eligible. The validator
rejects action/object clauses for API contracts, documentation/runbooks,
general CI/tests, product behavior/policy, ownership administration, and
non-OTel service configuration in closure-driving fields. Directly relevant
non-telemetry facts belong only in evidence, constraints, or operator-impact
prose.

Schema v1 is a frozen legacy audit input: do not infer v2 concerns,
decision/external ownership, or scan blockers. Preserve optional concerns and
decision/external ownership fields when they were already authored by a
transitional v1 producer, including authored concern order, so existing
selection digests remain valid. Do not add structured scan blockers to v1.
Upgrading requires authored classifications, human review, and regenerated
overlays. A selection without answers remains schema v1; a selection carrying
`decision_answers` is schema v2. Instrumentation, verification, scope, and gate
overlays remain schema v1. Every overlay binds either audit version by its
version-specific digest.

When an observation mixes telemetry with non-telemetry work, split the concerns:
the finding contains only the OTel change and telemetry proof. A functional or
operational fact may remain only as evidence or a constraint of that retained
finding when it directly proves the observed behavior or prevents telemetry
work from changing it. Omit unrelated non-telemetry debt from summary,
top-level evidence, readiness, anti-patterns, recommendations, findings, and
scenarios. `manual decision` and `external follow-up` classify prerequisites of
an otherwise valid OTel finding; neither mode makes a general operational task
an OTel finding. Recommendations and follow-up actions may contain only OTel
implementation, configuration, verification, or downstream telemetry-product
work.

Dependency direction is executable finding -> prerequisite. Keep a schema-v2
`manual decision` or `external follow-up` only when it is transitively required
by at least one executable finding. Reject orphan non-executable findings,
including downstream decisions that depend on instrumentation but do not block
it. When a telemetry choice genuinely blocks app-owned work, split it into a
pure prerequisite and a separate `default`/`fix all` finding that references
that prerequisite. Omit the prerequisite from every report section when no
executable OTel closure depends on it.

- Write and validate `.observe/otel-audit.json` first. Treat it as the immutable
  source of truth for the audit.
- Render `.observe/otel.html` from the validated JSON for human review and
  scope planning, then generate `.observe/otel.md` as its readable compatibility
  view.
- Give every actionable finding and acceptance scenario a stable ID. Record
  finding dependencies so selection export can compute dependency closure.
- Give every finding one concise `product_outcome` sentence stating what the
  owner should see or gain after implementation and verification. Do not claim
  the source audit has already proven that outcome.
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
| GenAI ownership | <exactly Yes or No; no extra text> | <owned source paths or repository scan evidence> |
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

Every finding `area` must appear in at least one `[GAP: <area>]` marker so
tooling can validate the authored flow-to-finding association. Repeating one
area on multiple nodes is allowed when the same gap spans those components.
Audit HTML still renders that finding exactly once in the priority-first action
view; it does not group, repeat, or decorate findings by component.

Put `## Current Instrumentation` immediately after the flow map so readers see
what exists before they evaluate deficiencies. When present, put
`## GenAI Readiness` next because it is specialized current-state context. Put
the prioritized `## Gaps` table after that baseline and before
`## Verification Plan`. The executive summary remains responsible for keeping
the most important gaps visible on the first screen.

When source evidence shows incident-readiness ownership, `## Current
Instrumentation` may contain one `### Incident Readiness` subsection for
telemetry-scoped surfaces with this table:

```markdown
| Area | Status | Evidence | Required Signals / Gap | Detection / Localization Impact |
|---|---|---|---|---|
```

Every telemetry-scoped `partial` or `missing` row must have a prioritized,
unresolved `## Gaps` row whose `Area` cell is identical and whose
verification-scenario IDs define the telemetry proof handoff. Use only
`covered`, `partial`, `missing`, or `owner-mapped`; areas are unique, and
`covered` must not conflict with an unresolved same-area finding. `done`,
`rejected`, and `deferred` findings do not satisfy a partial/missing row and do
not conflict with a covered row. These rules prevent `Pass` from hiding missing
readiness. Do not add a readiness row solely for API
behavior, policy, documentation, contract, ownership links, or general test
hygiene. This is a nested current-state view, not a second top-level gap ledger.

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
- `deferred`: telemetry work requiring an exact OTel decision, known external
  telemetry owner, credentials, infrastructure, or an unsafe/oversized change.

Allowed instrument modes are `default`, `fix all`, `manual decision`, and
`external follow-up`. Use `default` for safe app-owned required work and
required verification, `fix all` for safe recommended work, and `manual
decision` only for an exact OTel signal, pipeline, sampling, cardinality, or
telemetry-privacy choice required by a separate executable finding. Resolve
source evidence before assigning that mode: one safe, reversible, app-owned
OTel implementation is executable and must not become a `manual decision`.
Use `default` or `fix all` even though the reviewer can leave that work out of
the selection. A genuine manual choice has two or three materially distinct,
source-supported answers; do not manufacture approve/decline options around a
safe default. Use
`external follow-up` only when a known owner
outside the service must supply an exact OTel signal, pipeline configuration,
or telemetry proof required by a separate executable finding; owner discovery
and independent downstream platform work are evidence, not findings. A required
gap may use `manual decision` when it cannot be repaired safely without that
telemetry-specific choice. Apply instrument modes
only after the OTel finding boundary; safe app ownership does not make generic
service work selectable. Split mixed telemetry ownership: an external telemetry
follow-up must never absorb independently executable service-owned OTel work.
Omit non-telemetry service code, configuration, contract, documentation, policy,
or general test work instead of splitting it into another finding. If no gaps
exist, keep the table header and write `No gaps found.` below it. Group rows by
remediation theme; do not repeat every route or flow edge.

Canonical manual-decision findings must carry `decision_owner` plus an exact
telemetry-specific `decision_question` naming an actual expected signal,
attribute, or configuration scope, and two or three explicit selectable
`decision_options`. Each option carries a unique stable `id`, a concise
`label`, a concrete `outcome`, and an `unlocks` list of executable findings
that depend on the manual finding. An empty `unlocks` list records an answer
that intentionally produces no instrumentation work. Canonical external-follow-up findings must
carry a known `external_owner` plus an exact `external_requirement` naming an
actual expected OTel signal, attribute, pipeline configuration scope, or
telemetry proof that owner must supply. Placeholder owners are invalid. The
exact external requirement must also be the finding's `required_fix`; these
fields are invalid on executable findings.

## Instrumentation Contract

Instrumentation is a goal workflow, not just a code edit:

1. When `.observe/otel-audit.json` exists, validate it together with
   `.observe/otel-selection.json`; do not infer selected scope from Markdown or prose.
2. Reconcile only the selection overlay's dependency-closed `approved_ids` with
   current source. If no valid selection overlay exists, return to human review
   in `.observe/otel.html` instead of silently selecting work.
3. Implement the dependency-closed selected scope.
4. Run project-runtime compile/import and focused tests.
5. Write and validate `.observe/otel-instrumentation.json`, with one row per
   dependency-closed selected finding in canonical audit order, then generate
   `.observe/otel-instrumentation.md` as its readable compatibility view and
   `.observe/otel-instrumentation.html` as the human change and impact view.
6. Invoke or apply the `$otel-verify` workflow unless the user explicitly opts
   out or a concrete prerequisite blocks it.
   When verification JSON is produced, refresh
   `.observe/otel-instrumentation.html` with item and scenario proof. Do not
   regenerate `.observe/otel.html` with downstream state.
   Before finalizing a failed result, apply the instrumentation skill's
   pre-finalization repair gate. Instrumentation-owned failures include current
   instrumentation regressions, missing wiring/config required by the current
   change, and pre-existing OTel defects inside selected scope that prevent a
   selected outcome. They exclude unrelated business logic and external or
   unselected dependencies. For every safe in-scope instrumentation-owned
   failure, keep the same workflow active, make a concrete repair attempt,
   rerun affected compile/focused tests, and automatically invoke verification
   for the affected scenarios again. A failing verification overlay written
   during this loop is intermediate, not the final instrumentation handoff.
   Present the repair as the user-facing action and the recheck as confirmation,
   never as a second action that could be mistaken for the fix.
7. If verified metric evidence exists and the user requested alerting/detectors,
   invoke or apply `$splunk-configure`.

Only when `.observe/otel-audit.json` is absent, use the legacy
`.observe/otel.md` gap-table workflow and write the legacy Markdown report. Do
not combine a legacy Markdown audit with JSON overlays.

For a normal instrumentation run, the HTML plan flow should offer every safe
app-owned `required` row whose instrument mode is `default`. When the user asks
to fix all gaps, it may also offer safe `recommended` rows whose mode is
`fix all`. Never select or silently implement `manual decision` or `external
follow-up` rows. A validated `decision_answers` entry resolves only its authored
manual choice: executable rows in that option's `unlocks` may then be selected,
while every other branch stays blocked. Reject unanswered manual dependencies,
external dependencies, and executable IDs that do not match the recorded
answer rather than auto-adding a non-executable prerequisite. The exported
selection overlay, including executable dependency closure, is the final scope authority;
untouched executable audit rows and their validated prerequisites remain
visible in the immutable audit and HTML review.

When canonical `current_instrumentation.incident_readiness` is non-empty,
reconcile those rows through the matching findings and `## Audit Gap Closure`.
Only in legacy fallback mode, read `### Incident Readiness` from
`.observe/otel.md` and reconcile it through the prioritized gaps. Do not create
a parallel incident closure section or claim a readiness surface is working
while one of its required signals remains missing or unproven.

The instrumentation overlay and its Markdown compatibility report must
reconcile every dependency-closed selected audit row under
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

Within each dependency-closed selected finding, give every added, modified, or removed telemetry
item a stable ID and preserve this join:

`item ID -> code/config change -> exact source/call site -> exact telemetry ->
product view -> next product action -> verification scenarios`

Each item-level change must state the concrete source-backed correction, such
as ownership removal/retention, exception and status handling, lifecycle
closure, bounded attributes, propagation, provider wiring, or flush/shutdown
behavior. Reject generic text such as "Added/modified `<name>` for the selected
bounded telemetry contract"; the exact item mapping is a reader-facing result,
not schema filler.

Metrics must name their chart/dashboard or detector follow-up. Newly added
attributes or dimensions must name the filter, slice, group-by, or breakdown
they enable. Verification must derive its expected item inventory directly from
these IDs and return one item result for each; a separately hand-authored list
cannot reduce the required coverage.

The instrumentation report must include:

```markdown
# OTel Instrumentation Report: <service>

**Result:** Pass | Partial | Fail | Blocked
**Source audit:** `.observe/otel-audit.json` | legacy `.observe/otel.md` | not found
**Selection:** `.observe/otel-selection.json` | legacy audit scope
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

When incident readiness applies because the user requested faster detection or
localization, incident evidence was supplied, canonical
`current_instrumentation.incident_readiness` is non-empty, or the legacy
Markdown audit contains `### Incident Readiness`, add this nested inventory
inside `## Signals Changed`:

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

The authoritative instrumentation JSON carries the same inventory in
top-level `genai_closure`, in audit surface order. Every row records `surface`,
the exact audit `required_signals` and `owner`, `implemented_proven`, `tests`,
durable `evidence`, `remaining_signals`, and `status`. Use lowercase
`working`, `partial`, `not_working`, `not_proven`, `not_configured`, `deferred`,
or `owner_mapped`. A working row requires nonempty implementation/proof, tests,
and evidence with no remaining signals; every non-working row names the exact
remaining signal or owner prerequisite. The instrumentation digest includes
this inventory, and the compatibility Markdown must project it exactly.

## Verification Report Contract

Verification reads the canonical audit and authoritative overlays:

- Audit source: `.observe/otel-audit.json`
- Selected scope: `.observe/otel-selection.json`
- Implementation source: `.observe/otel-instrumentation.json`
- Authoritative output: `.observe/otel-verify.json`
- Generated readable output: `.observe/otel-verify.md`

Validate `audit_id` and `audit_sha256` before using either input overlay, then
bind verification to the exact normalized instrumentation overlay with
`instrumentation_sha256`. A matching item inventory is not enough: any material
instrumentation change invalidates older proof. Write
one verification finding for every dependency-closed selected ID (`approved_ids`) in canonical audit order. A
finding may be `working` only when its scenarios cover the audit's required
scenario IDs and carry direct evidence. If the canonical audit is absent, use
the three legacy Markdown reports as one legacy chain; never combine them with
JSON overlays.

Reconcile delivery claims across that join. `otlp_accepted` and
`explorer_visible` are invalid when the matching instrumentation
`product_view` denies any OTLP pipeline or export path. Do not confuse absence
of an application-owned exporter with absence of an agent- or platform-owned
delivery path.

Record invocation state in verification metadata. Standalone verification uses
`workflow_mode: standalone` and `lifecycle: final`. Verification called by an
active instrumentation workflow uses `workflow_mode: instrumentation_child`;
a failed repair packet is `lifecycle: intermediate`, and the post-repair
current-state overlay may be `final` only after no executed check is
`not_working`. The shared `instrumentation-final-gate` enforces that boundary.

Write verification reports for a reader deciding whether the instrumentation
works. The first screen must answer, in this order:

1. What was added or modified?
2. Was each change tested?
3. Is it working?
4. If anything is not working or not proven, why and what is needed next?
5. What is the proof for the current conclusion?

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
Every `Working` row must name the test mode and direct evidence.

Canonical verification also writes one `item_results` row for every stable
instrumentation telemetry item ID, in instrumentation order. Each row maps the
item to its audit scenarios and records status, proof mode, visibility, direct
evidence, observed telemetry, product validation, and the required
`direct_assertion_passed` boolean. `Working` requires all of those fields and
`direct_assertion_passed: true`; every other item status requires it to be
`false`. Its `observed_telemetry` must put the exact item name and every required
attribute in one affirmative observation clause using direct language such as
observed, emitted, recorded, exported, received, accepted, or captured.
Expected, should/may, unconfirmed, or cross-clause token mentions are not proof.
Keep unit-only proof explicitly `not_explorer_visible`; use
`explorer_visible` only with saved Observer/query evidence. This item inventory,
not a hand-authored expected-items file, determines whether every code-to-
telemetry change was verified.

For a working `change_kind: removed` item, also require structured
`removal_proof`: `removed_signal` exactly equals the instrumentation item name,
`replacement_signal` names a distinct intended owner, and both
`absence_assertion_passed` and `replacement_assertion_passed` are true. This is
in addition to durable evidence and reader prose; a generic success sentence
cannot stand in for the two bounded assertions.

Every scenario with `status: blocked` also carries nonempty
`blocking_reason` and `unobserved_outcome` fields. Omit those fields from every
other status. Preserve remediation separately in finding `remaining` or
top-level `next_steps`; an unblock action is not the historical reason the
scenario could not run.

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

- Prefer `.observe/otel-audit.json` for service metadata, findings, current
  instrumentation, readiness, and candidate metrics.
- Validate `.observe/otel-selection.json`,
  `.observe/otel-instrumentation.json`, and `.observe/otel-verify.json` against
  that audit before consuming them. Scope downstream work to dependency-closed selected finding
  IDs and join implementation telemetry changes to verification by finding ID.
- Treat an exact metric as verified only when its source-backed or implemented
  telemetry item ID is covered by a `working` verification `item_results` row
  and scenario evidence proves its emitted name, unit, and required dimensions.
- Fall back to `.observe/otel.md`, `.observe/otel-instrumentation.md`, and
  `.observe/otel-verify.md` only when `.observe/otel-audit.json` is absent. If
  canonical JSON exists, Markdown is readable compatibility output, not input
  authority.
- Generate Terraform only for metrics that are present in source and either
  verified or explicitly accepted as source-only by the user.
- Put missing or unverified detector inputs in
  `GenAI Instrumentation Prerequisites`, `Instrumentation Prerequisites`, or
  `Skipped Metrics`; do not invent detectors for absent metrics.
- Always write `.observe/splunk-configure-verify.md`.

`$splunk-dashboard` applies the same input precedence and proof rule when
generating dashboard Terraform. After review, hand detector Terraform to
`$splunk-detector-publish` and dashboard Terraform to
`$splunk-dashboard-publish`. Publish skills consume reviewed Terraform and must
not rewrite the canonical audit or its overlays.

Dashboard generation also writes `.observe/dashboards.preview.json`. Validate
an exact one-to-one mapping between accepted signal provenance IDs, Terraform
charts, and preview charts, including resolved query and grid placement. Treat
implemented items as `OTEL-###.<item>`. Represent an explicitly accepted
pre-existing metric as `SOURCE-METRIC.<exact-metric-name>` so the source path is
stable without inventing an instrumentation item ID.
preview generation, Observer rendering, live value sanity, and live publish as
four separate states. A sidecar on disk proves only preview-contract generation;
never claim the UI rendered it, the query returned plausible data, or a live
resource exists without direct evidence for that stage.

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
