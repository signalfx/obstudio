import test from 'node:test';
import assert from 'node:assert/strict';
import assertion from './assertion.mjs';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync, chmodSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import HarnessProvider from './provider.mjs';

test('Promptfoo boundary is conservative; statuses remain in the raw output/reason', () => {
  const result = { schema_version: 1, gate: true, errors: [], checks: [] };
  assert.equal(assertion(JSON.stringify(result)).pass, true);
  for (const value of [
    { ...result, gate: false }, { ...result, schema_version: 2 },
    { ...result, errors: ['judge timeout'] }, {},
  ]) assert.equal(assertion(JSON.stringify(value)).pass, false);
  assert.throws(() => assertion('not JSON'));
  for (const status of ['fail', 'not-proven', 'not-applicable', 'ungraded']) {
    const value = { ...result, gate: false, checks: [{ id: 'rubric-1', status }] };
    const graded = assertion(value);
    assert.equal(graded.score, 0);
    assert.match(graded.reason, new RegExp(status));
  }
});

test('installed Promptfoo CLI preserves all five statuses and exits red on incomplete grading', () => {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const directory = mkdtempSync(path.join(os.tmpdir(), 'promptfoo-contract-'));
  try {
    const statuses = ['pass', 'fail', 'not-proven', 'not-applicable', 'ungraded'];
    writeFileSync(path.join(directory, 'config.json'), JSON.stringify({
      prompts: statuses.map(status => JSON.stringify({ schema_version: 1,
        gate: status === 'pass', errors: [], checks: [{ id: 'rubric-1', status }] })),
      providers: ['echo'], tests: [{ assert: [{ type: 'javascript',
        value: `file://${path.join(here, 'assertion.mjs')}` }] }],
    }));
    const result = spawnSync(path.join(here, 'node_modules/.bin/promptfoo'), [
      'eval', '--config', path.join(directory, 'config.json'), '--no-cache', '--no-share',
      '--no-write', '--no-table', '--no-progress-bar', '--output', path.join(directory, 'result.json'),
    ], { encoding: 'utf8', env: { ...process.env, PROMPTFOO_CONFIG_DIR: directory,
      PROMPTFOO_DISABLE_TELEMETRY: '1', PROMPTFOO_DISABLE_UPDATE: '1' } });
    assert.notEqual(result.status, 0, result.stdout + result.stderr);
    const exported = JSON.parse(readFileSync(path.join(directory, 'result.json')));
    assert.equal(exported.results.stats.successes, 1);
    assert.equal(exported.results.stats.failures, 4);
    assert.equal(exported.results.stats.errors, 0);
    for (const row of exported.results.results) {
      const raw = JSON.parse(row.response.output);
      assert.equal(row.success, raw.gate);
      assert.ok(row.gradingResult.reason.includes(raw.checks[0].status));
    }
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('provider sends EOF to the adapter subprocess and passes the original task as one argument', async () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'promptfoo-provider-'));
  const oldPath = process.env.PATH;
  const oldOutput = process.env.PILOT_RUN_DIR;
  try {
    const executable = path.join(directory, 'uv');
    writeFileSync(executable, `#!${process.execPath}\n
const timer = setTimeout(() => process.exit(42), 3000);
process.stdin.resume();
process.stdin.on('end', () => { clearTimeout(timer); console.log(JSON.stringify({
  schema_version: 1, gate: false, errors: [], checks: [], arguments: process.argv.slice(2)
})); });\n`);
    chmodSync(executable, 0o755);
    process.env.PATH = `${directory}${path.delimiter}${oldPath}`;
    process.env.PILOT_RUN_DIR = path.join(directory, 'evidence');
    const result = JSON.parse((await new HarnessProvider().callApi('$otel-audit')).output);
    assert.ok(result.arguments.includes('$otel-audit'));
    assert.ok(result.arguments.includes('--locked'));
    assert.equal(result.gate, false);
  } finally {
    process.env.PATH = oldPath;
    if (oldOutput === undefined) delete process.env.PILOT_RUN_DIR;
    else process.env.PILOT_RUN_DIR = oldOutput;
    rmSync(directory, { recursive: true, force: true });
  }
});
