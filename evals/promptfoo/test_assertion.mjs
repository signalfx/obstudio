import test from 'node:test';
import assert from 'node:assert/strict';
import assertion from './assertion.mjs';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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
