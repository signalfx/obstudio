# Agent Observability eval findings still open

These failures were observed in model-generated application code and reports.
They remain open for skill-quality review. The fixture log-endpoint fixes do
not resolve them, and a later passing model sample does not close the earlier
counterexamples.

## Completed evidence baseline

Commit `53406c89fa8128748e0223a4c10adf46df9a691a` contains the complete affected
sweep: **15 tasks, 10 fully passing, 86/93 checks**. All four preservation modes
passed the changed resource/API criterion (`rubric-6`). Overall grades were
generic 8/8, GenAI 7/8, metrics 8/8, and logs 6/8.

The committed `eval-reports/<skill>/rubric/benchmark.json` files at that commit
retain the failed criteria and evidence notes. Full local actor artifacts are
under `.workspace/codex-evals/<skill>/<run-id>/cases/`.

| Finding | Task / criterion | Observed failure | Status |
|---|---|---|---|
| Quoted scalar redaction bypass | `preserve-logs-instrument` / `rubric-3` | JSON-encoded scalar email, token/reasoning text, and `private-prompt-sentinel` survive sanitization. Object/list JSON tests missed the scalar branch. | Open |
| Hidden reasoning and size bounds | `preserve-genai-instrument` / `rubric-3` | `hidden_reasoning=HIDDEN_SENTINEL` survives. Sanitizing embedded JSON with sixteen 2,000-character fields produces 16,614 bytes, then assigns retrieval text directly despite declared 1,024/8,192-byte bounds. | Open |
| Verification trace provenance | `preserve-logs-instrument` / `rubric-8` | Public and rejected scenarios cite the Studio scenario's trace IDs; both intersections with their cited captures are empty. | Open |
| Per-mode producer ownership | `active-signal-matrix-audit` / `rubric-2` | Metrics/logs plans exclude workflow/model creators as if existing trace producers owned them. The modes have no such producers; provider binding is also contradictory. | Open |
| Language-specific support evidence | `agent-resource-table-audit` / `rubric-2` | A fresh Go case cites Python exporter 1.45.1 and an existing exporter absent from that snapshot. | Open |
| Source-bound applicability | `agent-resource-table-audit` / `rubric-6` | Template leakage carries Python support into Go and an applicable AO-header row into a non-agent control marked N/A. | Open |
| Non-agent state consistency | `agent-resource-table-verify` / `rubric-3` | Top-level AO resources are N/A, while state rows require or block resource resolution and delivery. | Open |

## Reproduction and source locations

The logs and GenAI safety/provenance failures were independently reproduced.
Local evidence is retained in
`.workspace/claude-review-fixes-pass2-20261020/independent-new-failure-repro.json`
and `independent-genai-failure-repro.json`.

| Skill | Baseline run |
|---|---|
| `otel-audit` | `20261020T200853939788Z` |
| `otel-instrument` | `20261020T200855159694Z` |
| `otel-verify` | `20261020T200855276877Z` |

Each task's `with_skill/rubric_grade.json` records its full criterion notes.
The logs-generated sanitizer is at `service/instrumentation.py:62-72`; its
incorrect trace citations are at `service/.observe/otel-verify.json:376,402`.
The GenAI-generated sanitizer/query assignment is at
`service/instrumentation.py:31,55,169` within its own case directory.

## Fresh recurrence

The fresh instrumentation run `20261020T210914152057Z` repeats the content
safety failure in `preserve-logs-instrument` (7/8, `rubric-3`). Its generated
`service/content_capture.py:15-51` preserves
`hidden_reasoning=thought-sentinel` and transforms
`private_prompt=hidden-sentinel` into `[redacted]=hidden-sentinel`.
Both were independently reproduced; local evidence is in
`.workspace/claude-review-fixes-pass3-20261020/independent-current-logs-redaction-repro.json`.
The evaluator also reproduced propagation through native OTLP encode/decode.

The same run has an additional evidence gap in
`native-agent-resource-defaults` (5/6, `rubric-6`). Its complete receiver/API
outage case records business success, zero receipts, and an exporter error,
without independently capturing completed native spans, metric points or
LogRecords. Signal emission during that outage remains unproven. Closing this
gap requires independent native/in-memory observations in the outage case.

The full instrumentation run `20261020T214331268302Z` adds a typed-part
counterexample in `preserve-genai-instrument` (7/8, `rubric-3`). Its generated
`service/safe_content.py:17-35` redacts sensitive field names but preserves
`{"type":"reasoning","content":"hidden-reasoning-sentinel"}`, including when
JSON-encoded inside the actual prompt. An independent copied-runtime replay
preserved the business result while exposing the sentinel on completed
retrieval, chat, agent and workflow spans and in the encoded native OTLP payload.
Evidence is retained in
`.workspace/combined-review-67a2503-20261020/fresh-reasoning-repro.json`.
The connection-probe corrections do not resolve this sanitizer failure.

## Closure requirements

Keep each finding open until a focused correction and regression exercise the
original failing input or report association. Preserve the prior evidence when
publishing fresh full-scope results. Record the exact correction, command, and
outcome here when closing a finding. These local evaluations do not establish
new live-cloud delivery.
