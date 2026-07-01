export const meta = {
  name: 'obstudio-dashboards-fix-converge',
  description: 'Autonomous fix -> rebuild/test -> adversarial re-review loop until 2 dry rounds (max 4) on obstudio dashboards feature',
  phases: [
    { title: 'Round Fix', detail: 'sequential fix agents by file-area, each writes regression tests' },
    { title: 'Round Gate', detail: 'full build + lint + test; repair if red' },
    { title: 'Round Review', detail: '7-dimension parallel review of cumulative diff' },
    { title: 'Round Verify', detail: 'adversarially verify each new finding' },
  ],
}

const REPO = '/Users/btiwana/obstudio'
const DIFF_CMD = 'git diff main' // working tree (incl. uncommitted fixes) vs main

// ---- schemas ----------------------------------------------------------------
const FIX_RESULT_SCHEMA = {
  type: 'object',
  properties: {
    summary: { type: 'string', description: 'what was changed, in 1-3 sentences' },
    files_changed: { type: 'array', items: { type: 'string' } },
    findings_addressed: { type: 'array', items: { type: 'string' }, description: 'finding ids fixed' },
    findings_skipped: {
      type: 'array',
      items: { type: 'object', properties: { id: { type: 'string' }, why: { type: 'string' } }, required: ['id', 'why'] },
    },
    tests_added: { type: 'array', items: { type: 'string' }, description: 'test names/files added or extended' },
    local_tests_pass: { type: 'boolean', description: 'did the area-local test run pass after the change' },
    notes: { type: 'string' },
  },
  required: ['summary', 'files_changed', 'findings_addressed', 'local_tests_pass'],
}

const GATE_SCHEMA = {
  type: 'object',
  properties: {
    green: { type: 'boolean', description: 'true only if go build, go vet, golangci-lint, go test, vitest, and tsc all pass' },
    go_build: { type: 'boolean' },
    go_test: { type: 'boolean' },
    go_lint: { type: 'boolean' },
    client_test: { type: 'boolean' },
    client_typecheck: { type: 'boolean' },
    repairs_made: { type: 'array', items: { type: 'string' } },
    remaining_failures: { type: 'array', items: { type: 'string' } },
  },
  required: ['green', 'go_build', 'go_test', 'client_test', 'client_typecheck'],
}

const FINDING_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          line: { type: 'integer' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          summary: { type: 'string' },
          failure_scenario: { type: 'string' },
          suggested_fix: { type: 'string' },
        },
        required: ['file', 'summary', 'failure_scenario', 'severity'],
      },
    },
  },
  required: ['findings'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['CONFIRMED', 'PLAUSIBLE', 'REFUTED'] },
    reasoning: { type: 'string' },
    corrected_severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
  },
  required: ['verdict', 'reasoning'],
}

// ---- review dimensions (reused every round) ---------------------------------
const DIMENSIONS = [
  { key: 'go-signalflow', prompt: `Review the Go SignalFlow extraction/resolution logic. Focus ONLY on: observer/internal/dashboards/signalflow.go and signalflow_test.go. Hunt for: regex correctness, filter parsing (literal vs nested-function vs negation), service-alias matching, dedup, case-sensitivity inconsistencies, unwired/dead fields, off-by-one, edge cases tests miss.` },
  { key: 'go-preview', prompt: `Review the Go dashboard preview/resolution logic. Focus ONLY on: observer/internal/dashboards/preview.go, preview_test.go, model.go. Hunt for: filter-then-truncate ordering, percentile interpolation length-invariant/NaN, monotonic counter rate transforms (single-sample), nil derefs, error swallowing, per-request resource amplification, test gaps.` },
  { key: 'go-api', prompt: `Review the Go API/store changes. Focus ONLY on: observer/internal/api/handler.go, handler_test.go, observer/internal/store/store.go, observer/cmd/obstudio/main.go. Hunt for: missing auth/authz, unbounded reads (size cap), input validation, path traversal/disclosure, concurrency/race, locking, error handling.` },
  { key: 'react-grid-panel', prompt: `Review the React dashboard grid/panel components. Focus ONLY on: observer/client/src/dashboards/DashboardGrid.tsx, DashboardPanel.tsx, and their .test.tsx. Hunt for: CSS grid row/column packing math that ignores panel height (overlap), key collisions, rendering of edge values (NaN/null/single-sample), span calc, multi-row height>1 test coverage.` },
  { key: 'react-tab-hooks', prompt: `Review the React dashboard tab, hooks, API client. Focus ONLY on: observer/client/src/dashboards/DashboardsTab.tsx, useDashboardPreview.ts, types.ts, index.ts, observer/client/src/api/client.ts, observer/client/src/AppView.tsx. Hunt for: hook misuse defeating memoization, stale closures, missing deps, out-of-order async responses, error/loading handling (transient error blanking data), type-safety/contract mismatch.` },
  { key: 'skills-evals', prompt: `Review skills guidance and eval tests. Focus ONLY on: skills/splunk-dashboard/SKILL.md, skills/splunk-dashboard-sync/SKILL.md, skills/references/*.md, skills/splunk-dashboard*/references/*.md, evals/test_dashboard_skill_guidance.py. Hunt for: guidance producing incorrect dashboards (overlap templates, wrong SignalFlow like bare .last(), classification gates that drop valid metrics), prose/code contradictions, chartType vocabulary mismatches (table vs event), evals asserting the wrong thing.` },
  { key: 'cross-contract', prompt: `Review cross-cutting correctness: contract between Go types (observer/internal/dashboards/model.go) and TS types (observer/client/src/dashboards/types.ts), JSON field naming, nullable/optional mismatches, whether UI-rendered fields are populated by the backend. Also observer/client/src/metrics/TimeSeriesChart.tsx and observer/client/src/dashboards/testFixtures.ts for fixtures masking bugs.` },
]

// ---- initial backlog: the 12 confirmed + 2 plausible from the prior review --
const INITIAL_BACKLOG = {
  'go-resolver': [
    { id: 'F2', sev: 'HIGH', file: 'observer/internal/dashboards/preview.go:122', desc: 'Multi-value service filter silently dropped. When filter(service.name, a, b) yields >1 value, svcArg stays "" (only set for exactly 1 value) so the store returns ALL services, and applyDimensionFilters skips service keys (isServiceKey->continue) so the constraint is never re-applied. A store with {checkout,payments,billing} returns billing too. The comment claims OR-narrowing that never happens.', fix: 'In the multi-value service case, enforce the constraint: post-filter groups by g.ServiceName against svcValues using strings.EqualFold (service identity lives in the dedicated Resource.ServiceName field, which attrMatchesAny does NOT inspect), or push the value-set into the store query. Add a preview_test.go case with a multi-value service filter asserting unrelated services are excluded.' },
    { id: 'F5', sev: 'MED', file: 'observer/internal/dashboards/signalflow.go:79', desc: 'canonicalServiceFilter/svcAliasConflict/svcUnion use exact case-sensitive map lookups for service.name/sf_service keys, while isServiceKey, attrMatchesAny, and store.QueryMetricsFiltered all use EqualFold. A mixed-case SERVICE.NAME key is dropped -> over-match; service.name=Checkout + sf_service=checkout falsely flagged as a conflict.', fix: 'Look up alias keys case-insensitively (iterate filters with strings.EqualFold against service.name/sf_service) and compare alias values with EqualFold in svcAliasConflict/svcUnion. Add signalflow_test.go cases for mixed-case key and mixed-case alias values.' },
    { id: 'F4', sev: 'MED', file: 'observer/internal/dashboards/preview.go:129', desc: 'Filter-then-truncate ordering: store applies its 50-group limit BEFORE applyDimensionFilters runs, so a matching series in a group beyond the cap is dropped and the panel falsely reports unmatched.', fix: 'Apply dimension filters before the cap: either push env/route filters into QueryMetricsFiltered so the limit applies to already-filtered groups, or request a larger group set and apply the 50-cap after applyDimensionFilters. Add a preview_test.go case with >50 groups where only an out-of-cap group matches the dimension filter.' },
    { id: 'F10', sev: 'LOW', file: 'observer/internal/dashboards/signalflow.go:142', desc: 'ParsedQuery.IgnoredFilters is documented (model.go), typed in TS (types.ts), and fully wired into the UI (the "filters partial" chip + IgnoredFilterChips) but ParseProgramText NEVER populates it. Dropped filters (unresolved ${...}, empty, unparseable, nested-function) vanish silently and the warning UI never fires.', fix: 'In collectSingleValueFilters/collectMultiValueFilters, when a filter key is skipped because its value is empty / contains ${ / is unparseable (and is not negated), append the key to q.IgnoredFilters (deduped). Add a signalflow_test.go case asserting IgnoredFilters contains the dropped key for a ${var.*} value.' },
    { id: 'F6', sev: 'MED', file: 'observer/internal/dashboards/preview.go:70', desc: 'Build() re-snapshots the entire metric ring buffer once per non-text panel (QueryMetricsFiltered calls snapshot() each call) -> O(panels x ringSize). No panel-count cap. Amplifiable via the Access-Control-Allow-Origin:* endpoint.', fix: 'Snapshot the metric ring once at the start of Build() and resolve all panels against that single snapshot (add a store method that accepts a pre-taken snapshot/view, or expose the snapshot). Also cap the number of panels resolved per request. Add a test asserting the snapshot is taken once per Build regardless of panel count (or a panel-count cap test).' },
    { id: 'F11', sev: 'LOW', file: 'observer/internal/dashboards/preview.go:40', desc: 'The resolved absolute filesystem path (filepath.Abs) is always returned in PreviewResponse.Source and in the human-readable Message, readable cross-origin due to Access-Control-Allow-Origin:* -> discloses OS username/home/working-dir layout.', fix: 'Return only a relative path or basename in Source/Message, or omit the absolute path from the cross-origin response. Add a test asserting the response Source/Message does not contain the absolute repo path.' },
    { id: 'P1', sev: 'PLAUSIBLE-LOW', file: 'observer/internal/dashboards/preview.go:47', desc: 'os.ReadFile reads the whole sidecar into memory every request with no size cap (no Stat/io.LimitReader), then json.Unmarshal allocates again. Operator/env-controlled path, but defensive cap warranted for a file fed into a network handler.', fix: 'Stat the file and reject (Available:false + message) when it exceeds a sane cap (e.g. a few MB), or read through io.LimitReader before unmarshalling. Add a test for the oversized-file path.' },
  ],
  'react': [
    { id: 'F1', sev: 'HIGH', file: 'observer/client/src/dashboards/DashboardGrid.tsx:42', desc: 'buildRowMap packs distinct Splunk row values into consecutive ordinals (0,2 -> 0,1) ignoring panel height. Splunk row is an absolute y-coordinate. The skill canonical template (KPI row=0,h=2 above chart row=2,h=3 same column) renders as gridRow 1/span2 and 2/span3 -> overlap on grid row 2. Breaks the common vertical-stack layout.', fix: 'Make row placement height-aware. Either pass the real Splunk row straight through (gridRow `${row+1} / span ${height}`) and rely on grid-auto-rows, or compute a packing where each panels start line = max bottom edge of already-placed panels sharing its columns. Add a DashboardGrid.test.tsx case with two SAME-column panels (upper row=0 h=2, lower row=2 h=3) asserting the lower panels gridRow start is strictly past the upper panels last occupied line (no overlap).' },
    { id: 'F7', sev: 'MED', file: 'observer/client/src/dashboards/DashboardsTab.tsx:103', desc: 'A single transient auto-refresh fetch failure blanks the whole rendered dashboard: renderState checks `if (error)` BEFORE the data branch, and useDashboardPreview never clears prior data on error nor clears error on a new fetch/refresh. One failed 5s poll wipes a valid dashboard until the next success.', fix: 'In renderState only short-circuit to the error message when there is no data to show (`if (error && !data)`); surface a transient error as a small inline banner above the existing grid. Optionally clear error at the start of each fetch/refresh. Add a DashboardsTab.test.tsx case: render with data, then a failing refresh, assert the grid still renders and the error is shown inline (not replacing the grid).' },
    { id: 'F12', sev: 'LOW', file: 'observer/client/src/dashboards/DashboardPanel.tsx:218', desc: 'usePreparedMetrics drops a matched single_value/list/heatmap panel to empty (renders 0/blank) when a monotonic-counter or histogram series has exactly one data point: the rate/delta loop starts at i=1 producing zero points, then the trailing filter removes the group, despite panel.matched=true.', fix: 'For latest-value renderings (single_value/list/heatmap), or when a rate/delta series collapses to zero output points, fall back to the latest raw value instead of dropping the group. Add a DashboardPanel.test.tsx case: a monotonic counter single_value panel with exactly one data point renders the raw latest value, not 0.' },
    { id: 'F8-renderer', sev: 'MED', file: 'observer/client/src/dashboards/DashboardPanel.tsx:124', desc: 'chartType "table" (produced by the generator templates/classification and handled by the sync skill as TableChart) has NO render branch in DashboardPanel.tsx, so it falls through to the time_series SVG line chart and the type badge shows the raw "table" string. (Coordinate the vocabulary side with the skills agent: keep table, drop the never-produced event, OR add a table branch.)', fix: 'Add a "table" rendering branch in DashboardPanel.tsx (a simple tabular rendering of the matched series/latest values) and a CHART_TYPE_LABELS entry, so a generated table panel renders correctly. Add a DashboardPanel.test.tsx case for chartType:"table".' },
  ],
  'skills-evals': [
    { id: 'F3', sev: 'HIGH', file: 'skills/splunk-dashboard/references/dashboard-classification.md:43', desc: 'Error/Throughput classification rules require the metric name to end in .total/.count, so common counters like *.errors / *.processed are routed to "skip (no panel)". The in-repo eval fixture counters (checkout.payment.errors, checkout.orders.processed) match neither -> no error panel and no throughput panel, contradicting SKILL.md Step 3 prose ("error/failure counters", "non-error counters") and the graded eval rubric.', fix: 'Broaden the Error/Throughput rules so classification keys on counter-ness + the error keyword regardless of a .total/.count suffix (match .total/.count/.errors/.processed or any metric whose audit Type is a counter). Align the decision flowchart and SKILL.md Step 3 prose. (No code test; this is doc guidance verified by the eval guidance test.)' },
    { id: 'F8-vocab', sev: 'MED', file: 'skills/splunk-dashboard/SKILL.md:186', desc: 'The generate preview-sidecar chartType vocabulary lists "event" (never produced by any generator artifact) and omits "table" (produced by dashboard-classification.md and dashboard-templates.md, handled by the sync skill). Vocabulary disagreement across SKILL.md / templates / renderer.', fix: 'Reconcile the chartType vocabulary across SKILL.md line ~186, dashboard-templates.md, and dashboard-classification.md so the generate contract, the REST mapping, and the renderer agree on ONE set: include "table" and drop the unused "event" (coordinate with the renderer agent that adds the table branch).' },
    { id: 'F9', sev: 'MED', file: 'evals/test_dashboard_skill_guidance.py:194', desc: 'test_dashboard_skill_emits_preview_sidecar_contract asserts the wrong chartType vocabulary: it pins "event" (never emitted) and never checks "table" (which is emitted and was unrendered). It green-lights the inconsistent vocabulary and would turn RED if SKILL.md were corrected to list table.', fix: 'Update the eval to assert the vocabulary the generator actually emits and the Observer actually renders (include "table"; verify parity between SKILL.md, dashboard-templates.md REST mapping, and DashboardPanel.tsx supported types) rather than a hard-coded list containing the unused "event". Keep the test green only when the vocabulary is internally consistent.' },
    { id: 'P2', sev: 'PLAUSIBLE-MED', file: 'skills/references/signalflow-patterns.md:30', desc: 'The shared SignalFlow reference lists bare ".last()" (no window) as a valid saturation aggregation, contradicting dashboard-templates.md and splunk-dashboard-sync/SKILL.md which say bare .last() is rejected with HTTP 400 and .mean() must be used. Steers the chart toward a create-time 400.', fix: 'In signalflow-patterns.md drop bare .last() from the saturation row and the line-32 guidance (or require an explicit window e.g. .last("1m")), and recommend .mean() as the safe no-argument aggregation, matching dashboard-templates.md.' },
  ],
}

// ---- helpers ----------------------------------------------------------------
function backlogToText(items) {
  return items
    .map(
      (f) =>
        `### ${f.id} [${f.sev}] ${f.file}\nDEFECT: ${f.desc}\nREQUIRED FIX: ${f.fix}`
    )
    .join('\n\n')
}

const FIX_PREFACE = `You are fixing confirmed code-review defects in the obstudio repo. Working directory: ${REPO}. Current branch is feature/splunk-dashboards-review-fixes (already checked out; do NOT switch branches, do NOT commit, do NOT push). Edit files in place.\n\nDISCIPLINE (from the repo CLAUDE.md):\n- Every fix MUST have an accompanying regression test that FAILS before the fix and PASSES after. Write the test, confirm it fails against the unfixed behavior if feasible, apply the fix, confirm it passes.\n- Do not mock internal functions; use real implementations with isolated state.\n- Match the surrounding code style.\n- After your edits, run the AREA-LOCAL test command below and confirm it passes. Report local_tests_pass honestly.\n- If a finding turns out to be a false positive on closer reading, SKIP it and record why in findings_skipped rather than forcing a change.`

// ---- the loop ---------------------------------------------------------------
const MAX_ROUNDS = 4
const DRY_ROUNDS_TO_STOP = 2

let dryStreak = 0
let backlog = INITIAL_BACKLOG // round 1 backlog, grouped by area
const roundSummaries = []

for (let round = 1; round <= MAX_ROUNDS; round++) {
  const goItems = backlog['go-resolver'] || []
  const reactItems = backlog['react'] || []
  const skillsItems = backlog['skills-evals'] || []
  const totalItems = goItems.length + reactItems.length + skillsItems.length

  if (round > 1 && totalItems === 0) {
    // nothing new to fix this round; it is a dry round by construction
    log(`Round ${round}: no new findings to fix (already dry from prior review).`)
  }

  // ---------- FIX (sequential by area to avoid compile races) ----------
  phase(`Round ${round} Fix`)
  const fixResults = { go: null, react: null, skills: null }

  if (goItems.length) {
    fixResults.go = await agent(
      `${FIX_PREFACE}\n\nFIX THESE GO RESOLVER/STORE/API DEFECTS (edit observer/internal/dashboards/*.go, observer/internal/store/store.go, observer/internal/api/handler.go only):\n\n${backlogToText(goItems)}\n\nNote for F2/F5: service identity is in the dedicated Resource.ServiceName field (group.ServiceName), which attribute matching does NOT inspect; enforce service constraints against that field with strings.EqualFold.\n\nAREA-LOCAL TEST: cd observer && go test ./internal/dashboards/... ./internal/store/... ./internal/api/... && go vet ./internal/dashboards/... && gofmt -l internal/dashboards`,
      { label: `fix:go-resolver:r${round}`, phase: `Round ${round} Fix`, schema: FIX_RESULT_SCHEMA, model: 'opus', effort: 'high' }
    )
  }
  if (reactItems.length) {
    fixResults.react = await agent(
      `${FIX_PREFACE}\n\nFIX THESE REACT DASHBOARD DEFECTS (edit observer/client/src/dashboards/*.tsx/*.ts only):\n\n${backlogToText(reactItems)}\n\nNote for F8-renderer: coordinate the chartType vocabulary with the skills docs — the agreed direction is KEEP "table" (add a real render branch + CHART_TYPE_LABELS entry) and treat "event" as deprecated. Do not remove the existing text/event handling that other code may rely on; just ensure "table" renders correctly.\n\nAREA-LOCAL TEST: cd observer/client && npx vitest run && npx tsc --noEmit -p tsconfig.json`,
      { label: `fix:react:r${round}`, phase: `Round ${round} Fix`, schema: FIX_RESULT_SCHEMA, model: 'opus', effort: 'high' }
    )
  }
  if (skillsItems.length) {
    fixResults.skills = await agent(
      `${FIX_PREFACE}\n\nFIX THESE SKILLS-GUIDANCE / EVAL DEFECTS (edit skills/**/*.md and evals/test_dashboard_skill_guidance.py only):\n\n${backlogToText(skillsItems)}\n\nNote for F8-vocab: the agreed direction is the chartType vocabulary should INCLUDE "table" and DROP the never-produced "event", consistently across SKILL.md, dashboard-templates.md, dashboard-classification.md, and the eval (F9). The renderer agent is adding a "table" branch in parallel.\n\nAREA-LOCAL TEST: cd ${REPO} && python -m pytest evals/test_dashboard_skill_guidance.py -q  (if pytest/deps unavailable, instead read the test carefully and statically verify your edits satisfy every assertion; report that in notes).`,
      { label: `fix:skills-evals:r${round}`, phase: `Round ${round} Fix`, schema: FIX_RESULT_SCHEMA, model: 'opus', effort: 'high' }
    )
  }

  // ---------- GATE (full build + lint + test; repair if red) ----------
  phase(`Round ${round} Gate`)
  const gate = await agent(
    `You are the build/test gate for the obstudio repo. Working directory: ${REPO}, branch feature/splunk-dashboards-review-fixes (do NOT commit/push/switch branches). Uncommitted fixes from this round are in the working tree.\n\nRun ALL of these and make them pass, repairing any breakage the fixes introduced (compile errors, broken tests, lint/format, type errors). Repair minimally and in the spirit of the fixes; do not revert a fix to make a test pass — fix the code or update the test correctly.\n\n1. cd observer && go build ./...\n2. cd observer && go vet ./internal/...\n3. cd observer && gofmt -l internal/  (must print nothing; gofmt -w any listed files)\n4. cd observer && golangci-lint run ./internal/dashboards/... ./internal/store/... ./internal/api/...  (fix all warnings)\n5. cd observer && go test ./internal/... \n6. cd observer/client && npx vitest run\n7. cd observer/client && npx tsc --noEmit -p tsconfig.json\n\nReport each as a boolean and set green=true ONLY if every one passes. List any repairs you made and any failures you could not fix.`,
    { label: `gate:r${round}`, phase: `Round ${round} Gate`, schema: GATE_SCHEMA, model: 'opus', effort: 'high' }
  )
  log(`Round ${round} gate: green=${gate?.green} (build=${gate?.go_build} goTest=${gate?.go_test} lint=${gate?.go_lint} clientTest=${gate?.client_test} tsc=${gate?.client_typecheck})`)

  // ---------- REVIEW (7-dimension, cumulative diff) + adversarial VERIFY ----------
  phase(`Round ${round} Review`)
  const reviewed = await pipeline(
    DIMENSIONS,
    (d) =>
      agent(
        `You are reviewing the obstudio repo, branch feature/splunk-dashboards-review-fixes. Working directory: ${REPO}. Run \`${DIFF_CMD}\` for the full cumulative diff vs main (this INCLUDES the uncommitted fixes just applied this round). Read the relevant FULL files, not just hunks.\n\n${d.prompt}\n\nReport ONLY real defects you can back with a concrete failure scenario, including any defect NEWLY INTRODUCED by this round's fixes (regressions, incomplete fixes, off-by-one in the new packing math, etc.). Do not report style nits. If the area is now clean, return an empty findings array.`,
        { label: `review:${d.key}:r${round}`, phase: `Round ${round} Review`, schema: FINDING_SCHEMA, model: 'opus', effort: 'high' }
      ),
    (review, d) => {
      const findings = (review && review.findings) || []
      if (!findings.length) return []
      return parallel(
        findings.map((f) => () =>
          agent(
            `Adversarially verify this code-review finding against the ACTUAL current working-tree code in the obstudio repo (working dir ${REPO}, branch feature/splunk-dashboards-review-fixes — includes uncommitted fixes). Read the cited file and surrounding code. Default stance: skepticism — try to REFUTE. Return CONFIRMED only if the defect genuinely exists in the CURRENT code and the scenario reproduces; PLAUSIBLE if real but uncertain/hard to trigger; REFUTED if the current code is actually correct (e.g. the fix already handles it), the scenario can't happen, or the finding misreads the code.\n\nFINDING:\nFile: ${f.file}:${f.line || '?'}\nSeverity: ${f.severity}\nSummary: ${f.summary}\nFailure scenario: ${f.failure_scenario}\nSuggested fix: ${f.suggested_fix || '(none)'}`,
            { label: `verify:${d.key}:${f.line || '?'}:r${round}`, phase: `Round ${round} Verify`, schema: VERDICT_SCHEMA, model: 'opus', effort: 'high' }
          ).then((v) => ({ ...f, dimension: d.key, ...v }))
        )
      )
    }
  )

  const all = reviewed.flat().filter(Boolean)
  const confirmed = all.filter((f) => f.verdict === 'CONFIRMED')
  const plausible = all.filter((f) => f.verdict === 'PLAUSIBLE')
  const refuted = all.filter((f) => f.verdict === 'REFUTED')

  // build next round's backlog from survivors (confirmed + plausible), regrouped by area
  const survivors = [...confirmed, ...plausible]
  const next = { 'go-resolver': [], react: [], 'skills-evals': [] }
  for (const f of survivors) {
    const item = {
      id: `R${round}-${f.dimension}-${f.line || 'x'}`,
      sev: (f.corrected_severity || f.severity || 'medium').toUpperCase(),
      file: `${f.file}:${f.line || '?'}`,
      desc: f.failure_scenario || f.summary,
      fix: f.suggested_fix || 'Address the defect described.',
    }
    const dim = f.dimension || ''
    if (dim.startsWith('go-') || dim === 'cross-contract') {
      // route cross-contract by file path
      if (f.file && f.file.includes('client/')) next.react.push(item)
      else if (f.file && (f.file.includes('skills') || f.file.includes('evals'))) next['skills-evals'].push(item)
      else next['go-resolver'].push(item)
    } else if (dim.startsWith('react')) next.react.push(item)
    else if (dim === 'skills-evals') next['skills-evals'].push(item)
    else next['go-resolver'].push(item)
  }

  roundSummaries.push({
    round,
    gate_green: !!(gate && gate.green),
    fixed_this_round: {
      go: fixResults.go?.findings_addressed || [],
      react: fixResults.react?.findings_addressed || [],
      skills: fixResults.skills?.findings_addressed || [],
    },
    review: {
      confirmed: confirmed.length,
      plausible: plausible.length,
      refuted: refuted.length,
    },
    confirmed_findings: confirmed.map((f) => ({ file: f.file, line: f.line, sev: f.corrected_severity || f.severity, summary: f.summary })),
    plausible_findings: plausible.map((f) => ({ file: f.file, line: f.line, summary: f.summary })),
  })

  log(`Round ${round} review: ${confirmed.length} confirmed, ${plausible.length} plausible, ${refuted.length} refuted. dryStreak before=${dryStreak}`)

  if (confirmed.length === 0) {
    dryStreak += 1
  } else {
    dryStreak = 0
  }

  if (dryStreak >= DRY_ROUNDS_TO_STOP) {
    log(`Converged: ${dryStreak} consecutive dry rounds. Stopping at round ${round}.`)
    roundSummaries.push({ converged: true, at_round: round })
    break
  }

  if (round === MAX_ROUNDS) {
    log(`Hit MAX_ROUNDS=${MAX_ROUNDS} without ${DRY_ROUNDS_TO_STOP} dry rounds. Outstanding survivors carried in last round summary.`)
    roundSummaries.push({ converged: false, hit_max_rounds: true, outstanding: survivors.length })
    break
  }

  backlog = next
}

return {
  converged: dryStreak >= DRY_ROUNDS_TO_STOP,
  dry_streak: dryStreak,
  rounds_run: roundSummaries.filter((r) => r.round).length,
  round_summaries: roundSummaries,
  note: 'Fixes are in the working tree on branch feature/splunk-dashboards-review-fixes, uncommitted, with regression tests. Review the diff and the gate status per round before committing.',
}
