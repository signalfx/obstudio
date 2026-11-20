import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { deepStrictEqual } from 'node:assert';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, copyFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

export function restoreNativeExport(proof) {
  const { promptfoo_export: packed, promptfoo_stats, promptfoo_version, ...evidence } = proof;
  if (promptfoo_version !== '0.126.0' || !packed) throw new Error('Publish the native export with npm run report first');
  const output = JSON.stringify(evidence);
  if (createHash('sha256').update(output).digest('hex') !== packed.output_sha256) {
    throw new Error('Native provider output no longer matches the original automated evidence');
  }
  const record = structuredClone(packed.template);
  const rows = record.results.results;
  if (rows.length !== 1 || rows[0].response.output !== null) throw new Error('Expected one deduplicated native result');
  if (!/^[A-Za-z0-9][A-Za-z0-9:._-]{1,199}$/.test(record.evalId)) throw new Error('Invalid native eval ID');
  rows[0].response.output = output;
  return record;
}

export function createBundle(proofPath, directory) {
  const proof = JSON.parse(readFileSync(proofPath, 'utf8'));
  const record = restoreNativeExport(proof);
  mkdirSync(directory, { recursive: true });
  const jsonPath = path.resolve(directory, 'promptfoo-eval.json');
  writeFileSync(jsonPath, JSON.stringify(record, null, 2) + '\n');
  const temporary = mkdtempSync(path.join(tmpdir(), 'promptfoo-export-'));
  const cli = path.join(here, 'node_modules/.bin/promptfoo');
  const options = { encoding: 'utf8', input: '', timeout: 60_000, maxBuffer: 4 * 1024 * 1024,
    env: { ...process.env, PROMPTFOO_CONFIG_DIR: temporary, PROMPTFOO_DISABLE_TELEMETRY: '1',
      PROMPTFOO_DISABLE_UPDATE: '1', PROMPTFOO_DISABLE_SHARING: 'true' } };
  try {
    // Import/export is presentation only: it never executes providers or makes model calls.
    execFileSync(cli, ['import', jsonPath], options);
    execFileSync(cli, ['export', 'eval', record.evalId, '--output', path.resolve(directory, 'report.html')], options);
    const roundtrip = path.join(temporary, 'roundtrip.json');
    execFileSync(cli, ['export', 'eval', record.evalId, '--output', roundtrip], options);
    const saved = JSON.parse(readFileSync(roundtrip, 'utf8'));
    deepStrictEqual(saved.results.results[0].response.output, record.results.results[0].response.output);
    deepStrictEqual(saved.results.results[0].gradingResult, record.results.results[0].gradingResult);
    for (const key of ['successes', 'failures', 'errors']) deepStrictEqual(saved.results.stats[key], record.results.stats[key]);
  } finally { rmSync(temporary, { recursive: true, force: true }); }
  copyFileSync(proofPath, path.join(directory, 'benchmark.json'));
  const markdown = path.join(path.dirname(proofPath), 'report.md');
  copyFileSync(markdown, path.join(directory, 'evidence.md'));
  writeFileSync(path.join(directory, 'README.txt'),
    'Extract this artifact, then open report.html in your browser. No server or account is required.\n' +
    'This is Promptfoo\'s portable HTML export of a real local evaluation, not a new CI model run.\n' +
    'The full server Web UI (ratings and run comparisons) remains separate from this HTML export.\n' +
    'evidence.md and benchmark.json retain the exact rules, five-state grades, evidence and source hashes.\n' +
    'For the full local Web UI: import promptfoo-eval.json with the pinned Promptfoo CLI, then run promptfoo view --no.\n');
  console.log(`Portable Promptfoo browser report: ${path.resolve(directory, 'report.html')}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 4) throw new Error('Usage: node bundle.mjs <benchmark.json> <artifact-directory>');
  createBundle(path.resolve(process.argv[2]), path.resolve(process.argv[3]));
}
