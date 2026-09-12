# Audit Artifact and Handoff Contract

Load only after source assessment is complete and immediately before writing
`.observe/otel-audit.json`. This file is the sole normative audit artifact,
reader, and handoff contract. Do not load or merge the older shared audit
wording.

### Step 3 -- Report

Write two audit artifacts inside the scanned service root (create the
`.observe/` directory if it does not exist):

- `.observe/otel-audit.json` -- canonical machine-readable audit source.
- `.observe/otel.html` -- self-contained human review report generated from the
  JSON. This is the normal human interaction surface for expanding and
  selecting finding IDs. Keep it audit-only; never render instrumentation
  or verification overlays into this file.
Use `.observe/otel-audit.json` as the source of truth for stable finding IDs,
selection, and downstream tool handoff. Do not require humans to read or edit
the JSON directly; generate `.observe/otel.html` from it.
The reviewer uses `.observe/otel.html` to understand findings, answer any
manual decision controls, choose executable instrumentation scope, and save or
copy the exact `$otel-instrument` command. It is not a proof report. After
instrumentation, change-impact and proof status move to
`.observe/otel-instrumentation.html`; scope changes should return to
`.observe/otel.html`, not edit generated HTML or JSON by hand.

In HTML, put selectable findings immediately after the concise decision
summary. Do not render the component map, connection lanes, component-coverage
groups, raw flow map, full current-state inventory, or a duplicate all-findings
decision table. Keep `signal_flow` in canonical JSON for machine use. Reserve
one collapsed technical appendix at the
report level after the findings for cross-finding source-visible
instrumentation evidence, the shared verification plan, audit evidence, and
recommendations; keep finding-specific proof and implementation detail on its
card.

After the card header and selection or decision control, keep the expanded
narrative decision-sized. Its four first-level fields are
`Gap`, `Why it matters`, a mode-aware required action, and `Next step`. Label
the action `Instrumentation change` for executable work, `Decision needed` for
a manual prerequisite, and `External requirement` for an external
prerequisite. For a currently selectable executable finding, `Next step` is to
select the finding, copy the generated command, and run `$otel-instrument`; do not
present authored verification or dashboard work as
the reviewer's immediate action.
Keep that copy synchronized with selection state: selected work proceeds to
the generated command, an auto-added dependency explains why it is included, and
blocked work names the blocking `OTEL-###` IDs and directs the reviewer to
resolve them first. Show a compact telemetry shape on the card from exact
`expected_telemetry[*].type` counts, including configuration and resource
items. When a finding has dependencies, show their stable IDs as a selection effect.
Do not infer a material-safety badge from free-text constraints, severity, or
priority; the schema does not author that judgment.

Put exact expected telemetry, evidence, acceptance criteria, and authored
constraints behind one collapsed `Technical details`
disclosure. Label constraints `Implementation guardrails`, and summarize the
disclosure with acceptance-check, guardrail, and source-reference counts. Do
not render raw verification-scenario IDs, repeated full scope classification,
canonical `follow_up_actions`, resolution metadata, or
a second dependency list in finding HTML. Those fields remain in canonical
JSON for `$otel-instrument` and `$otel-verify`. Put post-instrumentation product actions in
`.observe/otel-instrumentation.html`, not in the audit finding card. Keep a
manual decision's owner and question in its decision control and `Next step`;
keep an external prerequisite's owner and required telemetry in its primary
action and `Next step`.

Keep the HTML complete and usable on its own. It may link to the canonical JSON
as an optional alternate format, but must not require the reviewer to open
Markdown to understand or select a finding.

Write the HTML summary as a decision brief, not a compressed defect list. Use
3-7 plain-language bullets and state the total finding count, what source or
configuration currently shows, the highest-priority app-owned work, and any
exact owner decision or external prerequisite that blocks executable work.
Keep this detail in the HTML report; the chat handoff is intentionally limited
to the single report link defined below. Do not present canonical
`meta.status` as a human outcome in HTML: it classifies the machine report and
does not claim runtime proof. Do not repeat a generic runtime-unproven warning
in the decision summary. Put finding-specific missing proof in that finding's
nested `Technical details`; reserve the report-level technical appendix for
cross-finding current-state evidence, the shared verification plan, and audit
notes. Give every finding one concise
`product_outcome` sentence answering what the owner should see or gain after
implementation and verification. Lead with monitoring and product outcomes such as a reliable trace
waterfall, route or dependency filtering, a chart, detector, or readiness view. Move
class names, provider topology, exporter details, and other implementation
jargon into finding evidence or technical highlights unless they are the
decision itself.

In the HTML decision view, render exactly one findings list ordered by
machine-readable priority: `required`, then `recommended`, then `deferred`,
preserving canonical order within the same priority. Priority defines ordering
only. Put one concise current-baseline sentence and one
highest-priority-first explanation before the list, then show a compact
`Findings · N` heading immediately above the cards. Keep quick-win, effort,
severity, priority, and execution-state metadata machine-readable in canonical
JSON.

Each card has one title, one expected monitoring outcome, one neutral selection
control when executable, and the stable `OTEL-###` ID as a secondary
cross-report reference. IDs must remain deterministic across selection,
instrumentation, verification, and configuration handoffs. Priority is expressed
only by list order; lifecycle is reflected by the checkbox, next-step copy, and
saved selection state, and effort remains machine-readable only in canonical
JSON.

Use the instrument modes consistently in the human view:

- `default` is safe app-owned work that can enter the instrumentation handoff
  after the reviewer selects it.
- `fix all` is safe broader work that remains opt-in; render the same neutral
  `Select` checkbox as `default`, without an `optional` tag.
- `manual decision` renders as `decision needed`: a named telemetry-specific
  prerequisite offers two or three explicit answers and blocks separate
  executable findings until one answer is selected. The manual finding remains
  visible but its ID cannot enter instrumentation scope.
- `external follow-up` renders as `external follow-up`: a known owner outside
  the service must supply an exact prerequisite needed by a separate executable
  finding. It remains visible as `External follow-up` but cannot enter
  instrumentation scope.

Render the neutral `Select` checkbox only for executable `default` and
`fix all` findings. For `manual decision`, render its two or three
`decision_options` as an accessible one-of answer control, never as a `Select`
checkbox. Keep `external follow-up` non-interactive and never emit a
checkbox for it; never emit a checkbox for either non-executable finding mode.
Persist the chosen option under `decision_answers` in the saved selection. The
answer unlocks only executable findings listed in that
option's `unlocks`; every other branch remains blocked. Answering does not
select or auto-add unlocked work. If the answer changes, remove any now-invalid
requested or dependency-closed work before export. Keep the full mode
classification, verification-scenario references, ownership, and requirements
in canonical JSON. In HTML, keep
manual decision ownership and the question in the answer control and `Next
step`; keep external ownership and its requirement in the primary action and
`Next step`. Render explicit lifecycle state as `selected` and an auto-added
dependency as `included`, never `approved` or `decision requested`. A checked
checkbox records explicit reviewer intent; dependency inclusion is derived
separately and must not make an auto-added executable dependency look explicitly
chosen.

Use this shape for `.observe/otel-audit.json`:

```json
{
  "schema_version": 2,
  "kind": "otel-audit",
  "meta": {
    "audit_id": "example-service-20260717",
    "service_name": "example-service",
    "commit": "abc1234",
    "language": "go",
    "framework": "chi",
    "date": "2026-07-17",
    "status": "Partial",
    "genai_ownership_detected": false
  },
  "summary": ["highest impact finding first"],
  "flow": "audit -> select -> instrument -> verify -> configure/dashboard -> publish",
  "evidence": [
    {"check": "Manifest", "finding": "Go module", "source": "go.mod"},
    {"check": "Entry point", "finding": "HTTP service", "source": "main.go"},
    {"check": "Route source", "finding": "GET /health", "source": "main.go:42"},
    {"check": "Runtime/startup", "finding": "Go test runner", "source": "go.mod"},
    {"check": "GenAI ownership", "finding": "No", "source": "repository source scan"}
  ],
  "routes": [{"method": "GET", "path": "/health"}],
  "signal_flow": {
    "component_flow_map": "main.go [SOURCE-COVERED] -> handler [GAP: HTTP latency]"
  },
  "current_instrumentation": {
    "spans": [{"name": "GET /health", "source": "otelhttp", "type": "auto"}],
    "metrics": [],
    "logs": [],
    "incident_readiness": []
  },
  "genai_readiness": [],
  "findings": [
    {
      "id": "OTEL-001",
      "title": "HTTP latency lacks route-level proof",
      "severity": "high",
      "priority": "required",
      "effort": "small",
      "status": "proposed",
      "area": "HTTP latency",
      "gap": "Source shows no route latency metric or span timing.",
      "impact": "Operators cannot isolate slow routes in Splunk Observability.",
      "product_outcome": "Operators should see one route-named trace plus route latency, request-rate, and error views.",
      "required_fix": "Add HTTP server instrumentation and route attributes.",
      "instrument_mode": "default",
      "verification_scenarios": ["http.health.success"],
      "dependencies": [],
      "evidence": ["main.go:42"],
      "acceptance_criteria": ["One server span has http.route=/health."],
      "constraints": ["Keep route values low cardinality."],
      "expected_telemetry": [
        {
          "type": "span",
          "name": "GET /health",
          "attributes": ["http.route"],
          "product_view": "Trace waterfall and route filtering"
        }
      ],
      "follow_up_actions": ["After instrumentation proof exists, filter the span in Splunk Observability Studio before merge."]
    }
  ],
  "verification": {
    "environments": [
      {
        "id": "go.local",
        "surface": "example service",
        "config_evidence": "go.mod",
        "runner": "go test ./...",
        "scope": "module",
        "prerequisites": "none"
      }
    ],
    "scenarios": [
      {
        "id": "http.health.success",
        "trigger": "GET /health",
        "entrypoint": "main.go:42",
        "expected_signals": "GET /health span",
        "proof_level": "full runtime",
        "acceptance_criteria": "span is emitted with stable route attributes",
        "environments": ["go.local"]
      }
    ]
  },
  "anti_patterns": [],
  "recommendation": ["Run $otel-instrument with selected executable finding IDs."]
}
```

JSON requirements:

- Write new audits as schema v2. Every saved selection and downstream overlay binds
  the exact normalized audit by its digest.
- Use stable finding IDs such as `OTEL-001`, `OTEL-002`, in priority order.
- Use finding `status: proposed` for newly audited gaps. Selection, implementation,
  and verification overlays update later artifacts; the audit baseline remains
  source-derived.
- Use only `critical`, `high`, `medium`, `low`, or `info` severity values.
- Use only `required`, `recommended`, or `deferred` priorities and only
  `default`, `fix all`, `manual decision`, or `external follow-up` instrument
  modes.
- Every `manual decision` must include a non-placeholder `decision_owner` and
  an exact telemetry-specific `decision_question` that names an actual expected
  signal, attribute, or configuration scope, plus two or three explicit
  `decision_options`. Each option has a stable `id`, concise `label`, concrete
  `outcome`, and an `unlocks` list containing only executable finding IDs that
  depend on the manual finding. Option IDs are unique within the decision, and
  option unlock sets are pairwise disjoint. An option may use an empty
  `unlocks` list when that answer intentionally produces no instrumentation
  work. Do not create a `manual decision` finding for a product/runtime choice
  unless it gates a concrete service-owned OTel finding. Every
  `external follow-up` must
  include a known non-placeholder `external_owner` and an exact
  `external_requirement` naming an actual expected OTel signal, attribute,
  configuration scope, or telemetry proof that owner must supply. The exact
  external requirement must also be the finding's `required_fix`, so
  service-owned implementation cannot be hidden in an unselectable item. Do not
  create an `external follow-up` finding only to record business, billing,
  product, governance, or platform context; keep that context in readiness rows
  unless it blocks an in-scope service-owned OTel finding. Those fields are
  invalid on other modes.
- In schema v2, every `manual decision` and `external follow-up` must be in the
  transitive dependency closure of at least one `default`/`fix all` finding.
  Reject orphan non-executable findings. A non-executable finding contains only
  its prerequisite decision or externally supplied telemetry requirement; put
  app-owned implementation in a separate executable finding that lists the
  prerequisite in `dependencies`. For real OTel branches, create one
  option-locked executable finding per option and put each ID only in the
  matching option's `unlocks`; do not pre-create branch findings as visible,
  simultaneous independent gaps that inflate the audit count before the user
  answers.
- Classify effort as `small`, `medium`, `large`, or `decision` so owners can
  distinguish quick wins from longer or choice-dependent work.
- Every finding must include human impact, one concise `product_outcome`,
  required fix, evidence, acceptance criteria, expected telemetry with its
  Splunk Observability Studio `product_view`, and at least one follow-up action. The outcome
  states what the owner should see or gain after implementation and
  verification without claiming it is already proven. Include verification
  scenario IDs when runnable.
- When a finding would modify an existing emitted metric, span, resource, log,
  exporter, or dashboard/detector contract, call out telemetry consumer
  compatibility in the finding's gap, required fix, constraints, or acceptance
  criteria. Distinguish additive semantic-convention fields from breaking
  removals or renames. Require safe existing aliases to be preserved by default;
  if an unsafe high-cardinality field such as raw URL `path` must be removed,
  name the bounded replacement such as `http.route` and state that dashboards or
  detectors using the old field need migration.
- Every mapped verification scenario must reference an ID in
  `verification.scenarios`.
- Do not use `$otel-verify` or generic `run
  verification` as an audit recommendation, finding follow-up, or chat next
  step; audit owns selection planning, while `$otel-instrument` invokes
  verification internally after implementation.
- Every finding dependency must reference another finding ID and point from the
  work toward its prerequisite. Every verification scenario reference must
  exist in `verification.scenarios`.
- Put bulky command output under `.observe/evidence/` and cite it from JSON.

After writing `.observe/otel-audit.json`, run `finalize-audit`. This command
validates the canonical source, renders the interactive HTML view, and prints
one compact digest:

```bash
python3 -I "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" finalize-audit \
  .observe/otel-audit.json \
  --html .observe/otel.html
```

`render-html` infers the source repository root when the audit is under
`.observe/` and turns exact existing repository-relative citations into local
file links. When rendering an audit from another directory, pass
`--repo-root <service-root>` explicitly; never embed an absolute host path in
the canonical JSON.

Resolve both placeholders directly from the directory containing the loaded
otel-audit skill entrypoint; never use a service-root or repository-root script by
name. If finalization fails, repair the reported canonical input or renderer
problem and rerun `finalize-audit`; never patch generated HTML.
If validation and HTML rendering succeeded but the only failure is starting the
loopback report server, keep those valid artifacts and stop. Do not inspect the
helper implementation, probe its private state, invoke help, or repeat the same
server start without a concrete environment remedy. Report the exact server
blocker concisely and never invent a review URL.
When an earlier loopback command in the same run exposed an exact environment
error, include that proven error class (for example,
`bind: operation not permitted`) in the blocker sentence; do not shorten it to
"the server could not start." If no deeper cause was exposed, quote the exact
`finalize-audit` failure text and say that it exposed no deeper cause.

`finalize-audit` starts or reuses a detached report server bound only to
`127.0.0.1` on an available port and returns the HTTP Markdown link in
`links.review_report`. The server exposes only `otel.html`,
`otel-instrumentation.html`, `otel-audit.json`, and its private health check; it
never serves the repository.
It requires an unguessable token in the URL path, rejects symlinked report
files, disables caching and content sniffing, and stores versioned reuse state
with user-only permissions where the platform supports them. The launch token
is transferred through that private state rather than process arguments,
concurrent finalizers reuse one server, and the server exits after eight hours
without a request. Under loopback HTTP, repository source citations are
copyable path text rather than broken links; the server never exposes source
files. Do not open the browser automatically. A loopback link works directly
in desktop IDEs; remote workspaces may require their normal localhost port
forwarding.

The HTML is the human review and selection surface. Keep its empty fixed tray
`hidden` and `inert`. After a reviewer selects work or records a decision
answer, show only the plain selectable terminal command section. Do not render
a selection-count summary, save guidance, or a `Save selection` button. The
command must be regenerated from the current explicit `requested_ids`
and canonical `decision_answers` as
`$otel-instrument --ids OTEL-001,OTEL-002 --decision OTEL-003=option-id <absolute-service-root>`.
Embed the validated absolute service root supplied to `finalize-audit` in the
HTML payload and use it in the generated command, including when the report is
served over loopback HTTP. Keep `file://` path inference only as a compatibility
fallback; a normally finalized report must never show the literal
`<service-root>` placeholder.
Use explicit requested IDs, not auto-added dependency closure, because
`$otel-instrument` recomputes and validates dependencies. If the reviewer has
recorded only decision answers and no executable selection, show that no
instrumentation command can be generated until an executable finding is
selected. The cards, terminal command, and polite live region must
distinguish explicit selections from auto-added dependencies.

The terminal command is the only visible selection handoff. It must carry the
explicit requested IDs and decision answers needed for `$otel-instrument` to
recompute and validate dependency closure. Keep selected-audit and
`.observe/otel-selection.json` compatibility in the machine workflow, but do
not expose browser save or download controls in audit HTML.

The expanded finding's collapsed `Technical details` must retain every expected
telemetry item, acceptance criteria, authored constraint labelled
`Implementation guardrails`, and source evidence. Canonical JSON retains
verification-scenario references, full mode ownership and requirements,
follow-up actions, dependencies, and resolution metadata for downstream
skills.

The saved audit report may carry `review_selection`; `$otel-instrument` must
extract and validate it before instrumentation. For compatibility, the
instrumentation preflight may materialize the same validated selection as
`.observe/otel-selection.json`, but that is an internal handoff artifact, not a
manual user copy step. It records explicit requests, executable dependency
closure, and `decision_answers`.
`decision_answers` is separate from `requested_ids` and `approved_ids`: it is
a canonical-audit-order list of `finding_id`/`option_id` entries and never
contains executable scope; a selection carrying `decision_answers` is schema v2.
Preserve the machine schema names `requested_ids` and
`approved_ids` for compatibility, but do not present `approved_ids` as human
approval: it is the dependency-closed executable selection. A manual
decision ID and an external follow-up ID can never appear in either executable
ID list. Reject unanswered decision dependencies, answers not authored by the
audit, and requested or approved executable work not listed in the chosen
option's `unlocks`. A valid answer only unlocks matching executable work; it
never selects that work automatically. Persist an answer even when its option
unlocks no work, without inventing requested or approved IDs. Announce
automatic dependency changes and save/adoption feedback through an
`aria-live="polite"`, `aria-atomic="true"` status region. Never hand-edit
generated HTML. When the user provides
IDs in the same request, create and validate the bound selection with:

```bash
python3 "<directory-containing-loaded-SKILL.md>/scripts/observe_report.py" select \
  .observe/otel-audit.json \
  --ids OTEL-001,OTEL-004 \
  -o .observe/otel-selection.json
```

The tool validates IDs, binds the selection to the audit ID and SHA-256 digest,
and auto-includes dependencies in audit order. Do not edit code until the owner
has selected executable IDs.

Keep these essential input semantics in the canonical JSON:

- Encode each audited interface in `routes` with parameterized paths and any
  required query-name shape, for example `/kv/{key}` and
  `/search?word={word}`. This is interface inventory only: expected OTel
  `http.route` values remain path-only (for example, `/search`) and never
  contain query strings or values.
- In `verification.scenarios[*].trigger`, never embed concrete key, query,
  path-parameter, request-body, tenant, or user values. Use placeholders such
  as `{key}` and `{word}`, or semantic conditions such as `an existing key` and
  `a missing key`; keep expected telemetry on the same low-cardinality route
  templates.
- `meta.genai_ownership_detected` is the explicit ownership switch. Populate
  `genai_readiness` only when it is true. Human HTML must not render full
  Incident or GenAI readiness ledgers as separate primary sections; preserve
  authored readiness rows in canonical JSON for downstream skills. The human
  decision view renders actionable findings only; readiness ledgers remain
  machine-readable downstream context.
- Put source inventory in `current_instrumentation` and actionable work in
  `findings`. Keep every span, metric, and log integration as an individual
  JSON row rather than grouping exact signals into prose.
- In `signal_flow.component_flow_map`, use only `[SOURCE-COVERED]` and
  `[GAP: <area>]`. Every gap marker must use the exact `area` of a finding, and
  every finding area must appear in at least one marker. Repeat an area only
  when the same finding explicitly spans multiple components; do not create a
  duplicate finding for the repeated association.
- Every telemetry-scoped partial, missing, or owner-mapped
  `current_instrumentation.incident_readiness` row must have an unresolved
  (`proposed`, `approved`, or `in_progress`) finding with an identical `area`
  and mapped verification scenarios. A `covered` row conflicts only with an
  unresolved same-area finding. Validate incident `area` and
  `required_signals`, plus GenAI `surface`, `required_signals`, and
  `acceptance_criteria`, as OTel closure fields; evidence and operator-impact
  prose remain context. A row is telemetry-scoped only when its required
  signals name service-owned OTel telemetry or configuration, not merely a
  product contract, cost owner, safety policy, content-governance rule, or
  external business prerequisite. Do not put general operational observations
  in either canonical readiness array merely to force a finding. Do not render
  authored readiness tables as visible peer sections in audit HTML; finding
  cards carry the user-facing action context.
- Define reusable environments in `verification.environments`; every
  `verification.scenarios[*].environments` value must reference those IDs.
- Audit scenarios and signal inventory are source-derived plans, not runtime
  proof. Keep bulky evidence outside JSON and cite its path.

`finalize-audit` runs the dependency-free validator bundled with the shared
renderer. Resolve the helper from the loaded skill directory, never the audited
repository.

**Chat handoff:** After successfully writing and finalizing the audit artifacts,
the final response must contain exactly this one line and nothing else:

```text
Review report: [otel.html](http://127.0.0.1:<port>/<token>/otel.html)
```

Copy `links.review_report` from successful `finalize-audit` output verbatim
after the `Review report: ` label. Do not include summary bullets, finding
counts, recommendations, a machine-report link, artifact-write narration, or
any other text in the final response. Keep the canonical JSON as an internal
downstream artifact even though it is not linked in chat.
The exact one-line handoff applies only when `links.review_report` exists. On
the server-only blocker above, return one concise blocker sentence instead.

### Step 4 -- Downstream Handoff

Do not perform telemetry execution inside the audit workflow. The report's
`Verification Plan` is a proof plan consumed downstream; it is not the
reviewer's immediate command.

- Recommend selecting executable findings, copying the generated command, and
  running `$otel-instrument` for source gaps. `$otel-instrument` owns the internal
  verification child after implementation.
- Do not present `$otel-verify` or generic `run verification` as the audit
  prompt's next step, recommendation line, or finding follow-up. If proof is
  requested without code changes, state that standalone verification is a
  separate explicit `$otel-verify` request after the audit is complete.
- If the same user request explicitly asks for both audit and standalone
  verification, finish and validate the audit report first, then start
  `$otel-verify` as a separate workflow only after handing off the audit links.

## Troubleshooting

**No dependency manifest found:** Ask the user which subdirectory contains the service, then re-scan from that root.

**Multiple languages detected:** Ask which service to audit, or audit each independently.
