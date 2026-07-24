# Canonical dashboard input contract

Use this contract only when `.observe/otel-audit.json` exists. Canonical JSON is
authoritative; never open or read an audit Markdown report.

## Inputs and binding

1. Read service metadata and existing metrics from `.observe/otel-audit.json`.
2. Load `.observe/otel-selection.json`, `.observe/otel-instrumentation.json`, and
   `.observe/otel-verify.json` when they exist.
3. Require every overlay's `audit_id` and `audit_sha256` to match the audit.
   Require instrumentation's `selection_sha256` to match the exact normalized
   selection and verification's `instrumentation_sha256` to match the exact
   normalized instrumentation.
4. Reject stale, malformed, partially present, or inventory-drifting downstream
   overlays. Do not switch audit formats.

## Metric eligibility and provenance

- A pre-existing `current_instrumentation.metrics` row is source-backed. Preserve
  its exact `name`, `source`, and `type`.
- A newly implemented metric is proof-ready only when its selected finding has
  an instrumentation telemetry item with `type: metric` and a matching
  verification `item_results` row marked `working`. Direct executed proof must
  name the exact metric, unit, dimensions, and scenario IDs.
- Do not infer proof from a finding-level result, aggregate receiver count, or a
  similarly named signal.
- Give a verified chart its stable `OTEL-###.<item>` ID.
- Give an explicitly accepted pre-existing metric without item proof the exact
  ID `SOURCE-METRIC.<metric-name>`. Record that exception in `dashboards.md` and
  pass the same ID with `--allow-source-only-item`.
- Skip every other metric and state the exact verification prerequisite.

## Deterministic validation

For a complete verified chain, run exactly:

```bash
python3 scripts/validate_dashboard_output.py \
  --terraform <repo>/.observe/terraform/dashboards.tf \
  --preview <repo>/.observe/dashboards.preview.json \
  --report <repo>/.observe/dashboards.md \
  --audit <repo>/.observe/otel-audit.json \
  --selection <repo>/.observe/otel-selection.json \
  --instrumentation <repo>/.observe/otel-instrumentation.json \
  --verification <repo>/.observe/otel-verify.json
```

For an explicitly accepted audit-only metric, omit absent downstream arguments,
keep `--audit`, and append one exact argument per charted metric:

```text
--allow-source-only-item SOURCE-METRIC.<exact-metric-name>
```

Treat the validator as an opaque executable. Do not read its source or tests in
the normal workflow. Its compact JSON errors identify the artifact or binding to
repair. A zero exit proves mapping and artifact parity, not Observer rendering,
live values, or publication.
