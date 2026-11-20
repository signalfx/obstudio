// Status interpretation lives in adapter.py; this is only Promptfoo's conservative gate.
export default function assertion(output) {
  const result = typeof output === 'string' ? JSON.parse(output) : output;
  const pass = result.schema_version === 1 && result.gate === true &&
    Array.isArray(result.errors) && result.errors.length === 0;
  return { pass, score: pass ? 1 : 0, reason: JSON.stringify({
    gate: result.gate, reasons: result.reasons, checks: result.checks,
  }) };
}
