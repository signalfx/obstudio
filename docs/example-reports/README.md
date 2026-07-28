# Interactive OTel Report Examples

These self-contained HTML reports are generated from the synthetic
`evals/go/chi-basic` fixture. They contain no private repository data and need
no server, JavaScript package, or external asset at viewing time.

- [Audit and scope selection](otel.html)
- [Instrumentation outcome and verification](otel-instrumentation.html)

Download either file and open it in a browser to use its interactions. The
audit HTML lists every finding once in highest-priority-first order, supports
selection, and demonstrates the keyboard-copyable `$otel-instrument` handoff
without category groups or action tags. Its service root is intentionally
omitted, so regenerate an audit inside a real service before running the
command. The instrumentation example explains each selected finding, what
changed, how observability improves, and the proof obtained.

The sanitized canonical [audit](otel-audit.json),
[selection](otel-selection.json), [instrumentation](otel-instrumentation.json),
and [verification](otel-verify.json) artifacts remain available in this
directory. Generated HTML navigation links only to browser-renderable report
surfaces; workflow responses keep Markdown and JSON as local-file links.
The instrumentation artifact is bound to the exact normalized selection with
`selection_sha256`; verification is transitively bound through the complete
instrumentation digest.

Regenerate both examples from the repository root:

```bash
python3 skills/references/scripts/observe_report.py render-html \
  docs/example-reports/otel-audit.json \
  --selection-json docs/example-reports/otel-selection.json \
  --repo-root evals/go/chi-basic \
  --omit-service-root \
  --output docs/example-reports/otel.html

python3 skills/references/scripts/observe_report.py render-instrumentation-html \
  docs/example-reports/otel-audit.json \
  --selection-json docs/example-reports/otel-selection.json \
  --instrumentation-json docs/example-reports/otel-instrumentation.json \
  --verify-json docs/example-reports/otel-verify.json \
  --repo-root evals/go/chi-basic \
  --output docs/example-reports/otel-instrumentation.html
```
