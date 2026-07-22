# Interactive OTel Report Examples

These self-contained HTML reports are generated from the synthetic
`evals/go/chi-basic` fixture. They contain no private repository data and need
no server, JavaScript package, or external asset at viewing time.

- [Audit and scope selection](otel.html)
- [Instrumentation outcome and verification](otel-instrumentation.html)

Download either file and open it in a browser to use its interactions. The
audit example supports selecting findings and saving the bound selection JSON;
the instrumentation example explains each selected finding, what changed, how
observability improves, and the proof obtained.

The report navigation links resolve to the sanitized canonical
[audit](otel-audit.json), [selection](otel-selection.json),
[instrumentation](otel-instrumentation.json), and
[verification](otel-verify.json) artifacts in this directory.
The instrumentation artifact is bound to the exact normalized selection with
`selection_sha256`; verification is transitively bound through the complete
instrumentation digest.

Regenerate both examples from the repository root:

```bash
python3 skills/references/scripts/observe_report.py render-html \
  evals/go/chi-basic/eval/inputs/otel-audit.json \
  --selection-json evals/go/chi-basic/eval/inputs/otel-selection.json \
  --repo-root evals/go/chi-basic \
  --output docs/example-reports/otel.html

python3 skills/references/scripts/observe_report.py render-instrumentation-html \
  evals/go/chi-basic/eval/inputs/otel-audit.json \
  --selection-json evals/go/chi-basic/eval/inputs/otel-selection.json \
  --instrumentation-json evals/go/chi-basic/eval/inputs/otel-instrumentation.json \
  --verify-json evals/go/chi-basic/eval/inputs/otel-verify.json \
  --repo-root evals/go/chi-basic \
  --output docs/example-reports/otel-instrumentation.html
```
